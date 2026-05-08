"""rebuild ths_daily valuation fields

Revision ID: 20260508_000101
Revises: 20260508_000100
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op


revision = "20260508_000101"
down_revision = "20260508_000100"
branch_labels = None
depends_on = None

RAW_SCHEMA = "raw_tushare"
SERVING_SCHEMA = "core_serving"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Destructive rebuild confirmed by user on 2026-05-08.
    # Source doc 0260 now includes pe_ttm/pb_mrq, and existing tables did not
    # persist those source fields.
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SERVING_SCHEMA}")
    op.execute(f"DROP TABLE IF EXISTS {SERVING_SCHEMA}.ths_daily")
    op.execute(f"DROP TABLE IF EXISTS {RAW_SCHEMA}.ths_daily")

    op.execute(
        f"""
        CREATE TABLE {RAW_SCHEMA}.ths_daily (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            close NUMERIC(24, 6),
            open NUMERIC(24, 6),
            high NUMERIC(24, 6),
            low NUMERIC(24, 6),
            pre_close NUMERIC(24, 6),
            avg_price NUMERIC(24, 6),
            change NUMERIC(24, 6),
            pct_change NUMERIC(18, 6),
            vol NUMERIC(30, 4),
            turnover_rate NUMERIC(18, 6),
            total_mv NUMERIC(30, 4),
            float_mv NUMERIC(30, 4),
            pe_ttm NUMERIC(18, 6),
            pb_mrq NUMERIC(18, 6),
            api_name VARCHAR(32) NOT NULL DEFAULT 'ths_daily',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT,
            CONSTRAINT pk_raw_tushare_ths_daily PRIMARY KEY (ts_code, trade_date)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SERVING_SCHEMA}.ths_daily (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            close NUMERIC(24, 6),
            open NUMERIC(24, 6),
            high NUMERIC(24, 6),
            low NUMERIC(24, 6),
            pre_close NUMERIC(24, 6),
            avg_price NUMERIC(24, 6),
            change NUMERIC(24, 6),
            pct_change NUMERIC(18, 6),
            vol NUMERIC(30, 4),
            turnover_rate NUMERIC(18, 6),
            total_mv NUMERIC(30, 4),
            float_mv NUMERIC(30, 4),
            pe_ttm NUMERIC(18, 6),
            pb_mrq NUMERIC(18, 6),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_core_serving_ths_daily PRIMARY KEY (ts_code, trade_date)
        )
        """
    )
    op.execute(f"CREATE INDEX idx_ths_daily_trade_date ON {SERVING_SCHEMA}.ths_daily (trade_date)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"DROP TABLE IF EXISTS {SERVING_SCHEMA}.ths_daily")
    op.execute(f"DROP TABLE IF EXISTS {RAW_SCHEMA}.ths_daily")

    op.execute(
        f"""
        CREATE TABLE {RAW_SCHEMA}.ths_daily (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            close NUMERIC(24, 6),
            open NUMERIC(24, 6),
            high NUMERIC(24, 6),
            low NUMERIC(24, 6),
            pre_close NUMERIC(24, 6),
            avg_price NUMERIC(24, 6),
            change NUMERIC(24, 6),
            pct_change NUMERIC(18, 6),
            vol NUMERIC(30, 4),
            turnover_rate NUMERIC(18, 6),
            total_mv NUMERIC(30, 4),
            float_mv NUMERIC(30, 4),
            api_name VARCHAR(32) NOT NULL DEFAULT 'ths_daily',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT,
            CONSTRAINT pk_raw_tushare_ths_daily PRIMARY KEY (ts_code, trade_date)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SERVING_SCHEMA}.ths_daily (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            close NUMERIC(24, 6),
            open NUMERIC(24, 6),
            high NUMERIC(24, 6),
            low NUMERIC(24, 6),
            pre_close NUMERIC(24, 6),
            avg_price NUMERIC(24, 6),
            change NUMERIC(24, 6),
            pct_change NUMERIC(18, 6),
            vol NUMERIC(30, 4),
            turnover_rate NUMERIC(18, 6),
            total_mv NUMERIC(30, 4),
            float_mv NUMERIC(30, 4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_core_serving_ths_daily PRIMARY KEY (ts_code, trade_date)
        )
        """
    )
    op.execute(f"CREATE INDEX idx_ths_daily_trade_date ON {SERVING_SCHEMA}.ths_daily (trade_date)")
