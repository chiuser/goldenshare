"""add etf series active table

Revision ID: 20260618_000117
Revises: 20260602_000116
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260618_000117"
down_revision = "20260602_000116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")
    op.create_table(
        "etf_series_active",
        sa.Column("resource", sa.String(length=64), nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("first_seen_date", sa.Date(), nullable=False),
        sa.Column("last_seen_date", sa.Date(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("resource", "ts_code", name="pk_etf_series_active"),
        schema="ops",
    )
    op.create_index("idx_etf_series_active_resource", "etf_series_active", ["resource"], schema="ops")
    op.create_index(
        "idx_etf_series_active_resource_last_seen",
        "etf_series_active",
        ["resource", "last_seen_date"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index("idx_etf_series_active_resource_last_seen", table_name="etf_series_active", schema="ops")
    op.drop_index("idx_etf_series_active_resource", table_name="etf_series_active", schema="ops")
    op.drop_table("etf_series_active", schema="ops")
