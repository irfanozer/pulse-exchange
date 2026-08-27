"""PulseExchange FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pulseexchange.api.routes import router
from pulseexchange.broadcast import MarketBroadcaster
from pulseexchange.commands import IdempotencyConflictError, QueueCapacityError
from pulseexchange.config import Settings, get_settings
from pulseexchange.database import create_engine, create_session_factory
from pulseexchange.notifications import PostgresMarketListener
from pulseexchange.observability import (
    CorrelationMiddleware,
    HttpMetrics,
    SecurityHeadersMiddleware,
    StreamStats,
    configure_logging,
)
from pulseexchange.processor import CommandProcessor
from pulseexchange.safety import DemoSafetyMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(resolved)
        session_factory = create_session_factory(engine)
        stream_stats = StreamStats()
        broadcaster = MarketBroadcaster(
            resolved.websocket_queue_size,
            max_connections=resolved.max_websocket_connections,
            stats=stream_stats,
        )
        event_relay = PostgresMarketListener(resolved, broadcaster)
        processor = (
            CommandProcessor(session_factory, broadcaster, resolved)
            if resolved.processor_enabled
            else None
        )

        app.state.settings = resolved
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.broadcaster = broadcaster
        app.state.processor = processor
        app.state.event_relay = event_relay
        app.state.stream_stats = stream_stats

        processor_task: asyncio.Task[None] | None = None
        relay_task: asyncio.Task[None] | None = None
        if processor is not None:
            processor_task = asyncio.create_task(
                processor.run(), name="pulseexchange-command-processor"
            )
        if resolved.event_relay_enabled:
            relay_task = asyncio.create_task(
                event_relay.run(), name="pulseexchange-market-event-relay"
            )
        try:
            yield
        finally:
            if processor is not None:
                processor.stop()
            event_relay.stop()
            if processor_task is not None:
                try:
                    await asyncio.wait_for(processor_task, timeout=5)
                except TimeoutError:
                    processor_task.cancel()
                    await asyncio.gather(processor_task, return_exceptions=True)
            if relay_task is not None:
                try:
                    await asyncio.wait_for(relay_task, timeout=5)
                except TimeoutError:
                    relay_task.cancel()
                    await asyncio.gather(relay_task, return_exceptions=True)
            await engine.dispose()

    app = FastAPI(
        title=resolved.app_name,
        version="0.1.0",
        description=(
            "A deterministic fictional exchange demonstrating ordered command "
            "processing, concurrency safety, and real-time market updates."
        ),
        lifespan=lifespan,
    )
    http_metrics = HttpMetrics()
    app.state.http_metrics = http_metrics
    app.add_middleware(DemoSafetyMiddleware, settings=resolved)
    app.add_middleware(CorrelationMiddleware, metrics=http_metrics)
    app.add_middleware(SecurityHeadersMiddleware)
    # CORS is registered last so it remains the outermost wrapper and adds
    # headers even to safety-limit and exception responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Correlation-ID"],
        expose_headers=["Location", "X-Correlation-ID"],
    )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(
        _request: Request, error: IdempotencyConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(error)},
        )

    @app.exception_handler(QueueCapacityError)
    async def queue_capacity(_request: Request, error: QueueCapacityError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(error)},
            headers={"Retry-After": "1"},
        )

    app.include_router(router)
    return app


configure_logging()
app = create_app()
