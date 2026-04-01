"""add board datasets from ths and dc"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260401_000019"
down_revision = "20260331_000018"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "ths_index",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("count", sa.Integer()),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("list_date", sa.Date()),
        sa.Column("type", sa.String(length=32)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="ths_index"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "ths_member",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("con_code", sa.String(length=16), primary_key=True),
        sa.Column("con_name", sa.String(length=128)),
        sa.Column("weight", sa.Numeric(12, 6)),
        sa.Column("in_date", sa.Date()),
        sa.Column("out_date", sa.Date()),
        sa.Column("is_new", sa.String(length=8)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="ths_member"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "ths_daily",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("avg_price", sa.Numeric(18, 4)),
        sa.Column("change", sa.Numeric(18, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("float_mv", sa.Numeric(20, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="ths_daily"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "dc_index",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("leading", sa.String(length=128)),
        sa.Column("leading_code", sa.String(length=16)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("leading_pct", sa.Numeric(10, 4)),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("up_num", sa.Integer()),
        sa.Column("down_num", sa.Integer()),
        sa.Column("idx_type", sa.String(length=32)),
        sa.Column("level", sa.String(length=32)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="dc_index"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "dc_member",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("con_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="dc_member"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )
    op.create_table(
        "dc_daily",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("change", sa.Numeric(18, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("swing", sa.Numeric(10, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="dc_daily"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "ths_index",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("count", sa.Integer()),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("list_date", sa.Date()),
        sa.Column("type", sa.String(length=32)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_ths_index_exchange", "ths_index", ["exchange"], schema="core")
    op.create_index("idx_ths_index_type", "ths_index", ["type"], schema="core")

    op.create_table(
        "ths_member",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("con_code", sa.String(length=16), primary_key=True),
        sa.Column("con_name", sa.String(length=128)),
        sa.Column("weight", sa.Numeric(12, 6)),
        sa.Column("in_date", sa.Date()),
        sa.Column("out_date", sa.Date()),
        sa.Column("is_new", sa.String(length=8)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_ths_member_con_code", "ths_member", ["con_code"], schema="core")
    op.create_index("idx_ths_member_is_new", "ths_member", ["is_new"], schema="core")

    op.create_table(
        "ths_daily",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("avg_price", sa.Numeric(18, 4)),
        sa.Column("change", sa.Numeric(18, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("float_mv", sa.Numeric(20, 4)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_ths_daily_trade_date", "ths_daily", ["trade_date"], schema="core")

    op.create_table(
        "dc_index",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("leading", sa.String(length=128)),
        sa.Column("leading_code", sa.String(length=16)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("leading_pct", sa.Numeric(10, 4)),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("up_num", sa.Integer()),
        sa.Column("down_num", sa.Integer()),
        sa.Column("idx_type", sa.String(length=32)),
        sa.Column("level", sa.String(length=32)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_dc_index_trade_date", "dc_index", ["trade_date"], schema="core")
    op.create_index("idx_dc_index_idx_type_trade_date", "dc_index", ["idx_type", "trade_date"], schema="core")

    op.create_table(
        "dc_member",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("con_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_dc_member_trade_date", "dc_member", ["trade_date"], schema="core")
    op.create_index("idx_dc_member_con_code_trade_date", "dc_member", ["con_code", "trade_date"], schema="core")

    op.create_table(
        "dc_daily",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("change", sa.Numeric(18, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("swing", sa.Numeric(10, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_dc_daily_trade_date", "dc_daily", ["trade_date"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_dc_daily_trade_date", table_name="dc_daily", schema="core")
    op.drop_table("dc_daily", schema="core")
    op.drop_index("idx_dc_member_con_code_trade_date", table_name="dc_member", schema="core")
    op.drop_index("idx_dc_member_trade_date", table_name="dc_member", schema="core")
    op.drop_table("dc_member", schema="core")
    op.drop_index("idx_dc_index_idx_type_trade_date", table_name="dc_index", schema="core")
    op.drop_index("idx_dc_index_trade_date", table_name="dc_index", schema="core")
    op.drop_table("dc_index", schema="core")
    op.drop_index("idx_ths_daily_trade_date", table_name="ths_daily", schema="core")
    op.drop_table("ths_daily", schema="core")
    op.drop_index("idx_ths_member_is_new", table_name="ths_member", schema="core")
    op.drop_index("idx_ths_member_con_code", table_name="ths_member", schema="core")
    op.drop_table("ths_member", schema="core")
    op.drop_index("idx_ths_index_type", table_name="ths_index", schema="core")
    op.drop_index("idx_ths_index_exchange", table_name="ths_index", schema="core")
    op.drop_table("ths_index", schema="core")

    op.drop_table("dc_daily", schema="raw")
    op.drop_table("dc_member", schema="raw")
    op.drop_table("dc_index", schema="raw")
    op.drop_table("ths_daily", schema="raw")
    op.drop_table("ths_member", schema="raw")
    op.drop_table("ths_index", schema="raw")
