"""Create durable commands and materialized market state.

Revision ID: 20260825_0001
Revises: None
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260825_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_commands",
        sa.Column(
            "sequence",
            sa.BigInteger(),
            sa.Identity(start=1),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("command_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column(
            "command_type",
            sa.Enum(
                "submit_order",
                "cancel_order",
                name="command_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "completed",
                "rejected",
                name="command_status",
                native_enum=False,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("command_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_market_commands_queue",
        "market_commands",
        ["status", "sequence"],
    )
    op.create_index(
        "ix_market_commands_symbol_sequence",
        "market_commands",
        ["symbol", "sequence"],
    )

    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column(
            "side",
            sa.Enum("buy", "sell", name="order_side", native_enum=False),
            nullable=False,
        ),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("remaining_quantity", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "partially_filled",
                "filled",
                "cancelled",
                name="order_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("price > 0", name="ck_orders_positive_price"),
        sa.CheckConstraint("quantity > 0", name="ck_orders_positive_quantity"),
        sa.CheckConstraint(
            "remaining_quantity >= 0 AND remaining_quantity <= quantity",
            name="ck_orders_valid_remaining_quantity",
        ),
        sa.UniqueConstraint("sequence"),
    )
    op.create_index(
        "ix_orders_active_book",
        "orders",
        ["symbol", "status", "price", "sequence"],
    )

    op.create_table(
        "trades",
        sa.Column(
            "trade_id",
            sa.BigInteger(),
            sa.Identity(start=1),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("trade_sequence", sa.BigInteger(), nullable=False),
        sa.Column("command_sequence", sa.BigInteger(), nullable=False),
        sa.Column("maker_order_id", sa.String(length=36), nullable=False),
        sa.Column("taker_order_id", sa.String(length=36), nullable=False),
        sa.Column(
            "maker_side",
            sa.Enum("buy", "sell", name="trade_maker_side", native_enum=False),
            nullable=False,
        ),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("price > 0", name="ck_trades_positive_price"),
        sa.CheckConstraint("quantity > 0", name="ck_trades_positive_quantity"),
        sa.ForeignKeyConstraint(
            ["command_sequence"],
            ["market_commands.sequence"],
        ),
        sa.UniqueConstraint(
            "symbol",
            "trade_sequence",
            name="uq_trades_symbol_sequence",
        ),
    )
    op.create_index("ix_trades_symbol_created", "trades", ["symbol", "trade_id"])

    op.create_table(
        "market_events",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.Identity(start=1),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("command_sequence", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "order_accepted",
                "order_cancelled",
                "command_rejected",
                name="market_event_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["command_sequence"],
            ["market_commands.sequence"],
        ),
    )
    op.create_index(
        "ix_market_events_symbol_event",
        "market_events",
        ["symbol", "event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_events_symbol_event", table_name="market_events")
    op.drop_table("market_events")
    op.drop_index("ix_trades_symbol_created", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_orders_active_book", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_market_commands_symbol_sequence", table_name="market_commands")
    op.drop_index("ix_market_commands_queue", table_name="market_commands")
    op.drop_table("market_commands")
