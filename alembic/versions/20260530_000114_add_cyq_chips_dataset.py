"""add cyq chips dataset

Revision ID: 20260530_000114
Revises: 20260520_000113
Create Date: 2026-05-30
"""

from __future__ import annotations

from alembic import op


revision = "20260530_000114"
down_revision = "20260520_000113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare.cyq_chips (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            price NUMERIC(18, 4) NOT NULL,
            percent NUMERIC(10, 4),
            api_name VARCHAR(32) NOT NULL DEFAULT 'cyq_chips',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT,
            PRIMARY KEY (ts_code, trade_date, price)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_cyq_chips_trade_date
        ON raw_tushare.cyq_chips (trade_date)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_cyq_chips_ts_code_trade_date
        ON raw_tushare.cyq_chips (ts_code, trade_date)
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving.equity_cyq_chips AS
        SELECT
            ts_code,
            trade_date,
            price,
            percent
        FROM raw_tushare.cyq_chips
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving.equity_cyq_chips")
    op.execute("DROP TABLE IF EXISTS raw_tushare.cyq_chips")
