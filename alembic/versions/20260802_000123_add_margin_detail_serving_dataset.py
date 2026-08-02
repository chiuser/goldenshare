"""add direct-serving margin detail dataset

Revision ID: 20260802_000123
Revises: 20260802_000122
Create Date: 2026-08-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_000123"
down_revision = "20260802_000122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    inspector = sa.inspect(bind)
    if inspector.has_table("equity_margin_detail", schema="core_serving"):
        return

    op.execute(
        """
        CREATE TABLE core_serving.equity_margin_detail (
            trade_date DATE NOT NULL,
            ts_code VARCHAR(16) NOT NULL,
            name VARCHAR(64),
            rzye NUMERIC(20, 4),
            rqye NUMERIC(20, 4),
            rzmre NUMERIC(20, 4),
            rqyl NUMERIC(20, 4),
            rzche NUMERIC(20, 4),
            rqchl NUMERIC(20, 4),
            rqmcl NUMERIC(20, 4),
            rzrqye NUMERIC(20, 4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_equity_margin_detail PRIMARY KEY (trade_date, ts_code)
        ) PARTITION BY RANGE (trade_date)
        """
    )

    for year in range(2010, 2028):
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS core_serving.equity_margin_detail_p{year}
            PARTITION OF core_serving.equity_margin_detail
            FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')
            """
        )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS core_serving.equity_margin_detail_pmax
        PARTITION OF core_serving.equity_margin_detail DEFAULT
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_equity_margin_detail_trade_date
        ON core_serving.equity_margin_detail (trade_date)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_equity_margin_detail_ts_code_trade_date_desc
        ON core_serving.equity_margin_detail (ts_code, trade_date DESC)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS core_serving.equity_margin_detail CASCADE")
