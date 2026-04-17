"""widen auth_invite_code.code_hint for full invite display

Revision ID: 20260417_000066
Revises: 20260417_000065
Create Date: 2026-04-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_000066"
down_revision = "20260417_000065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "auth_invite_code",
        "code_hint",
        schema="app",
        existing_type=sa.String(length=16),
        type_=sa.String(length=128),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "auth_invite_code",
        "code_hint",
        schema="app",
        existing_type=sa.String(length=128),
        type_=sa.String(length=16),
        existing_nullable=False,
    )

