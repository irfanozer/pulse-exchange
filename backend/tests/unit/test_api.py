"""API surface and readiness tests that do not require a running database."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from pulseexchange.api import routes as routes_module
from pulseexchange.api.routes import (
    _is_new_event,
    api,
    market_stream,
    normalize_symbol,
    ready_with_request,
)
from pulseexchange.broadcast import MarketBroadcaster
from pulseexchange.commands import IdempotencyConflictError
from pulseexchange.config import Settings
from pulseexchange.main import create_app
from pulseexchange.notifications import asyncpg_dsn
from pulseexchange.observability import (
    CorrelationMiddleware,
    HttpMetrics,
    SecurityHeadersMiddleware,
    StreamStats,
    correlation_id_from_header,
)
from pulseexchange.safety import DemoSafetyMiddleware, MutationRateLimiter, _client_key


def test_openapi_exposes_command_market_and_health_routes() -> None:
    app = create_app(Settings(processor_enabled=False))
    paths = app.openapi()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/api/v1/orders" in paths
    assert "/api/v1/orders/{order_id}" in paths
    assert "/api/v1/commands/{command_id}" in paths
    assert "/api/v1/markets" in paths
    assert "/api/v1/markets/{symbol}" in paths
    assert "/api/v1/markets/{symbol}/book" in paths
    assert "/api/v1/markets/{symbol}/trades" in paths
    assert "/api/v1/diagnostics/summary" in paths


def test_local_database_default_matches_compose_host_port() -> None:
    default_database_url = Settings.model_fields["database_url"].default

    assert isinstance(default_database_url, str)
    assert "@localhost:5433/" in default_database_url


def test_database_url_can_be_overridden_by_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ci_database_url = (
        "postgresql+asyncpg://pulseexchange:pulseexchange@localhost:5432/pulseexchange_test"
    )
    monkeypatch.setenv("PULSEEXCHANGE_DATABASE_URL", ci_database_url)

    assert Settings(_env_file=None).database_url == ci_database_url


def test_cors_origins_accept_json_or_comma_separated_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PULSEEXCHANGE_CORS_ORIGINS", "http://one.test,http://two.test")
    assert Settings(_env_file=None).cors_origins == ["http://one.test", "http://two.test"]

    monkeypatch.setenv(
        "PULSEEXCHANGE_CORS_ORIGINS", '["http://json-one.test","http://json-two.test"]'
    )
    assert Settings(_env_file=None).cors_origins == [
        "http://json-one.test",
        "http://json-two.test",
    ]


def test_submit_and_cancel_require_idempotency_keys() -> None:
    schema = create_app(Settings(processor_enabled=False)).openapi()
    post_parameters = schema["paths"]["/api/v1/orders"]["post"]["parameters"]
    delete_parameters = schema["paths"]["/api/v1/orders/{order_id}"]["delete"]["parameters"]

    assert any(
        parameter["name"] == "Idempotency-Key" and parameter["required"]
        for parameter in post_parameters
    )
    assert any(
        parameter["name"] == "Idempotency-Key" and parameter["required"]
        for parameter in delete_parameters
    )


def test_websocket_market_stream_is_registered() -> None:
    websocket_paths = {getattr(route, "path", None) for route in api.routes}

    assert "/api/v1/markets/{symbol}/stream" in websocket_paths


@pytest.mark.asyncio
async def test_websocket_rejects_an_unapproved_browser_origin() -> None:
    state = SimpleNamespace(
        settings=Settings(
            processor_enabled=False,
            websocket_origins=["https://pulseexchange.example"],
        )
    )

    class _WebSocket:
        def __init__(self) -> None:
            self.app = SimpleNamespace(state=state)
            self.headers = {"origin": "https://attacker.example"}
            self.closed: tuple[int, str] | None = None

        async def close(self, code: int, reason: str) -> None:
            self.closed = (code, reason)

    websocket = _WebSocket()
    await market_stream(cast(Any, websocket), "NOVA")

    assert websocket.closed == (1008, "websocket origin is not allowed")


def test_path_symbols_are_limited_to_documented_fictional_markets() -> None:
    assert normalize_symbol("nova") == "NOVA"
    assert normalize_symbol("orbit") == "ORBIT"
    with pytest.raises(HTTPException, match="NOVA or ORBIT"):
        normalize_symbol("ACME")


def test_app_maps_idempotency_reuse_conflicts_to_http_409() -> None:
    app = create_app(Settings(processor_enabled=False))

    assert IdempotencyConflictError in app.exception_handlers


def test_stream_drops_updates_already_represented_by_snapshot() -> None:
    assert not _is_new_event({"event_id": 9}, current_event_id=9)
    assert not _is_new_event({"event_id": 8}, current_event_id=9)
    assert _is_new_event({"event_id": 10}, current_event_id=9)


class _ReadySession:
    def __init__(self, error: SQLAlchemyError | None = None) -> None:
        self.error = error
        self.statement: Any = None

    async def execute(self, statement: Any) -> None:
        self.statement = statement
        if self.error is not None:
            raise self.error

    async def scalar(self, _statement: Any) -> None:
        return None


def _readiness_request(session: _ReadySession) -> Request:
    @asynccontextmanager
    async def session_context() -> Any:
        yield session

    state = SimpleNamespace(
        processor=SimpleNamespace(running=True),
        session_factory=session_context,
        settings=Settings(processor_enabled=True),
    )
    return cast(Request, SimpleNamespace(app=SimpleNamespace(state=state)))


@pytest.mark.asyncio
async def test_readiness_queries_an_application_table_not_only_the_connection() -> None:
    session = _ReadySession()

    response = await ready_with_request(_readiness_request(session))

    assert response.status == "ok"
    assert "market_commands" in str(session.statement)


@pytest.mark.asyncio
async def test_readiness_rejects_a_connected_database_with_no_schema() -> None:
    request = _readiness_request(_ReadySession(SQLAlchemyError("schema missing")))

    with pytest.raises(HTTPException) as captured:
        await ready_with_request(request)

    assert captured.value.status_code == 503
    assert captured.value.detail == "database is not ready"


@pytest.mark.asyncio
async def test_heartbeat_reads_durable_event_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()

    @asynccontextmanager
    async def session_context() -> Any:
        yield session

    async def durable_cursor(candidate: object, symbol: str) -> int:
        assert candidate is session
        assert symbol == "NOVA"
        return 27

    monkeypatch.setattr(routes_module, "latest_market_event_id", durable_cursor)

    assert await routes_module._read_latest_event_id(session_context, "NOVA") == 27  # type: ignore[arg-type]


def test_asyncpg_dsn_removes_sqlalchemy_driver_name() -> None:
    dsn = asyncpg_dsn("postgresql+asyncpg://user:secret@db:5432/pulse")

    assert dsn == "postgresql://user:secret@db:5432/pulse"


def test_asyncpg_dsn_translates_sqlalchemy_ssl_for_azure() -> None:
    dsn = asyncpg_dsn("postgresql+asyncpg://user:secret@db:5432/pulse?ssl=require")

    assert dsn == "postgresql://user:secret@db:5432/pulse?sslmode=require"


def test_correlation_id_accepts_safe_values_and_replaces_unsafe_values() -> None:
    assert correlation_id_from_header("request_abc-123") == "request_abc-123"
    replacement = correlation_id_from_header("unsafe value with spaces")
    assert replacement != "unsafe value with spaces"
    assert len(replacement) == 36


@pytest.mark.asyncio
async def test_mutation_rate_limiter_returns_retry_after() -> None:
    limiter = MutationRateLimiter(limit=1, window_seconds=60)

    assert await limiter.allow("client") == (True, 0)
    allowed, retry_after = await limiter.allow("client")
    assert not allowed
    assert retry_after > 0


@pytest.mark.asyncio
async def test_mutation_rate_limiter_bounds_unknown_client_storage() -> None:
    limiter = MutationRateLimiter(limit=1, window_seconds=60, max_client_keys=1)

    assert await limiter.allow("known-client") == (True, 0)
    assert await limiter.allow("first-overflow-client") == (True, 0)
    allowed, retry_after = await limiter.allow("second-overflow-client")

    assert not allowed
    assert retry_after > 0
    assert set(limiter._requests) == {"known-client", "__overflow__"}


def test_forwarded_client_identity_requires_explicit_proxy_trust() -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [(b"x-forwarded-for", b"198.51.100.10")],
            "client": ("203.0.113.20", 1234),
            "server": ("testserver", 80),
        }
    )

    assert _client_key(request, trust_proxy_headers=False) == "203.0.113.20"
    assert _client_key(request, trust_proxy_headers=True) == "198.51.100.10"


def test_safety_middleware_replays_bounded_streamed_body_and_rejects_oversize() -> None:
    app = FastAPI()
    app.add_middleware(
        DemoSafetyMiddleware,
        settings=Settings(
            processor_enabled=False,
            max_request_body_bytes=512,
            mutation_rate_limit=10,
        ),
    )

    @app.post("/api/v1/echo")
    async def echo(request: Request) -> dict[str, str]:
        return {"body": (await request.body()).decode()}

    client = TestClient(app)
    accepted = client.post(
        "/api/v1/echo",
        content=iter([b'{"message":', b'"safe"}']),
        headers={"Content-Type": "application/json"},
    )
    rejected = client.post(
        "/api/v1/echo",
        content=iter([b'{"message":"', b"x" * 520, b'"}']),
        headers={"Content-Type": "application/json"},
    )

    assert accepted.status_code == 200
    assert accepted.json() == {"body": '{"message":"safe"}'}
    assert rejected.status_code == 413
    assert rejected.json() == {"detail": "request body exceeds the public demo limit"}


@pytest.mark.asyncio
async def test_websocket_capacity_closes_with_try_again_later() -> None:
    broadcaster = MarketBroadcaster(max_connections=1)
    settings = Settings(processor_enabled=False)
    state = SimpleNamespace(
        broadcaster=broadcaster,
        settings=settings,
        stream_stats=StreamStats(),
        session_factory=None,
    )

    class _WebSocket:
        def __init__(self) -> None:
            self.app = SimpleNamespace(state=state)
            self.accepted = False
            self.closed: tuple[int, str] | None = None

        async def accept(self) -> None:
            self.accepted = True

        async def close(self, code: int, reason: str) -> None:
            self.closed = (code, reason)

    websocket = _WebSocket()
    async with broadcaster.subscribe("ORBIT"):
        await market_stream(cast(Any, websocket), "NOVA")

    assert websocket.accepted
    assert websocket.closed == (1013, "live stream connection limit reached")
    assert state.stream_stats.snapshot().connected == 0


def test_http_correlation_metrics_and_security_headers() -> None:
    app = FastAPI()
    metrics = HttpMetrics()
    app.add_middleware(CorrelationMiddleware, metrics=metrics)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, str]:
        return {"correlation_id": request.state.correlation_id}

    response = TestClient(app).get("/probe", headers={"X-Correlation-ID": "trace-123"})

    assert response.status_code == 200
    assert response.json() == {"correlation_id": "trace-123"}
    assert response.headers["X-Correlation-ID"] == "trace-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert metrics.snapshot().total == 1
