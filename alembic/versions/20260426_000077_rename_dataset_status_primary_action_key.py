"""rename dataset status primary action key

Revision ID: 20260426_000077
Revises: 20260426_000076
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_000077"
down_revision = "20260426_000076"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
TABLE_NAME = "dataset_status_snapshot"
OLD_COLUMN = "primary_execution_spec_key"
NEW_COLUMN = "primary_action_key"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name, schema=OPS_SCHEMA)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name, schema=OPS_SCHEMA))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, TABLE_NAME):
        return
    has_old = _has_column(inspector, TABLE_NAME, OLD_COLUMN)
    has_new = _has_column(inspector, TABLE_NAME, NEW_COLUMN)
    if has_old and not has_new:
        op.alter_column(TABLE_NAME, OLD_COLUMN, new_column_name=NEW_COLUMN, schema=OPS_SCHEMA)
        return
    if not has_new:
        op.add_column(TABLE_NAME, sa.Column(NEW_COLUMN, sa.String(length=128), nullable=True), schema=OPS_SCHEMA)
    if has_old:
        op.drop_column(TABLE_NAME, OLD_COLUMN, schema=OPS_SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, TABLE_NAME):
        return
    has_old = _has_column(inspector, TABLE_NAME, OLD_COLUMN)
    has_new = _has_column(inspector, TABLE_NAME, NEW_COLUMN)
    if has_new and not has_old:
        op.alter_column(TABLE_NAME, NEW_COLUMN, new_column_name=OLD_COLUMN, schema=OPS_SCHEMA)
        return
    if not has_old:
        op.add_column(TABLE_NAME, sa.Column(OLD_COLUMN, sa.String(length=128), nullable=True), schema=OPS_SCHEMA)
    if has_new:
        op.drop_column(TABLE_NAME, NEW_COLUMN, schema=OPS_SCHEMA)
