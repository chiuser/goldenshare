"""add index serving tables

Revision ID: 20260404_000029
Revises: 20260404_000028
Create Date: 2026-04-04 14:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260404_000029"
down_revision = "20260404_000028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "index_daily_serving",
        sa.Column("ts_code", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("pre_close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("change_amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("pct_chg", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("vol", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'api'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("ts_code", "trade_date", name=op.f("pk_index_daily_serving")),
        schema="core",
    )
    op.create_index(
        "idx_index_daily_serving_trade_date",
        "index_daily_serving",
        ["trade_date"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "index_weekly_serving",
        sa.Column("ts_code", sa.String(length=32), nullable=False),
        sa.Column("period_start_date", sa.Date(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("pre_close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("change_amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("pct_chg", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("vol", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'api'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("ts_code", "trade_date", name=op.f("pk_index_weekly_serving")),
        schema="core",
    )
    op.create_index(
        "idx_index_weekly_serving_trade_date",
        "index_weekly_serving",
        ["trade_date"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "idx_index_weekly_serving_period_start",
        "index_weekly_serving",
        ["period_start_date"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_index_weekly_serving_ts_period",
        "index_weekly_serving",
        ["ts_code", "period_start_date"],
        unique=True,
        schema="core",
    )

    op.create_table(
        "index_monthly_serving",
        sa.Column("ts_code", sa.String(length=32), nullable=False),
        sa.Column("period_start_date", sa.Date(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("pre_close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("change_amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("pct_chg", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("vol", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'api'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("ts_code", "trade_date", name=op.f("pk_index_monthly_serving")),
        schema="core",
    )
    op.create_index(
        "idx_index_monthly_serving_trade_date",
        "index_monthly_serving",
        ["trade_date"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "idx_index_monthly_serving_period_start",
        "index_monthly_serving",
        ["period_start_date"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_index_monthly_serving_ts_period",
        "index_monthly_serving",
        ["ts_code", "period_start_date"],
        unique=True,
        schema="core",
    )

    op.execute(
        """
        insert into core.index_daily_serving
            (ts_code, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount, source)
        select
            ts_code, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount, 'api'
        from core.index_daily_bar
        on conflict (ts_code, trade_date) do nothing
        """
    )
    op.execute(
        """
        insert into core.index_weekly_serving
            (ts_code, period_start_date, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount, source)
        select
            ts_code, period_start_date, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount, 'api'
        from (
            select distinct on (ts_code, period_start_date)
                ts_code,
                period_start_date,
                trade_date,
                open,
                high,
                low,
                close,
                pre_close,
                change_amount,
                pct_chg,
                vol,
                amount
            from (
                select
                    ts_code,
                    date_trunc('week', trade_date)::date as period_start_date,
                    trade_date,
                    open,
                    high,
                    low,
                    close,
                    pre_close,
                    change_amount,
                    pct_chg,
                    vol,
                    amount
                from core.index_weekly_bar
            ) weekly_raw
            order by ts_code, period_start_date, trade_date desc
        ) weekly_dedup
        on conflict (ts_code, period_start_date) do update set
            trade_date = excluded.trade_date,
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            pre_close = excluded.pre_close,
            change_amount = excluded.change_amount,
            pct_chg = excluded.pct_chg,
            vol = excluded.vol,
            amount = excluded.amount,
            source = excluded.source,
            updated_at = now()
        """
    )
    op.execute(
        """
        insert into core.index_monthly_serving
            (ts_code, period_start_date, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount, source)
        select
            ts_code, period_start_date, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount, 'api'
        from (
            select distinct on (ts_code, period_start_date)
                ts_code,
                period_start_date,
                trade_date,
                open,
                high,
                low,
                close,
                pre_close,
                change_amount,
                pct_chg,
                vol,
                amount
            from (
                select
                    ts_code,
                    date_trunc('month', trade_date)::date as period_start_date,
                    trade_date,
                    open,
                    high,
                    low,
                    close,
                    pre_close,
                    change_amount,
                    pct_chg,
                    vol,
                    amount
                from core.index_monthly_bar
            ) monthly_raw
            order by ts_code, period_start_date, trade_date desc
        ) monthly_dedup
        on conflict (ts_code, period_start_date) do update set
            trade_date = excluded.trade_date,
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            pre_close = excluded.pre_close,
            change_amount = excluded.change_amount,
            pct_chg = excluded.pct_chg,
            vol = excluded.vol,
            amount = excluded.amount,
            source = excluded.source,
            updated_at = now()
        """
    )


def downgrade() -> None:
    op.drop_index("uq_index_monthly_serving_ts_period", table_name="index_monthly_serving", schema="core")
    op.drop_index("idx_index_monthly_serving_period_start", table_name="index_monthly_serving", schema="core")
    op.drop_index("idx_index_monthly_serving_trade_date", table_name="index_monthly_serving", schema="core")
    op.drop_table("index_monthly_serving", schema="core")
    op.drop_index("uq_index_weekly_serving_ts_period", table_name="index_weekly_serving", schema="core")
    op.drop_index("idx_index_weekly_serving_period_start", table_name="index_weekly_serving", schema="core")
    op.drop_index("idx_index_weekly_serving_trade_date", table_name="index_weekly_serving", schema="core")
    op.drop_table("index_weekly_serving", schema="core")
    op.drop_index("idx_index_daily_serving_trade_date", table_name="index_daily_serving", schema="core")
    op.drop_table("index_daily_serving", schema="core")
