"""drop redundant equity daily bar composite index"""

from __future__ import annotations

from alembic import op


revision = "20260324_000004"
down_revision = "20260324_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_equity_daily_bar_ts_code_trade_date_desc", table_name="equity_daily_bar", schema="core")


def downgrade() -> None:
    op.create_index(
        "idx_equity_daily_bar_ts_code_trade_date_desc",
        "equity_daily_bar",
        ["ts_code", "trade_date"],
        schema="core",
    )
