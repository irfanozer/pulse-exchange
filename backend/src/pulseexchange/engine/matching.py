"""Deterministic, in-memory price-time-priority matching engine."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable

from .exceptions import (
    BookInvariantError,
    DuplicateOrderError,
    DuplicateSequenceError,
    InvalidOrderError,
    OrderNotCancellableError,
    OutOfSequenceError,
    UnknownOrderError,
)
from .models import BookSnapshot, LimitOrder, MatchResult, OrderStatus, PriceLevel, Side, Trade


class MatchingEngine:
    """Match limit orders using deterministic price-time priority.

    The engine is intentionally independent from HTTP, databases, clocks, and
    random identifiers. Callers provide the durable order sequence; the engine
    emits stable trade sequences and can rebuild FIFO priority from persisted
    active orders.
    """

    def __init__(self, *, next_trade_sequence: int = 1) -> None:
        if (
            isinstance(next_trade_sequence, bool)
            or not isinstance(next_trade_sequence, int)
            or next_trade_sequence <= 0
        ):
            raise InvalidOrderError("next_trade_sequence must be a positive integer")

        self._orders: dict[str, LimitOrder] = {}
        self._bids: dict[int, deque[str]] = {}
        self._asks: dict[int, deque[str]] = {}
        self._resting_ids: set[str] = set()
        self._used_order_sequences: set[int] = set()
        self._trades: list[Trade] = []
        self._last_order_sequence = 0
        self._next_trade_sequence = next_trade_sequence

    @classmethod
    def restore(
        cls,
        active_orders: Iterable[LimitOrder],
        *,
        next_trade_sequence: int = 1,
    ) -> MatchingEngine:
        """Rebuild an active book in persisted creation-sequence order.

        Input ordering is deliberately ignored. A crossed restored book, a
        duplicate identifier/sequence, or an inactive order is rejected.
        """

        engine = cls(next_trade_sequence=next_trade_sequence)
        orders = list(active_orders)
        if any(not isinstance(order, LimitOrder) for order in orders):
            raise InvalidOrderError("restore accepts LimitOrder instances only")
        orders.sort(key=lambda order: order.sequence)

        for order in orders:
            if not order.is_active:
                raise InvalidOrderError("restore accepts active orders only")
            if order.order_id in engine._orders:
                raise DuplicateOrderError(f"duplicate order_id: {order.order_id}")
            if order.sequence in engine._used_order_sequences:
                raise DuplicateSequenceError(f"duplicate order sequence: {order.sequence}")

            engine._orders[order.order_id] = order
            engine._used_order_sequences.add(order.sequence)
            engine._last_order_sequence = max(engine._last_order_sequence, order.sequence)
            engine._rest(order)

        engine.assert_invariants()
        return engine

    @property
    def last_order_sequence(self) -> int:
        return self._last_order_sequence

    @property
    def next_trade_sequence(self) -> int:
        return self._next_trade_sequence

    @property
    def trades(self) -> tuple[Trade, ...]:
        return tuple(self._trades)

    def submit(self, order: LimitOrder) -> MatchResult:
        """Accept and synchronously match one fresh limit order."""

        if not isinstance(order, LimitOrder):
            raise InvalidOrderError("submit accepts a LimitOrder instance")
        if order.status is not OrderStatus.OPEN or order.remaining_quantity != order.quantity:
            raise InvalidOrderError("submitted orders must be fresh and open")
        if order.order_id in self._orders:
            raise DuplicateOrderError(f"order_id already exists: {order.order_id}")
        if order.sequence in self._used_order_sequences:
            raise DuplicateSequenceError(f"order sequence already exists: {order.sequence}")
        if order.sequence <= self._last_order_sequence:
            raise OutOfSequenceError(
                f"order sequence {order.sequence} must be greater than {self._last_order_sequence}"
            )

        current = order
        trades: list[Trade] = []
        changed_orders: list[LimitOrder] = []

        while current.remaining_quantity > 0:
            maker = self._best_crossing_order(current)
            if maker is None:
                break

            fill_quantity = min(current.remaining_quantity, maker.remaining_quantity)
            updated_maker = maker.apply_fill(fill_quantity)
            current = current.apply_fill(fill_quantity)
            trade = Trade(
                sequence=self._next_trade_sequence,
                maker_order_id=maker.order_id,
                taker_order_id=current.order_id,
                price=maker.price,
                quantity=fill_quantity,
                maker_side=maker.side,
            )
            self._next_trade_sequence += 1
            self._trades.append(trade)
            trades.append(trade)
            changed_orders.append(updated_maker)
            self._orders[maker.order_id] = updated_maker

            if updated_maker.status is OrderStatus.FILLED:
                self._remove_best(maker)

        self._orders[current.order_id] = current
        self._used_order_sequences.add(current.sequence)
        self._last_order_sequence = current.sequence
        if current.is_active:
            self._rest(current)

        self.assert_invariants()
        return MatchResult(
            order=current,
            trades=tuple(trades),
            changed_orders=tuple(changed_orders),
            snapshot=self.snapshot(),
        )

    def place_limit_order(
        self,
        *,
        order_id: str,
        side: Side | str,
        price: int,
        quantity: int,
        sequence: int | None = None,
    ) -> MatchResult:
        """Construct and submit a limit order, assigning a sequence if omitted."""

        assigned_sequence = self._last_order_sequence + 1 if sequence is None else sequence
        return self.submit(
            LimitOrder(
                order_id=order_id,
                side=side,
                price=price,
                quantity=quantity,
                sequence=assigned_sequence,
            )
        )

    def cancel(self, order_id: str) -> LimitOrder:
        """Cancel an active resting order and return its terminal state."""

        try:
            order = self._orders[order_id]
        except KeyError as error:
            raise UnknownOrderError(f"unknown order_id: {order_id}") from error
        if not order.is_active:
            raise OrderNotCancellableError(f"order {order_id!r} is already {order.status.value}")

        book = self._book_for(order.side)
        queue = book.get(order.price)
        if queue is None or order_id not in queue:
            raise BookInvariantError(f"active order {order_id!r} is missing from its price level")

        queue.remove(order_id)
        if not queue:
            del book[order.price]
        self._resting_ids.remove(order_id)
        cancelled = order.cancel()
        self._orders[order_id] = cancelled
        self.assert_invariants()
        return cancelled

    def get_order(self, order_id: str) -> LimitOrder:
        try:
            return self._orders[order_id]
        except KeyError as error:
            raise UnknownOrderError(f"unknown order_id: {order_id}") from error

    def active_orders(self, side: Side | str | None = None) -> tuple[LimitOrder, ...]:
        """Return active orders in creation sequence, optionally for one side."""

        selected_side = Side(side) if side is not None else None
        return tuple(
            sorted(
                (
                    order
                    for order in self._orders.values()
                    if order.is_active and (selected_side is None or order.side is selected_side)
                ),
                key=lambda order: order.sequence,
            )
        )

    def snapshot(self) -> BookSnapshot:
        return BookSnapshot(
            bids=self._aggregate(self._bids, reverse=True),
            asks=self._aggregate(self._asks, reverse=False),
            last_order_sequence=self._last_order_sequence,
            last_trade_sequence=self._next_trade_sequence - 1,
        )

    def assert_invariants(self) -> None:
        """Raise ``BookInvariantError`` if internal safety guarantees are broken."""

        sequences = [order.sequence for order in self._orders.values()]
        if len(sequences) != len(set(sequences)):
            raise BookInvariantError("order creation sequences must be unique")

        for order in self._orders.values():
            if order.remaining_quantity < 0:
                raise BookInvariantError(
                    f"order {order.order_id!r} has negative remaining quantity"
                )
            if order.is_active and order.remaining_quantity <= 0:
                raise BookInvariantError(
                    f"active order {order.order_id!r} has no remaining quantity"
                )

        seen: list[str] = []
        self._check_book(self._bids, Side.BUY, seen)
        self._check_book(self._asks, Side.SELL, seen)
        counts = Counter(seen)
        duplicates = sorted(order_id for order_id, count in counts.items() if count > 1)
        if duplicates:
            raise BookInvariantError(f"duplicate resting entries: {', '.join(duplicates)}")

        seen_ids = set(seen)
        if seen_ids != self._resting_ids:
            raise BookInvariantError("resting-order index does not match price-level entries")
        active_ids = {order.order_id for order in self._orders.values() if order.is_active}
        if seen_ids != active_ids:
            raise BookInvariantError("every active order must rest exactly once")

        best_bid = max(self._bids, default=None)
        best_ask = min(self._asks, default=None)
        if best_bid is not None and best_ask is not None and best_bid >= best_ask:
            raise BookInvariantError(
                f"crossed book: best bid {best_bid} is not below best ask {best_ask}"
            )

        trade_sequences = [trade.sequence for trade in self._trades]
        if any(
            left >= right for left, right in zip(trade_sequences, trade_sequences[1:], strict=False)
        ):
            raise BookInvariantError("trade sequences must be strictly increasing")

    def _best_crossing_order(self, taker: LimitOrder) -> LimitOrder | None:
        maker_book = self._asks if taker.side is Side.BUY else self._bids
        if not maker_book:
            return None

        maker_price = min(maker_book) if taker.side is Side.BUY else max(maker_book)
        crosses = (
            maker_price <= taker.price if taker.side is Side.BUY else maker_price >= taker.price
        )
        if not crosses:
            return None
        return self._orders[maker_book[maker_price][0]]

    def _remove_best(self, maker: LimitOrder) -> None:
        book = self._book_for(maker.side)
        queue = book[maker.price]
        if not queue or queue[0] != maker.order_id:
            raise BookInvariantError("the executed maker is not first at its price level")
        queue.popleft()
        self._resting_ids.remove(maker.order_id)
        if not queue:
            del book[maker.price]

    def _rest(self, order: LimitOrder) -> None:
        if order.order_id in self._resting_ids:
            raise BookInvariantError(f"order {order.order_id!r} is already resting")
        book = self._book_for(order.side)
        book.setdefault(order.price, deque()).append(order.order_id)
        self._resting_ids.add(order.order_id)

    def _book_for(self, side: Side) -> dict[int, deque[str]]:
        return self._bids if side is Side.BUY else self._asks

    def _aggregate(
        self,
        book: dict[int, deque[str]],
        *,
        reverse: bool,
    ) -> tuple[PriceLevel, ...]:
        return tuple(
            PriceLevel(
                price=price,
                quantity=sum(self._orders[order_id].remaining_quantity for order_id in book[price]),
                order_count=len(book[price]),
            )
            for price in sorted(book, reverse=reverse)
        )

    def _check_book(
        self,
        book: dict[int, deque[str]],
        expected_side: Side,
        seen: list[str],
    ) -> None:
        for price, queue in book.items():
            if not queue:
                raise BookInvariantError(f"empty {expected_side.value} price level: {price}")
            level_sequences: list[int] = []
            for order_id in queue:
                order = self._orders.get(order_id)
                if order is None:
                    raise BookInvariantError(f"resting order {order_id!r} does not exist")
                if not order.is_active:
                    raise BookInvariantError(f"inactive order {order_id!r} is resting")
                if order.side is not expected_side or order.price != price:
                    raise BookInvariantError(f"order {order_id!r} is on the wrong price level")
                seen.append(order_id)
                level_sequences.append(order.sequence)
            if level_sequences != sorted(level_sequences):
                raise BookInvariantError(
                    f"{expected_side.value} price level {price} is not in FIFO sequence order"
                )
