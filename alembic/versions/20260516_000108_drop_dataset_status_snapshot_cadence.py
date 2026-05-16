"""drop dataset status snapshot cadence

Revision ID: 20260516_000108
Revises: 20260515_000107
Create Date: 2026-05-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260516_000108"
down_revision = "20260515_000107"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
TABLE_NAME = "dataset_status_snapshot"
COLUMN_NAME = "cadence"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name, schema=OPS_SCHEMA)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name, schema=OPS_SCHEMA))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _has_column(inspector, TABLE_NAME, COLUMN_NAME):
        op.drop_column(TABLE_NAME, COLUMN_NAME, schema=OPS_SCHEMA)


def downgrade() -> None:
    # cadence 是已退场的旧展示节奏标签，迁移不恢复该列。
    return
