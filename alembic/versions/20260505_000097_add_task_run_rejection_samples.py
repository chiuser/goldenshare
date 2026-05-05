"""add task run rejection samples

Revision ID: 20260505_000097
Revises: 20260505_000096
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260505_000097"
down_revision = "20260505_000096"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not inspector.has_table(table_name, schema=OPS_SCHEMA):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name, schema=OPS_SCHEMA))


def _sample_column() -> sa.Column:
    return sa.Column(
        "rejected_reason_samples_json",
        sa.JSON(),
        nullable=False,
        server_default=sa.text("'{}'"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "task_run", "rejected_reason_samples_json"):
        op.add_column("task_run", _sample_column(), schema=OPS_SCHEMA)
    if not _has_column(inspector, "task_run_node", "rejected_reason_samples_json"):
        op.add_column("task_run_node", _sample_column(), schema=OPS_SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_column(inspector, "task_run_node", "rejected_reason_samples_json"):
        op.drop_column("task_run_node", "rejected_reason_samples_json", schema=OPS_SCHEMA)
    if _has_column(inspector, "task_run", "rejected_reason_samples_json"):
        op.drop_column("task_run", "rejected_reason_samples_json", schema=OPS_SCHEMA)
