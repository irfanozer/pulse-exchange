"""Opt-in end-to-end persistence test against a dedicated PostgreSQL database."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from pulseexchange.broadcast import MarketBroadcaster
from pulseexchange.commands import (
    IdempotencyConflictError,
    _acquire_ingest_lock,
    enqueue_cancel,
    enqueue_submit,
)
from pulseexchange.config import Settings
from pulseexchange.database import Base, create_engine, create_session_factory
from pulseexchange.market_data import _begin_consistent_read, build_stream_snapshot
from pulseexchange.models import (
    CommandStatus,
    MarketCommand,
    MarketEvent,
    OrderRecord,
    PersistedOrderStatus,
    PersistedSide,
    TradeRecord,
)
from pulseexchange.processor import CommandProcessor

TEST_DATABASE_URL = os.getenv("PULSEEXCHANGE_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        TEST_DATABASE_URL is None,
        reason="set PULSEEXCHANGE_TEST_DATABASE_URL to a disposable PostgreSQL database",
    ),
]


async def _reset_test_schema(engine: AsyncEngine, *, create: bool) -> None:
    """Reset both application tables and Alembic's migration marker.

    These tests intentionally use a disposable database. Leaving
    ``alembic_version`` behind after dropping only ORM tables makes the next
    ``alembic upgrade head`` incorrectly believe the missing schema exists.
    """

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        if create:
            await connection.run_sync(Base.metadata.create_all)


@pytest.mark.asyncio
async def test_ingest_lock_serializes_sequence_allocation_and_commit_visibility() -> None:
    assert TEST_DATABASE_URL is not None
    settings = Settings(database_url=TEST_DATABASE_URL, processor_enabled=False)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    await _reset_test_schema(engine, create=True)

    first_allocated = asyncio.Event()
    release_first = asyncio.Event()

    async def hold_first_acceptance() -> MarketCommand:
        async with factory() as session, session.begin():
            await _acquire_ingest_lock(session)
            first = MarketCommand(
                idempotency_key="concurrency-first",
                command_type="submit_order",
                symbol="NOVA",
                payload={
                    "order_id": "concurrency-first-order",
                    "side": "buy",
                    "price": 10_000,
                    "quantity": 1,
                },
            )
            session.add(first)
            await session.flush()
            first_allocated.set()
            await release_first.wait()
            return first

    async def accept_second() -> MarketCommand:
        await first_allocated.wait()
        async with factory() as session:
            return await enqueue_submit(
                session,
                idempotency_key="concurrency-second",
                symbol="NOVA",
                side=PersistedSide.SELL,
                price=10_100,
                quantity=1,
            )

    first_task = asyncio.create_task(hold_first_acceptance())
    second_task = asyncio.create_task(accept_second())
    try:
        await first_allocated.wait()
        await asyncio.sleep(0.05)
        assert not second_task.done()

        release_first.set()
        first, second = await asyncio.gather(first_task, second_task)
        assert first.sequence < second.sequence
    finally:
        release_first.set()
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(first_task, second_task, return_exceptions=True)
        await _reset_test_schema(engine, create=False)
        await engine.dispose()


@pytest.mark.asyncio
async def test_reconnect_snapshot_uses_one_repeatable_read_version() -> None:
    assert TEST_DATABASE_URL is not None
    settings = Settings(database_url=TEST_DATABASE_URL, processor_enabled=False)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    await _reset_test_schema(engine, create=True)

    try:
        async with factory() as snapshot_session:
            await _begin_consistent_read(snapshot_session)
            before = await snapshot_session.scalar(select(func.count(MarketCommand.sequence)))

            async with factory() as writer_session:
                await enqueue_submit(
                    writer_session,
                    idempotency_key="snapshot-concurrent-write",
                    symbol="ORBIT",
                    side=PersistedSide.BUY,
                    price=5_000,
                    quantity=1,
                )

            after = await snapshot_session.scalar(select(func.count(MarketCommand.sequence)))
            assert before == 0
            assert after == before

        async with factory() as fresh_session:
            visible_after_reconnect = await fresh_session.scalar(
                select(func.count(MarketCommand.sequence))
            )
            assert visible_after_reconnect == 1
    finally:
        await _reset_test_schema(engine, create=False)
        await engine.dispose()


@pytest.mark.asyncio
async def test_commands_match_atomically_and_idempotently() -> None:
    assert TEST_DATABASE_URL is not None
    settings = Settings(database_url=TEST_DATABASE_URL, processor_enabled=False)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    await _reset_test_schema(engine, create=True)

    broadcaster = MarketBroadcaster()
    processor = CommandProcessor(factory, broadcaster, settings)
    try:
        async with factory() as session:
            buy = await enqueue_submit(
                session,
                idempotency_key="integration-buy-0001",
                symbol="NOVA",
                side=PersistedSide.BUY,
                price=10_100,
                quantity=5,
            )
            duplicate = await enqueue_submit(
                session,
                idempotency_key="integration-buy-0001",
                symbol="NOVA",
                side=PersistedSide.BUY,
                price=10_100,
                quantity=5,
            )
            buy_id = buy.command_id
            buy_sequence = buy.sequence
            assert duplicate.command_id == buy_id
            with pytest.raises(IdempotencyConflictError):
                await enqueue_submit(
                    session,
                    idempotency_key="integration-buy-0001",
                    symbol="NOVA",
                    side=PersistedSide.BUY,
                    price=10_200,
                    quantity=5,
                )
            sell = await enqueue_submit(
                session,
                idempotency_key="integration-sell-0001",
                symbol="NOVA",
                side=PersistedSide.SELL,
                price=10_100,
                quantity=5,
            )
            rejected_cancel = await enqueue_cancel(
                session,
                idempotency_key="integration-cancel-0001",
                symbol="NOVA",
                order_id="does-not-exist",
            )
            follow_up = await enqueue_submit(
                session,
                idempotency_key="integration-follow-up-0001",
                symbol="NOVA",
                side=PersistedSide.BUY,
                price=9_900,
                quantity=2,
            )
            sell_id = sell.command_id
            rejected_cancel_id = rejected_cancel.command_id
            follow_up_id = follow_up.command_id
            assert sell.sequence > buy_sequence

        assert await processor.process_once()
        assert await processor.process_once()
        assert await processor.process_once()
        assert await processor.process_once()
        assert not await processor.process_once()

        async with factory() as session:
            orders = list(await session.scalars(select(OrderRecord)))
            trade_count = await session.scalar(select(func.count(TradeRecord.trade_id)))
            completed_commands = list(
                await session.scalars(
                    select(MarketCommand).where(
                        MarketCommand.command_id.in_(
                            (
                                buy_id,
                                sell_id,
                                rejected_cancel_id,
                                follow_up_id,
                            )
                        )
                    )
                )
            )
            assert len(orders) == 3
            assert sorted(order.status.value for order in orders) == ["filled", "filled", "open"]
            assert trade_count == 1
            statuses = {command.command_id: command.status for command in completed_commands}
            assert statuses[buy_id] == CommandStatus.COMPLETED
            assert statuses[sell_id] == CommandStatus.COMPLETED
            assert statuses[rejected_cancel_id] == CommandStatus.REJECTED
            assert statuses[follow_up_id] == CommandStatus.COMPLETED

            recovery = await build_stream_snapshot(
                session,
                "NOVA",
                after_event_id=0,
                replay_limit=2,
            )
            recovered_ids = [event.event_id for event in recovery.recovered_events]
            assert recovery.replay_truncated
            assert recovered_ids == sorted(recovered_ids)
            assert len(recovered_ids) == 2
            assert recovered_ids[-1] == recovery.event_id
    finally:
        await _reset_test_schema(engine, create=False)
        await engine.dispose()


class _LostBroadcast(MarketBroadcaster):
    async def publish(self, symbol: str, update: dict[str, object]) -> None:
        raise RuntimeError(f"simulated lost broadcast for {symbol}:{update['event_id']}")


@pytest.mark.asyncio
async def test_commit_survives_lost_broadcast_and_replays_from_postgres() -> None:
    assert TEST_DATABASE_URL is not None
    settings = Settings(database_url=TEST_DATABASE_URL, processor_enabled=False)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    await _reset_test_schema(engine, create=True)

    try:
        async with factory() as session:
            command = await enqueue_submit(
                session,
                idempotency_key="recovery-committed-before-broadcast",
                symbol="ORBIT",
                side=PersistedSide.BUY,
                price=5_100,
                quantity=3,
            )
            command_id = command.command_id
            command_sequence = command.sequence

        interrupted = CommandProcessor(factory, _LostBroadcast(), settings)
        with pytest.raises(RuntimeError, match="simulated lost broadcast"):
            await interrupted.process_once()

        restarted = CommandProcessor(factory, MarketBroadcaster(), settings)
        assert not await restarted.process_once()

        async with factory() as session:
            persisted = await session.scalar(
                select(MarketCommand).where(MarketCommand.command_id == command_id)
            )
            assert persisted is not None
            assert persisted.status == CommandStatus.COMPLETED
            assert await session.scalar(select(func.count(OrderRecord.order_id))) == 1
            assert await session.scalar(select(func.count(MarketEvent.event_id))) == 1

            snapshot = await build_stream_snapshot(
                session,
                "ORBIT",
                after_event_id=0,
                replay_limit=10,
            )
            assert [event.sequence for event in snapshot.recovered_events] == [command_sequence]
            assert snapshot.recovered_events[0].payload["order_id"] == command.payload["order_id"]
    finally:
        await _reset_test_schema(engine, create=False)
        await engine.dispose()


@pytest.mark.asyncio
async def test_queued_command_resumes_after_processor_restart() -> None:
    """A committed queue entry survives losing the original process and pool."""

    assert TEST_DATABASE_URL is not None
    settings = Settings(database_url=TEST_DATABASE_URL, processor_enabled=False)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    await _reset_test_schema(engine, create=True)

    try:
        async with factory() as session:
            buy = await enqueue_submit(
                session,
                idempotency_key="restart-buy-0001",
                symbol="NOVA",
                side=PersistedSide.BUY,
                price=10_100,
                quantity=5,
            )
            sell = await enqueue_submit(
                session,
                idempotency_key="restart-sell-0001",
                symbol="NOVA",
                side=PersistedSide.SELL,
                price=10_100,
                quantity=5,
            )
            buy_id = buy.command_id
            sell_id = sell.command_id

        original_processor = CommandProcessor(factory, MarketBroadcaster(), settings)
        assert await original_processor.process_once()

        async with factory() as session:
            assert (
                await session.scalar(
                    select(MarketCommand.status).where(MarketCommand.command_id == buy_id)
                )
                == CommandStatus.COMPLETED
            )
            assert (
                await session.scalar(
                    select(MarketCommand.status).where(MarketCommand.command_id == sell_id)
                )
                == CommandStatus.QUEUED
            )

        # Discard the first process's entire connection pool. A new processor
        # must rebuild its engine from committed rows and claim the durable work.
        await engine.dispose()
        engine = create_engine(settings)
        restarted_factory = create_session_factory(engine)
        restarted_processor = CommandProcessor(
            restarted_factory,
            MarketBroadcaster(),
            settings,
        )

        assert await restarted_processor.process_once()
        assert not await restarted_processor.process_once()

        async with restarted_factory() as session:
            statuses = dict(
                (
                    await session.execute(
                        select(MarketCommand.command_id, MarketCommand.status).where(
                            MarketCommand.command_id.in_((buy_id, sell_id))
                        )
                    )
                ).all()
            )
            orders = list(await session.scalars(select(OrderRecord).order_by(OrderRecord.sequence)))
            trade_count = await session.scalar(select(func.count(TradeRecord.trade_id)))
            event_count = await session.scalar(select(func.count(MarketEvent.event_id)))

            assert statuses == {
                buy_id: CommandStatus.COMPLETED,
                sell_id: CommandStatus.COMPLETED,
            }
            assert [order.status for order in orders] == [
                PersistedOrderStatus.FILLED,
                PersistedOrderStatus.FILLED,
            ]
            assert trade_count == 1
            assert event_count == 2
    finally:
        await _reset_test_schema(engine, create=False)
        await engine.dispose()


class SimulatedProcessCrash(RuntimeError):
    """Test-only fault representing process death at a transaction boundary."""


@pytest.mark.asyncio
async def test_crash_before_commit_rolls_back_and_retry_cannot_duplicate_trade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flushed matching writes roll back together when commit never happens."""

    assert TEST_DATABASE_URL is not None
    settings = Settings(database_url=TEST_DATABASE_URL, processor_enabled=False)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    await _reset_test_schema(engine, create=True)

    try:
        async with factory() as session:
            buy = await enqueue_submit(
                session,
                idempotency_key="pre-commit-crash-buy-0001",
                symbol="NOVA",
                side=PersistedSide.BUY,
                price=10_100,
                quantity=5,
            )
            sell = await enqueue_submit(
                session,
                idempotency_key="pre-commit-crash-sell-0001",
                symbol="NOVA",
                side=PersistedSide.SELL,
                price=10_100,
                quantity=5,
            )
            buy_order_id = str(buy.payload["order_id"])
            sell_order_id = str(sell.payload["order_id"])
            sell_command_id = sell.command_id

        processor = CommandProcessor(factory, MarketBroadcaster(), settings)
        assert await processor.process_once()

        original_apply = processor._apply_command

        async def crash_after_flushed_mutations(
            session: AsyncSession,
            command: MarketCommand,
        ) -> dict[str, Any]:
            await original_apply(session, command)
            raise SimulatedProcessCrash("process exited after flush but before commit")

        monkeypatch.setattr(processor, "_apply_command", crash_after_flushed_mutations)
        with pytest.raises(SimulatedProcessCrash):
            await processor.process_once()

        async with factory() as session:
            sell_status = await session.scalar(
                select(MarketCommand.status).where(MarketCommand.command_id == sell_command_id)
            )
            buy_order = await session.get(OrderRecord, buy_order_id)
            sell_order = await session.get(OrderRecord, sell_order_id)
            trade_count = await session.scalar(select(func.count(TradeRecord.trade_id)))
            event_count = await session.scalar(select(func.count(MarketEvent.event_id)))

            assert sell_status == CommandStatus.QUEUED
            assert buy_order is not None
            assert buy_order.status == PersistedOrderStatus.OPEN
            assert buy_order.remaining_quantity == 5
            assert sell_order is None
            assert trade_count == 0
            assert event_count == 1

        await engine.dispose()
        engine = create_engine(settings)
        restarted_factory = create_session_factory(engine)
        restarted_processor = CommandProcessor(
            restarted_factory,
            MarketBroadcaster(),
            settings,
        )

        assert await restarted_processor.process_once()
        assert not await restarted_processor.process_once()

        async with restarted_factory() as session:
            sell_status = await session.scalar(
                select(MarketCommand.status).where(MarketCommand.command_id == sell_command_id)
            )
            orders = list(await session.scalars(select(OrderRecord).order_by(OrderRecord.sequence)))
            trades = list(await session.scalars(select(TradeRecord)))
            event_count = await session.scalar(select(func.count(MarketEvent.event_id)))

            assert sell_status == CommandStatus.COMPLETED
            assert [order.status for order in orders] == [
                PersistedOrderStatus.FILLED,
                PersistedOrderStatus.FILLED,
            ]
            assert len(trades) == 1
            assert trades[0].trade_sequence == 1
            assert event_count == 2
    finally:
        await _reset_test_schema(engine, create=False)
        await engine.dispose()


@pytest.mark.asyncio
async def test_publish_failure_after_commit_is_not_reprocessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fan-out failure cannot turn a committed command into duplicate work."""

    assert TEST_DATABASE_URL is not None
    settings = Settings(database_url=TEST_DATABASE_URL, processor_enabled=False)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    await _reset_test_schema(engine, create=True)

    try:
        async with factory() as session:
            await enqueue_submit(
                session,
                idempotency_key="post-commit-crash-buy-0001",
                symbol="NOVA",
                side=PersistedSide.BUY,
                price=10_100,
                quantity=5,
            )
            sell = await enqueue_submit(
                session,
                idempotency_key="post-commit-crash-sell-0001",
                symbol="NOVA",
                side=PersistedSide.SELL,
                price=10_100,
                quantity=5,
            )
            sell_command_id = sell.command_id
            sell_sequence = sell.sequence

        broadcaster = MarketBroadcaster()
        processor = CommandProcessor(factory, broadcaster, settings)
        assert await processor.process_once()

        async def fail_publish(_symbol: str, _update: dict[str, Any]) -> None:
            raise SimulatedProcessCrash("process exited after commit during publish")

        monkeypatch.setattr(broadcaster, "publish", fail_publish)
        with pytest.raises(SimulatedProcessCrash):
            await processor.process_once()

        async with factory() as session:
            sell_status = await session.scalar(
                select(MarketCommand.status).where(MarketCommand.command_id == sell_command_id)
            )
            trade_count = await session.scalar(select(func.count(TradeRecord.trade_id)))
            event_count = await session.scalar(select(func.count(MarketEvent.event_id)))
            matching_event_count = await session.scalar(
                select(func.count(MarketEvent.event_id)).where(
                    MarketEvent.command_sequence == sell_sequence
                )
            )

            assert sell_status == CommandStatus.COMPLETED
            assert trade_count == 1
            assert event_count == 2
            assert matching_event_count == 1

        await engine.dispose()
        engine = create_engine(settings)
        restarted_factory = create_session_factory(engine)
        restarted_processor = CommandProcessor(
            restarted_factory,
            MarketBroadcaster(),
            settings,
        )

        assert not await restarted_processor.process_once()

        async with restarted_factory() as session:
            queued_count = await session.scalar(
                select(func.count(MarketCommand.sequence)).where(
                    MarketCommand.status == CommandStatus.QUEUED
                )
            )
            trade_count = await session.scalar(select(func.count(TradeRecord.trade_id)))
            event_count = await session.scalar(select(func.count(MarketEvent.event_id)))
            matching_event_count = await session.scalar(
                select(func.count(MarketEvent.event_id)).where(
                    MarketEvent.command_sequence == sell_sequence
                )
            )

            assert queued_count == 0
            assert trade_count == 1
            assert event_count == 2
            assert matching_event_count == 1
    finally:
        await _reset_test_schema(engine, create=False)
        await engine.dispose()
