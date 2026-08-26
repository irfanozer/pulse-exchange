"""Domain exceptions raised by the deterministic matching engine."""


class EngineError(Exception):
    """Base class for matching-engine domain failures."""


class InvalidOrderError(EngineError, ValueError):
    """Raised when an order cannot represent valid engine state."""


class DuplicateOrderError(EngineError):
    """Raised when an order identifier has already been accepted."""


class DuplicateSequenceError(EngineError):
    """Raised when two orders use the same creation sequence."""


class OutOfSequenceError(EngineError):
    """Raised when a new order arrives behind the processed sequence."""


class UnknownOrderError(EngineError, LookupError):
    """Raised when an operation references an unknown order identifier."""


class OrderNotCancellableError(EngineError):
    """Raised when an order is already filled or cancelled."""


class BookInvariantError(EngineError, RuntimeError):
    """Raised when internal order-book state violates a safety invariant."""
