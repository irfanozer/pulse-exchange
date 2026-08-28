"""Independent ordered command processor process."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from functools import partial

from pulseexchange.config import Settings, get_settings
from pulseexchange.database import create_engine, create_session_factory
from pulseexchange.observability import configure_logging
from pulseexchange.processor import CommandProcessor


async def _health_response(
    processor: CommandProcessor,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Serve tiny internal liveness/readiness responses for platform probes."""

    status_code = 503
    reason = "Service Unavailable"
    body = b"not ready\n"
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=2)
        parts = request_line.decode("ascii", errors="replace").split()
        path = parts[1] if len(parts) >= 2 else ""
        if path == "/live" and processor.running:
            status_code, reason, body = 200, "OK", b"ok\n"
        elif path == "/ready" and processor.running and processor.heartbeat_fresh:
            status_code, reason, body = 200, "OK", b"ready\n"
    except TimeoutError:
        pass

    writer.write(
        (
            f"HTTP/1.1 {status_code} {reason}\r\n"
            "Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        + body
    )
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def run_worker(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    engine = create_engine(resolved)
    session_factory = create_session_factory(engine)
    processor = CommandProcessor(session_factory, resolved)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signum, processor.stop)

    health_server = await asyncio.start_server(
        partial(_health_response, processor),
        host="0.0.0.0",
        port=resolved.worker_health_port,
    )
    try:
        async with health_server:
            await processor.run()
    finally:
        health_server.close()
        await health_server.wait_closed()
        await engine.dispose()


def main() -> None:
    configure_logging()
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
