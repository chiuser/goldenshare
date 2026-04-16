"""add moneyflow std table

Revision ID: 20260416_000050
Revises: 20260416_000049
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000050"
down_revision = "20260416_000049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core_multi")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("moneyflow_std", schema="core_multi"):
        return

    op.create_table(
        "moneyflow_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("buy_sm_vol", sa.Numeric(20, 4)),
        sa.Column("buy_sm_amount", sa.Numeric(20, 4)),
        sa.Column("sell_sm_vol", sa.Numeric(20, 4)),
        sa.Column("sell_sm_amount", sa.Numeric(20, 4)),
        sa.Column("buy_md_vol", sa.Numeric(20, 4)),
        sa.Column("buy_md_amount", sa.Numeric(20, 4)),
        sa.Column("sell_md_vol", sa.Numeric(20, 4)),
        sa.Column("sell_md_amount", sa.Numeric(20, 4)),
        sa.Column("buy_lg_vol", sa.Numeric(20, 4)),
        sa.Column("buy_lg_amount", sa.Numeric(20, 4)),
        sa.Column("sell_lg_vol", sa.Numeric(20, 4)),
        sa.Column("sell_lg_amount", sa.Numeric(20, 4)),
        sa.Column("buy_elg_vol", sa.Numeric(20, 4)),
        sa.Column("buy_elg_amount", sa.Numeric(20, 4)),
        sa.Column("sell_elg_vol", sa.Numeric(20, 4)),
        sa.Column("sell_elg_amount", sa.Numeric(20, 4)),
        sa.Column("net_mf_vol", sa.Numeric(20, 4)),
        sa.Column("net_mf_amount", sa.Numeric(20, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="core_multi",
    )
    op.create_index("idx_moneyflow_std_trade_date", "moneyflow_std", ["trade_date"], schema="core_multi")
    op.create_index(
        "idx_moneyflow_std_source_trade_date",
        "moneyflow_std",
        ["source_key", "trade_date"],
        schema="core_multi",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("moneyflow_std", schema="core_multi"):
        return
    op.drop_index("idx_moneyflow_std_source_trade_date", table_name="moneyflow_std", schema="core_multi")
    op.drop_index("idx_moneyflow_std_trade_date", table_name="moneyflow_std", schema="core_multi")
    op.drop_table("moneyflow_std", schema="core_multi")
