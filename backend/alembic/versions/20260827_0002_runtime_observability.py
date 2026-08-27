"""Add cross-process runtime and correlation evidence.

Revision ID: 20260827_0002
Revises: 20260825_0001
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260827_0002"
down_revision: str | None = "20260825_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "market_commands",
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE market_commands SET correlation_id = command_id")
    op.alter_column("market_commands", "correlation_id", nullable=False)
    op.add_column(
        "market_commands",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "runtime_heartbeats",
        sa.Column("service_name", sa.String(length=50), nullable=False),
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("service_name", "instance_id"),
    )
    op.create_index(
        "ix_runtime_heartbeats_service_seen",
        "runtime_heartbeats",
        ["service_name", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_heartbeats_service_seen",
        table_name="runtime_heartbeats",
    )
    op.drop_table("runtime_heartbeats")
    op.drop_column("market_commands", "processing_started_at")
    op.drop_column("market_commands", "correlation_id")
