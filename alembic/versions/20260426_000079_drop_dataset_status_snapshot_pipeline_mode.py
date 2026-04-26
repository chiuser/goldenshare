"""drop dataset status snapshot copied mode field

Revision ID: 20260426_000079
Revises: 20260426_000078
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_000079"
down_revision = "20260426_000078"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
TABLE_NAME = "dataset_status_snapshot"
COLUMN_NAME = "pipeline_" + "mode"


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
    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, TABLE_NAME):
        return
    if not _has_column(inspector, TABLE_NAME, COLUMN_NAME):
        op.add_column(
            TABLE_NAME,
            sa.Column(COLUMN_NAME, sa.String(length=32), nullable=False, server_default=sa.text("'single_source_direct'")),
            schema=OPS_SCHEMA,
        )
