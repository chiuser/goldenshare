"""drop legacy index daily bar table

Revision ID: 20260517_000112
Revises: 20260517_000111
Create Date: 2026-05-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260517_000112"
down_revision = "20260517_000111"
branch_labels = None
depends_on = None


CORE_SCHEMA = "core"
TABLE_NAME = "index_daily_bar"


def upgrade() -> None:
    op.drop_table(TABLE_NAME, schema=CORE_SCHEMA)


def downgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("change_amount", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema=CORE_SCHEMA,
    )
    op.create_index("idx_index_daily_bar_trade_date", TABLE_NAME, ["trade_date"], schema=CORE_SCHEMA)
