"""Transactional PostgreSQL notifications and API-side event relay."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from pulseexchange.broadcast import MarketBroadcaster
from pulseexchange.config import Settings

logger = logging.getLogger(__name__)
MARKET_EVENTS_CHANNEL = "pulseexchange_market_events"


async def notify_market_event(session: AsyncSession, *, symbol: str, event_id: int) -> None:
    """Queue a small notification that PostgreSQL emits only after commit."""

    if session.get_bind().dialect.name != "postgresql":
        return
    payload = json.dumps({"symbol": symbol, "event_id": event_id}, separators=(",", ":"))
    await session.execute(
        text(f"SELECT pg_notify('{MARKET_EVENTS_CHANNEL}', :payload)"),
        {"payload": payload},
    )


def asyncpg_dsn(database_url: str) -> str:
    """Convert SQLAlchemy's async driver URL into an asyncpg DSN."""

    url = make_url(database_url).set(drivername="postgresql")
    query = dict(url.query)
    ssl_mode = query.pop("ssl", None)
    if ssl_mode is not None:
        query.setdefault("sslmode", ssl_mode)
    url = url.set(query=query)
    return url.render_as_string(hide_password=False)


class PostgresMarketListener:
    """Relay database commit hints to WebSocket clients in this API process."""

    def __init__(self, settings: Settings, broadcaster: MarketBroadcaster) -> None:
        self._settings = settings
        self._broadcaster = broadcaster
        self._stop = asyncio.Event()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1_024)
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._stop.set()

    def _received(
        self,
        _connection: asyncpg.Connection,
        _pid: int,
        _channel: str,
        payload: str,
    ) -> None:
        try:
            decoded = json.loads(payload)
            symbol = decoded["symbol"]
            event_id = decoded["event_id"]
            if not isinstance(symbol, str) or not isinstance(event_id, int):
                raise ValueError("invalid notification fields")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("ignored invalid market notification", extra={"payload": payload[:200]})
            return

        marker = {"type": "live_refresh_required", "symbol": symbol, "event_id": event_id}
        if self._queue.full():
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        self._queue.put_nowait(marker)

    async def run(self) -> None:
        """Reconnect indefinitely; durable heartbeat polling repairs any missed hint."""

        dsn = asyncpg_dsn(self._settings.database_url)
        while not self._stop.is_set():
            connection: asyncpg.Connection | None = None
            try:
                connection = await asyncpg.connect(dsn)
                await connection.add_listener(MARKET_EVENTS_CHANNEL, self._received)
                self._running = True
                logger.info("market notification relay started")
                while not self._stop.is_set() and not connection.is_closed():
                    try:
                        marker = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                    except TimeoutError:
                        continue
                    await self._broadcaster.publish(str(marker["symbol"]), marker)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market notification relay disconnected")
            finally:
                self._running = False
                if connection is not None and not connection.is_closed():
                    await connection.close()

            if not self._stop.is_set():
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)

        logger.info("market notification relay stopped")
