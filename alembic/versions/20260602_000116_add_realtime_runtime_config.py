"""add realtime runtime config table

Revision ID: 20260602_000116
Revises: 20260531_000115
Create Date: 2026-06-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260602_000116"
down_revision = "20260531_000115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS foundation")
    op.create_table(
        "realtime_runtime_config",
        sa.Column("object_key", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("object_kind", sa.String(length=32), nullable=False),
        sa.Column("runtime_config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("requires_collector_restart", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="foundation",
    )


def downgrade() -> None:
    op.drop_table("realtime_runtime_config", schema="foundation")
