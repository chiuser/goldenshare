"""add limit theme datasets"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_000026"
down_revision = "20260403_000025"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "limit_list_ths",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("query_limit_type", sa.String(length=32), primary_key=True),
        sa.Column("query_market", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("price", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("open_num", sa.Integer()),
        sa.Column("lu_desc", sa.Text()),
        sa.Column("limit_type", sa.String(length=32)),
        sa.Column("tag", sa.String(length=32)),
        sa.Column("status", sa.String(length=64)),
        sa.Column("first_lu_time", sa.String(length=32)),
        sa.Column("last_lu_time", sa.String(length=32)),
        sa.Column("first_ld_time", sa.String(length=32)),
        sa.Column("last_ld_time", sa.String(length=32)),
        sa.Column("limit_order", sa.Numeric(20, 4)),
        sa.Column("limit_amount", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("free_float", sa.Numeric(20, 4)),
        sa.Column("lu_limit_order", sa.Numeric(20, 4)),
        sa.Column("limit_up_suc_rate", sa.Numeric(10, 4)),
        sa.Column("turnover", sa.Numeric(20, 4)),
        sa.Column("rise_rate", sa.Numeric(10, 4)),
        sa.Column("sum_float", sa.Numeric(20, 4)),
        sa.Column("market_type", sa.String(length=16)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="limit_list_ths"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "limit_step",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("nums", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="limit_step"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "limit_cpt_list",
        sa.Column("ts_code", sa.String(length=32), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("days", sa.Integer()),
        sa.Column("up_stat", sa.String(length=64)),
        sa.Column("cons_nums", sa.Integer()),
        sa.Column("up_nums", sa.Integer()),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("rank", sa.String(length=32)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="limit_cpt_list"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "limit_list_ths",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("query_limit_type", sa.String(length=32), primary_key=True),
        sa.Column("query_market", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("price", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("open_num", sa.Integer()),
        sa.Column("lu_desc", sa.Text()),
        sa.Column("limit_type", sa.String(length=32)),
        sa.Column("tag", sa.String(length=32)),
        sa.Column("status", sa.String(length=64)),
        sa.Column("first_lu_time", sa.String(length=32)),
        sa.Column("last_lu_time", sa.String(length=32)),
        sa.Column("first_ld_time", sa.String(length=32)),
        sa.Column("last_ld_time", sa.String(length=32)),
        sa.Column("limit_order", sa.Numeric(20, 4)),
        sa.Column("limit_amount", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("free_float", sa.Numeric(20, 4)),
        sa.Column("lu_limit_order", sa.Numeric(20, 4)),
        sa.Column("limit_up_suc_rate", sa.Numeric(10, 4)),
        sa.Column("turnover", sa.Numeric(20, 4)),
        sa.Column("rise_rate", sa.Numeric(10, 4)),
        sa.Column("sum_float", sa.Numeric(20, 4)),
        sa.Column("market_type", sa.String(length=16)),
        sa.Column("raw_payload", sa.Text()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_limit_list_ths_trade_date", "limit_list_ths", ["trade_date"], schema="core")
    op.create_index("idx_limit_list_ths_query_trade_date", "limit_list_ths", ["query_limit_type", "trade_date"], schema="core")
    op.create_index("idx_limit_list_ths_market_trade_date", "limit_list_ths", ["query_market", "trade_date"], schema="core")
    op.create_index("idx_limit_list_ths_ts_code_trade_date", "limit_list_ths", ["ts_code", "trade_date"], schema="core")

    op.create_table(
        "limit_step",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("nums", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("raw_payload", sa.Text()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_limit_step_trade_date", "limit_step", ["trade_date"], schema="core")
    op.create_index("idx_limit_step_nums_trade_date", "limit_step", ["nums", "trade_date"], schema="core")

    op.create_table(
        "limit_cpt_list",
        sa.Column("ts_code", sa.String(length=32), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("days", sa.Integer()),
        sa.Column("up_stat", sa.String(length=64)),
        sa.Column("cons_nums", sa.Integer()),
        sa.Column("up_nums", sa.Integer()),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("rank", sa.String(length=32)),
        sa.Column("raw_payload", sa.Text()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_limit_cpt_list_trade_date", "limit_cpt_list", ["trade_date"], schema="core")
    op.create_index("idx_limit_cpt_list_rank_trade_date", "limit_cpt_list", ["rank", "trade_date"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_limit_cpt_list_rank_trade_date", table_name="limit_cpt_list", schema="core")
    op.drop_index("idx_limit_cpt_list_trade_date", table_name="limit_cpt_list", schema="core")
    op.drop_table("limit_cpt_list", schema="core")

    op.drop_index("idx_limit_step_nums_trade_date", table_name="limit_step", schema="core")
    op.drop_index("idx_limit_step_trade_date", table_name="limit_step", schema="core")
    op.drop_table("limit_step", schema="core")

    op.drop_index("idx_limit_list_ths_ts_code_trade_date", table_name="limit_list_ths", schema="core")
    op.drop_index("idx_limit_list_ths_market_trade_date", table_name="limit_list_ths", schema="core")
    op.drop_index("idx_limit_list_ths_query_trade_date", table_name="limit_list_ths", schema="core")
    op.drop_index("idx_limit_list_ths_trade_date", table_name="limit_list_ths", schema="core")
    op.drop_table("limit_list_ths", schema="core")

    op.drop_table("limit_cpt_list", schema="raw")
    op.drop_table("limit_step", schema="raw")
    op.drop_table("limit_list_ths", schema="raw")
