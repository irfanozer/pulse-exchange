"""Small, explicit public-demo resource limits."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from pulseexchange.config import Settings


class MutationRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        max_client_keys: int = 10_000,
    ) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._max_client_keys = max_client_keys
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._guard = asyncio.Lock()
        self._last_cleanup = 0.0

    async def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        async with self._guard:
            if now - self._last_cleanup >= self._window_seconds:
                for existing_key, existing_timestamps in tuple(self._requests.items()):
                    while existing_timestamps and existing_timestamps[0] <= cutoff:
                        existing_timestamps.popleft()
                    if not existing_timestamps:
                        self._requests.pop(existing_key, None)
                self._last_cleanup = now
            if key not in self._requests and len(self._requests) >= self._max_client_keys:
                # Unknown clients share one bounded overflow bucket instead of
                # growing memory without limit during abusive traffic.
                key = "__overflow__"
            timestamps = self._requests[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self._limit:
                retry_after = max(1, int(self._window_seconds - (now - timestamps[0])))
                return False, retry_after
            timestamps.append(now)
            return True, 0


def _client_key(request: Request, *, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        forwarded = request.headers.get("X-Real-IP") or request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",", maxsplit=1)[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


class DemoSafetyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings
        self._limiter = MutationRateLimiter(
            settings.mutation_rate_limit,
            settings.mutation_rate_window_seconds,
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        is_mutation = request.method in {"POST", "DELETE"} and request.url.path.startswith(
            "/api/v1/"
        )
        if not is_mutation:
            return await call_next(request)

        content_length = request.headers.get("Content-Length")
        if content_length is not None:
            try:
                too_large = int(content_length) > self._settings.max_request_body_bytes
            except ValueError:
                too_large = True
            if too_large:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "request body exceeds the public demo limit"},
                )

        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > self._settings.max_request_body_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "request body exceeds the public demo limit"},
                )
            body.extend(chunk)
        # Starlette will replay this bounded body to FastAPI's parser.
        request._body = bytes(body)

        allowed, retry_after = await self._limiter.allow(
            _client_key(
                request,
                trust_proxy_headers=self._settings.trust_proxy_headers,
            )
        )
        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "public demo request rate exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
