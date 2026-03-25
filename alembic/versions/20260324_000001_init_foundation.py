"""init foundation"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260324_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS dm")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    op.create_table(
        "stock_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("symbol", sa.String(length=16)),
        sa.Column("name", sa.String(length=64)),
        sa.Column("area", sa.String(length=64)),
        sa.Column("industry", sa.String(length=64)),
        sa.Column("market", sa.String(length=32)),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("curr_type", sa.String(length=16)),
        sa.Column("list_status", sa.String(length=8)),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("is_hs", sa.String(length=8)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="stock_basic"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "trade_cal",
        sa.Column("exchange", sa.String(length=16), primary_key=True),
        sa.Column("cal_date", sa.Date(), primary_key=True),
        sa.Column("is_open", sa.Boolean()),
        sa.Column("pretrade_date", sa.Date()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="trade_cal"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "daily",
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
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="daily"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "adj_factor",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("adj_factor", sa.Numeric(20, 8)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="adj_factor"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "daily_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
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
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="daily_basic"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "moneyflow",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("buy_sm_vol", sa.Numeric(20, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(20, 4)),
        sa.Column("sell_sm_vol", sa.Numeric(20, 4)),
        sa.Column("sell_sm_amount", sa.Numeric(20, 4)),
        sa.Column("buy_md_vol", sa.Numeric(20, 4)),
        sa.Column("buy_md_amount", sa.Numeric(20, 4)),
        sa.Column("sell_md_vol", sa.Numeric(20, 4)),
        sa.Column("sell_md_amount", sa.Numeric(20, 4)),
        sa.Column("buy_lg_vol", sa.Numeric(20, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(20, 4)),
        sa.Column("sell_lg_vol", sa.Numeric(20, 4)),
        sa.Column("sell_lg_amount", sa.Numeric(20, 4)),
        sa.Column("buy_elg_vol", sa.Numeric(20, 4)),
        sa.Column("buy_elg_amount", sa.Numeric(20, 4)),
        sa.Column("sell_elg_vol", sa.Numeric(20, 4)),
        sa.Column("sell_elg_amount", sa.Numeric(20, 4)),
        sa.Column("net_mf_vol", sa.Numeric(20, 4)),
        sa.Column("net_mf_amount", sa.Numeric(20, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="moneyflow"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "top_list",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("reason", sa.Text(), primary_key=True),
        sa.Column("name", sa.String(length=64)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("l_sell", sa.Numeric(20, 4)),
        sa.Column("l_buy", sa.Numeric(20, 4)),
        sa.Column("l_amount", sa.Numeric(20, 4)),
        sa.Column("net_amount", sa.Numeric(20, 4)),
        sa.Column("net_rate", sa.Numeric(12, 4)),
        sa.Column("amount_rate", sa.Numeric(12, 4)),
        sa.Column("float_values", sa.Numeric(20, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="top_list"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "block_trade",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("buyer", sa.String(length=128), primary_key=True),
        sa.Column("seller", sa.String(length=128), primary_key=True),
        sa.Column("price", sa.Numeric(18, 4), primary_key=True),
        sa.Column("vol", sa.Numeric(20, 4), primary_key=True),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="block_trade"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "dividend",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("ann_date", sa.Date(), primary_key=True),
        sa.Column("record_date", sa.Date(), primary_key=True),
        sa.Column("ex_date", sa.Date(), primary_key=True),
        sa.Column("pay_date", sa.Date()),
        sa.Column("imp_ann_date", sa.Date()),
        sa.Column("base_date", sa.Date()),
        sa.Column("base_share", sa.Numeric(20, 4)),
        sa.Column("div_proc", sa.String(length=32)),
        sa.Column("stk_div", sa.Numeric(12, 6)),
        sa.Column("stk_bo_rate", sa.Numeric(12, 6)),
        sa.Column("stk_co_rate", sa.Numeric(12, 6)),
        sa.Column("cash_div", sa.Numeric(12, 6)),
        sa.Column("cash_div_tax", sa.Numeric(12, 6)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="dividend"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "fund_daily",
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
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="fund_daily"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "index_daily",
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
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="index_daily"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "holdernumber",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("ann_date", sa.Date(), primary_key=True),
        sa.Column("end_date", sa.Date()),
        sa.Column("holder_num", sa.BigInteger()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="stk_holdernumber"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
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

    timestamp_cols = [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]

    op.create_table(
        "security",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("symbol", sa.String(length=16)),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("area", sa.String(length=64)),
        sa.Column("industry", sa.String(length=64)),
        sa.Column("market", sa.String(length=32)),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("list_status", sa.String(length=8)),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("is_hs", sa.String(length=8)),
        sa.Column("security_type", sa.String(length=16), nullable=False, server_default="EQUITY"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="tushare"),
        *timestamp_cols,
        schema="core",
    )
    op.create_index("idx_security_name", "security", ["name"], schema="core")
    op.create_index("idx_security_industry", "security", ["industry"], schema="core")
    op.create_index("idx_security_list_status", "security", ["list_status"], schema="core")

    op.create_table(
        "trade_calendar",
        sa.Column("exchange", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("pretrade_date", sa.Date()),
        schema="core",
    )
    op.create_index("idx_trade_calendar_trade_date", "trade_calendar", ["trade_date"], schema="core")

    def create_core_daily_table(name: str, include_source: bool = False) -> None:
        extra_columns = []
        if include_source:
            extra_columns.append(sa.Column("source", sa.String(length=32), nullable=False, server_default="tushare"))
        op.create_table(
            name,
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
            *extra_columns,
            *timestamp_cols,
            schema="core",
        )

    create_core_daily_table("fund_daily_bar")
    create_core_daily_table("index_daily_bar")
    create_core_daily_table("equity_daily_bar", include_source=True)
    op.create_index("idx_equity_daily_bar_trade_date", "equity_daily_bar", ["trade_date"], schema="core")
    op.create_index("idx_equity_daily_bar_ts_code_trade_date_desc", "equity_daily_bar", ["ts_code", "trade_date"], schema="core")

    op.create_table(
        "equity_adj_factor",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("adj_factor", sa.Numeric(20, 8), nullable=False),
        *timestamp_cols,
        schema="core",
    )
    op.create_index("idx_equity_adj_factor_trade_date", "equity_adj_factor", ["trade_date"], schema="core")

    op.create_table(
        "equity_daily_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
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
        *timestamp_cols,
        schema="core",
    )
    op.create_index("idx_equity_daily_basic_trade_date", "equity_daily_basic", ["trade_date"], schema="core")
    op.create_index("idx_equity_daily_basic_pb_trade_date", "equity_daily_basic", ["trade_date", "pb"], schema="core")
    op.create_index("idx_equity_daily_basic_total_mv_trade_date", "equity_daily_basic", ["trade_date", "total_mv"], schema="core")

    op.create_table(
        "equity_moneyflow",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("buy_sm_vol", sa.Numeric(20, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(20, 4)),
        sa.Column("sell_sm_vol", sa.Numeric(20, 4)),
        sa.Column("sell_sm_amount", sa.Numeric(20, 4)),
        sa.Column("buy_md_vol", sa.Numeric(20, 4)),
        sa.Column("buy_md_amount", sa.Numeric(20, 4)),
        sa.Column("sell_md_vol", sa.Numeric(20, 4)),
        sa.Column("sell_md_amount", sa.Numeric(20, 4)),
        sa.Column("buy_lg_vol", sa.Numeric(20, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(20, 4)),
        sa.Column("sell_lg_vol", sa.Numeric(20, 4)),
        sa.Column("sell_lg_amount", sa.Numeric(20, 4)),
        sa.Column("buy_elg_vol", sa.Numeric(20, 4)),
        sa.Column("buy_elg_amount", sa.Numeric(20, 4)),
        sa.Column("sell_elg_vol", sa.Numeric(20, 4)),
        sa.Column("sell_elg_amount", sa.Numeric(20, 4)),
        sa.Column("net_mf_vol", sa.Numeric(20, 4)),
        sa.Column("net_mf_amount", sa.Numeric(20, 4)),
        *timestamp_cols,
        schema="core",
    )
    op.create_index("idx_equity_moneyflow_trade_date", "equity_moneyflow", ["trade_date"], schema="core")
    op.create_index("idx_equity_moneyflow_net_mf_amount_trade_date", "equity_moneyflow", ["trade_date", "net_mf_amount"], schema="core")

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
        *timestamp_cols,
        schema="core",
    )
    op.create_index("idx_equity_limit_list_trade_date", "equity_limit_list", ["trade_date"], schema="core")

    op.create_table(
        "equity_top_list",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("reason", sa.Text(), primary_key=True),
        sa.Column("name", sa.String(length=64)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("l_sell", sa.Numeric(20, 4)),
        sa.Column("l_buy", sa.Numeric(20, 4)),
        sa.Column("l_amount", sa.Numeric(20, 4)),
        sa.Column("net_amount", sa.Numeric(20, 4)),
        sa.Column("net_rate", sa.Numeric(12, 4)),
        sa.Column("amount_rate", sa.Numeric(12, 4)),
        sa.Column("float_values", sa.Numeric(20, 4)),
        *timestamp_cols,
        schema="core",
    )
    op.create_index("idx_equity_top_list_trade_date", "equity_top_list", ["trade_date"], schema="core")

    op.create_table(
        "equity_block_trade",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("buyer", sa.String(length=128), primary_key=True),
        sa.Column("seller", sa.String(length=128), primary_key=True),
        sa.Column("price", sa.Numeric(18, 4), primary_key=True),
        sa.Column("vol", sa.Numeric(20, 4), primary_key=True),
        sa.Column("amount", sa.Numeric(20, 4)),
        *timestamp_cols,
        schema="core",
    )
    op.create_index("idx_equity_block_trade_trade_date", "equity_block_trade", ["trade_date"], schema="core")

    op.create_table(
        "equity_dividend",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("ann_date", sa.Date(), primary_key=True),
        sa.Column("record_date", sa.Date(), primary_key=True),
        sa.Column("ex_date", sa.Date(), primary_key=True),
        sa.Column("pay_date", sa.Date()),
        sa.Column("imp_ann_date", sa.Date()),
        sa.Column("base_date", sa.Date()),
        sa.Column("base_share", sa.Numeric(20, 4)),
        sa.Column("div_proc", sa.String(length=32)),
        sa.Column("stk_div", sa.Numeric(12, 6)),
        sa.Column("stk_bo_rate", sa.Numeric(12, 6)),
        sa.Column("stk_co_rate", sa.Numeric(12, 6)),
        sa.Column("cash_div", sa.Numeric(12, 6)),
        sa.Column("cash_div_tax", sa.Numeric(12, 6)),
        *timestamp_cols,
        schema="core",
    )
    op.create_index("idx_equity_dividend_ex_date", "equity_dividend", ["ex_date"], schema="core")
    op.create_index("idx_equity_dividend_ann_date", "equity_dividend", ["ann_date"], schema="core")

    op.create_table(
        "equity_holder_number",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("ann_date", sa.Date(), primary_key=True),
        sa.Column("end_date", sa.Date()),
        sa.Column("holder_num", sa.BigInteger()),
        *timestamp_cols,
        schema="core",
    )
    op.create_index("idx_equity_holder_number_end_date", "equity_holder_number", ["end_date"], schema="core")

    op.create_table(
        "sync_job_state",
        sa.Column("job_name", sa.String(length=64), primary_key=True),
        sa.Column("target_table", sa.String(length=128), nullable=False),
        sa.Column("last_success_date", sa.Date()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_cursor", sa.String(length=128)),
        sa.Column("full_sync_done", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="ops",
    )
    op.create_table(
        "sync_run_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_name", sa.String(length=64), nullable=False),
        sa.Column("run_type", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rows_fetched", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("rows_written", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text()),
        schema="ops",
    )
    op.create_index("idx_sync_run_log_job_name_started_at", "sync_run_log", ["job_name", "started_at"], schema="ops")

    op.execute(
        """
        CREATE MATERIALIZED VIEW dm.equity_daily_snapshot AS
        SELECT
            b.ts_code,
            s.name,
            s.industry,
            s.market,
            b.trade_date,
            b.open,
            b.high,
            b.low,
            b.close,
            b.pct_chg,
            b.vol,
            b.amount,
            db.turnover_rate,
            db.volume_ratio,
            db.pe,
            db.pb,
            db.total_mv,
            db.circ_mv,
            mf.net_mf_amount
        FROM core.equity_daily_bar b
        JOIN core.security s ON s.ts_code = b.ts_code
        LEFT JOIN core.equity_daily_basic db
            ON db.ts_code = b.ts_code AND db.trade_date = b.trade_date
        LEFT JOIN core.equity_moneyflow mf
            ON mf.ts_code = b.ts_code AND mf.trade_date = b.trade_date
        WITH NO DATA
        """
    )
    op.execute(
        """
        CREATE VIEW dm.equity_qfq_bar AS
        WITH end_factor AS (
            SELECT ts_code, MAX(trade_date) AS end_trade_date
            FROM core.equity_adj_factor
            GROUP BY ts_code
        ),
        factor_base AS (
            SELECT a.ts_code, a.trade_date, a.adj_factor, e.end_trade_date
            FROM core.equity_adj_factor a
            JOIN end_factor e ON e.ts_code = a.ts_code
        ),
        factor_end AS (
            SELECT fb.ts_code, fb.trade_date, fb.adj_factor, ae.adj_factor AS end_adj_factor
            FROM factor_base fb
            JOIN core.equity_adj_factor ae
              ON ae.ts_code = fb.ts_code AND ae.trade_date = fb.end_trade_date
        )
        SELECT
            b.ts_code,
            b.trade_date,
            ROUND(b.open * fe.adj_factor / NULLIF(fe.end_adj_factor, 0), 4) AS open_qfq,
            ROUND(b.high * fe.adj_factor / NULLIF(fe.end_adj_factor, 0), 4) AS high_qfq,
            ROUND(b.low * fe.adj_factor / NULLIF(fe.end_adj_factor, 0), 4) AS low_qfq,
            ROUND(b.close * fe.adj_factor / NULLIF(fe.end_adj_factor, 0), 4) AS close_qfq,
            b.open,
            b.high,
            b.low,
            b.close,
            fe.adj_factor,
            fe.end_adj_factor
        FROM core.equity_daily_bar b
        JOIN factor_end fe
          ON fe.ts_code = b.ts_code AND fe.trade_date = b.trade_date
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS dm.equity_qfq_bar")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS dm.equity_daily_snapshot")
    for name in ["sync_run_log", "sync_job_state"]:
        op.drop_table(name, schema="ops")
    for name in [
        "equity_holder_number",
        "equity_dividend",
        "equity_block_trade",
        "equity_top_list",
        "equity_limit_list",
        "equity_moneyflow",
        "equity_daily_basic",
        "equity_adj_factor",
        "equity_daily_bar",
        "index_daily_bar",
        "fund_daily_bar",
        "trade_calendar",
        "security",
    ]:
        op.drop_table(name, schema="core")
    for name in [
        "limit_list",
        "holdernumber",
        "index_daily",
        "fund_daily",
        "dividend",
        "block_trade",
        "top_list",
        "moneyflow",
        "daily_basic",
        "adj_factor",
        "daily",
        "trade_cal",
        "stock_basic",
    ]:
        op.drop_table(name, schema="raw")
    op.execute("DROP SCHEMA IF EXISTS ops CASCADE")
    op.execute("DROP SCHEMA IF EXISTS dm CASCADE")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
    op.execute("DROP SCHEMA IF EXISTS raw CASCADE")
