"""add fund and index daily bar indexes"""

from __future__ import annotations

from alembic import op


revision = "20260324_000003"
down_revision = "20260324_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_fund_daily_bar_trade_date", "fund_daily_bar", ["trade_date"], schema="core")
    op.create_index("idx_index_daily_bar_trade_date", "index_daily_bar", ["trade_date"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_index_daily_bar_trade_date", table_name="index_daily_bar", schema="core")
    op.drop_index("idx_fund_daily_bar_trade_date", table_name="fund_daily_bar", schema="core")
