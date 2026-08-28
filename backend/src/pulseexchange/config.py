"""Runtime configuration loaded from environment variables."""

import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Environment variables use the ``PULSEEXCHANGE_`` prefix.  The committed
    defaults are suitable for running the API against the Compose PostgreSQL
    port from the host. Docker Compose and production supply their own database
    URL and allowed origins.
    """

    model_config = SettingsConfigDict(
        env_prefix="PULSEEXCHANGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PulseExchange"
    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://pulseexchange:pulseexchange@localhost:5433/pulseexchange"
    )
    database_pool_size: int = Field(default=3, ge=1, le=20)
    database_max_overflow: int = Field(default=2, ge=0, le=20)
    database_pool_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3001", "http://localhost:5173"]
    )
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver", "api"]
    )
    websocket_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3001", "http://localhost:5173"]
    )
    processor_poll_interval_ms: int = Field(default=150, ge=10, le=10_000)
    processor_error_backoff_ms: int = Field(default=1_000, ge=10, le=60_000)
    processor_enabled: bool = False
    event_relay_enabled: bool = True
    processor_heartbeat_interval_seconds: float = Field(default=2.0, ge=0.25, le=60.0)
    processor_heartbeat_stale_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    websocket_heartbeat_seconds: float = Field(default=10.0, ge=0.5, le=300.0)
    websocket_queue_size: int = Field(default=128, ge=1, le=10_000)
    websocket_replay_limit: int = Field(default=100, ge=1, le=1_000)
    max_websocket_connections: int = Field(default=100, ge=1, le=10_000)
    mutation_rate_limit: int = Field(default=60, ge=1, le=100_000)
    mutation_rate_window_seconds: float = Field(default=60.0, ge=1.0, le=3_600.0)
    trust_proxy_headers: bool = False
    max_request_body_bytes: int = Field(default=16_384, ge=512, le=10_000_000)
    max_queued_commands: int = Field(default=1_000, ge=1, le=1_000_000)
    max_total_commands: int = Field(default=100_000, ge=100, le=10_000_000)
    require_processor_for_readiness: bool = False
    worker_health_port: int = Field(default=8002, ge=1_024, le=65_535)

    @field_validator("cors_origins", "allowed_hosts", "websocket_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        """Accept a comma-separated environment variable as well as JSON."""

        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable settings instance."""

    return Settings()
