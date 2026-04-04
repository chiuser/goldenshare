"""add index series active pool

Revision ID: 20260404_000028
Revises: 20260403_000027
Create Date: 2026-04-04 10:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260404_000028"
down_revision = "20260403_000027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "index_series_active",
        sa.Column("resource", sa.String(length=64), nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("first_seen_date", sa.Date(), nullable=False),
        sa.Column("last_seen_date", sa.Date(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("resource", "ts_code", name=op.f("pk_index_series_active")),
        schema="ops",
    )
    op.create_index(op.f("ix_ops_index_series_active_resource"), "index_series_active", ["resource"], unique=False, schema="ops")
    op.create_index(
        "idx_index_series_active_resource_last_seen",
        "index_series_active",
        ["resource", "last_seen_date"],
        unique=False,
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index("idx_index_series_active_resource_last_seen", table_name="index_series_active", schema="ops")
    op.drop_index(op.f("ix_ops_index_series_active_resource"), table_name="index_series_active", schema="ops")
    op.drop_table("index_series_active", schema="ops")
