"""relax research report nullable fields

Revision ID: 20260514_000106
Revises: 20260514_000105
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op


revision = "20260514_000106"
down_revision = "20260514_000105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        ALTER TABLE raw_tushare.research_report
            ALTER COLUMN trade_date DROP NOT NULL,
            ALTER COLUMN title DROP NOT NULL,
            ALTER COLUMN report_type DROP NOT NULL,
            ALTER COLUMN inst_csname DROP NOT NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        ALTER TABLE raw_tushare.research_report
            ALTER COLUMN trade_date SET NOT NULL,
            ALTER COLUMN title SET NOT NULL,
            ALTER COLUMN report_type SET NOT NULL,
            ALTER COLUMN inst_csname SET NOT NULL
        """
    )
