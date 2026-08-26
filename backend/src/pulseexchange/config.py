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
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )
    processor_poll_interval_ms: int = Field(default=150, ge=10, le=10_000)
    processor_error_backoff_ms: int = Field(default=1_000, ge=10, le=60_000)
    processor_enabled: bool = True
    websocket_heartbeat_seconds: float = 10.0
    websocket_queue_size: int = 128
    websocket_replay_limit: int = Field(default=100, ge=1, le=1_000)

    @field_validator("cors_origins", mode="before")
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
