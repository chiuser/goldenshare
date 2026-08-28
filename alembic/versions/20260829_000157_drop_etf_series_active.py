"""Drop the retired ETF series active table.

Revision ID: 20260829_000157
Revises: 20260828_000156
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op


revision = "20260829_000157"
down_revision = "20260828_000156"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("etf_series_active", schema="ops")


def downgrade() -> None:
    raise RuntimeError("ops.etf_series_active retirement is irreversible")
