"""Contract tests for API validation and serialization."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pulseexchange.models import PersistedSide
from pulseexchange.schemas import (
    BookResponse,
    RecoveredMarketEvent,
    StreamSnapshot,
    SubmitOrderRequest,
)


def test_submit_order_normalizes_symbol_and_keeps_integer_ticks() -> None:
    request = SubmitOrderRequest(
        symbol="nova",
        side=PersistedSide.BUY,
        price=10_250,
        quantity=25,
    )

    assert request.symbol == "NOVA"
    assert request.price == 10_250
    assert request.quantity == 25


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price", 0),
        ("price", 100.5),
        ("quantity", 0),
        ("quantity", True),
    ],
)
def test_submit_order_rejects_non_positive_or_non_integer_values(field: str, value: object) -> None:
    body: dict[str, object] = {
        "symbol": "NOVA",
        "side": "buy",
        "price": 10_250,
        "quantity": 25,
    }
    body[field] = value

    with pytest.raises(ValidationError):
        SubmitOrderRequest.model_validate(body)


@pytest.mark.parametrize("symbol", ["$NOVA", "A", "TOO-LONG-SYMBOL", "ACME"])
def test_submit_order_rejects_invalid_symbols(symbol: str) -> None:
    with pytest.raises(ValidationError):
        SubmitOrderRequest(
            symbol=symbol,
            side=PersistedSide.SELL,
            price=10_250,
            quantity=25,
        )


def test_reconnect_snapshot_serializes_durable_recovery_evidence() -> None:
    recovered = RecoveredMarketEvent(
        event_id=12,
        sequence=15,
        event_type="order_accepted",
        payload={"order_id": "order-12"},
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    book = BookResponse(symbol="NOVA", sequence=15, event_id=12, bids=[], asks=[])

    snapshot = StreamSnapshot(
        symbol="NOVA",
        sequence=15,
        event_id=12,
        book=book,
        trades=[],
        recovered_events=[recovered],
        replay_truncated=True,
    )

    encoded = snapshot.model_dump(mode="json")
    assert encoded["type"] == "snapshot"
    assert encoded["recovered_events"][0]["event_id"] == 12
    assert encoded["recovered_events"][0]["sequence"] == 15
    assert encoded["replay_truncated"] is True
