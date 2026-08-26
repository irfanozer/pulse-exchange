"""Public domain API for the PulseExchange matching engine."""

from .exceptions import (
    BookInvariantError,
    DuplicateOrderError,
    DuplicateSequenceError,
    EngineError,
    InvalidOrderError,
    OrderNotCancellableError,
    OutOfSequenceError,
    UnknownOrderError,
)
from .matching import MatchingEngine
from .models import BookSnapshot, LimitOrder, MatchResult, OrderStatus, PriceLevel, Side, Trade

__all__ = [
    "BookInvariantError",
    "BookSnapshot",
    "DuplicateOrderError",
    "DuplicateSequenceError",
    "EngineError",
    "InvalidOrderError",
    "LimitOrder",
    "MatchResult",
    "MatchingEngine",
    "OrderNotCancellableError",
    "OrderStatus",
    "OutOfSequenceError",
    "PriceLevel",
    "Side",
    "Trade",
    "UnknownOrderError",
]
