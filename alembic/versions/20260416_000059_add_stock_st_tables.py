"""add stock_st tables for tushare raw and serving

Revision ID: 20260416_000059
Revises: 20260416_000058
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000059"
down_revision = "20260416_000058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("stock_st", schema="raw_tushare"):
        op.create_table(
            "stock_st",
            sa.Column("ts_code", sa.String(length=16), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column("name", sa.String(length=128)),
            sa.Column("type_name", sa.String(length=128)),
            sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'stock_st'")),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", sa.Text()),
            sa.PrimaryKeyConstraint("ts_code", "trade_date", "type"),
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_stock_st_trade_date",
            "stock_st",
            ["trade_date"],
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_stock_st_ts_code_trade_date",
            "stock_st",
            ["ts_code", "trade_date"],
            schema="raw_tushare",
        )

    if not inspector.has_table("equity_stock_st", schema="core_serving"):
        op.create_table(
            "equity_stock_st",
            sa.Column("ts_code", sa.String(length=16), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column("name", sa.String(length=128)),
            sa.Column("type_name", sa.String(length=128)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("ts_code", "trade_date", "type"),
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_stock_st_trade_date",
            "equity_stock_st",
            ["trade_date"],
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_stock_st_ts_code_trade_date",
            "equity_stock_st",
            ["ts_code", "trade_date"],
            schema="core_serving",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("equity_stock_st", schema="core_serving"):
        op.drop_index("idx_equity_stock_st_ts_code_trade_date", table_name="equity_stock_st", schema="core_serving")
        op.drop_index("idx_equity_stock_st_trade_date", table_name="equity_stock_st", schema="core_serving")
        op.drop_table("equity_stock_st", schema="core_serving")

    if inspector.has_table("stock_st", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_stock_st_ts_code_trade_date", table_name="stock_st", schema="raw_tushare")
        op.drop_index("idx_raw_tushare_stock_st_trade_date", table_name="stock_st", schema="raw_tushare")
        op.drop_table("stock_st", schema="raw_tushare")
