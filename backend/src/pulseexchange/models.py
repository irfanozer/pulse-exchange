"""Relational persistence model for accepted commands and market state."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pulseexchange.database import Base


class CommandType(enum.StrEnum):
    SUBMIT_ORDER = "submit_order"
    CANCEL_ORDER = "cancel_order"


class CommandStatus(enum.StrEnum):
    QUEUED = "queued"
    COMPLETED = "completed"
    REJECTED = "rejected"


class PersistedSide(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


class PersistedOrderStatus(enum.StrEnum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"


class MarketEventType(enum.StrEnum):
    ORDER_ACCEPTED = "order_accepted"
    ORDER_CANCELLED = "order_cancelled"
    COMMAND_REJECTED = "command_rejected"


def enum_column(enum_type: type[enum.StrEnum], name: str) -> Enum:
    """Store stable enum values rather than Python member names."""

    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda values: [member.value for member in values],
    )


json_type = JSON().with_variant(JSONB(), "postgresql")
identity_type = BigInteger().with_variant(Integer(), "sqlite")


class MarketCommand(Base):
    """Durable, globally sequenced intent accepted by the public API."""

    __tablename__ = "market_commands"
    __table_args__ = (
        Index("ix_market_commands_queue", "status", "sequence"),
        Index("ix_market_commands_symbol_sequence", "symbol", "sequence"),
    )

    sequence: Mapped[int] = mapped_column(
        identity_type,
        Identity(start=1),
        primary_key=True,
    )
    command_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    command_type: Mapped[CommandType] = mapped_column(
        enum_column(CommandType, "command_type"), nullable=False
    )
    status: Mapped[CommandStatus] = mapped_column(
        enum_column(CommandStatus, "command_status"),
        nullable=False,
        default=CommandStatus.QUEUED,
        server_default=CommandStatus.QUEUED.value,
    )
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(json_type, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderRecord(Base):
    """Materialized order state rebuilt by the ordered command processor."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_orders_positive_price"),
        CheckConstraint("quantity > 0", name="ck_orders_positive_quantity"),
        CheckConstraint(
            "remaining_quantity >= 0 AND remaining_quantity <= quantity",
            name="ck_orders_valid_remaining_quantity",
        ),
        Index("ix_orders_active_book", "symbol", "status", "price", "sequence"),
    )

    order_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    side: Mapped[PersistedSide] = mapped_column(
        enum_column(PersistedSide, "order_side"), nullable=False
    )
    # Prices are integer minor units.  This avoids binary floating-point and
    # makes replay bit-for-bit deterministic.
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remaining_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    status: Mapped[PersistedOrderStatus] = mapped_column(
        enum_column(PersistedOrderStatus, "order_status"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TradeRecord(Base):
    """Immutable execution produced by a matching command."""

    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("symbol", "trade_sequence", name="uq_trades_symbol_sequence"),
        CheckConstraint("price > 0", name="ck_trades_positive_price"),
        CheckConstraint("quantity > 0", name="ck_trades_positive_quantity"),
        Index("ix_trades_symbol_created", "symbol", "trade_id"),
    )

    trade_id: Mapped[int] = mapped_column(
        identity_type,
        Identity(start=1),
        primary_key=True,
    )
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    trade_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    command_sequence: Mapped[int] = mapped_column(
        ForeignKey("market_commands.sequence"), nullable=False
    )
    maker_order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    taker_order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    maker_side: Mapped[PersistedSide] = mapped_column(
        enum_column(PersistedSide, "trade_maker_side"), nullable=False
    )
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketEvent(Base):
    """Append-only update consumed by real-time clients."""

    __tablename__ = "market_events"
    __table_args__ = (Index("ix_market_events_symbol_event", "symbol", "event_id"),)

    event_id: Mapped[int] = mapped_column(
        identity_type,
        Identity(start=1),
        primary_key=True,
    )
    command_sequence: Mapped[int] = mapped_column(
        ForeignKey("market_commands.sequence"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    event_type: Mapped[MarketEventType] = mapped_column(
        enum_column(MarketEventType, "market_event_type"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
