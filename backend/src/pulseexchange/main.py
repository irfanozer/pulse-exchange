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
from pulseexchange.commands import IdempotencyConflictError
from pulseexchange.config import Settings, get_settings
from pulseexchange.database import create_engine, create_session_factory
from pulseexchange.processor import CommandProcessor


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(resolved)
        session_factory = create_session_factory(engine)
        broadcaster = MarketBroadcaster(resolved.websocket_queue_size)
        processor = CommandProcessor(session_factory, broadcaster, resolved)

        app.state.settings = resolved
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.broadcaster = broadcaster
        app.state.processor = processor

        processor_task: asyncio.Task[None] | None = None
        if resolved.processor_enabled:
            processor_task = asyncio.create_task(
                processor.run(), name="pulseexchange-command-processor"
            )
        try:
            yield
        finally:
            processor.stop()
            if processor_task is not None:
                try:
                    await asyncio.wait_for(processor_task, timeout=5)
                except TimeoutError:
                    processor_task.cancel()
                    await asyncio.gather(processor_task, return_exceptions=True)
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(
        _request: Request, error: IdempotencyConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(error)},
        )

    app.include_router(router)
    return app


app = create_app()
