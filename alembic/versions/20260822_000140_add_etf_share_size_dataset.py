"""add etf share size dataset

Revision ID: 20260822_000140
Revises: 20260822_000139
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260822_000140"
down_revision = "20260822_000139"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    op.create_table(
        "etf_share_size",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("etf_name", sa.String(length=256), nullable=True),
        sa.Column("total_share", sa.Numeric(24, 6), nullable=True),
        sa.Column("total_size", sa.Numeric(24, 6), nullable=True),
        sa.Column("nav", sa.Numeric(18, 8), nullable=True),
        sa.Column("close", sa.Numeric(18, 8), nullable=True),
        sa.Column("exchange", sa.String(length=16), nullable=True),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'etf_share_size'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("trade_date", "ts_code", name="pk_raw_tushare_etf_share_size"),
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_etf_share_size_ts_code_trade_date",
        "etf_share_size",
        ["ts_code", "trade_date"],
        schema="raw_tushare",
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving.etf_share_size AS
        SELECT
            trade_date,
            ts_code,
            etf_name,
            total_share,
            total_size,
            nav,
            close,
            exchange,
            api_name,
            fetched_at,
            raw_payload
        FROM raw_tushare.etf_share_size
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core_serving.etf_share_size")
    op.drop_index(
        "idx_raw_tushare_etf_share_size_ts_code_trade_date",
        table_name="etf_share_size",
        schema="raw_tushare",
    )
    op.drop_table("etf_share_size", schema="raw_tushare")
