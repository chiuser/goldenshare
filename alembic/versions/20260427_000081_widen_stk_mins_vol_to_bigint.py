"""widen stk_mins vol to bigint

Revision ID: 20260427_000081
Revises: 20260427_000080
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_000081"
down_revision = "20260427_000080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core_serving.equity_minute_bar")
    op.alter_column(
        "stk_mins",
        "vol",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
        schema="raw_tushare",
    )
    _create_equity_minute_bar_view()


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core_serving.equity_minute_bar")
    op.alter_column(
        "stk_mins",
        "vol",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
        schema="raw_tushare",
    )
    _create_equity_minute_bar_view()


def _create_equity_minute_bar_view() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving.equity_minute_bar AS
        SELECT
            ts_code,
            freq,
            trade_time,
            trade_time::date AS trade_date,
            open,
            close,
            high,
            low,
            vol,
            amount,
            'tushare'::varchar(32) AS source
        FROM raw_tushare.stk_mins
        """
    )
