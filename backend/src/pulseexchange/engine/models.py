"""Immutable domain objects used by the matching engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .exceptions import InvalidOrderError


class Side(StrEnum):
    """The side of a limit order."""

    BUY = "buy"
    SELL = "sell"

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderStatus(StrEnum):
    """Lifecycle state of an accepted order."""

    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        return self in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidOrderError(f"{name} must be a positive integer")
    return value


def _coerce_side(side: Side | str) -> Side:
    try:
        return side if isinstance(side, Side) else Side(side)
    except (TypeError, ValueError) as error:
        raise InvalidOrderError("side must be 'buy' or 'sell'") from error


def _coerce_status(status: OrderStatus | str) -> OrderStatus:
    try:
        return status if isinstance(status, OrderStatus) else OrderStatus(status)
    except (TypeError, ValueError) as error:
        raise InvalidOrderError(f"unknown order status: {status!r}") from error


@dataclass(frozen=True, slots=True, init=False)
class LimitOrder:
    """A limit order and its immutable current lifecycle state.

    New orders can omit ``remaining_quantity`` and ``status``. Persisted active
    orders can provide both fields when a book is restored.
    """

    order_id: str
    side: Side
    price: int
    quantity: int
    sequence: int
    remaining_quantity: int
    status: OrderStatus

    def __init__(
        self,
        order_id: str,
        side: Side | str,
        price: int,
        quantity: int,
        sequence: int,
        remaining_quantity: int | None = None,
        status: OrderStatus | str | None = None,
    ) -> None:
        if not isinstance(order_id, str) or not order_id.strip():
            raise InvalidOrderError("order_id must be a non-empty string")

        clean_order_id = order_id.strip()
        clean_side = _coerce_side(side)
        clean_price = _positive_integer("price", price)
        clean_quantity = _positive_integer("quantity", quantity)
        clean_sequence = _positive_integer("sequence", sequence)

        if remaining_quantity is None:
            clean_remaining = clean_quantity
        elif isinstance(remaining_quantity, bool) or not isinstance(remaining_quantity, int):
            raise InvalidOrderError("remaining_quantity must be an integer")
        else:
            clean_remaining = remaining_quantity

        if clean_remaining < 0 or clean_remaining > clean_quantity:
            raise InvalidOrderError("remaining_quantity must be between zero and quantity")

        if status is None:
            if clean_remaining == 0:
                clean_status = OrderStatus.FILLED
            elif clean_remaining == clean_quantity:
                clean_status = OrderStatus.OPEN
            else:
                clean_status = OrderStatus.PARTIALLY_FILLED
        else:
            clean_status = _coerce_status(status)

        self._validate_state(clean_quantity, clean_remaining, clean_status)
        object.__setattr__(self, "order_id", clean_order_id)
        object.__setattr__(self, "side", clean_side)
        object.__setattr__(self, "price", clean_price)
        object.__setattr__(self, "quantity", clean_quantity)
        object.__setattr__(self, "sequence", clean_sequence)
        object.__setattr__(self, "remaining_quantity", clean_remaining)
        object.__setattr__(self, "status", clean_status)

    @staticmethod
    def _validate_state(
        quantity: int,
        remaining_quantity: int,
        status: OrderStatus,
    ) -> None:
        if status is OrderStatus.OPEN and remaining_quantity != quantity:
            raise InvalidOrderError("an open order must have its full quantity remaining")
        if status is OrderStatus.PARTIALLY_FILLED and not 0 < remaining_quantity < quantity:
            raise InvalidOrderError(
                "a partially filled order must have a partial quantity remaining"
            )
        if status is OrderStatus.FILLED and remaining_quantity != 0:
            raise InvalidOrderError("a filled order must have no quantity remaining")
        if status is OrderStatus.CANCELLED and remaining_quantity <= 0:
            raise InvalidOrderError("a cancelled order must have unfilled quantity remaining")

    @property
    def filled_quantity(self) -> int:
        return self.quantity - self.remaining_quantity

    @property
    def is_active(self) -> bool:
        return self.status.is_active

    def apply_fill(self, fill_quantity: int) -> LimitOrder:
        """Return the next immutable state after applying one execution."""

        fill_quantity = _positive_integer("fill_quantity", fill_quantity)
        if not self.is_active:
            raise InvalidOrderError(f"order {self.order_id!r} is not active")
        if fill_quantity > self.remaining_quantity:
            raise InvalidOrderError("fill_quantity cannot exceed remaining_quantity")

        remaining = self.remaining_quantity - fill_quantity
        next_status = OrderStatus.FILLED if remaining == 0 else OrderStatus.PARTIALLY_FILLED
        return LimitOrder(
            order_id=self.order_id,
            side=self.side,
            price=self.price,
            quantity=self.quantity,
            sequence=self.sequence,
            remaining_quantity=remaining,
            status=next_status,
        )

    def cancel(self) -> LimitOrder:
        """Return the cancelled state while retaining unfilled quantity."""

        if not self.is_active:
            raise InvalidOrderError(f"order {self.order_id!r} is not active")
        return LimitOrder(
            order_id=self.order_id,
            side=self.side,
            price=self.price,
            quantity=self.quantity,
            sequence=self.sequence,
            remaining_quantity=self.remaining_quantity,
            status=OrderStatus.CANCELLED,
        )


@dataclass(frozen=True, slots=True)
class Trade:
    """One deterministic maker/taker execution."""

    sequence: int
    maker_order_id: str
    taker_order_id: str
    price: int
    quantity: int
    maker_side: Side

    def __post_init__(self) -> None:
        _positive_integer("trade sequence", self.sequence)
        _positive_integer("trade price", self.price)
        _positive_integer("trade quantity", self.quantity)
        if not self.maker_order_id or not self.taker_order_id:
            raise InvalidOrderError("trade order identifiers cannot be empty")
        if self.maker_order_id == self.taker_order_id:
            raise InvalidOrderError("maker and taker must be different orders")
        object.__setattr__(self, "maker_side", _coerce_side(self.maker_side))

    @property
    def trade_id(self) -> str:
        return f"trade-{self.sequence:012d}"

    @property
    def taker_side(self) -> Side:
        return self.maker_side.opposite


@dataclass(frozen=True, slots=True)
class PriceLevel:
    """Aggregated visible liquidity at one integer price."""

    price: int
    quantity: int
    order_count: int


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """A deterministic, aggregated view of both sides of the book."""

    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    last_order_sequence: int
    last_trade_sequence: int

    @property
    def best_bid(self) -> PriceLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> PriceLevel | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The complete deterministic result of accepting one limit order."""

    order: LimitOrder
    trades: tuple[Trade, ...]
    changed_orders: tuple[LimitOrder, ...]
    snapshot: BookSnapshot

    @property
    def executed_quantity(self) -> int:
        return sum(trade.quantity for trade in self.trades)

    @property
    def rested(self) -> bool:
        return self.order.is_active
