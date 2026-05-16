"""add stock auction open and close datasets

Revision ID: 20260516_000109
Revises: 20260516_000108
Create Date: 2026-05-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260516_000109"
down_revision = "20260516_000108"
branch_labels = None
depends_on = None


def _create_raw_table(*, table_name: str, api_name: str, index_name: str) -> None:
    op.create_table(
        table_name,
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("vwap", sa.Numeric(18, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text(f"'{api_name}'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_tushare",
    )
    op.create_index(index_name, table_name, ["trade_date"], schema="raw_tushare")


def _create_serving_table(*, table_name: str, index_name: str) -> None:
    op.create_table(
        table_name,
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("vwap", sa.Numeric(18, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core_serving",
    )
    op.create_index(index_name, table_name, ["trade_date"], schema="core_serving")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("stk_auction_o", schema="raw_tushare"):
        _create_raw_table(
            table_name="stk_auction_o",
            api_name="stk_auction_o",
            index_name="idx_raw_tushare_stk_auction_o_trade_date",
        )
    if not inspector.has_table("stk_auction_c", schema="raw_tushare"):
        _create_raw_table(
            table_name="stk_auction_c",
            api_name="stk_auction_c",
            index_name="idx_raw_tushare_stk_auction_c_trade_date",
        )
    if not inspector.has_table("equity_auction_open", schema="core_serving"):
        _create_serving_table(
            table_name="equity_auction_open",
            index_name="idx_equity_auction_open_trade_date",
        )
    if not inspector.has_table("equity_auction_close", schema="core_serving"):
        _create_serving_table(
            table_name="equity_auction_close",
            index_name="idx_equity_auction_close_trade_date",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("equity_auction_close", schema="core_serving"):
        op.drop_index("idx_equity_auction_close_trade_date", table_name="equity_auction_close", schema="core_serving")
        op.drop_table("equity_auction_close", schema="core_serving")
    if inspector.has_table("equity_auction_open", schema="core_serving"):
        op.drop_index("idx_equity_auction_open_trade_date", table_name="equity_auction_open", schema="core_serving")
        op.drop_table("equity_auction_open", schema="core_serving")
    if inspector.has_table("stk_auction_c", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_stk_auction_c_trade_date", table_name="stk_auction_c", schema="raw_tushare")
        op.drop_table("stk_auction_c", schema="raw_tushare")
    if inspector.has_table("stk_auction_o", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_stk_auction_o_trade_date", table_name="stk_auction_o", schema="raw_tushare")
        op.drop_table("stk_auction_o", schema="raw_tushare")
