"""add six tushare moneyflow datasets (raw + serving)

Revision ID: 20260417_000065
Revises: 20260417_000064
Create Date: 2026-04-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_000065"
down_revision = "20260417_000064"
branch_labels = None
depends_on = None


def _create_raw_moneyflow_ths(inspector: sa.Inspector) -> None:
    if inspector.has_table("moneyflow_ths", schema="raw_tushare"):
        return
    op.create_table(
        "moneyflow_ths",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=64)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("latest", sa.Numeric(18, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("net_d5_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_md_amount", sa.Numeric(24, 4)),
        sa.Column("buy_md_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(24, 4)),
        sa.Column("buy_sm_amount_rate", sa.Numeric(10, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'moneyflow_ths'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_tushare",
    )
    op.create_index("idx_raw_tushare_moneyflow_ths_trade_date", "moneyflow_ths", ["trade_date"], schema="raw_tushare")
    op.create_index(
        "idx_raw_tushare_moneyflow_ths_ts_code_trade_date",
        "moneyflow_ths",
        ["ts_code", "trade_date"],
        schema="raw_tushare",
    )


def _create_raw_moneyflow_dc(inspector: sa.Inspector) -> None:
    if inspector.has_table("moneyflow_dc", schema="raw_tushare"):
        return
    op.create_table(
        "moneyflow_dc",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=64)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_elg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_elg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_md_amount", sa.Numeric(24, 4)),
        sa.Column("buy_md_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(24, 4)),
        sa.Column("buy_sm_amount_rate", sa.Numeric(10, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'moneyflow_dc'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_tushare",
    )
    op.create_index("idx_raw_tushare_moneyflow_dc_trade_date", "moneyflow_dc", ["trade_date"], schema="raw_tushare")
    op.create_index(
        "idx_raw_tushare_moneyflow_dc_ts_code_trade_date",
        "moneyflow_dc",
        ["ts_code", "trade_date"],
        schema="raw_tushare",
    )


def _create_raw_moneyflow_cnt_ths(inspector: sa.Inspector) -> None:
    if inspector.has_table("moneyflow_cnt_ths", schema="raw_tushare"):
        return
    op.create_table(
        "moneyflow_cnt_ths",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("lead_stock", sa.String(length=128)),
        sa.Column("close_price", sa.Numeric(18, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("industry_index", sa.Numeric(24, 4)),
        sa.Column("company_num", sa.Integer()),
        sa.Column("pct_change_stock", sa.Numeric(10, 4)),
        sa.Column("net_buy_amount", sa.Numeric(24, 4)),
        sa.Column("net_sell_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'moneyflow_cnt_ths'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_moneyflow_cnt_ths_trade_date",
        "moneyflow_cnt_ths",
        ["trade_date"],
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_moneyflow_cnt_ths_ts_code_trade_date",
        "moneyflow_cnt_ths",
        ["ts_code", "trade_date"],
        schema="raw_tushare",
    )


def _create_raw_moneyflow_ind_ths(inspector: sa.Inspector) -> None:
    if inspector.has_table("moneyflow_ind_ths", schema="raw_tushare"):
        return
    op.create_table(
        "moneyflow_ind_ths",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("industry", sa.String(length=128)),
        sa.Column("lead_stock", sa.String(length=128)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("company_num", sa.Integer()),
        sa.Column("pct_change_stock", sa.Numeric(10, 4)),
        sa.Column("close_price", sa.Numeric(18, 4)),
        sa.Column("net_buy_amount", sa.Numeric(24, 4)),
        sa.Column("net_sell_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'moneyflow_ind_ths'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_moneyflow_ind_ths_trade_date",
        "moneyflow_ind_ths",
        ["trade_date"],
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_moneyflow_ind_ths_ts_code_trade_date",
        "moneyflow_ind_ths",
        ["ts_code", "trade_date"],
        schema="raw_tushare",
    )


def _create_raw_moneyflow_ind_dc(inspector: sa.Inspector) -> None:
    if inspector.has_table("moneyflow_ind_dc", schema="raw_tushare"):
        return
    op.create_table(
        "moneyflow_ind_dc",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("content_type", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_elg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_elg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_md_amount", sa.Numeric(24, 4)),
        sa.Column("buy_md_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(24, 4)),
        sa.Column("buy_sm_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount_stock", sa.String(length=128)),
        sa.Column("rank", sa.Integer()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'moneyflow_ind_dc'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_moneyflow_ind_dc_trade_date",
        "moneyflow_ind_dc",
        ["trade_date"],
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_moneyflow_ind_dc_content_type_trade_date",
        "moneyflow_ind_dc",
        ["content_type", "trade_date"],
        schema="raw_tushare",
    )


def _create_raw_moneyflow_mkt_dc(inspector: sa.Inspector) -> None:
    if inspector.has_table("moneyflow_mkt_dc", schema="raw_tushare"):
        return
    op.create_table(
        "moneyflow_mkt_dc",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("close_sh", sa.Numeric(18, 4)),
        sa.Column("pct_change_sh", sa.Numeric(10, 4)),
        sa.Column("close_sz", sa.Numeric(18, 4)),
        sa.Column("pct_change_sz", sa.Numeric(10, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_elg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_elg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_md_amount", sa.Numeric(24, 4)),
        sa.Column("buy_md_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(24, 4)),
        sa.Column("buy_sm_amount_rate", sa.Numeric(10, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'moneyflow_mkt_dc'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_moneyflow_mkt_dc_trade_date",
        "moneyflow_mkt_dc",
        ["trade_date"],
        schema="raw_tushare",
    )


def _create_serving_moneyflow_ths(inspector: sa.Inspector) -> None:
    if inspector.has_table("equity_moneyflow_ths", schema="core_serving"):
        return
    op.create_table(
        "equity_moneyflow_ths",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=64)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("latest", sa.Numeric(18, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("net_d5_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_md_amount", sa.Numeric(24, 4)),
        sa.Column("buy_md_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(24, 4)),
        sa.Column("buy_sm_amount_rate", sa.Numeric(10, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core_serving",
    )
    op.create_index(
        "idx_equity_moneyflow_ths_trade_date",
        "equity_moneyflow_ths",
        ["trade_date"],
        schema="core_serving",
    )
    op.create_index(
        "idx_equity_moneyflow_ths_ts_code_trade_date",
        "equity_moneyflow_ths",
        ["ts_code", "trade_date"],
        schema="core_serving",
    )


def _create_serving_moneyflow_dc(inspector: sa.Inspector) -> None:
    if inspector.has_table("equity_moneyflow_dc", schema="core_serving"):
        return
    op.create_table(
        "equity_moneyflow_dc",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=64)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_elg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_elg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_md_amount", sa.Numeric(24, 4)),
        sa.Column("buy_md_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(24, 4)),
        sa.Column("buy_sm_amount_rate", sa.Numeric(10, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core_serving",
    )
    op.create_index(
        "idx_equity_moneyflow_dc_trade_date",
        "equity_moneyflow_dc",
        ["trade_date"],
        schema="core_serving",
    )
    op.create_index(
        "idx_equity_moneyflow_dc_ts_code_trade_date",
        "equity_moneyflow_dc",
        ["ts_code", "trade_date"],
        schema="core_serving",
    )


def _create_serving_moneyflow_cnt_ths(inspector: sa.Inspector) -> None:
    if inspector.has_table("concept_moneyflow_ths", schema="core_serving"):
        return
    op.create_table(
        "concept_moneyflow_ths",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("lead_stock", sa.String(length=128)),
        sa.Column("close_price", sa.Numeric(18, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("industry_index", sa.Numeric(24, 4)),
        sa.Column("company_num", sa.Integer()),
        sa.Column("pct_change_stock", sa.Numeric(10, 4)),
        sa.Column("net_buy_amount", sa.Numeric(24, 4)),
        sa.Column("net_sell_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core_serving",
    )
    op.create_index(
        "idx_concept_moneyflow_ths_trade_date",
        "concept_moneyflow_ths",
        ["trade_date"],
        schema="core_serving",
    )
    op.create_index(
        "idx_concept_moneyflow_ths_ts_code_trade_date",
        "concept_moneyflow_ths",
        ["ts_code", "trade_date"],
        schema="core_serving",
    )


def _create_serving_moneyflow_ind_ths(inspector: sa.Inspector) -> None:
    if inspector.has_table("industry_moneyflow_ths", schema="core_serving"):
        return
    op.create_table(
        "industry_moneyflow_ths",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("industry", sa.String(length=128)),
        sa.Column("lead_stock", sa.String(length=128)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("company_num", sa.Integer()),
        sa.Column("pct_change_stock", sa.Numeric(10, 4)),
        sa.Column("close_price", sa.Numeric(18, 4)),
        sa.Column("net_buy_amount", sa.Numeric(24, 4)),
        sa.Column("net_sell_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core_serving",
    )
    op.create_index(
        "idx_industry_moneyflow_ths_trade_date",
        "industry_moneyflow_ths",
        ["trade_date"],
        schema="core_serving",
    )
    op.create_index(
        "idx_industry_moneyflow_ths_ts_code_trade_date",
        "industry_moneyflow_ths",
        ["ts_code", "trade_date"],
        schema="core_serving",
    )


def _create_serving_moneyflow_ind_dc(inspector: sa.Inspector) -> None:
    if inspector.has_table("board_moneyflow_dc", schema="core_serving"):
        return
    op.create_table(
        "board_moneyflow_dc",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("content_type", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_elg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_elg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_md_amount", sa.Numeric(24, 4)),
        sa.Column("buy_md_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(24, 4)),
        sa.Column("buy_sm_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount_stock", sa.String(length=128)),
        sa.Column("rank", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core_serving",
    )
    op.create_index(
        "idx_board_moneyflow_dc_trade_date",
        "board_moneyflow_dc",
        ["trade_date"],
        schema="core_serving",
    )
    op.create_index(
        "idx_board_moneyflow_dc_content_type_trade_date",
        "board_moneyflow_dc",
        ["content_type", "trade_date"],
        schema="core_serving",
    )


def _create_serving_moneyflow_mkt_dc(inspector: sa.Inspector) -> None:
    if inspector.has_table("market_moneyflow_dc", schema="core_serving"):
        return
    op.create_table(
        "market_moneyflow_dc",
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("close_sh", sa.Numeric(18, 4)),
        sa.Column("pct_change_sh", sa.Numeric(10, 4)),
        sa.Column("close_sz", sa.Numeric(18, 4)),
        sa.Column("pct_change_sz", sa.Numeric(10, 4)),
        sa.Column("net_amount", sa.Numeric(24, 4)),
        sa.Column("net_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_elg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_elg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(24, 4)),
        sa.Column("buy_lg_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_md_amount", sa.Numeric(24, 4)),
        sa.Column("buy_md_amount_rate", sa.Numeric(10, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(24, 4)),
        sa.Column("buy_sm_amount_rate", sa.Numeric(10, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core_serving",
    )
    op.create_index(
        "idx_market_moneyflow_dc_trade_date",
        "market_moneyflow_dc",
        ["trade_date"],
        schema="core_serving",
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    inspector = sa.inspect(op.get_bind())

    _create_raw_moneyflow_ths(inspector)
    _create_raw_moneyflow_dc(inspector)
    _create_raw_moneyflow_cnt_ths(inspector)
    _create_raw_moneyflow_ind_ths(inspector)
    _create_raw_moneyflow_ind_dc(inspector)
    _create_raw_moneyflow_mkt_dc(inspector)

    _create_serving_moneyflow_ths(inspector)
    _create_serving_moneyflow_dc(inspector)
    _create_serving_moneyflow_cnt_ths(inspector)
    _create_serving_moneyflow_ind_ths(inspector)
    _create_serving_moneyflow_ind_dc(inspector)
    _create_serving_moneyflow_mkt_dc(inspector)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if inspector.has_table("market_moneyflow_dc", schema="core_serving"):
        op.drop_index("idx_market_moneyflow_dc_trade_date", table_name="market_moneyflow_dc", schema="core_serving")
        op.drop_table("market_moneyflow_dc", schema="core_serving")

    if inspector.has_table("board_moneyflow_dc", schema="core_serving"):
        op.drop_index("idx_board_moneyflow_dc_content_type_trade_date", table_name="board_moneyflow_dc", schema="core_serving")
        op.drop_index("idx_board_moneyflow_dc_trade_date", table_name="board_moneyflow_dc", schema="core_serving")
        op.drop_table("board_moneyflow_dc", schema="core_serving")

    if inspector.has_table("industry_moneyflow_ths", schema="core_serving"):
        op.drop_index("idx_industry_moneyflow_ths_ts_code_trade_date", table_name="industry_moneyflow_ths", schema="core_serving")
        op.drop_index("idx_industry_moneyflow_ths_trade_date", table_name="industry_moneyflow_ths", schema="core_serving")
        op.drop_table("industry_moneyflow_ths", schema="core_serving")

    if inspector.has_table("concept_moneyflow_ths", schema="core_serving"):
        op.drop_index("idx_concept_moneyflow_ths_ts_code_trade_date", table_name="concept_moneyflow_ths", schema="core_serving")
        op.drop_index("idx_concept_moneyflow_ths_trade_date", table_name="concept_moneyflow_ths", schema="core_serving")
        op.drop_table("concept_moneyflow_ths", schema="core_serving")

    if inspector.has_table("equity_moneyflow_dc", schema="core_serving"):
        op.drop_index("idx_equity_moneyflow_dc_ts_code_trade_date", table_name="equity_moneyflow_dc", schema="core_serving")
        op.drop_index("idx_equity_moneyflow_dc_trade_date", table_name="equity_moneyflow_dc", schema="core_serving")
        op.drop_table("equity_moneyflow_dc", schema="core_serving")

    if inspector.has_table("equity_moneyflow_ths", schema="core_serving"):
        op.drop_index("idx_equity_moneyflow_ths_ts_code_trade_date", table_name="equity_moneyflow_ths", schema="core_serving")
        op.drop_index("idx_equity_moneyflow_ths_trade_date", table_name="equity_moneyflow_ths", schema="core_serving")
        op.drop_table("equity_moneyflow_ths", schema="core_serving")

    if inspector.has_table("moneyflow_mkt_dc", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_moneyflow_mkt_dc_trade_date", table_name="moneyflow_mkt_dc", schema="raw_tushare")
        op.drop_table("moneyflow_mkt_dc", schema="raw_tushare")

    if inspector.has_table("moneyflow_ind_dc", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_moneyflow_ind_dc_content_type_trade_date", table_name="moneyflow_ind_dc", schema="raw_tushare")
        op.drop_index("idx_raw_tushare_moneyflow_ind_dc_trade_date", table_name="moneyflow_ind_dc", schema="raw_tushare")
        op.drop_table("moneyflow_ind_dc", schema="raw_tushare")

    if inspector.has_table("moneyflow_ind_ths", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_moneyflow_ind_ths_ts_code_trade_date", table_name="moneyflow_ind_ths", schema="raw_tushare")
        op.drop_index("idx_raw_tushare_moneyflow_ind_ths_trade_date", table_name="moneyflow_ind_ths", schema="raw_tushare")
        op.drop_table("moneyflow_ind_ths", schema="raw_tushare")

    if inspector.has_table("moneyflow_cnt_ths", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_moneyflow_cnt_ths_ts_code_trade_date", table_name="moneyflow_cnt_ths", schema="raw_tushare")
        op.drop_index("idx_raw_tushare_moneyflow_cnt_ths_trade_date", table_name="moneyflow_cnt_ths", schema="raw_tushare")
        op.drop_table("moneyflow_cnt_ths", schema="raw_tushare")

    if inspector.has_table("moneyflow_dc", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_moneyflow_dc_ts_code_trade_date", table_name="moneyflow_dc", schema="raw_tushare")
        op.drop_index("idx_raw_tushare_moneyflow_dc_trade_date", table_name="moneyflow_dc", schema="raw_tushare")
        op.drop_table("moneyflow_dc", schema="raw_tushare")

    if inspector.has_table("moneyflow_ths", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_moneyflow_ths_ts_code_trade_date", table_name="moneyflow_ths", schema="raw_tushare")
        op.drop_index("idx_raw_tushare_moneyflow_ths_trade_date", table_name="moneyflow_ths", schema="raw_tushare")
        op.drop_table("moneyflow_ths", schema="raw_tushare")
