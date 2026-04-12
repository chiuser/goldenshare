"""add market column to raw_tushare.stock_basic"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_000041"
down_revision = "20260412_000040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_basic",
        sa.Column("market", sa.String(length=32), nullable=True),
        schema="raw_tushare",
    )


def downgrade() -> None:
    op.drop_column("stock_basic", "market", schema="raw_tushare")
