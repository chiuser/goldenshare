"""add margin tables for tushare raw and serving

Revision ID: 20260416_000057
Revises: 20260416_000056
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000057"
down_revision = "20260416_000056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("margin", schema="raw_tushare"):
        op.create_table(
            "margin",
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("exchange_id", sa.String(length=8), nullable=False),
            sa.Column("rzye", sa.Numeric(20, 4)),
            sa.Column("rzmre", sa.Numeric(20, 4)),
            sa.Column("rzche", sa.Numeric(20, 4)),
            sa.Column("rqye", sa.Numeric(20, 4)),
            sa.Column("rqmcl", sa.Numeric(20, 4)),
            sa.Column("rzrqye", sa.Numeric(20, 4)),
            sa.Column("rqyl", sa.Numeric(20, 4)),
            sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'margin'")),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", sa.Text()),
            sa.PrimaryKeyConstraint("trade_date", "exchange_id"),
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_margin_trade_date",
            "margin",
            ["trade_date"],
            schema="raw_tushare",
        )
        op.create_index(
            "idx_raw_tushare_margin_exchange_trade_date",
            "margin",
            ["exchange_id", "trade_date"],
            schema="raw_tushare",
        )

    if not inspector.has_table("equity_margin", schema="core_serving"):
        op.create_table(
            "equity_margin",
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("exchange_id", sa.String(length=8), nullable=False),
            sa.Column("rzye", sa.Numeric(20, 4)),
            sa.Column("rzmre", sa.Numeric(20, 4)),
            sa.Column("rzche", sa.Numeric(20, 4)),
            sa.Column("rqye", sa.Numeric(20, 4)),
            sa.Column("rqmcl", sa.Numeric(20, 4)),
            sa.Column("rzrqye", sa.Numeric(20, 4)),
            sa.Column("rqyl", sa.Numeric(20, 4)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("trade_date", "exchange_id"),
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_margin_trade_date",
            "equity_margin",
            ["trade_date"],
            schema="core_serving",
        )
        op.create_index(
            "idx_equity_margin_exchange_trade_date",
            "equity_margin",
            ["exchange_id", "trade_date"],
            schema="core_serving",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("equity_margin", schema="core_serving"):
        op.drop_index("idx_equity_margin_exchange_trade_date", table_name="equity_margin", schema="core_serving")
        op.drop_index("idx_equity_margin_trade_date", table_name="equity_margin", schema="core_serving")
        op.drop_table("equity_margin", schema="core_serving")

    if inspector.has_table("margin", schema="raw_tushare"):
        op.drop_index("idx_raw_tushare_margin_exchange_trade_date", table_name="margin", schema="raw_tushare")
        op.drop_index("idx_raw_tushare_margin_trade_date", table_name="margin", schema="raw_tushare")
        op.drop_table("margin", schema="raw_tushare")

