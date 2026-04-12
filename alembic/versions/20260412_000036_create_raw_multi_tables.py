"""create raw multi tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_000036"
down_revision = "20260412_000035"
branch_labels = None
depends_on = None


def _create_equity_daily_bar(schema: str, api_name: str) -> None:
    op.create_table(
        "equity_daily_bar",
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("change_amount", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text(f"'{api_name}'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema=schema,
    )


def _create_equity_adj_factor(schema: str, api_name: str) -> None:
    op.create_table(
        "equity_adj_factor",
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("adj_factor", sa.Numeric(20, 8)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text(f"'{api_name}'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema=schema,
    )


def _create_equity_daily_basic(schema: str, api_name: str) -> None:
    op.create_table(
        "equity_daily_basic",
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("turnover_rate_f", sa.Numeric(12, 4)),
        sa.Column("volume_ratio", sa.Numeric(12, 4)),
        sa.Column("pe", sa.Numeric(18, 4)),
        sa.Column("pe_ttm", sa.Numeric(18, 4)),
        sa.Column("pb", sa.Numeric(18, 4)),
        sa.Column("ps", sa.Numeric(18, 4)),
        sa.Column("ps_ttm", sa.Numeric(18, 4)),
        sa.Column("dv_ratio", sa.Numeric(12, 4)),
        sa.Column("dv_ttm", sa.Numeric(12, 4)),
        sa.Column("total_share", sa.Numeric(20, 4)),
        sa.Column("float_share", sa.Numeric(20, 4)),
        sa.Column("free_share", sa.Numeric(20, 4)),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("circ_mv", sa.Numeric(20, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text(f"'{api_name}'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema=schema,
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_biying")

    _create_equity_daily_bar("raw_tushare", "daily")
    _create_equity_adj_factor("raw_tushare", "adj_factor")
    _create_equity_daily_basic("raw_tushare", "daily_basic")

    _create_equity_daily_bar("raw_biying", "equity_daily_bar")
    _create_equity_adj_factor("raw_biying", "equity_adj_factor")
    _create_equity_daily_basic("raw_biying", "equity_daily_basic")


def downgrade() -> None:
    op.drop_table("equity_daily_basic", schema="raw_biying")
    op.drop_table("equity_adj_factor", schema="raw_biying")
    op.drop_table("equity_daily_bar", schema="raw_biying")

    op.drop_table("equity_daily_basic", schema="raw_tushare")
    op.drop_table("equity_adj_factor", schema="raw_tushare")
    op.drop_table("equity_daily_bar", schema="raw_tushare")
