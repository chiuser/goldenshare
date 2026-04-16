"""add cyq_perf tables for tushare raw and serving

Revision ID: 20260416_000060
Revises: 20260416_000059
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000060"
down_revision = "20260416_000059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("cyq_perf", schema="raw_tushare"):
        op.create_table(
            "cyq_perf",
            sa.Column("ts_code", sa.String(length=16), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("his_low", sa.Numeric(18, 4)),
            sa.Column("his_high", sa.Numeric(18, 4)),
            sa.Column("cost_5pct", sa.Numeric(18, 4)),
            sa.Column("cost_15pct", sa.Numeric(18, 4)),
            sa.Column("cost_50pct", sa.Numeric(18, 4)),
            sa.Column("cost_85pct", sa.Numeric(18, 4)),
            sa.Column("cost_95pct", sa.Numeric(18, 4)),
            sa.Column("weight_avg", sa.Numeric(18, 4)),
            sa.Column("winner_rate", sa.Numeric(10, 4)),
            sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'cyq_perf'")),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", sa.Text()),
            sa.PrimaryKeyConstraint("ts_code", "trade_date"),
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_cyq_perf_trade_date",
            "cyq_perf",
            ["trade_date"],
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_cyq_perf_ts_code_trade_date",
            "cyq_perf",
            ["ts_code", "trade_date"],
            schema="raw_tushare",
        )

    if not inspector.has_table("equity_cyq_perf", schema="core_serving"):
        op.create_table(
            "equity_cyq_perf",
            sa.Column("ts_code", sa.String(length=16), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("his_low", sa.Numeric(18, 4)),
            sa.Column("his_high", sa.Numeric(18, 4)),
            sa.Column("cost_5pct", sa.Numeric(18, 4)),
            sa.Column("cost_15pct", sa.Numeric(18, 4)),
            sa.Column("cost_50pct", sa.Numeric(18, 4)),
            sa.Column("cost_85pct", sa.Numeric(18, 4)),
            sa.Column("cost_95pct", sa.Numeric(18, 4)),
            sa.Column("weight_avg", sa.Numeric(18, 4)),
            sa.Column("winner_rate", sa.Numeric(10, 4)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("ts_code", "trade_date"),
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_cyq_perf_trade_date",
            "equity_cyq_perf",
            ["trade_date"],
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_cyq_perf_ts_code_trade_date",
            "equity_cyq_perf",
            ["ts_code", "trade_date"],
            schema="core_serving",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("equity_cyq_perf", schema="core_serving"):
        op.drop_index("idx_equity_cyq_perf_ts_code_trade_date", table_name="equity_cyq_perf", schema="core_serving")
        op.drop_index("idx_equity_cyq_perf_trade_date", table_name="equity_cyq_perf", schema="core_serving")
        op.drop_table("equity_cyq_perf", schema="core_serving")

    if inspector.has_table("cyq_perf", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_cyq_perf_ts_code_trade_date", table_name="cyq_perf", schema="raw_tushare")
        op.drop_index("idx_raw_tushare_cyq_perf_trade_date", table_name="cyq_perf", schema="raw_tushare")
        op.drop_table("cyq_perf", schema="raw_tushare")
