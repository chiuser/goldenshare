"""widen index_basic ts_code length

Revision ID: 20260423_000071
Revises: 20260423_000070
Create Date: 2026-04-23 14:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260423_000071"
down_revision = "20260423_000070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "index_basic",
        "ts_code",
        schema="raw_tushare",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "index_basic",
        "ts_code",
        schema="core_serving",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "index_basic",
        "ts_code",
        schema="core_serving",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.alter_column(
        "index_basic",
        "ts_code",
        schema="raw_tushare",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
