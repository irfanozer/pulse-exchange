"""Independent ordered command processor process."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from pulseexchange.config import Settings, get_settings
from pulseexchange.database import create_engine, create_session_factory
from pulseexchange.observability import configure_logging
from pulseexchange.processor import CommandProcessor


async def run_worker(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    engine = create_engine(resolved)
    session_factory = create_session_factory(engine)
    processor = CommandProcessor(session_factory, resolved)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signum, processor.stop)

    try:
        await processor.run()
    finally:
        await engine.dispose()


def main() -> None:
    configure_logging()
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
