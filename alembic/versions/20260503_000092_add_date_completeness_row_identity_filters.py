"""add date completeness row identity filters

Revision ID: 20260503_000092
Revises: 20260503_000091
Create Date: 2026-05-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_000092"
down_revision = "20260503_000091"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"


def upgrade() -> None:
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("row_identity_filters_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        schema=OPS_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("dataset_date_completeness_run", "row_identity_filters_json", schema=OPS_SCHEMA)
