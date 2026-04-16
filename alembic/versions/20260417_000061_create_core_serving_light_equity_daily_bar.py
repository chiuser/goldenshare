"""create core_serving_light equity_daily_bar_light partitioned table

Revision ID: 20260417_000061
Revises: 20260416_000060
Create Date: 2026-04-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_000061"
down_revision = "20260416_000060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving_light")
    inspector = sa.inspect(bind)
    if inspector.has_table("equity_daily_bar_light", schema="core_serving_light"):
        return

    op.execute(
        """
        CREATE TABLE core_serving_light.equity_daily_bar_light (
            ts_code VARCHAR(16) NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            pre_close DOUBLE PRECISION,
            change_amount DOUBLE PRECISION,
            pct_chg DOUBLE PRECISION,
            vol DOUBLE PRECISION,
            amount DOUBLE PRECISION,
            source VARCHAR(32) NOT NULL DEFAULT 'tushare',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_equity_daily_bar_light PRIMARY KEY (ts_code, trade_date)
        )
        PARTITION BY RANGE (trade_date)
        """
    )

    for year in range(1990, 2036):
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS core_serving_light.equity_daily_bar_light_p{year}
            PARTITION OF core_serving_light.equity_daily_bar_light
            FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')
            """
        )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS core_serving_light.equity_daily_bar_light_pmax
        PARTITION OF core_serving_light.equity_daily_bar_light
        DEFAULT
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_equity_daily_bar_light_trade_date
        ON core_serving_light.equity_daily_bar_light (trade_date)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_equity_daily_bar_light_ts_code_trade_date_desc
        ON core_serving_light.equity_daily_bar_light (ts_code, trade_date DESC)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP TABLE IF EXISTS core_serving_light.equity_daily_bar_light CASCADE")

