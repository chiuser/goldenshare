"""retire ops layer snapshot observability

Revision ID: 20260515_000107
Revises: 20260514_000106
Create Date: 2026-05-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260515_000107"
down_revision = "20260514_000106"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
STATUS_TABLE = "dataset_status_snapshot"
LAYER_TABLES = ("dataset_layer_snapshot_current", "dataset_layer_snapshot_history")
STATUS_STAGE_COLUMNS = (
    "raw_stage_status",
    "std_stage_status",
    "resolution_stage_status",
    "serving_stage_status",
)


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name, schema=OPS_SCHEMA)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name, schema=OPS_SCHEMA))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _has_table(inspector, STATUS_TABLE):
        for column_name in STATUS_STAGE_COLUMNS:
            if _has_column(inspector, STATUS_TABLE, column_name):
                op.drop_column(STATUS_TABLE, column_name, schema=OPS_SCHEMA)

    for table_name in LAYER_TABLES:
        if _has_table(inspector, table_name):
            op.drop_table(table_name, schema=OPS_SCHEMA)


def downgrade() -> None:
    # Layer snapshot 是已退场的旧观测模型，本迁移不恢复旧表和旧列。
    return
