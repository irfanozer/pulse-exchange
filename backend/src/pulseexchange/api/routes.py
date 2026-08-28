"""Public HTTP and WebSocket interface."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

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
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulseexchange.broadcast import MarketBroadcaster, StreamCapacityError
from pulseexchange.commands import enqueue_cancel, enqueue_submit
from pulseexchange.database import session_dependency
from pulseexchange.diagnostics import build_diagnostics_summary
from pulseexchange.market_data import (
    build_book,
    build_stream_snapshot,
    latest_market_event_id,
    recent_trades,
)
from pulseexchange.market_profiles import MARKET_PROFILES, SUPPORTED_SYMBOLS
from pulseexchange.models import MarketCommand, OrderRecord
from pulseexchange.observability import StreamStats
from pulseexchange.runtime import PROCESSOR_SERVICE, latest_heartbeat
from pulseexchange.schemas import (
    BookResponse,
    CommandResponse,
    DiagnosticsSummary,
    HealthResponse,
    MarketProfileResponse,
    MarketsResponse,
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
    processor = getattr(request.app.state, "processor", None)
    event_relay = getattr(request.app.state, "event_relay", None)
    processor_heartbeat = None
    try:
        async with request.app.state.session_factory() as session:
            # A successful connection is not enough: the service is only ready
            # after Alembic has installed the application schema.
            await session.execute(select(MarketCommand.sequence).limit(1))
            if processor is None:
                processor_heartbeat = await latest_heartbeat(session, PROCESSOR_SERVICE)
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="database is not ready") from error
    if request.app.state.settings.processor_enabled and (
        processor is None or not processor.running
    ):
        raise HTTPException(status_code=503, detail="command processor is not running")
    if (
        request.app.state.settings.event_relay_enabled
        and event_relay is not None
        and not event_relay.running
    ):
        raise HTTPException(status_code=503, detail="market event relay is not running")
    processor_running = processor.running if processor is not None else False
    if processor_heartbeat is not None:
        heartbeat_age = datetime.now(UTC) - processor_heartbeat.last_seen_at
        processor_running = (
            heartbeat_age.total_seconds()
            <= request.app.state.settings.processor_heartbeat_stale_seconds
        )
    if request.app.state.settings.require_processor_for_readiness and not processor_running:
        raise HTTPException(status_code=503, detail="command processor is not ready")
    return HealthResponse(
        status="ok",
        processor_running=processor_running,
        event_relay_running=event_relay.running if event_relay is not None else None,
    )


@api.get(
    "/diagnostics/summary",
    response_model=DiagnosticsSummary,
    tags=["diagnostics"],
)
async def diagnostics_summary(request: Request, session: SESSION) -> DiagnosticsSummary:
    return await build_diagnostics_summary(
        session,
        request.app.state.settings,
        request.app.state.stream_stats,
    )


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(request: Request, session: SESSION) -> PlainTextResponse:
    summary = await build_diagnostics_summary(
        session,
        request.app.state.settings,
        request.app.state.stream_stats,
    )
    http = request.app.state.http_metrics.snapshot()
    lines = [
        "# HELP pulseexchange_http_requests_total HTTP requests handled by this API process.",
        "# TYPE pulseexchange_http_requests_total counter",
    ]
    for (method, status_code), count in sorted(http.by_status.items()):
        lines.append(
            f'pulseexchange_http_requests_total{{method="{method}",status="{status_code}"}} {count}'
        )
    lines.extend(
        [
            "# HELP pulseexchange_http_request_duration_milliseconds_sum Total request time.",
            "# TYPE pulseexchange_http_request_duration_milliseconds_sum counter",
            f"pulseexchange_http_request_duration_milliseconds_sum {http.duration_ms_sum}",
            "# HELP pulseexchange_command_queue_depth Durable commands waiting for processing.",
            "# TYPE pulseexchange_command_queue_depth gauge",
            f"pulseexchange_command_queue_depth {summary.queue.depth}",
            "# HELP pulseexchange_websocket_connections Current WebSocket clients.",
            "# TYPE pulseexchange_websocket_connections gauge",
            f"pulseexchange_websocket_connections {summary.streams.connected}",
            (
                "# HELP pulseexchange_stream_recovered_events_total "
                "Durable events replayed to clients."
            ),
            "# TYPE pulseexchange_stream_recovered_events_total counter",
            f"pulseexchange_stream_recovered_events_total {summary.streams.recovered_events}",
            "# HELP pulseexchange_stream_resyncs_total Authoritative stream resynchronizations.",
            "# TYPE pulseexchange_stream_resyncs_total counter",
            f"pulseexchange_stream_resyncs_total {summary.streams.resyncs}",
            "# HELP pulseexchange_processor_up Whether the processor heartbeat is fresh.",
            "# TYPE pulseexchange_processor_up gauge",
            "pulseexchange_processor_up "
            f"{1 if summary.services.processor.status == 'online' else 0}",
            "# HELP pulseexchange_commands_total Durable commands accepted.",
            "# TYPE pulseexchange_commands_total gauge",
            f"pulseexchange_commands_total {summary.commands.accepted}",
            "# HELP pulseexchange_trades_total Durable trades produced.",
            "# TYPE pulseexchange_trades_total gauge",
            f"pulseexchange_trades_total {summary.market.trades}",
        ]
    )
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@api.post(
    "/orders",
    response_model=QueuedCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["orders"],
)
async def submit_order(
    body: SubmitOrderRequest,
    request: Request,
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
        correlation_id=request.state.correlation_id,
        max_queued_commands=request.app.state.settings.max_queued_commands,
        max_total_commands=request.app.state.settings.max_total_commands,
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
    request: Request,
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
        correlation_id=request.state.correlation_id,
        max_queued_commands=request.app.state.settings.max_queued_commands,
        max_total_commands=request.app.state.settings.max_total_commands,
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


@api.get("/markets", response_model=MarketsResponse, tags=["markets"])
async def list_markets() -> MarketsResponse:
    """Describe the independent fictional instruments shown by the demo."""

    return MarketsResponse(
        items=[
            MarketProfileResponse.model_validate(profile) for profile in MARKET_PROFILES.values()
        ]
    )


@api.get("/markets/{symbol}", response_model=MarketProfileResponse, tags=["markets"])
async def get_market(symbol: str) -> MarketProfileResponse:
    """Return the display profile for one fictional instrument."""

    return MarketProfileResponse.model_validate(MARKET_PROFILES[normalize_symbol(symbol)])


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
    origin = getattr(websocket, "headers", {}).get("origin")
    allowed_origins: list[str] = websocket.app.state.settings.websocket_origins
    if origin is not None and origin not in allowed_origins:
        await websocket.close(code=1008, reason="websocket origin is not allowed")
        return
    try:
        clean_symbol = normalize_symbol(symbol)
    except HTTPException:
        await websocket.close(code=1008, reason="invalid market symbol")
        return

    session_factory: async_sessionmaker[AsyncSession] = websocket.app.state.session_factory
    broadcaster: MarketBroadcaster = websocket.app.state.broadcaster
    heartbeat_seconds: float = websocket.app.state.settings.websocket_heartbeat_seconds
    replay_limit: int = websocket.app.state.settings.websocket_replay_limit
    stream_stats = websocket.app.state.stream_stats
    await websocket.accept()

    try:
        async with broadcaster.subscribe(clean_symbol) as queue:
            await _consume_market_stream(
                websocket,
                queue,
                session_factory,
                clean_symbol,
                after_event_id=after_event_id,
                replay_limit=replay_limit,
                heartbeat_seconds=heartbeat_seconds,
                stream_stats=stream_stats,
            )
    except StreamCapacityError:
        await websocket.close(code=1013, reason="live stream connection limit reached")


async def _consume_market_stream(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any]],
    session_factory: async_sessionmaker[AsyncSession],
    symbol: str,
    *,
    after_event_id: int | None,
    replay_limit: int,
    heartbeat_seconds: float,
    stream_stats: StreamStats,
) -> None:
    snapshot = await _send_snapshot(
        websocket,
        session_factory,
        symbol,
        after_event_id=after_event_id,
        replay_limit=replay_limit,
        delivery_reason="reconnect" if after_event_id is not None else "initial",
    )
    if snapshot.delivery_reason == "reconnect":
        stream_stats.recovered(len(snapshot.recovered_events))
    sequence = snapshot.book.sequence
    event_id = snapshot.book.event_id
    try:
        while True:
            try:
                update = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                durable_event_id = await _read_latest_event_id(session_factory, symbol)
                if durable_event_id > event_id:
                    snapshot = await _send_snapshot(
                        websocket,
                        session_factory,
                        symbol,
                        after_event_id=event_id,
                        replay_limit=replay_limit,
                        delivery_reason="recovery",
                    )
                    stream_stats.resynchronized()
                    stream_stats.recovered(len(snapshot.recovered_events))
                    sequence = snapshot.book.sequence
                    event_id = snapshot.book.event_id
                    continue
                await websocket.send_json(
                    StreamHeartbeat(
                        symbol=symbol,
                        sequence=sequence,
                        event_id=event_id,
                        emitted_at=datetime.now(UTC),
                    ).model_dump(mode="json")
                )
                continue

            update_type = update.get("type")
            if update_type in {"live_refresh_required", "resync_required"}:
                is_recovery = update_type == "resync_required"
                if is_recovery:
                    stream_stats.resynchronized()
                snapshot = await _send_snapshot(
                    websocket,
                    session_factory,
                    symbol,
                    after_event_id=event_id,
                    replay_limit=replay_limit,
                    delivery_reason="recovery" if is_recovery else "live_refresh",
                )
                if is_recovery:
                    stream_stats.recovered(len(snapshot.recovered_events))
                sequence = snapshot.book.sequence
                event_id = snapshot.book.event_id
                continue

            # Subscription is established before the snapshot to avoid a
            # lost-update window. An update may therefore already be included
            # in that snapshot and must not regress the book.
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
    delivery_reason: Literal["initial", "live_refresh", "reconnect", "recovery"] = "initial",
) -> StreamSnapshot:
    async with session_factory() as session:
        snapshot = await build_stream_snapshot(
            session,
            symbol,
            after_event_id=after_event_id,
            replay_limit=replay_limit,
        )
    snapshot.delivery_reason = delivery_reason
    await websocket.send_json(snapshot.model_dump(mode="json"))
    return snapshot


async def _read_latest_event_id(
    session_factory: async_sessionmaker[AsyncSession], symbol: str
) -> int:
    async with session_factory() as session:
        return await latest_market_event_id(session, symbol)


router.include_router(api)
