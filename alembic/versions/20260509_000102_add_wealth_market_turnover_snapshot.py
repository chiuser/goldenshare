"""add wealth market turnover snapshot

Revision ID: 20260509_000102
Revises: 20260508_000101
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op


revision = "20260509_000102"
down_revision = "20260508_000101"
branch_labels = None
depends_on = None

SERVING_SCHEMA = "core_serving"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SERVING_SCHEMA}")
    op.execute(f"DROP TABLE IF EXISTS {SERVING_SCHEMA}.wealth_market_turnover_snapshot")
    op.execute(
        f"""
        CREATE TABLE {SERVING_SCHEMA}.wealth_market_turnover_snapshot (
            type VARCHAR(16) NOT NULL,
            market VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            freq SMALLINT NOT NULL,
            latest_trade_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            security_count INTEGER NOT NULL,
            source_row_count BIGINT NOT NULL,
            total_amount NUMERIC(20, 2) NOT NULL,
            total_vol NUMERIC(20, 2) NOT NULL,
            points_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            build_status VARCHAR(16) NOT NULL DEFAULT 'READY',
            build_version VARCHAR(32) NOT NULL DEFAULT 'v1',
            built_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            build_note TEXT,
            CONSTRAINT pk_wealth_market_turnover_snapshot PRIMARY KEY (type, market, trade_date, freq),
            CONSTRAINT ck_wealth_market_turnover_snapshot_type
                CHECK (type IN ('stock', 'index', 'sector')),
            CONSTRAINT ck_wealth_market_turnover_snapshot_market
                CHECK (market = 'CN_A'),
            CONSTRAINT ck_wealth_market_turnover_snapshot_freq
                CHECK (freq IN (1, 5, 15, 30, 60)),
            CONSTRAINT ck_wealth_market_turnover_snapshot_status
                CHECK (build_status IN ('READY', 'FAILED'))
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_wealth_market_turnover_snapshot_lookup
        ON {SERVING_SCHEMA}.wealth_market_turnover_snapshot
            (type, market, freq, build_status, trade_date DESC)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"DROP TABLE IF EXISTS {SERVING_SCHEMA}.wealth_market_turnover_snapshot")
