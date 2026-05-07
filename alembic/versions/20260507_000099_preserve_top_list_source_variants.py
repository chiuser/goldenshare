"""preserve top_list source variants

Revision ID: 20260507_000099
Revises: 20260506_000098
Create Date: 2026-05-07
"""

from __future__ import annotations

from alembic import op


revision = "20260507_000099"
down_revision = "20260506_000098"
branch_labels = None
depends_on = None

RAW_SCHEMA = "raw_tushare"
RAW_LEGACY_SCHEMA = "raw"
SERVING_SCHEMA = "core_serving"
SERVING_LEGACY_SCHEMA = "core"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # This migration is intentionally destructive for top_list history.
    # The user has accepted clearing old top_list data and rebuilding by re-sync.
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SERVING_SCHEMA}")

    op.execute(f"DROP TABLE IF EXISTS {SERVING_SCHEMA}.equity_top_list")
    op.execute(f"DROP TABLE IF EXISTS {RAW_SCHEMA}.top_list")
    op.execute(f"DROP TABLE IF EXISTS {SERVING_LEGACY_SCHEMA}.equity_top_list")
    op.execute(f"DROP TABLE IF EXISTS {RAW_LEGACY_SCHEMA}.top_list")

    op.execute(
        f"""
        CREATE TABLE {RAW_SCHEMA}.top_list (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            reason TEXT NOT NULL,
            payload_hash VARCHAR(64) NOT NULL,
            reason_hash VARCHAR(64) NOT NULL,
            name VARCHAR(64),
            close NUMERIC(18, 4),
            pct_change NUMERIC(10, 4),
            turnover_rate NUMERIC(12, 4),
            amount NUMERIC(20, 4),
            l_sell NUMERIC(20, 4),
            l_buy NUMERIC(20, 4),
            l_amount NUMERIC(20, 4),
            net_amount NUMERIC(20, 4),
            net_rate NUMERIC(12, 4),
            amount_rate NUMERIC(12, 4),
            float_values NUMERIC(20, 4),
            api_name VARCHAR(32) NOT NULL DEFAULT 'top_list',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT,
            CONSTRAINT pk_raw_tushare_top_list PRIMARY KEY (ts_code, trade_date, reason, payload_hash)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_raw_tushare_top_list_reason_hash
        ON {RAW_SCHEMA}.top_list (ts_code, trade_date, reason_hash)
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_raw_tushare_top_list_trade_date
        ON {RAW_SCHEMA}.top_list (trade_date)
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SERVING_SCHEMA}.equity_top_list (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            reason TEXT NOT NULL,
            reason_hash VARCHAR(64) NOT NULL,
            selected_payload_hash VARCHAR(64) NOT NULL,
            variant_count INTEGER NOT NULL,
            resolution_policy_version VARCHAR(64) NOT NULL,
            name VARCHAR(64),
            close NUMERIC(18, 4),
            pct_chg NUMERIC(10, 4),
            turnover_rate NUMERIC(12, 4),
            amount NUMERIC(20, 4),
            l_sell NUMERIC(20, 4),
            l_buy NUMERIC(20, 4),
            l_amount NUMERIC(20, 4),
            net_amount NUMERIC(20, 4),
            net_rate NUMERIC(12, 4),
            amount_rate NUMERIC(12, 4),
            float_values NUMERIC(20, 4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_core_serving_equity_top_list PRIMARY KEY (ts_code, trade_date, reason)
        )
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_equity_top_list_ts_code_trade_date_reason_hash
        ON {SERVING_SCHEMA}.equity_top_list (ts_code, trade_date, reason_hash)
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_equity_top_list_trade_date
        ON {SERVING_SCHEMA}.equity_top_list (trade_date)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"DROP TABLE IF EXISTS {SERVING_SCHEMA}.equity_top_list")
    op.execute(f"DROP TABLE IF EXISTS {RAW_SCHEMA}.top_list")
