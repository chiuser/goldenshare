"""add stk_mins raw table and serving view

Revision ID: 20260424_000072
Revises: 20260423_000071
Create Date: 2026-04-24 10:30:00.000000
"""

from __future__ import annotations

from datetime import date

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260424_000072"
down_revision = "20260423_000071"
branch_labels = None
depends_on = None


def _month_starts(start_year: int, end_year_exclusive: int) -> list[date]:
    return [date(year, month, 1) for year in range(start_year, end_year_exclusive) for month in range(1, 13)]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare.stk_mins (
            ts_code varchar(16) NOT NULL,
            freq varchar(8) NOT NULL,
            trade_date date NOT NULL,
            trade_time timestamp without time zone NOT NULL,
            session_tag varchar(16) NOT NULL,
            open double precision,
            close double precision,
            high double precision,
            low double precision,
            vol double precision,
            amount double precision,
            api_name varchar(64) NOT NULL DEFAULT 'stk_mins',
            fetched_at timestamptz NOT NULL DEFAULT now(),
            raw_payload text,
            CONSTRAINT pk_raw_tushare_stk_mins PRIMARY KEY (ts_code, freq, trade_date, trade_time)
        ) PARTITION BY RANGE (trade_date)
        """
    )

    month_starts = _month_starts(2010, 2037)
    for index, start_date in enumerate(month_starts):
        if index + 1 < len(month_starts):
            end_date = month_starts[index + 1]
        else:
            end_date = date(start_date.year + 1, 1, 1)
        partition_name = f"stk_mins_{start_date:%Y_%m}"
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS raw_tushare.{partition_name}
            PARTITION OF raw_tushare.stk_mins
            FOR VALUES FROM ('{start_date.isoformat()}') TO ('{end_date.isoformat()}')
            """
        )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare.stk_mins_default
        PARTITION OF raw_tushare.stk_mins DEFAULT
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_stk_mins_trade_date_freq
        ON raw_tushare.stk_mins (trade_date, freq)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_stk_mins_ts_code_freq_trade_time
        ON raw_tushare.stk_mins (ts_code, freq, trade_time DESC)
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving.equity_minute_bar AS
        SELECT
            ts_code,
            freq,
            trade_time,
            trade_date,
            session_tag,
            open,
            close,
            high,
            low,
            vol,
            amount,
            'tushare'::varchar(32) AS source,
            fetched_at AS updated_at
        FROM raw_tushare.stk_mins
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core_serving.equity_minute_bar")
    op.execute("DROP TABLE IF EXISTS raw_tushare.stk_mins CASCADE")
