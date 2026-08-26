"""Read models used by HTTP routes, WebSockets, and the processor."""

from __future__ import annotations

from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pulseexchange.models import (
    CommandStatus,
    MarketCommand,
    MarketEvent,
    OrderRecord,
    PersistedOrderStatus,
    PersistedSide,
    TradeRecord,
)
from pulseexchange.schemas import (
    BookResponse,
    PriceLevelResponse,
    RecoveredMarketEvent,
    StreamSnapshot,
    TradeResponse,
)

ACTIVE_ORDER_STATUSES = (
    PersistedOrderStatus.OPEN,
    PersistedOrderStatus.PARTIALLY_FILLED,
)


async def _begin_consistent_read(session: AsyncSession) -> None:
    """Pin all snapshot queries to one PostgreSQL MVCC version."""

    if session.in_transaction():
        return
    if session.get_bind().dialect.name == "postgresql":
        # Obtaining the connection begins the transaction with this isolation
        # level before the first SELECT establishes its snapshot.
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})


async def build_book(session: AsyncSession, symbol: str) -> BookResponse:
    """Aggregate the persisted active book into deterministic price levels."""

    await _begin_consistent_read(session)
    levels = await session.execute(
        select(
            OrderRecord.side,
            OrderRecord.price,
            func.sum(OrderRecord.remaining_quantity).label("quantity"),
            func.count(OrderRecord.order_id).label("order_count"),
        )
        .where(
            OrderRecord.symbol == symbol,
            OrderRecord.status.in_(ACTIVE_ORDER_STATUSES),
        )
        .group_by(OrderRecord.side, OrderRecord.price)
        .order_by(
            OrderRecord.side,
            case(
                (OrderRecord.side == PersistedSide.BUY, -OrderRecord.price),
                else_=OrderRecord.price,
            ),
        )
    )

    bids: list[PriceLevelResponse] = []
    asks: list[PriceLevelResponse] = []
    for side, price, quantity, order_count in levels:
        item = PriceLevelResponse(
            price=price,
            quantity=int(quantity),
            order_count=int(order_count),
        )
        (bids if side == PersistedSide.BUY else asks).append(item)

    sequence = await session.scalar(
        select(func.coalesce(func.max(MarketCommand.sequence), 0)).where(
            MarketCommand.symbol == symbol,
            MarketCommand.status.in_((CommandStatus.COMPLETED, CommandStatus.REJECTED)),
        )
    )
    event_id = await session.scalar(
        select(func.coalesce(func.max(MarketEvent.event_id), 0)).where(MarketEvent.symbol == symbol)
    )
    return BookResponse(
        symbol=symbol,
        sequence=int(sequence or 0),
        event_id=int(event_id or 0),
        bids=bids,
        asks=asks,
    )


async def recent_trades(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = 50,
    before: int | None = None,
) -> list[TradeRecord]:
    statement = select(TradeRecord).where(TradeRecord.symbol == symbol)
    if before is not None:
        statement = statement.where(TradeRecord.trade_id < before)
    result = await session.scalars(statement.order_by(desc(TradeRecord.trade_id)).limit(limit))
    return list(result)


async def latest_market_event_id(session: AsyncSession, symbol: str) -> int:
    value = await session.scalar(
        select(func.coalesce(func.max(MarketEvent.event_id), 0)).where(MarketEvent.symbol == symbol)
    )
    return int(value or 0)


async def recover_market_events(
    session: AsyncSession,
    symbol: str,
    *,
    after_event_id: int,
    through_event_id: int,
    limit: int,
) -> tuple[list[RecoveredMarketEvent], bool]:
    """Read a bounded, ascending suffix of durable events missed by a client."""

    await _begin_consistent_read(session)
    records = list(
        await session.scalars(
            select(MarketEvent)
            .where(
                MarketEvent.symbol == symbol,
                MarketEvent.event_id > after_event_id,
                MarketEvent.event_id <= through_event_id,
            )
            .order_by(desc(MarketEvent.event_id))
            .limit(limit + 1)
        )
    )
    truncated = len(records) > limit
    selected = records[:limit]
    selected.reverse()
    return (
        [
            RecoveredMarketEvent(
                event_id=record.event_id,
                sequence=record.command_sequence,
                event_type=record.event_type.value,
                payload=record.payload,
                created_at=record.created_at,
            )
            for record in selected
        ],
        truncated,
    )


async def build_stream_snapshot(
    session: AsyncSession,
    symbol: str,
    *,
    after_event_id: int | None = None,
    replay_limit: int = 100,
) -> StreamSnapshot:
    """Build one MVCC-consistent reconnect authority and optional event replay."""

    book = await build_book(session, symbol)
    trades = await recent_trades(session, symbol, limit=25)
    recovered_events: list[RecoveredMarketEvent] = []
    replay_truncated = False
    if after_event_id is not None and after_event_id < book.event_id:
        recovered_events, replay_truncated = await recover_market_events(
            session,
            symbol,
            after_event_id=after_event_id,
            through_event_id=book.event_id,
            limit=replay_limit,
        )
    return StreamSnapshot(
        symbol=symbol,
        sequence=book.sequence,
        event_id=book.event_id,
        book=book,
        trades=[TradeResponse.model_validate(trade) for trade in trades],
        recovered_events=recovered_events,
        replay_truncated=replay_truncated,
    )
