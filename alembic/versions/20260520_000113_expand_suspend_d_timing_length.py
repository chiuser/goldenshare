"""expand suspend_d timing length

Revision ID: 20260520_000113
Revises: 20260517_000112
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260520_000113"
down_revision = "20260517_000112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "suspend_d",
        "suspend_timing",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=True,
        schema="raw_tushare",
    )
    op.alter_column(
        "equity_suspend_d",
        "suspend_timing",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=True,
        schema="core_serving",
    )


def downgrade() -> None:
    op.alter_column(
        "equity_suspend_d",
        "suspend_timing",
        existing_type=sa.String(length=128),
        type_=sa.String(length=32),
        existing_nullable=True,
        schema="core_serving",
    )
    op.alter_column(
        "suspend_d",
        "suspend_timing",
        existing_type=sa.String(length=128),
        type_=sa.String(length=32),
        existing_nullable=True,
        schema="raw_tushare",
    )
