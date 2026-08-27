"""Process-local fan-out for committed market events.

The database remains the source of truth.  Slow clients receive an explicit
resynchronization marker and the WebSocket route sends them a fresh snapshot.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pulseexchange.observability import StreamStats


class StreamCapacityError(Exception):
    """The public demo has reached its configured live-client limit."""


class MarketBroadcaster:
    def __init__(
        self,
        queue_size: int = 128,
        *,
        max_connections: int = 10_000,
        stats: StreamStats | None = None,
    ) -> None:
        self._queue_size = queue_size
        self._max_connections = max_connections
        self._stats = stats
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._guard = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return sum(len(queues) for queues in self._subscribers.values())

    @asynccontextmanager
    async def subscribe(self, symbol: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        async with self._guard:
            if self.connection_count >= self._max_connections:
                raise StreamCapacityError("live stream connection limit reached")
            self._subscribers[symbol].add(queue)
            if self._stats is not None:
                self._stats.connected_client()
        try:
            yield queue
        finally:
            async with self._guard:
                self._subscribers[symbol].discard(queue)
                if self._stats is not None:
                    self._stats.disconnected_client()
                if not self._subscribers[symbol]:
                    self._subscribers.pop(symbol, None)

    async def publish(self, symbol: str, update: dict[str, Any]) -> None:
        async with self._guard:
            subscribers = tuple(self._subscribers.get(symbol, ()))
        for queue in subscribers:
            if queue.full():
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                queue.put_nowait({"type": "resync_required", "symbol": symbol})
            else:
                queue.put_nowait(update)
