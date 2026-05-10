"""wealth turnover snapshot total vol bigint

Revision ID: 20260510_000103
Revises: 20260509_000102
Create Date: 2026-05-10
"""

from __future__ import annotations

from alembic import op


revision = "20260510_000103"
down_revision = "20260509_000102"
branch_labels = None
depends_on = None

SERVING_SCHEMA = "core_serving"
TABLE_NAME = "wealth_market_turnover_snapshot"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"""
        ALTER TABLE {SERVING_SCHEMA}.{TABLE_NAME}
        ALTER COLUMN total_vol TYPE BIGINT
        USING total_vol::bigint
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"""
        ALTER TABLE {SERVING_SCHEMA}.{TABLE_NAME}
        ALTER COLUMN total_vol TYPE NUMERIC(20, 2)
        USING total_vol::numeric(20, 2)
        """
    )
