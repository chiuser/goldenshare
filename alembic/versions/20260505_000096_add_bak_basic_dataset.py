"""add bak_basic dataset

Revision ID: 20260505_000096
Revises: 20260505_000095
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op


revision = "20260505_000096"
down_revision = "20260505_000095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving_light")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare.bak_basic (
            trade_date DATE NOT NULL,
            ts_code VARCHAR(16) NOT NULL,
            name VARCHAR(64),
            industry VARCHAR(64),
            area VARCHAR(64),
            pe DOUBLE PRECISION,
            float_share DOUBLE PRECISION,
            total_share DOUBLE PRECISION,
            total_assets DOUBLE PRECISION,
            liquid_assets DOUBLE PRECISION,
            fixed_assets DOUBLE PRECISION,
            reserved DOUBLE PRECISION,
            reserved_pershare DOUBLE PRECISION,
            eps DOUBLE PRECISION,
            bvps DOUBLE PRECISION,
            pb DOUBLE PRECISION,
            list_date DATE,
            undp DOUBLE PRECISION,
            per_undp DOUBLE PRECISION,
            rev_yoy DOUBLE PRECISION,
            profit_yoy DOUBLE PRECISION,
            gpr DOUBLE PRECISION,
            npr DOUBLE PRECISION,
            holder_num INTEGER,
            api_name VARCHAR(32) NOT NULL DEFAULT 'bak_basic',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT,
            PRIMARY KEY (trade_date, ts_code)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_bak_basic_ts_code_trade_date
        ON raw_tushare.bak_basic (ts_code, trade_date)
        """
    )

    op.execute("DROP VIEW IF EXISTS core_serving_light.bak_basic")
    op.execute(
        """
        CREATE VIEW core_serving_light.bak_basic AS
        SELECT
            trade_date,
            ts_code,
            name,
            industry,
            area,
            pe,
            float_share,
            total_share,
            total_assets,
            liquid_assets,
            fixed_assets,
            reserved,
            reserved_pershare,
            eps,
            bvps,
            pb,
            list_date,
            undp,
            per_undp,
            rev_yoy,
            profit_yoy,
            gpr,
            npr,
            holder_num,
            fetched_at
        FROM raw_tushare.bak_basic
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving_light.bak_basic")
    op.execute("DROP TABLE IF EXISTS raw_tushare.bak_basic")
