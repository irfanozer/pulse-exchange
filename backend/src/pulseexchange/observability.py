"""Structured request correlation and lightweight stream measurements."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def configure_logging() -> None:
    """Configure machine-readable logs once for both API and worker processes."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def correlation_id_from_header(value: str | None) -> str:
    """Reuse a safe caller trace identifier or generate a new UUID."""

    if value is not None and CORRELATION_PATTERN.fullmatch(value):
        return value
    return str(uuid.uuid4())


class CorrelationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, metrics: HttpMetrics | None = None) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._metrics = metrics

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = correlation_id_from_header(request.headers.get("X-Correlation-ID"))
        request.state.correlation_id = correlation_id
        clear_contextvars()
        bind_contextvars(correlation_id=correlation_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            duration_ms = round((time.perf_counter() - started) * 1_000, 3)
            if self._metrics is not None:
                self._metrics.observe(request.method, status_code, duration_ms)
            structlog.get_logger("pulseexchange.http").info(
                "request_finished",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            clear_contextvars()
        response.headers["X-Correlation-ID"] = correlation_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach browser hardening headers without breaking the interactive API docs."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


@dataclass(slots=True)
class HttpMetricsSnapshot:
    total: int
    duration_ms_sum: float
    by_status: dict[tuple[str, int], int]


class HttpMetrics:
    """Bounded process-local counters exposed in Prometheus text format."""

    def __init__(self) -> None:
        self._total = 0
        self._duration_ms_sum = 0.0
        self._by_status: dict[tuple[str, int], int] = defaultdict(int)

    def observe(self, method: str, status_code: int, duration_ms: float) -> None:
        self._total += 1
        self._duration_ms_sum += duration_ms
        self._by_status[(method, status_code)] += 1

    def snapshot(self) -> HttpMetricsSnapshot:
        return HttpMetricsSnapshot(
            total=self._total,
            duration_ms_sum=round(self._duration_ms_sum, 3),
            by_status=dict(self._by_status),
        )


@dataclass(slots=True)
class StreamStatsSnapshot:
    connected: int
    recovered_events: int
    resyncs: int


class StreamStats:
    """API-process stream counters used by the recruiter-facing diagnostics."""

    def __init__(self) -> None:
        self.connected = 0
        self.recovered_events = 0
        self.resyncs = 0

    def connected_client(self) -> None:
        self.connected += 1

    def disconnected_client(self) -> None:
        self.connected = max(0, self.connected - 1)

    def recovered(self, count: int) -> None:
        self.recovered_events += count

    def resynchronized(self) -> None:
        self.resyncs += 1

    def snapshot(self) -> StreamStatsSnapshot:
        return StreamStatsSnapshot(
            connected=self.connected,
            recovered_events=self.recovered_events,
            resyncs=self.resyncs,
        )
