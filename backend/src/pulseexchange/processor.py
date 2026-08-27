"""Single-writer ordered command processing.

The processor deliberately serializes matching commands.  A PostgreSQL
transaction-scoped advisory lock ensures that even if multiple application
replicas run this loop, only one mutates the order book at a time.  The command,
materialized order state, trades, and append-only market event commit together.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulseexchange.broadcast import MarketBroadcaster
from pulseexchange.config import Settings
from pulseexchange.engine import (
    BookSnapshot,
    EngineError,
    LimitOrder,
    MatchingEngine,
    OrderNotCancellableError,
    OrderStatus,
    Side,
    Trade,
    UnknownOrderError,
)
from pulseexchange.models import (
    CommandStatus,
    CommandType,
    MarketCommand,
    MarketEvent,
    MarketEventType,
    OrderRecord,
    PersistedOrderStatus,
    PersistedSide,
    TradeRecord,
)
from pulseexchange.notifications import notify_market_event
from pulseexchange.runtime import PROCESSOR_SERVICE, remove_heartbeat, write_heartbeat
from pulseexchange.schemas import BookResponse, PriceLevelResponse, StreamUpdate, TradeResponse

logger = logging.getLogger(__name__)

# A stable, application-specific signed bigint within PostgreSQL's advisory-lock range.
PROCESSOR_ADVISORY_LOCK_ID = 6_029_117_904_286_301


def _order_payload(order: LimitOrder) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "side": order.side.value,
        "price": order.price,
        "quantity": order.quantity,
        "remaining_quantity": order.remaining_quantity,
        "sequence": order.sequence,
        "status": order.status.value,
    }


def _trade_payload(trade: Trade) -> dict[str, Any]:
    return {
        "trade_sequence": trade.sequence,
        "maker_order_id": trade.maker_order_id,
        "taker_order_id": trade.taker_order_id,
        "maker_side": trade.maker_side.value,
        "price": trade.price,
        "quantity": trade.quantity,
    }


def _book_from_engine(
    symbol: str,
    command_sequence: int,
    event_id: int,
    snapshot: BookSnapshot,
) -> BookResponse:
    return BookResponse(
        symbol=symbol,
        sequence=command_sequence,
        event_id=event_id,
        bids=[
            PriceLevelResponse(
                price=level.price,
                quantity=level.quantity,
                order_count=level.order_count,
            )
            for level in snapshot.bids
        ],
        asks=[
            PriceLevelResponse(
                price=level.price,
                quantity=level.quantity,
                order_count=level.order_count,
            )
            for level in snapshot.asks
        ],
    )


class CommandProcessor:
    """Poll and atomically process the earliest durable queued command."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broadcaster: MarketBroadcaster | Settings | None = None,
        settings: Settings | None = None,
    ) -> None:
        # Accept the original (factory, broadcaster, settings) form while the
        # independent worker uses (factory, settings).
        if isinstance(broadcaster, Settings):
            settings = broadcaster
            broadcaster = None
        if settings is None:
            raise TypeError("CommandProcessor requires Settings")
        self._session_factory = session_factory
        self._broadcaster = broadcaster
        self._settings = settings
        self._stop = asyncio.Event()
        self._running = False
        self._instance_id = str(uuid.uuid4())
        self._started_at = datetime.now(UTC)

    @property
    def running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._running = True
        logger.info("ordered command processor started")
        next_heartbeat = 0.0
        try:
            while not self._stop.is_set():
                try:
                    now = time.monotonic()
                    if now >= next_heartbeat:
                        await write_heartbeat(
                            self._session_factory,
                            service_name=PROCESSOR_SERVICE,
                            instance_id=self._instance_id,
                            started_at=self._started_at,
                        )
                        next_heartbeat = now + self._settings.processor_heartbeat_interval_seconds
                    processed = await self.process_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # The surrounding transaction has rolled back, leaving the
                    # command queued for a later attempt instead of half-applied.
                    logger.exception("command processor iteration failed")
                    await self._wait(self._settings.processor_error_backoff_ms / 1_000)
                    continue

                if not processed:
                    await self._wait(self._settings.processor_poll_interval_ms / 1_000)
        finally:
            self._running = False
            try:
                await remove_heartbeat(
                    self._session_factory,
                    service_name=PROCESSOR_SERVICE,
                    instance_id=self._instance_id,
                )
            except Exception:
                logger.exception("failed to remove processor heartbeat")
            logger.info("ordered command processor stopped")

    async def _wait(self, seconds: float) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    async def process_once(self) -> bool:
        """Process one command, returning false when no work was claimed."""

        update: dict[str, Any] | None = None
        started = time.perf_counter()
        processed_command: MarketCommand | None = None
        async with self._session_factory() as session, session.begin():
            if not await self._acquire_single_writer_lock(session):
                return False

            command = await session.scalar(
                select(MarketCommand)
                .where(MarketCommand.status == CommandStatus.QUEUED)
                .order_by(MarketCommand.sequence)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if command is None:
                return False
            processed_command = command
            command.processing_started_at = datetime.now(UTC)

            try:
                update = await self._apply_command(session, command)
            except (UnknownOrderError, OrderNotCancellableError) as error:
                update = await self._reject_command(session, command, error)

        # Never publish before the database transaction is known to have committed.
        if update is not None and self._broadcaster is not None:
            await self._broadcaster.publish(update["symbol"], update)
        if processed_command is not None:
            structlog.get_logger("pulseexchange.processor").info(
                "command_processed",
                correlation_id=processed_command.correlation_id,
                command_id=processed_command.command_id,
                sequence=processed_command.sequence,
                symbol=processed_command.symbol,
                status=processed_command.status.value,
                duration_ms=round((time.perf_counter() - started) * 1_000, 3),
            )
        return True

    async def _acquire_single_writer_lock(self, session: AsyncSession) -> bool:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            # This branch exists only for isolated SQLite tests. Production is
            # PostgreSQL and always takes the transaction-scoped advisory lock.
            return True
        locked = await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
            {"lock_id": PROCESSOR_ADVISORY_LOCK_ID},
        )
        return bool(locked)

    async def _restore_engine(self, session: AsyncSession, symbol: str) -> MatchingEngine:
        active_records = await session.scalars(
            select(OrderRecord)
            .where(
                OrderRecord.symbol == symbol,
                OrderRecord.status.in_(
                    (
                        PersistedOrderStatus.OPEN,
                        PersistedOrderStatus.PARTIALLY_FILLED,
                    )
                ),
            )
            .order_by(OrderRecord.sequence)
        )
        active_orders = [
            LimitOrder(
                order_id=record.order_id,
                side=Side(record.side.value),
                price=record.price,
                quantity=record.quantity,
                sequence=record.sequence,
                remaining_quantity=record.remaining_quantity,
                status=OrderStatus(record.status.value),
            )
            for record in active_records
        ]
        last_trade_sequence = await session.scalar(
            select(func.coalesce(func.max(TradeRecord.trade_sequence), 0)).where(
                TradeRecord.symbol == symbol
            )
        )
        return MatchingEngine.restore(
            active_orders,
            next_trade_sequence=int(last_trade_sequence or 0) + 1,
        )

    async def _apply_command(self, session: AsyncSession, command: MarketCommand) -> dict[str, Any]:
        engine = await self._restore_engine(session, command.symbol)

        if command.command_type == CommandType.SUBMIT_ORDER:
            incoming = LimitOrder(
                order_id=command.payload["order_id"],
                side=Side(command.payload["side"]),
                price=int(command.payload["price"]),
                quantity=int(command.payload["quantity"]),
                sequence=command.sequence,
            )
            result = engine.submit(incoming)
            changed_orders = (*result.changed_orders, result.order)
            trades = result.trades
            snapshot = result.snapshot
            event_type = MarketEventType.ORDER_ACCEPTED
        elif command.command_type == CommandType.CANCEL_ORDER:
            cancelled = engine.cancel(command.payload["order_id"])
            changed_orders = (cancelled,)
            trades = ()
            snapshot = engine.snapshot()
            event_type = MarketEventType.ORDER_CANCELLED
        else:  # pragma: no cover - protected by the database enum
            raise RuntimeError(f"unsupported command type: {command.command_type}")

        for order in changed_orders:
            await self._persist_order(session, command.symbol, order)

        trade_records: list[TradeRecord] = []
        for trade in trades:
            record = TradeRecord(
                symbol=command.symbol,
                trade_sequence=trade.sequence,
                command_sequence=command.sequence,
                maker_order_id=trade.maker_order_id,
                taker_order_id=trade.taker_order_id,
                maker_side=PersistedSide(trade.maker_side.value),
                price=trade.price,
                quantity=trade.quantity,
            )
            session.add(record)
            trade_records.append(record)

        event_payload = {
            "command_id": command.command_id,
            "correlation_id": command.correlation_id,
            "order_id": command.payload["order_id"],
            "orders": [_order_payload(order) for order in changed_orders],
            "trades": [_trade_payload(trade) for trade in trades],
        }
        event = MarketEvent(
            command_sequence=command.sequence,
            symbol=command.symbol,
            event_type=event_type,
            payload=event_payload,
        )
        session.add(event)
        command.status = CommandStatus.COMPLETED
        command.completed_at = datetime.now(UTC)
        await session.flush()
        await notify_market_event(session, symbol=command.symbol, event_id=event.event_id)

        command.result = {
            "event_id": event.event_id,
            "order_ids": [order.order_id for order in changed_orders],
            "trade_sequences": [trade.sequence for trade in trades],
        }
        return StreamUpdate(
            symbol=command.symbol,
            sequence=command.sequence,
            event_id=event.event_id,
            event_type=event.event_type.value,
            payload=event_payload,
            book=_book_from_engine(command.symbol, command.sequence, event.event_id, snapshot),
            trades=[TradeResponse.model_validate(record) for record in trade_records],
        ).model_dump(mode="json")

    async def _persist_order(self, session: AsyncSession, symbol: str, order: LimitOrder) -> None:
        record = await session.get(OrderRecord, order.order_id)
        if record is None:
            record = OrderRecord(
                order_id=order.order_id,
                symbol=symbol,
                side=PersistedSide(order.side.value),
                price=order.price,
                quantity=order.quantity,
                remaining_quantity=order.remaining_quantity,
                sequence=order.sequence,
                status=PersistedOrderStatus(order.status.value),
            )
            session.add(record)
            return

        record.remaining_quantity = order.remaining_quantity
        record.status = PersistedOrderStatus(order.status.value)

    async def _reject_command(
        self,
        session: AsyncSession,
        command: MarketCommand,
        error: EngineError,
    ) -> dict[str, Any]:
        """Record a domain rejection and advance rather than stall the queue."""

        command.status = CommandStatus.REJECTED
        command.error_code = error.__class__.__name__
        command.error_message = str(error)
        command.completed_at = datetime.now(UTC)
        payload = {
            "command_id": command.command_id,
            "correlation_id": command.correlation_id,
            "order_id": command.payload.get("order_id"),
            "error_code": command.error_code,
            "error_message": command.error_message,
        }
        event = MarketEvent(
            command_sequence=command.sequence,
            symbol=command.symbol,
            event_type=MarketEventType.COMMAND_REJECTED,
            payload=payload,
        )
        session.add(event)
        await session.flush()
        await notify_market_event(session, symbol=command.symbol, event_id=event.event_id)
        command.result = {"event_id": event.event_id}

        engine = await self._restore_engine(session, command.symbol)
        return StreamUpdate(
            symbol=command.symbol,
            sequence=command.sequence,
            event_id=event.event_id,
            event_type=event.event_type.value,
            payload=payload,
            book=_book_from_engine(
                command.symbol,
                command.sequence,
                event.event_id,
                engine.snapshot(),
            ),
            trades=[],
        ).model_dump(mode="json")
