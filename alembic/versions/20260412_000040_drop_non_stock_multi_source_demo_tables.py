"""drop non-stock multi-source demo tables"""

from __future__ import annotations

from alembic import op


revision = "20260412_000040"
down_revision = "20260412_000039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core_multi.stk_period_bar_adj_std")
    op.execute("DROP TABLE IF EXISTS core_multi.stk_period_bar_std")
    op.execute("DROP TABLE IF EXISTS core_multi.equity_daily_basic_std")
    op.execute("DROP TABLE IF EXISTS core_multi.equity_adj_factor_std")
    op.execute("DROP TABLE IF EXISTS core_multi.equity_daily_bar_std")

    op.execute("DROP TABLE IF EXISTS raw_biying.equity_daily_basic")
    op.execute("DROP TABLE IF EXISTS raw_biying.equity_adj_factor")
    op.execute("DROP TABLE IF EXISTS raw_biying.equity_daily_bar")

    op.execute("DROP TABLE IF EXISTS raw_tushare.equity_daily_basic")
    op.execute("DROP TABLE IF EXISTS raw_tushare.equity_adj_factor")
    op.execute("DROP TABLE IF EXISTS raw_tushare.equity_daily_bar")


def downgrade() -> None:
    # Intentionally no-op: removed demo tables are not restored.
    pass
