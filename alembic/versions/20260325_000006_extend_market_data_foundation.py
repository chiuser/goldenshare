"""extend market data foundation with period bars and index supplements"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260325_000006"
down_revision = "20260324_000005"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.add_column("security", sa.Column("curr_type", sa.String(length=16), nullable=True), schema="core")

    op.create_table(
        "stk_period_bar",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("freq", sa.String(length=8), primary_key=True),
        sa.Column("end_date", sa.Date()),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("change", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="stk_weekly_monthly"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "stk_period_bar_adj",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("freq", sa.String(length=8), primary_key=True),
        sa.Column("end_date", sa.Date()),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("open_qfq", sa.Numeric(18, 4)),
        sa.Column("high_qfq", sa.Numeric(18, 4)),
        sa.Column("low_qfq", sa.Numeric(18, 4)),
        sa.Column("close_qfq", sa.Numeric(18, 4)),
        sa.Column("open_hfq", sa.Numeric(18, 4)),
        sa.Column("high_hfq", sa.Numeric(18, 4)),
        sa.Column("low_hfq", sa.Numeric(18, 4)),
        sa.Column("close_hfq", sa.Numeric(18, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("change", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="stk_week_month_adj"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "index_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("fullname", sa.String(length=256)),
        sa.Column("market", sa.String(length=32)),
        sa.Column("publisher", sa.String(length=128)),
        sa.Column("index_type", sa.String(length=64)),
        sa.Column("category", sa.String(length=64)),
        sa.Column("base_date", sa.Date()),
        sa.Column("base_point", sa.Numeric(20, 4)),
        sa.Column("list_date", sa.Date()),
        sa.Column("weight_rule", sa.String(length=128)),
        sa.Column("desc", sa.Text()),
        sa.Column("exp_date", sa.Date()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="index_basic"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    for table_name in ("index_weekly_bar", "index_monthly_bar"):
        api_name = "index_weekly" if table_name == "index_weekly_bar" else "index_monthly"
        op.create_table(
            table_name,
            sa.Column("ts_code", sa.String(length=16), primary_key=True),
            sa.Column("trade_date", sa.Date(), primary_key=True),
            sa.Column("close", sa.Numeric(18, 4)),
            sa.Column("open", sa.Numeric(18, 4)),
            sa.Column("high", sa.Numeric(18, 4)),
            sa.Column("low", sa.Numeric(18, 4)),
            sa.Column("pre_close", sa.Numeric(18, 4)),
            sa.Column("change", sa.Numeric(18, 4)),
            sa.Column("pct_chg", sa.Numeric(10, 4)),
            sa.Column("vol", sa.Numeric(20, 4)),
            sa.Column("amount", sa.Numeric(20, 4)),
            sa.Column("api_name", sa.String(length=32), nullable=False, server_default=api_name),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", sa.Text()),
            schema="raw",
        )
    op.create_table(
        "index_weight",
        sa.Column("index_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("con_code", sa.String(length=16), primary_key=True),
        sa.Column("weight", sa.Numeric(12, 6)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="index_weight"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "index_daily_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("float_mv", sa.Numeric(20, 4)),
        sa.Column("total_share", sa.Numeric(20, 4)),
        sa.Column("float_share", sa.Numeric(20, 4)),
        sa.Column("free_share", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("turnover_rate_f", sa.Numeric(12, 4)),
        sa.Column("pe", sa.Numeric(18, 4)),
        sa.Column("pe_ttm", sa.Numeric(18, 4)),
        sa.Column("pb", sa.Numeric(18, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="index_dailybasic"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "stk_period_bar",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("freq", sa.String(length=8), primary_key=True),
        sa.Column("end_date", sa.Date()),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("change_amount", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_stk_period_bar_freq_trade_date", "stk_period_bar", ["freq", "trade_date"], schema="core")
    op.create_index("idx_stk_period_bar_trade_date", "stk_period_bar", ["trade_date"], schema="core")

    op.create_table(
        "stk_period_bar_adj",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("freq", sa.String(length=8), primary_key=True),
        sa.Column("end_date", sa.Date()),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("open_qfq", sa.Numeric(18, 4)),
        sa.Column("high_qfq", sa.Numeric(18, 4)),
        sa.Column("low_qfq", sa.Numeric(18, 4)),
        sa.Column("close_qfq", sa.Numeric(18, 4)),
        sa.Column("open_hfq", sa.Numeric(18, 4)),
        sa.Column("high_hfq", sa.Numeric(18, 4)),
        sa.Column("low_hfq", sa.Numeric(18, 4)),
        sa.Column("close_hfq", sa.Numeric(18, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("change_amount", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_stk_period_bar_adj_freq_trade_date", "stk_period_bar_adj", ["freq", "trade_date"], schema="core")
    op.create_index("idx_stk_period_bar_adj_trade_date", "stk_period_bar_adj", ["trade_date"], schema="core")

    op.create_table(
        "index_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("fullname", sa.String(length=256)),
        sa.Column("market", sa.String(length=32)),
        sa.Column("publisher", sa.String(length=128)),
        sa.Column("index_type", sa.String(length=64)),
        sa.Column("category", sa.String(length=64)),
        sa.Column("base_date", sa.Date()),
        sa.Column("base_point", sa.Numeric(20, 4)),
        sa.Column("list_date", sa.Date()),
        sa.Column("weight_rule", sa.String(length=128)),
        sa.Column("desc", sa.Text()),
        sa.Column("exp_date", sa.Date()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_index_basic_market", "index_basic", ["market"], schema="core")
    op.create_index("idx_index_basic_publisher", "index_basic", ["publisher"], schema="core")
    op.create_index("idx_index_basic_category", "index_basic", ["category"], schema="core")

    for table_name in ("index_weekly_bar", "index_monthly_bar"):
        op.create_table(
            table_name,
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
            *TIMESTAMP_COLS,
            schema="core",
        )
        op.create_index(f"idx_{table_name}_trade_date", table_name, ["trade_date"], schema="core")

    op.create_table(
        "index_weight",
        sa.Column("index_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("con_code", sa.String(length=16), primary_key=True),
        sa.Column("weight", sa.Numeric(12, 6)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_index_weight_index_code_trade_date", "index_weight", ["index_code", "trade_date"], schema="core")
    op.create_index("idx_index_weight_con_code_trade_date", "index_weight", ["con_code", "trade_date"], schema="core")

    op.create_table(
        "index_daily_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("float_mv", sa.Numeric(20, 4)),
        sa.Column("total_share", sa.Numeric(20, 4)),
        sa.Column("float_share", sa.Numeric(20, 4)),
        sa.Column("free_share", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("turnover_rate_f", sa.Numeric(12, 4)),
        sa.Column("pe", sa.Numeric(18, 4)),
        sa.Column("pe_ttm", sa.Numeric(18, 4)),
        sa.Column("pb", sa.Numeric(18, 4)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_index_daily_basic_trade_date", "index_daily_basic", ["trade_date"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_index_daily_basic_trade_date", table_name="index_daily_basic", schema="core")
    op.drop_table("index_daily_basic", schema="core")
    op.drop_index("idx_index_weight_con_code_trade_date", table_name="index_weight", schema="core")
    op.drop_index("idx_index_weight_index_code_trade_date", table_name="index_weight", schema="core")
    op.drop_table("index_weight", schema="core")
    op.drop_index("idx_index_monthly_bar_trade_date", table_name="index_monthly_bar", schema="core")
    op.drop_table("index_monthly_bar", schema="core")
    op.drop_index("idx_index_weekly_bar_trade_date", table_name="index_weekly_bar", schema="core")
    op.drop_table("index_weekly_bar", schema="core")
    op.drop_index("idx_index_basic_category", table_name="index_basic", schema="core")
    op.drop_index("idx_index_basic_publisher", table_name="index_basic", schema="core")
    op.drop_index("idx_index_basic_market", table_name="index_basic", schema="core")
    op.drop_table("index_basic", schema="core")
    op.drop_index("idx_stk_period_bar_adj_trade_date", table_name="stk_period_bar_adj", schema="core")
    op.drop_index("idx_stk_period_bar_adj_freq_trade_date", table_name="stk_period_bar_adj", schema="core")
    op.drop_table("stk_period_bar_adj", schema="core")
    op.drop_index("idx_stk_period_bar_trade_date", table_name="stk_period_bar", schema="core")
    op.drop_index("idx_stk_period_bar_freq_trade_date", table_name="stk_period_bar", schema="core")
    op.drop_table("stk_period_bar", schema="core")

    op.drop_table("index_daily_basic", schema="raw")
    op.drop_table("index_weight", schema="raw")
    op.drop_table("index_monthly_bar", schema="raw")
    op.drop_table("index_weekly_bar", schema="raw")
    op.drop_table("index_basic", schema="raw")
    op.drop_table("stk_period_bar_adj", schema="raw")
    op.drop_table("stk_period_bar", schema="raw")

    op.drop_column("security", "curr_type", schema="core")
