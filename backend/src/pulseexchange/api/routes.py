"""Public HTTP and WebSocket interface."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulseexchange.broadcast import MarketBroadcaster
from pulseexchange.commands import enqueue_cancel, enqueue_submit
from pulseexchange.database import session_dependency
from pulseexchange.market_data import (
    build_book,
    build_stream_snapshot,
    latest_market_event_id,
    recent_trades,
)
from pulseexchange.models import MarketCommand, OrderRecord
from pulseexchange.schemas import (
    SUPPORTED_SYMBOLS,
    BookResponse,
    CommandResponse,
    HealthResponse,
    OrderResponse,
    QueuedCommandResponse,
    StreamHeartbeat,
    StreamSnapshot,
    SubmitOrderRequest,
    TradeResponse,
    TradesResponse,
)

router = APIRouter()
api = APIRouter(prefix="/api/v1")
IDEMPOTENCY_KEY = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=200,
        description="A caller-generated key reused when retrying this exact request.",
    ),
]
SESSION = Annotated[AsyncSession, Depends(session_dependency)]
SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9._-]{1,11}$")


def normalize_symbol(symbol: str) -> str:
    clean = symbol.upper()
    if not SYMBOL_PATTERN.fullmatch(clean) or clean not in SUPPORTED_SYMBOLS:
        raise HTTPException(status_code=422, detail="symbol must be NOVA or ORBIT")
    return clean


def _is_new_event(update: dict[str, object], current_event_id: int) -> bool:
    """Reject notifications already represented by the last snapshot/update."""

    event_id = update.get("event_id")
    return isinstance(event_id, int) and event_id > current_event_id


@router.get("/health/live", response_model=HealthResponse, tags=["health"])
async def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse, tags=["health"])
async def ready_with_request(request: Request) -> HealthResponse:
    processor = request.app.state.processor
    try:
        async with request.app.state.session_factory() as session:
            # A successful connection is not enough: the service is only ready
            # after Alembic has installed the application schema.
            await session.execute(select(MarketCommand.sequence).limit(1))
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="database is not ready") from error
    if request.app.state.settings.processor_enabled and not processor.running:
        raise HTTPException(status_code=503, detail="command processor is not running")
    return HealthResponse(status="ok", processor_running=processor.running)


@api.post(
    "/orders",
    response_model=QueuedCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["orders"],
)
async def submit_order(
    body: SubmitOrderRequest,
    idempotency_key: IDEMPOTENCY_KEY,
    response: Response,
    session: SESSION,
) -> QueuedCommandResponse:
    command = await enqueue_submit(
        session,
        idempotency_key=idempotency_key,
        symbol=body.symbol,
        side=body.side,
        price=body.price,
        quantity=body.quantity,
    )
    response.headers["Location"] = f"/api/v1/commands/{command.command_id}"
    return QueuedCommandResponse.from_command(command)


@api.delete(
    "/orders/{order_id}",
    response_model=QueuedCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["orders"],
)
async def cancel_order(
    order_id: str,
    idempotency_key: IDEMPOTENCY_KEY,
    response: Response,
    session: SESSION,
    symbol: str = Query(..., min_length=2, max_length=12),
) -> QueuedCommandResponse:
    command = await enqueue_cancel(
        session,
        idempotency_key=idempotency_key,
        symbol=normalize_symbol(symbol),
        order_id=order_id,
    )
    response.headers["Location"] = f"/api/v1/commands/{command.command_id}"
    return QueuedCommandResponse.from_command(command)


@api.get("/orders/{order_id}", response_model=OrderResponse, tags=["orders"])
async def get_order(
    order_id: str,
    session: SESSION,
) -> OrderResponse:
    order = await session.get(OrderRecord, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return OrderResponse.model_validate(order)


@api.get("/commands/{command_id}", response_model=CommandResponse, tags=["commands"])
async def get_command(
    command_id: str,
    session: SESSION,
) -> CommandResponse:
    command = await session.scalar(
        select(MarketCommand).where(MarketCommand.command_id == command_id)
    )
    if command is None:
        raise HTTPException(status_code=404, detail="command not found")
    return CommandResponse.model_validate(command)


@api.get("/markets/{symbol}/book", response_model=BookResponse, tags=["markets"])
async def get_book(
    symbol: str,
    session: SESSION,
) -> BookResponse:
    return await build_book(session, normalize_symbol(symbol))


@api.get("/markets/{symbol}/trades", response_model=TradesResponse, tags=["markets"])
async def get_trades(
    symbol: str,
    session: SESSION,
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None, ge=1),
) -> TradesResponse:
    items = await recent_trades(
        session,
        normalize_symbol(symbol),
        limit=limit + 1,
        before=before,
    )
    has_more = len(items) > limit
    page = items[:limit]
    return TradesResponse(
        items=[TradeResponse.model_validate(item) for item in page],
        next_before=page[-1].trade_id if has_more and page else None,
    )


@api.websocket("/markets/{symbol}/stream")
async def market_stream(
    websocket: WebSocket,
    symbol: str,
    after_event_id: int | None = Query(default=None, ge=0),
) -> None:
    try:
        clean_symbol = normalize_symbol(symbol)
    except HTTPException:
        await websocket.close(code=1008, reason="invalid market symbol")
        return

    session_factory: async_sessionmaker[AsyncSession] = websocket.app.state.session_factory
    broadcaster: MarketBroadcaster = websocket.app.state.broadcaster
    heartbeat_seconds: float = websocket.app.state.settings.websocket_heartbeat_seconds
    replay_limit: int = websocket.app.state.settings.websocket_replay_limit
    await websocket.accept()

    async with broadcaster.subscribe(clean_symbol) as queue:
        snapshot = await _send_snapshot(
            websocket,
            session_factory,
            clean_symbol,
            after_event_id=after_event_id,
            replay_limit=replay_limit,
        )
        sequence = snapshot.book.sequence
        event_id = snapshot.book.event_id
        try:
            while True:
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                except TimeoutError:
                    durable_event_id = await _read_latest_event_id(session_factory, clean_symbol)
                    if durable_event_id > event_id:
                        snapshot = await _send_snapshot(
                            websocket,
                            session_factory,
                            clean_symbol,
                            after_event_id=event_id,
                            replay_limit=replay_limit,
                        )
                        sequence = snapshot.book.sequence
                        event_id = snapshot.book.event_id
                        continue
                    await websocket.send_json(
                        StreamHeartbeat(
                            symbol=clean_symbol,
                            sequence=sequence,
                            event_id=event_id,
                            emitted_at=datetime.now(UTC),
                        ).model_dump(mode="json")
                    )
                    continue

                if update.get("type") == "resync_required":
                    snapshot = await _send_snapshot(
                        websocket,
                        session_factory,
                        clean_symbol,
                        after_event_id=event_id,
                        replay_limit=replay_limit,
                    )
                    sequence = snapshot.book.sequence
                    event_id = snapshot.book.event_id
                    continue

                # Subscription is established before the snapshot to avoid a
                # lost-update window. An update may therefore already be
                # included in that snapshot and must not regress the book.
                if not _is_new_event(update, event_id):
                    continue
                sequence = int(update["sequence"])
                event_id = int(update["event_id"])
                await websocket.send_json(update)
        except WebSocketDisconnect:
            return


async def _send_snapshot(
    websocket: WebSocket,
    session_factory: async_sessionmaker[AsyncSession],
    symbol: str,
    *,
    after_event_id: int | None,
    replay_limit: int,
) -> StreamSnapshot:
    async with session_factory() as session:
        snapshot = await build_stream_snapshot(
            session,
            symbol,
            after_event_id=after_event_id,
            replay_limit=replay_limit,
        )
    await websocket.send_json(snapshot.model_dump(mode="json"))
    return snapshot


async def _read_latest_event_id(
    session_factory: async_sessionmaker[AsyncSession], symbol: str
) -> int:
    async with session_factory() as session:
        return await latest_market_event_id(session, symbol)


router.include_router(api)
