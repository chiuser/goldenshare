"""add fund_adj resource"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260406_000031"
down_revision = "20260406_000030"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "fund_adj",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("adj_factor", sa.Numeric(20, 8)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="fund_adj"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "fund_adj_factor",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("adj_factor", sa.Numeric(20, 8), nullable=False),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_fund_adj_factor_trade_date", "fund_adj_factor", ["trade_date"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_fund_adj_factor_trade_date", table_name="fund_adj_factor", schema="core")
    op.drop_table("fund_adj_factor", schema="core")
    op.drop_table("fund_adj", schema="raw")
