"""Async SQLAlchemy engine and request-scoped session helpers."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from pulseexchange.config import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base shared by all persisted models."""


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create the application's async database engine."""

    resolved = settings or get_settings()
    return create_async_engine(
        resolved.database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=resolved.database_pool_size,
        max_overflow=resolved.database_max_overflow,
        pool_timeout=resolved.database_pool_timeout_seconds,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create sessions that expire only when explicitly refreshed."""

    return async_sessionmaker(engine, expire_on_commit=False)


async def session_dependency(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a session from the factory installed on FastAPI application state."""

    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session
