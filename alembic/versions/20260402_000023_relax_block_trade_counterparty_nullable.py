"""relax block_trade buyer/seller nullable"""

from __future__ import annotations

from alembic import op


revision = "20260402_000023"
down_revision = "20260402_000022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE raw.block_trade ALTER COLUMN buyer DROP NOT NULL")
    op.execute("ALTER TABLE raw.block_trade ALTER COLUMN seller DROP NOT NULL")
    op.execute("ALTER TABLE core.equity_block_trade ALTER COLUMN buyer DROP NOT NULL")
    op.execute("ALTER TABLE core.equity_block_trade ALTER COLUMN seller DROP NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE core.equity_block_trade ALTER COLUMN seller SET NOT NULL")
    op.execute("ALTER TABLE core.equity_block_trade ALTER COLUMN buyer SET NOT NULL")
    op.execute("ALTER TABLE raw.block_trade ALTER COLUMN seller SET NOT NULL")
    op.execute("ALTER TABLE raw.block_trade ALTER COLUMN buyer SET NOT NULL")
