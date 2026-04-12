"""add market column to raw_tushare.stock_basic"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_000041"
down_revision = "20260412_000040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("stock_basic", schema="raw_tushare")}
    if "market" in columns:
        return
    op.add_column(
        "stock_basic",
        sa.Column("market", sa.String(length=32), nullable=True),
        schema="raw_tushare",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("stock_basic", schema="raw_tushare")}
    if "market" not in columns:
        return
    op.drop_column("stock_basic", "market", schema="raw_tushare")
