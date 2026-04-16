"""add suspend_d tables for tushare raw and serving

Revision ID: 20260416_000056
Revises: 20260416_000055
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000056"
down_revision = "20260416_000055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("suspend_d", schema="raw_tushare"):
        op.create_table(
            "suspend_d",
            sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
            sa.Column("row_key_hash", sa.String(length=64), nullable=False),
            sa.Column("ts_code", sa.String(length=16), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("suspend_timing", sa.String(length=32)),
            sa.Column("suspend_type", sa.String(length=16)),
            sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'suspend_d'")),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", sa.Text()),
            schema="raw_tushare",
        )
        op.create_index(
            "uq_raw_tushare_suspend_d_row_key_hash",
            "suspend_d",
            ["row_key_hash"],
            unique=True,
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_suspend_d_trade_date",
            "suspend_d",
            ["trade_date"],
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_suspend_d_ts_code_trade_date",
            "suspend_d",
            ["ts_code", "trade_date"],
            schema="raw_tushare",
        )

    if not inspector.has_table("equity_suspend_d", schema="core_serving"):
        op.create_table(
            "equity_suspend_d",
            sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
            sa.Column("row_key_hash", sa.String(length=64), nullable=False),
            sa.Column("ts_code", sa.String(length=16), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("suspend_timing", sa.String(length=32)),
            sa.Column("suspend_type", sa.String(length=16)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            schema="core_serving",
        )
        op.create_index(
            "uq_equity_suspend_d_row_key_hash",
            "equity_suspend_d",
            ["row_key_hash"],
            unique=True,
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_suspend_d_trade_date",
            "equity_suspend_d",
            ["trade_date"],
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_suspend_d_ts_code_trade_date",
            "equity_suspend_d",
            ["ts_code", "trade_date"],
            schema="core_serving",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("equity_suspend_d", schema="core_serving"):
        op.drop_index("idx_equity_suspend_d_ts_code_trade_date", table_name="equity_suspend_d", schema="core_serving")
        op.drop_index("idx_equity_suspend_d_trade_date", table_name="equity_suspend_d", schema="core_serving")
        op.drop_index("uq_equity_suspend_d_row_key_hash", table_name="equity_suspend_d", schema="core_serving")
        op.drop_table("equity_suspend_d", schema="core_serving")

    if inspector.has_table("suspend_d", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_suspend_d_ts_code_trade_date", table_name="suspend_d", schema="raw_tushare")
        op.drop_index("idx_raw_tushare_suspend_d_trade_date", table_name="suspend_d", schema="raw_tushare")
        op.drop_index("uq_raw_tushare_suspend_d_row_key_hash", table_name="suspend_d", schema="raw_tushare")
        op.drop_table("suspend_d", schema="raw_tushare")

