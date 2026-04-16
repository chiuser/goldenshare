"""add stk_limit tables for tushare raw and serving

Revision ID: 20260416_000054
Revises: 20260416_000053
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000054"
down_revision = "20260416_000053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("stk_limit", schema="raw_tushare"):
        op.create_table(
            "stk_limit",
            sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
            sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
            sa.Column("pre_close", sa.Numeric(18, 4)),
            sa.Column("up_limit", sa.Numeric(18, 4)),
            sa.Column("down_limit", sa.Numeric(18, 4)),
            sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'stk_limit'")),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", sa.Text()),
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_stk_limit_trade_date",
            "stk_limit",
            ["trade_date"],
            schema="raw_tushare",
        )

    if not inspector.has_table("equity_stk_limit", schema="core_serving"):
        op.create_table(
            "equity_stk_limit",
            sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
            sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
            sa.Column("pre_close", sa.Numeric(18, 4)),
            sa.Column("up_limit", sa.Numeric(18, 4)),
            sa.Column("down_limit", sa.Numeric(18, 4)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_stk_limit_trade_date",
            "equity_stk_limit",
            ["trade_date"],
            schema="core_serving",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("equity_stk_limit", schema="core_serving"):
        op.drop_index("idx_equity_stk_limit_trade_date", table_name="equity_stk_limit", schema="core_serving")
        op.drop_table("equity_stk_limit", schema="core_serving")

    if inspector.has_table("stk_limit", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_stk_limit_trade_date", table_name="stk_limit", schema="raw_tushare")
        op.drop_table("stk_limit", schema="raw_tushare")
