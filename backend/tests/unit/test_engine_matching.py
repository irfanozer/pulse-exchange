"""Executable domain specification for the deterministic matching engine."""

from collections import deque

import pytest

from pulseexchange.engine import (
    BookInvariantError,
    DuplicateOrderError,
    DuplicateSequenceError,
    InvalidOrderError,
    LimitOrder,
    MatchingEngine,
    OrderNotCancellableError,
    OrderStatus,
    OutOfSequenceError,
    PriceLevel,
    Side,
    UnknownOrderError,
)


def make_order(
    order_id: str,
    side: Side,
    price: int,
    quantity: int,
    sequence: int,
) -> LimitOrder:
    return LimitOrder(
        order_id=order_id,
        side=side,
        price=price,
        quantity=quantity,
        sequence=sequence,
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"order_id": ""}, "order_id"),
        ({"side": "hold"}, "side"),
        ({"price": 0}, "price"),
        ({"price": True}, "price"),
        ({"quantity": -1}, "quantity"),
        ({"sequence": 0}, "sequence"),
        ({"remaining_quantity": -1}, "remaining_quantity"),
        ({"remaining_quantity": 11}, "remaining_quantity"),
    ],
)
def test_limit_order_rejects_invalid_input(changes: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "order_id": "order-1",
        "side": Side.BUY,
        "price": 100,
        "quantity": 10,
        "sequence": 1,
    }
    values.update(changes)

    with pytest.raises(InvalidOrderError, match=message):
        LimitOrder(**values)  # type: ignore[arg-type]


def test_order_state_is_immutable_and_transitions_are_explicit() -> None:
    order = make_order("buy-1", Side.BUY, 100, 10, 1)

    partial = order.apply_fill(4)
    filled = partial.apply_fill(6)

    assert order.status is OrderStatus.OPEN
    assert order.remaining_quantity == 10
    assert partial.status is OrderStatus.PARTIALLY_FILLED
    assert partial.remaining_quantity == 6
    assert partial.filled_quantity == 4
    assert filled.status is OrderStatus.FILLED
    assert filled.remaining_quantity == 0


def test_snapshot_aggregates_liquidity_and_sorts_best_prices_first() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("bid-low", Side.BUY, 99, 2, 1))
    engine.submit(make_order("bid-high-a", Side.BUY, 101, 3, 2))
    engine.submit(make_order("bid-high-b", Side.BUY, 101, 4, 3))
    engine.submit(make_order("ask-high", Side.SELL, 105, 6, 4))
    engine.submit(make_order("ask-low", Side.SELL, 103, 5, 5))

    snapshot = engine.snapshot()

    assert snapshot.bids == (
        PriceLevel(price=101, quantity=7, order_count=2),
        PriceLevel(price=99, quantity=2, order_count=1),
    )
    assert snapshot.asks == (
        PriceLevel(price=103, quantity=5, order_count=1),
        PriceLevel(price=105, quantity=6, order_count=1),
    )
    assert snapshot.best_bid == snapshot.bids[0]
    assert snapshot.best_ask == snapshot.asks[0]
    assert snapshot.last_order_sequence == 5


def test_same_price_uses_fifo_and_trades_at_maker_price() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("maker-first", Side.SELL, 100, 3, 1))
    engine.submit(make_order("maker-second", Side.SELL, 100, 3, 2))

    result = engine.submit(make_order("buyer", Side.BUY, 105, 4, 3))

    assert [trade.maker_order_id for trade in result.trades] == [
        "maker-first",
        "maker-second",
    ]
    assert [trade.price for trade in result.trades] == [100, 100]
    assert [trade.quantity for trade in result.trades] == [3, 1]
    assert [trade.trade_id for trade in result.trades] == [
        "trade-000000000001",
        "trade-000000000002",
    ]
    assert result.order.status is OrderStatus.FILLED
    assert engine.get_order("maker-first").status is OrderStatus.FILLED
    assert engine.get_order("maker-second").remaining_quantity == 2
    assert result.snapshot.asks == (PriceLevel(price=100, quantity=2, order_count=1),)


def test_partial_fill_updates_both_order_state_and_visible_book() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("large-ask", Side.SELL, 100, 10, 1))

    result = engine.submit(make_order("small-buy", Side.BUY, 100, 4, 2))

    assert result.executed_quantity == 4
    assert not result.rested
    assert result.order.status is OrderStatus.FILLED
    assert result.changed_orders == (engine.get_order("large-ask"),)
    assert result.changed_orders[0].status is OrderStatus.PARTIALLY_FILLED
    assert result.changed_orders[0].remaining_quantity == 6
    assert result.snapshot.asks == (PriceLevel(price=100, quantity=6, order_count=1),)


def test_taker_walks_prices_then_fifo_within_a_price() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("old-101", Side.SELL, 101, 3, 1))
    engine.submit(make_order("only-100", Side.SELL, 100, 2, 2))
    engine.submit(make_order("new-101", Side.SELL, 101, 4, 3))

    result = engine.submit(make_order("buyer", Side.BUY, 102, 8, 4))

    assert [trade.maker_order_id for trade in result.trades] == [
        "only-100",
        "old-101",
        "new-101",
    ]
    assert [trade.price for trade in result.trades] == [100, 101, 101]
    assert [trade.quantity for trade in result.trades] == [2, 3, 3]
    assert result.order.status is OrderStatus.FILLED
    assert engine.get_order("new-101").remaining_quantity == 1


def test_sell_taker_uses_resting_bid_as_maker_price() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("bid", Side.BUY, 105, 2, 1))

    result = engine.submit(make_order("seller", Side.SELL, 100, 1, 2))

    assert result.trades[0].price == 105
    assert result.trades[0].maker_order_id == "bid"
    assert result.trades[0].maker_side is Side.BUY
    assert result.trades[0].taker_side is Side.SELL


def test_non_crossing_order_rests_without_a_trade() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("ask", Side.SELL, 105, 2, 1))

    result = engine.submit(make_order("bid", Side.BUY, 104, 3, 2))

    assert result.trades == ()
    assert result.rested
    assert result.order.status is OrderStatus.OPEN
    assert result.snapshot.best_bid is not None
    assert result.snapshot.best_bid.price == 104
    assert result.snapshot.best_ask is not None
    assert result.snapshot.best_ask.price == 105
    engine.assert_invariants()


def test_cancel_removes_only_the_selected_resting_order() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("first", Side.BUY, 100, 3, 1))
    engine.submit(make_order("second", Side.BUY, 100, 4, 2))

    cancelled = engine.cancel("first")

    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.remaining_quantity == 3
    assert engine.snapshot().bids == (PriceLevel(price=100, quantity=4, order_count=1),)
    assert [order.order_id for order in engine.active_orders()] == ["second"]

    with pytest.raises(OrderNotCancellableError):
        engine.cancel("first")
    with pytest.raises(UnknownOrderError):
        engine.cancel("missing")


def test_filled_order_cannot_be_cancelled() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("ask", Side.SELL, 100, 1, 1))
    engine.submit(make_order("buy", Side.BUY, 100, 1, 2))

    with pytest.raises(OrderNotCancellableError, match="filled"):
        engine.cancel("ask")


def test_duplicate_identifiers_sequences_and_late_sequences_are_rejected() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("first", Side.BUY, 90, 1, 2))

    with pytest.raises(DuplicateOrderError):
        engine.submit(make_order("first", Side.BUY, 89, 1, 3))
    with pytest.raises(DuplicateSequenceError):
        engine.submit(make_order("second", Side.BUY, 89, 1, 2))
    with pytest.raises(OutOfSequenceError):
        engine.submit(make_order("late", Side.BUY, 89, 1, 1))


def test_restore_ignores_input_order_and_rebuilds_fifo_from_sequence() -> None:
    newer_partial = LimitOrder(
        order_id="newer",
        side=Side.SELL,
        price=100,
        quantity=5,
        sequence=3,
        remaining_quantity=3,
        status=OrderStatus.PARTIALLY_FILLED,
    )
    older = make_order("older", Side.SELL, 100, 5, 1)
    bid = make_order("bid", Side.BUY, 90, 2, 2)

    engine = MatchingEngine.restore(
        [newer_partial, bid, older],
        next_trade_sequence=42,
    )
    result = engine.submit(make_order("buyer", Side.BUY, 100, 6, 4))

    assert [trade.maker_order_id for trade in result.trades] == ["older", "newer"]
    assert [trade.sequence for trade in result.trades] == [42, 43]
    assert engine.get_order("newer").remaining_quantity == 2
    assert engine.last_order_sequence == 4
    assert engine.next_trade_sequence == 44


def test_restore_rejects_inactive_duplicate_and_crossed_state() -> None:
    filled = LimitOrder(
        order_id="filled",
        side=Side.BUY,
        price=100,
        quantity=1,
        sequence=1,
        remaining_quantity=0,
        status=OrderStatus.FILLED,
    )
    with pytest.raises(InvalidOrderError, match="active"):
        MatchingEngine.restore([filled])

    one = make_order("one", Side.BUY, 99, 1, 1)
    duplicate_id = make_order("one", Side.BUY, 98, 1, 2)
    with pytest.raises(DuplicateOrderError):
        MatchingEngine.restore([one, duplicate_id])

    duplicate_sequence = make_order("two", Side.BUY, 98, 1, 1)
    with pytest.raises(DuplicateSequenceError):
        MatchingEngine.restore([one, duplicate_sequence])

    crossing_ask = make_order("ask", Side.SELL, 99, 1, 2)
    crossing_bid = make_order("bid", Side.BUY, 100, 1, 1)
    with pytest.raises(BookInvariantError, match="crossed book"):
        MatchingEngine.restore([crossing_ask, crossing_bid])


def test_replaying_the_same_order_sequence_is_deterministic() -> None:
    orders = [
        make_order("ask-a", Side.SELL, 100, 3, 1),
        make_order("ask-b", Side.SELL, 101, 4, 2),
        make_order("buy-a", Side.BUY, 102, 5, 3),
        make_order("bid-a", Side.BUY, 99, 6, 4),
        make_order("sell-a", Side.SELL, 99, 2, 5),
    ]

    first = MatchingEngine()
    second = MatchingEngine()
    first_results = [first.submit(order) for order in orders]
    second_results = [second.submit(order) for order in orders]

    assert first_results == second_results
    assert first.trades == second.trades
    assert first.snapshot() == second.snapshot()


def test_invariant_checker_detects_duplicate_resting_entries() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("bid", Side.BUY, 100, 1, 1))
    engine._bids[100].append("bid")

    with pytest.raises(BookInvariantError, match="duplicate resting entries"):
        engine.assert_invariants()


def test_invariant_checker_detects_fifo_corruption() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("first", Side.BUY, 100, 1, 1))
    engine.submit(make_order("second", Side.BUY, 100, 1, 2))
    engine._bids[100] = deque(["second", "first"])

    with pytest.raises(BookInvariantError, match="FIFO"):
        engine.assert_invariants()


def test_invariant_checker_detects_negative_remaining_quantity() -> None:
    engine = MatchingEngine()
    engine.submit(make_order("bid", Side.BUY, 100, 1, 1))
    object.__setattr__(engine._orders["bid"], "remaining_quantity", -1)

    with pytest.raises(BookInvariantError, match="negative remaining"):
        engine.assert_invariants()
