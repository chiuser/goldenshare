"""add ranking and kpl datasets"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260402_000021"
down_revision = "20260401_000020"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "ths_hot",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("data_type", sa.String(length=64), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("rank_time", sa.String(length=32), primary_key=True),
        sa.Column("query_market", sa.String(length=32), primary_key=True),
        sa.Column("query_is_new", sa.String(length=8), primary_key=True),
        sa.Column("ts_name", sa.String(length=128)),
        sa.Column("rank", sa.Integer()),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("current_price", sa.Numeric(18, 4)),
        sa.Column("concept", sa.String(length=512)),
        sa.Column("rank_reason", sa.String(length=512)),
        sa.Column("hot", sa.Numeric(20, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="ths_hot"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "dc_hot",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("data_type", sa.String(length=64), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("rank_time", sa.String(length=32), primary_key=True),
        sa.Column("query_market", sa.String(length=32), primary_key=True),
        sa.Column("query_hot_type", sa.String(length=32), primary_key=True),
        sa.Column("query_is_new", sa.String(length=8), primary_key=True),
        sa.Column("ts_name", sa.String(length=128)),
        sa.Column("rank", sa.Integer()),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("current_price", sa.Numeric(18, 4)),
        sa.Column("hot", sa.Numeric(20, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="dc_hot"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "kpl_list",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("tag", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("lu_time", sa.String(length=32)),
        sa.Column("ld_time", sa.String(length=32)),
        sa.Column("open_time", sa.String(length=32)),
        sa.Column("last_time", sa.String(length=32)),
        sa.Column("lu_desc", sa.Text()),
        sa.Column("theme", sa.String(length=256)),
        sa.Column("net_change", sa.Numeric(20, 4)),
        sa.Column("bid_amount", sa.Numeric(20, 4)),
        sa.Column("status", sa.String(length=64)),
        sa.Column("bid_change", sa.Numeric(20, 4)),
        sa.Column("bid_turnover", sa.Numeric(12, 4)),
        sa.Column("lu_bid_vol", sa.Numeric(20, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("bid_pct_chg", sa.Numeric(10, 4)),
        sa.Column("rt_pct_chg", sa.Numeric(10, 4)),
        sa.Column("limit_order", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("free_float", sa.Numeric(20, 4)),
        sa.Column("lu_limit_order", sa.Numeric(20, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="kpl_list"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "kpl_concept_cons",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("con_code", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("con_name", sa.String(length=128)),
        sa.Column("ts_name", sa.String(length=128)),
        sa.Column("desc", sa.Text()),
        sa.Column("hot_num", sa.Integer()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="kpl_concept_cons"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "ths_hot",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("data_type", sa.String(length=64), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("rank_time", sa.String(length=32), primary_key=True),
        sa.Column("query_market", sa.String(length=32), primary_key=True),
        sa.Column("query_is_new", sa.String(length=8), primary_key=True),
        sa.Column("ts_name", sa.String(length=128)),
        sa.Column("rank", sa.Integer()),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("current_price", sa.Numeric(18, 4)),
        sa.Column("concept", sa.String(length=512)),
        sa.Column("rank_reason", sa.String(length=512)),
        sa.Column("hot", sa.Numeric(20, 4)),
        sa.Column("raw_payload", sa.Text()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_ths_hot_trade_date", "ths_hot", ["trade_date"], schema="core")
    op.create_index("idx_ths_hot_data_type_trade_date", "ths_hot", ["data_type", "trade_date"], schema="core")
    op.create_index("idx_ths_hot_ts_code_trade_date", "ths_hot", ["ts_code", "trade_date"], schema="core")

    op.create_table(
        "dc_hot",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("data_type", sa.String(length=64), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("rank_time", sa.String(length=32), primary_key=True),
        sa.Column("query_market", sa.String(length=32), primary_key=True),
        sa.Column("query_hot_type", sa.String(length=32), primary_key=True),
        sa.Column("query_is_new", sa.String(length=8), primary_key=True),
        sa.Column("ts_name", sa.String(length=128)),
        sa.Column("rank", sa.Integer()),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("current_price", sa.Numeric(18, 4)),
        sa.Column("hot", sa.Numeric(20, 4)),
        sa.Column("raw_payload", sa.Text()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_dc_hot_trade_date", "dc_hot", ["trade_date"], schema="core")
    op.create_index("idx_dc_hot_data_type_trade_date", "dc_hot", ["data_type", "trade_date"], schema="core")
    op.create_index("idx_dc_hot_ts_code_trade_date", "dc_hot", ["ts_code", "trade_date"], schema="core")

    op.create_table(
        "kpl_list",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("tag", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("lu_time", sa.String(length=32)),
        sa.Column("ld_time", sa.String(length=32)),
        sa.Column("open_time", sa.String(length=32)),
        sa.Column("last_time", sa.String(length=32)),
        sa.Column("lu_desc", sa.Text()),
        sa.Column("theme", sa.String(length=256)),
        sa.Column("net_change", sa.Numeric(20, 4)),
        sa.Column("bid_amount", sa.Numeric(20, 4)),
        sa.Column("status", sa.String(length=64)),
        sa.Column("bid_change", sa.Numeric(20, 4)),
        sa.Column("bid_turnover", sa.Numeric(12, 4)),
        sa.Column("lu_bid_vol", sa.Numeric(20, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("bid_pct_chg", sa.Numeric(10, 4)),
        sa.Column("rt_pct_chg", sa.Numeric(10, 4)),
        sa.Column("limit_order", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("free_float", sa.Numeric(20, 4)),
        sa.Column("lu_limit_order", sa.Numeric(20, 4)),
        sa.Column("raw_payload", sa.Text()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_kpl_list_trade_date", "kpl_list", ["trade_date"], schema="core")
    op.create_index("idx_kpl_list_tag_trade_date", "kpl_list", ["tag", "trade_date"], schema="core")
    op.create_index("idx_kpl_list_ts_code_trade_date", "kpl_list", ["ts_code", "trade_date"], schema="core")

    op.create_table(
        "kpl_concept_cons",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("con_code", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("con_name", sa.String(length=128)),
        sa.Column("ts_name", sa.String(length=128)),
        sa.Column("desc", sa.Text()),
        sa.Column("hot_num", sa.Integer()),
        sa.Column("raw_payload", sa.Text()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_kpl_concept_cons_trade_date", "kpl_concept_cons", ["trade_date"], schema="core")
    op.create_index("idx_kpl_concept_cons_con_code_trade_date", "kpl_concept_cons", ["con_code", "trade_date"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_kpl_concept_cons_con_code_trade_date", table_name="kpl_concept_cons", schema="core")
    op.drop_index("idx_kpl_concept_cons_trade_date", table_name="kpl_concept_cons", schema="core")
    op.drop_table("kpl_concept_cons", schema="core")

    op.drop_index("idx_kpl_list_ts_code_trade_date", table_name="kpl_list", schema="core")
    op.drop_index("idx_kpl_list_tag_trade_date", table_name="kpl_list", schema="core")
    op.drop_index("idx_kpl_list_trade_date", table_name="kpl_list", schema="core")
    op.drop_table("kpl_list", schema="core")

    op.drop_index("idx_dc_hot_ts_code_trade_date", table_name="dc_hot", schema="core")
    op.drop_index("idx_dc_hot_data_type_trade_date", table_name="dc_hot", schema="core")
    op.drop_index("idx_dc_hot_trade_date", table_name="dc_hot", schema="core")
    op.drop_table("dc_hot", schema="core")

    op.drop_index("idx_ths_hot_ts_code_trade_date", table_name="ths_hot", schema="core")
    op.drop_index("idx_ths_hot_data_type_trade_date", table_name="ths_hot", schema="core")
    op.drop_index("idx_ths_hot_trade_date", table_name="ths_hot", schema="core")
    op.drop_table("ths_hot", schema="core")

    op.drop_table("kpl_concept_cons", schema="raw")
    op.drop_table("kpl_list", schema="raw")
    op.drop_table("dc_hot", schema="raw")
    op.drop_table("ths_hot", schema="raw")
