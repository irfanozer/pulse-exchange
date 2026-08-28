"""Bound the public demo by resetting and truthfully reseeding market state.

The production deployment runs this module as a scheduled Container Apps job.
It coordinates with the matching service's PostgreSQL advisory lock, removes
only fictional simulator rows, preserves monotonically increasing database
identities, and then rebuilds the starter markets through the public API.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text

from pulseexchange.config import Settings, get_settings
from pulseexchange.database import create_engine
from pulseexchange.processor import PROCESSOR_ADVISORY_LOCK_ID
from pulseexchange.seed import SeedError
from pulseexchange.seed import run as seed_market


async def reset_demo_state(settings: Settings | None = None) -> None:
    """Atomically remove fictional market rows while the processor is paused."""

    resolved = settings or get_settings()
    engine = create_engine(resolved)
    try:
        async with engine.begin() as connection:
            # The matching service takes the same transaction-scoped lock for
            # each command. Waiting here prevents a half-reset market without
            # introducing a second coordination system.
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": PROCESSOR_ADVISORY_LOCK_ID},
            )
            # Do not RESTART IDENTITY. WebSocket event cursors must continue to
            # move forward so connected clients can observe the fresh seed.
            await connection.execute(
                text("TRUNCATE TABLE market_events, trades, orders, market_commands")
            )
    finally:
        await engine.dispose()


def _reseed_enabled() -> bool:
    value = os.getenv("PULSEEXCHANGE_MAINTENANCE_RESEED", "true").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError("PULSEEXCHANGE_MAINTENANCE_RESEED must be true or false")


def run() -> None:
    asyncio.run(reset_demo_state())
    print("RESET fictional PulseExchange market state")
    if _reseed_enabled():
        seed_market()
        print("RESEEDED starter markets through the public order API")


def main() -> None:
    try:
        run()
    except (SeedError, ValueError) as error:
        print(f"MARKET MAINTENANCE FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
