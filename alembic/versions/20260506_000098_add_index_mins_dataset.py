"""add index mins dataset

Revision ID: 20260506_000098
Revises: 20260505_000097
Create Date: 2026-05-06
"""

from __future__ import annotations

from alembic import op


revision = "20260506_000098"
down_revision = "20260505_000097"
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
        CREATE TABLE IF NOT EXISTS raw_tushare.index_mins (
            ts_code VARCHAR(32) NOT NULL,
            freq VARCHAR(16) NOT NULL,
            trade_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            close DOUBLE PRECISION,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            vol DOUBLE PRECISION,
            amount DOUBLE PRECISION,
            exchange VARCHAR(16),
            vwap DOUBLE PRECISION,
            CONSTRAINT pk_raw_tushare_index_mins PRIMARY KEY (ts_code, freq, trade_time)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_raw_tushare_index_mins_trade_time
        ON raw_tushare.index_mins (trade_time)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_raw_tushare_index_mins_ts_code_trade_time
        ON raw_tushare.index_mins (ts_code, trade_time)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_raw_tushare_index_mins_freq_trade_time
        ON raw_tushare.index_mins (freq, trade_time)
        """
    )

    op.execute("DROP VIEW IF EXISTS core_serving.index_minute_bar")
    op.execute(
        """
        CREATE VIEW core_serving.index_minute_bar AS
        SELECT
            ts_code,
            trade_time,
            trade_time::date AS trade_date,
            freq,
            exchange,
            open,
            high,
            low,
            close,
            vol,
            amount,
            vwap,
            'tushare'::VARCHAR(32) AS source
        FROM raw_tushare.index_mins
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving.index_minute_bar")
    op.execute("DROP TABLE IF EXISTS raw_tushare.index_mins")
