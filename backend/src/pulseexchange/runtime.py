"""Durable liveness evidence for independently running services."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulseexchange.models import RuntimeHeartbeat

PROCESSOR_SERVICE = "command-processor"


async def write_heartbeat(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    service_name: str,
    instance_id: str,
    started_at: datetime,
) -> None:
    """Insert or refresh one service instance heartbeat in its own transaction."""

    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        if session.get_bind().dialect.name == "postgresql":
            statement = postgresql_insert(RuntimeHeartbeat).values(
                service_name=service_name,
                instance_id=instance_id,
                started_at=started_at,
                last_seen_at=now,
                metadata_json={},
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        RuntimeHeartbeat.service_name,
                        RuntimeHeartbeat.instance_id,
                    ],
                    set_={"last_seen_at": now},
                )
            )
            return

        heartbeat = await session.get(RuntimeHeartbeat, (service_name, instance_id))
        if heartbeat is None:
            session.add(
                RuntimeHeartbeat(
                    service_name=service_name,
                    instance_id=instance_id,
                    started_at=started_at,
                    last_seen_at=now,
                    metadata_json={},
                )
            )
        else:
            heartbeat.last_seen_at = now


async def remove_heartbeat(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    service_name: str,
    instance_id: str,
) -> None:
    """Remove this instance on a graceful shutdown."""

    async with session_factory() as session, session.begin():
        await session.execute(
            delete(RuntimeHeartbeat).where(
                RuntimeHeartbeat.service_name == service_name,
                RuntimeHeartbeat.instance_id == instance_id,
            )
        )


async def latest_heartbeat(
    session: AsyncSession,
    service_name: str,
) -> RuntimeHeartbeat | None:
    """Return the freshest instance heartbeat for a logical service."""

    return cast(
        RuntimeHeartbeat | None,
        await session.scalar(
            select(RuntimeHeartbeat)
            .where(RuntimeHeartbeat.service_name == service_name)
            .order_by(desc(RuntimeHeartbeat.last_seen_at))
            .limit(1)
        ),
    )
