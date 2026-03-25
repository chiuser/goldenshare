"""align schema with tushare docs"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260324_000002"
down_revision = "20260324_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_basic", sa.Column("fullname", sa.String(length=128)), schema="raw")
    op.add_column("stock_basic", sa.Column("enname", sa.String(length=128)), schema="raw")
    op.add_column("stock_basic", sa.Column("cnspell", sa.String(length=32)), schema="raw")
    op.add_column("stock_basic", sa.Column("act_name", sa.String(length=128)), schema="raw")
    op.add_column("stock_basic", sa.Column("act_ent_type", sa.String(length=64)), schema="raw")

    op.add_column("security", sa.Column("fullname", sa.String(length=128)), schema="core")
    op.add_column("security", sa.Column("enname", sa.String(length=128)), schema="core")
    op.add_column("security", sa.Column("cnspell", sa.String(length=32)), schema="core")
    op.add_column("security", sa.Column("act_name", sa.String(length=128)), schema="core")
    op.add_column("security", sa.Column("act_ent_type", sa.String(length=64)), schema="core")

    op.alter_column("daily", "change_amount", new_column_name="change", schema="raw")
    op.alter_column("fund_daily", "change_amount", new_column_name="change", schema="raw")
    op.alter_column("index_daily", "change_amount", new_column_name="change", schema="raw")
    op.alter_column("top_list", "pct_chg", new_column_name="pct_change", schema="raw")

    op.add_column("dividend", sa.Column("end_date", sa.Date()), schema="raw")
    op.add_column("dividend", sa.Column("div_listdate", sa.Date()), schema="raw")
    op.add_column("equity_dividend", sa.Column("end_date", sa.Date()), schema="core")
    op.add_column("equity_dividend", sa.Column("div_listdate", sa.Date()), schema="core")

    op.drop_table("limit_list", schema="raw")
    op.create_table(
        "limit_list",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("limit", sa.String(length=8), primary_key=True),
        sa.Column("industry", sa.String(length=64)),
        sa.Column("name", sa.String(length=64)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("limit_amount", sa.Numeric(20, 4)),
        sa.Column("float_mv", sa.Numeric(20, 4)),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("turnover_ratio", sa.Numeric(12, 4)),
        sa.Column("fd_amount", sa.Numeric(20, 4)),
        sa.Column("first_time", sa.String(length=16)),
        sa.Column("last_time", sa.String(length=16)),
        sa.Column("open_times", sa.Integer()),
        sa.Column("up_stat", sa.String(length=16)),
        sa.Column("limit_times", sa.Integer()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="limit_list_d"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.drop_index("idx_equity_limit_list_trade_date", table_name="equity_limit_list", schema="core")
    op.drop_table("equity_limit_list", schema="core")
    op.create_table(
        "equity_limit_list",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("limit_type", sa.String(length=16), primary_key=True),
        sa.Column("industry", sa.String(length=64)),
        sa.Column("name", sa.String(length=64)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("limit_amount", sa.Numeric(20, 4)),
        sa.Column("float_mv", sa.Numeric(20, 4)),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("turnover_ratio", sa.Numeric(12, 4)),
        sa.Column("fd_amount", sa.Numeric(20, 4)),
        sa.Column("first_time", sa.String(length=16)),
        sa.Column("last_time", sa.String(length=16)),
        sa.Column("open_times", sa.Integer()),
        sa.Column("up_stat", sa.String(length=16)),
        sa.Column("limit_times", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core",
    )
    op.create_index("idx_equity_limit_list_trade_date", "equity_limit_list", ["trade_date"], schema="core")

    op.execute("DROP INDEX IF EXISTS core.idx_equity_hk_hold_trade_date")
    op.execute("DROP TABLE IF EXISTS core.equity_hk_hold")
    op.execute("DROP TABLE IF EXISTS raw.hk_hold")


def downgrade() -> None:
    op.drop_index("idx_equity_limit_list_trade_date", table_name="equity_limit_list", schema="core")
    op.drop_table("equity_limit_list", schema="core")
    op.create_table(
        "equity_limit_list",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("limit_type", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=64)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("amp", sa.Numeric(10, 4)),
        sa.Column("fc_ratio", sa.Numeric(12, 4)),
        sa.Column("fl_ratio", sa.Numeric(12, 4)),
        sa.Column("fd_amount", sa.Numeric(20, 4)),
        sa.Column("first_time", sa.String(length=16)),
        sa.Column("last_time", sa.String(length=16)),
        sa.Column("open_times", sa.Integer()),
        sa.Column("strth", sa.Numeric(12, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core",
    )
    op.create_index("idx_equity_limit_list_trade_date", "equity_limit_list", ["trade_date"], schema="core")

    op.drop_table("limit_list", schema="raw")
    op.create_table(
        "limit_list",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("limit_type", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=64)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("amp", sa.Numeric(10, 4)),
        sa.Column("fc_ratio", sa.Numeric(12, 4)),
        sa.Column("fl_ratio", sa.Numeric(12, 4)),
        sa.Column("fd_amount", sa.Numeric(20, 4)),
        sa.Column("first_time", sa.String(length=16)),
        sa.Column("last_time", sa.String(length=16)),
        sa.Column("open_times", sa.Integer()),
        sa.Column("strth", sa.Numeric(12, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="limit_list_d"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.drop_column("equity_dividend", "div_listdate", schema="core")
    op.drop_column("equity_dividend", "end_date", schema="core")
    op.drop_column("dividend", "div_listdate", schema="raw")
    op.drop_column("dividend", "end_date", schema="raw")

    op.alter_column("top_list", "pct_change", new_column_name="pct_chg", schema="raw")
    op.alter_column("index_daily", "change", new_column_name="change_amount", schema="raw")
    op.alter_column("fund_daily", "change", new_column_name="change_amount", schema="raw")
    op.alter_column("daily", "change", new_column_name="change_amount", schema="raw")

    op.drop_column("security", "act_ent_type", schema="core")
    op.drop_column("security", "act_name", schema="core")
    op.drop_column("security", "cnspell", schema="core")
    op.drop_column("security", "enname", schema="core")
    op.drop_column("security", "fullname", schema="core")

    op.drop_column("stock_basic", "act_ent_type", schema="raw")
    op.drop_column("stock_basic", "act_name", schema="raw")
    op.drop_column("stock_basic", "cnspell", schema="raw")
    op.drop_column("stock_basic", "enname", schema="raw")
    op.drop_column("stock_basic", "fullname", schema="raw")
