"""add stk_nineturn tables for tushare raw and serving

Revision ID: 20260416_000055
Revises: 20260416_000054
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000055"
down_revision = "20260416_000054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("stk_nineturn", schema="raw_tushare"):
        op.create_table(
            "stk_nineturn",
            sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
            sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
            sa.Column("freq", sa.String(length=16)),
            sa.Column("open", sa.Numeric(18, 4)),
            sa.Column("high", sa.Numeric(18, 4)),
            sa.Column("low", sa.Numeric(18, 4)),
            sa.Column("close", sa.Numeric(18, 4)),
            sa.Column("vol", sa.Numeric(20, 4)),
            sa.Column("amount", sa.Numeric(24, 4)),
            sa.Column("up_count", sa.Numeric(10, 4)),
            sa.Column("down_count", sa.Numeric(10, 4)),
            sa.Column("nine_up_turn", sa.String(length=16)),
            sa.Column("nine_down_turn", sa.String(length=16)),
            sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'stk_nineturn'")),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", sa.Text()),
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_stk_nineturn_trade_date",
            "stk_nineturn",
            ["trade_date"],
            schema="raw_tushare",
        )

    if not inspector.has_table("equity_nineturn", schema="core_serving"):
        op.create_table(
            "equity_nineturn",
            sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
            sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
            sa.Column("freq", sa.String(length=16)),
            sa.Column("open", sa.Numeric(18, 4)),
            sa.Column("high", sa.Numeric(18, 4)),
            sa.Column("low", sa.Numeric(18, 4)),
            sa.Column("close", sa.Numeric(18, 4)),
            sa.Column("vol", sa.Numeric(20, 4)),
            sa.Column("amount", sa.Numeric(24, 4)),
            sa.Column("up_count", sa.Numeric(10, 4)),
            sa.Column("down_count", sa.Numeric(10, 4)),
            sa.Column("nine_up_turn", sa.String(length=16)),
            sa.Column("nine_down_turn", sa.String(length=16)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_nineturn_trade_date",
            "equity_nineturn",
            ["trade_date"],
            schema="core_serving",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("equity_nineturn", schema="core_serving"):
        op.drop_index("idx_equity_nineturn_trade_date", table_name="equity_nineturn", schema="core_serving")
        op.drop_table("equity_nineturn", schema="core_serving")

    if inspector.has_table("stk_nineturn", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_stk_nineturn_trade_date", table_name="stk_nineturn", schema="raw_tushare")
        op.drop_table("stk_nineturn", schema="raw_tushare")
