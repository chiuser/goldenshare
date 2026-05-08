"""rebuild dc_daily category identity

Revision ID: 20260508_000100
Revises: 20260507_000099
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op


revision = "20260508_000100"
down_revision = "20260507_000099"
branch_labels = None
depends_on = None

RAW_SCHEMA = "raw_tushare"
SERVING_SCHEMA = "core_serving"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Destructive rebuild confirmed by user on 2026-05-08.
    # Old dc_daily data used an incomplete identity (ts_code, trade_date) and
    # cannot be losslessly repaired without re-syncing category from Tushare.
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SERVING_SCHEMA}")
    op.execute(f"DROP TABLE IF EXISTS {SERVING_SCHEMA}.dc_daily")
    op.execute(f"DROP TABLE IF EXISTS {RAW_SCHEMA}.dc_daily")

    op.execute(
        f"""
        CREATE TABLE {RAW_SCHEMA}.dc_daily (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            category VARCHAR(32) NOT NULL,
            close NUMERIC(18, 4),
            open NUMERIC(18, 4),
            high NUMERIC(18, 4),
            low NUMERIC(18, 4),
            change NUMERIC(18, 4),
            pct_change NUMERIC(10, 4),
            vol NUMERIC(20, 4),
            amount NUMERIC(20, 4),
            swing NUMERIC(10, 4),
            turnover_rate NUMERIC(12, 4),
            api_name VARCHAR(32) NOT NULL DEFAULT 'dc_daily',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT,
            CONSTRAINT pk_raw_tushare_dc_daily PRIMARY KEY (ts_code, trade_date, category)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_raw_tushare_dc_daily_trade_date
        ON {RAW_SCHEMA}.dc_daily (trade_date)
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_raw_tushare_dc_daily_trade_date_category
        ON {RAW_SCHEMA}.dc_daily (trade_date, category)
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SERVING_SCHEMA}.dc_daily (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            category VARCHAR(32) NOT NULL,
            close NUMERIC(18, 4),
            open NUMERIC(18, 4),
            high NUMERIC(18, 4),
            low NUMERIC(18, 4),
            change NUMERIC(18, 4),
            pct_change NUMERIC(10, 4),
            vol NUMERIC(20, 4),
            amount NUMERIC(20, 4),
            swing NUMERIC(10, 4),
            turnover_rate NUMERIC(12, 4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_core_serving_dc_daily PRIMARY KEY (ts_code, trade_date, category)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_dc_daily_trade_date
        ON {SERVING_SCHEMA}.dc_daily (trade_date)
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_dc_daily_trade_date_category
        ON {SERVING_SCHEMA}.dc_daily (trade_date, category)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"DROP TABLE IF EXISTS {SERVING_SCHEMA}.dc_daily")
    op.execute(f"DROP TABLE IF EXISTS {RAW_SCHEMA}.dc_daily")

    op.execute(
        f"""
        CREATE TABLE {RAW_SCHEMA}.dc_daily (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            close NUMERIC(18, 4),
            open NUMERIC(18, 4),
            high NUMERIC(18, 4),
            low NUMERIC(18, 4),
            change NUMERIC(18, 4),
            pct_change NUMERIC(10, 4),
            vol NUMERIC(20, 4),
            amount NUMERIC(20, 4),
            swing NUMERIC(10, 4),
            turnover_rate NUMERIC(12, 4),
            api_name VARCHAR(32) NOT NULL DEFAULT 'dc_daily',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT,
            CONSTRAINT pk_raw_tushare_dc_daily PRIMARY KEY (ts_code, trade_date)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SERVING_SCHEMA}.dc_daily (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            close NUMERIC(18, 4),
            open NUMERIC(18, 4),
            high NUMERIC(18, 4),
            low NUMERIC(18, 4),
            change NUMERIC(18, 4),
            pct_change NUMERIC(10, 4),
            vol NUMERIC(20, 4),
            amount NUMERIC(20, 4),
            swing NUMERIC(10, 4),
            turnover_rate NUMERIC(12, 4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_core_serving_dc_daily PRIMARY KEY (ts_code, trade_date)
        )
        """
    )
    op.execute(f"CREATE INDEX idx_dc_daily_trade_date ON {SERVING_SCHEMA}.dc_daily (trade_date)")
