"""Unit tests for processor payloads and real-time backpressure behavior."""

import pytest

from pulseexchange.broadcast import MarketBroadcaster
from pulseexchange.commands import (
    IdempotencyConflictError,
    _persist_idempotently,
    _return_or_conflict,
)
from pulseexchange.engine import LimitOrder, MatchingEngine, Side
from pulseexchange.models import CommandType, MarketCommand
from pulseexchange.processor import _book_from_engine, _order_payload


def test_engine_snapshot_maps_to_public_book_contract() -> None:
    engine = MatchingEngine()
    engine.submit(
        LimitOrder(
            order_id="buy-1",
            side=Side.BUY,
            price=10_100,
            quantity=7,
            sequence=1,
        )
    )
    engine.submit(
        LimitOrder(
            order_id="sell-1",
            side=Side.SELL,
            price=10_200,
            quantity=4,
            sequence=2,
        )
    )

    book = _book_from_engine("NOVA", 2, 9, engine.snapshot())

    assert book.symbol == "NOVA"
    assert book.sequence == 2
    assert book.event_id == 9
    assert [(level.price, level.quantity) for level in book.bids] == [(10_100, 7)]
    assert [(level.price, level.quantity) for level in book.asks] == [(10_200, 4)]


def test_order_payload_contains_replay_relevant_state() -> None:
    order = LimitOrder(
        order_id="order-1",
        side=Side.BUY,
        price=9_900,
        quantity=10,
        sequence=4,
    )

    assert _order_payload(order) == {
        "order_id": "order-1",
        "side": "buy",
        "price": 9_900,
        "quantity": 10,
        "remaining_quantity": 10,
        "sequence": 4,
        "status": "open",
    }


@pytest.mark.asyncio
async def test_slow_subscriber_receives_explicit_resync_marker() -> None:
    broadcaster = MarketBroadcaster(queue_size=1)

    async with broadcaster.subscribe("NOVA") as queue:
        await broadcaster.publish("NOVA", {"type": "market_update", "sequence": 1})
        await broadcaster.publish("NOVA", {"type": "market_update", "sequence": 2})

        assert await queue.get() == {"type": "resync_required", "symbol": "NOVA"}


def _submission(*, price: int, order_id: str = "server-generated") -> MarketCommand:
    return MarketCommand(
        idempotency_key="same-client-key",
        command_type=CommandType.SUBMIT_ORDER,
        symbol="NOVA",
        payload={
            "order_id": order_id,
            "side": "buy",
            "price": price,
            "quantity": 5,
        },
    )


def test_same_idempotent_submission_returns_original_receipt() -> None:
    original = _submission(price=10_100, order_id="original-order")
    retried = _submission(price=10_100, order_id="newly-generated-but-ignored")

    assert _return_or_conflict(original, retried) is original


def test_idempotency_key_reuse_with_different_payload_is_a_conflict() -> None:
    original = _submission(price=10_100)
    changed = _submission(price=10_200)

    with pytest.raises(IdempotencyConflictError, match="different request"):
        _return_or_conflict(original, changed)


class _FakeBegin:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self) -> None:
        self.events.append("begin")

    async def __aexit__(self, *_args: object) -> None:
        self.events.append("commit")


class _FakePostgresSession:
    def __init__(self, existing: MarketCommand) -> None:
        self.existing = existing
        self.events: list[str] = []
        self.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()

    def begin(self) -> _FakeBegin:
        return _FakeBegin(self.events)

    def get_bind(self) -> object:
        return self.bind

    async def execute(self, *_args: object, **_kwargs: object) -> None:
        self.events.append("ingest-lock")

    async def scalar(self, *_args: object, **_kwargs: object) -> MarketCommand:
        self.events.append("idempotency-recheck")
        return self.existing

    def add(self, _value: object) -> None:
        raise AssertionError("an idempotent retry must not insert")


@pytest.mark.asyncio
async def test_ingest_lock_precedes_idempotency_recheck() -> None:
    original = _submission(price=10_100, order_id="original-order")
    retried = _submission(price=10_100, order_id="discarded-order")
    session = _FakePostgresSession(original)

    result = await _persist_idempotently(session, retried)  # type: ignore[arg-type]

    assert result is original
    assert session.events == ["begin", "ingest-lock", "idempotency-recheck", "commit"]
