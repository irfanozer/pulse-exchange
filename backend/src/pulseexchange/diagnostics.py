"""Database-derived operational evidence for the live demonstration."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pulseexchange.config import Settings
from pulseexchange.market_data import _begin_consistent_read
from pulseexchange.models import (
    CommandStatus,
    MarketCommand,
    MarketEvent,
    OrderRecord,
    TradeRecord,
)
from pulseexchange.observability import StreamStats
from pulseexchange.runtime import PROCESSOR_SERVICE, latest_heartbeat
from pulseexchange.schemas import (
    CommandsDiagnostics,
    DiagnosticsSummary,
    LatencyPercentiles,
    MarketDiagnostics,
    QueueDiagnostics,
    ServicesDiagnostics,
    ServiceStatus,
    StreamDiagnostics,
)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return round(ordered[low], 3)
    fraction = rank - low
    return round(ordered[low] + (ordered[high] - ordered[low]) * fraction, 3)


async def build_diagnostics_summary(
    session: AsyncSession,
    settings: Settings,
    stream_stats: StreamStats,
) -> DiagnosticsSummary:
    """Build a bounded summary without scanning an unbounded command history."""

    # Counts, latency samples, event integrity, and heartbeat age must describe
    # one database snapshot. Otherwise a processor commit between SELECTs can
    # briefly make a healthy system appear inconsistent in the live panel.
    await _begin_consistent_read(session)
    generated_at = datetime.now(UTC)
    raw_status_rows = (
        await session.execute(
            select(MarketCommand.status, func.count(MarketCommand.sequence)).group_by(
                MarketCommand.status
            )
        )
    ).all()
    status_rows: dict[CommandStatus, int] = {
        command_status: int(count) for command_status, count in raw_status_rows
    }
    queue_depth = int(status_rows.get(CommandStatus.QUEUED, 0))
    oldest_queued = await session.scalar(
        select(func.min(MarketCommand.created_at)).where(
            MarketCommand.status == CommandStatus.QUEUED
        )
    )
    oldest_age_ms = None
    if oldest_queued is not None:
        oldest_age_ms = round(max(0.0, (generated_at - oldest_queued).total_seconds() * 1_000), 3)

    completed_rows = (
        await session.execute(
            select(MarketCommand.created_at, MarketCommand.completed_at)
            .where(MarketCommand.completed_at.is_not(None))
            .order_by(desc(MarketCommand.sequence))
            .limit(1_000)
        )
    ).all()
    completion_latencies = [
        (completed_at - created_at).total_seconds() * 1_000
        for created_at, completed_at in completed_rows
        if completed_at is not None
    ]

    order_count, trade_count, event_count, latest_sequence = (
        await session.execute(
            select(
                select(func.count(OrderRecord.order_id)).scalar_subquery(),
                select(func.count(TradeRecord.trade_id)).scalar_subquery(),
                select(func.count(MarketEvent.event_id)).scalar_subquery(),
                select(func.coalesce(func.max(MarketCommand.sequence), 0)).scalar_subquery(),
            )
        )
    ).one()
    terminal_command_count = int(status_rows.get(CommandStatus.COMPLETED, 0)) + int(
        status_rows.get(CommandStatus.REJECTED, 0)
    )
    terminal_event_commands, queued_event_count = (
        await session.execute(
            select(
                func.count(func.distinct(MarketEvent.command_sequence)).filter(
                    MarketCommand.status.in_((CommandStatus.COMPLETED, CommandStatus.REJECTED))
                ),
                func.count(MarketEvent.event_id).filter(
                    MarketCommand.status == CommandStatus.QUEUED
                ),
            )
            .select_from(MarketEvent)
            .join(MarketCommand, MarketCommand.sequence == MarketEvent.command_sequence)
        )
    ).one()
    sequence_integrity = (
        int(event_count or 0) == terminal_command_count
        and int(terminal_event_commands or 0) == terminal_command_count
        and int(queued_event_count or 0) == 0
    )

    processor_heartbeat = await latest_heartbeat(session, PROCESSOR_SERVICE)
    processor_status: Literal["online", "stale", "offline"] = "offline"
    last_heartbeat_at = None
    heartbeat_age_ms = None
    if processor_heartbeat is not None:
        last_heartbeat_at = processor_heartbeat.last_seen_at
        age = (generated_at - last_heartbeat_at).total_seconds()
        heartbeat_age_ms = round(max(0.0, age * 1_000), 3)
        processor_status = (
            "online" if age <= settings.processor_heartbeat_stale_seconds else "stale"
        )

    streams = stream_stats.snapshot()
    return DiagnosticsSummary(
        generated_at=generated_at,
        services=ServicesDiagnostics(
            api=ServiceStatus(status="online"),
            processor=ServiceStatus(
                status=processor_status,
                last_heartbeat_at=last_heartbeat_at,
                age_ms=heartbeat_age_ms,
            ),
        ),
        queue=QueueDiagnostics(depth=queue_depth, oldest_age_ms=oldest_age_ms),
        commands=CommandsDiagnostics(
            accepted=(
                int(status_rows.get(CommandStatus.QUEUED, 0))
                + int(status_rows.get(CommandStatus.COMPLETED, 0))
                + int(status_rows.get(CommandStatus.REJECTED, 0))
            ),
            completed=int(status_rows.get(CommandStatus.COMPLETED, 0)),
            rejected=int(status_rows.get(CommandStatus.REJECTED, 0)),
            latency_ms=LatencyPercentiles(
                p50=_percentile(completion_latencies, 0.50),
                p95=_percentile(completion_latencies, 0.95),
                p99=_percentile(completion_latencies, 0.99),
            ),
        ),
        market=MarketDiagnostics(
            orders=int(order_count or 0),
            trades=int(trade_count or 0),
            events=int(event_count or 0),
            latest_sequence=int(latest_sequence or 0),
            sequence_integrity=sequence_integrity,
        ),
        streams=StreamDiagnostics(
            connected=streams.connected,
            recovered_events=streams.recovered_events,
            resyncs=streams.resyncs,
        ),
    )
