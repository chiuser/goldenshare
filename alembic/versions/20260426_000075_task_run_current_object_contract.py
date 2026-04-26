"""replace task run current context with current object

Revision ID: 20260426_000075
Revises: 20260426_000074
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_000075"
down_revision = "20260426_000074"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"

RUNTIME_RESET_TABLES = (
    "task_run_issue",
    "task_run_node",
    "task_run",
)

OPTIONAL_RESET_TABLES = (
    "sync_job_state",
    "dataset_status_snapshot",
    "dataset_layer_snapshot_current",
    "dataset_layer_snapshot_history",
    "probe_run_log",
    "job_schedule",
)


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name, schema=OPS_SCHEMA)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name, schema=OPS_SCHEMA))


def _truncate_or_delete(table_names: tuple[str, ...]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [table_name for table_name in table_names if _has_table(inspector, table_name)]
    if not existing:
        return
    if bind.dialect.name == "postgresql":
        tables = ", ".join(f'"{OPS_SCHEMA}"."{table_name}"' for table_name in existing)
        op.execute(sa.text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        return
    for table_name in existing:
        op.execute(sa.text(f'DELETE FROM "{OPS_SCHEMA}"."{table_name}"'))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "task_run") and not _has_column(inspector, "task_run", "current_object_json"):
        op.add_column(
            "task_run",
            sa.Column("current_object_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            schema=OPS_SCHEMA,
        )
    inspector = sa.inspect(bind)
    if _has_table(inspector, "task_run") and _has_column(inspector, "task_run", "current_context_json"):
        op.drop_column("task_run", "current_context_json", schema=OPS_SCHEMA)

    inspector = sa.inspect(bind)
    if _has_table(inspector, "task_run_issue") and not _has_column(inspector, "task_run_issue", "object_json"):
        op.add_column(
            "task_run_issue",
            sa.Column("object_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            schema=OPS_SCHEMA,
        )

    _truncate_or_delete(RUNTIME_RESET_TABLES)
    _truncate_or_delete(OPTIONAL_RESET_TABLES)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "task_run") and not _has_column(inspector, "task_run", "current_context_json"):
        op.add_column(
            "task_run",
            sa.Column("current_context_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            schema=OPS_SCHEMA,
        )
    inspector = sa.inspect(bind)
    if _has_table(inspector, "task_run") and _has_column(inspector, "task_run", "current_object_json"):
        op.drop_column("task_run", "current_object_json", schema=OPS_SCHEMA)

    inspector = sa.inspect(bind)
    if _has_table(inspector, "task_run_issue") and _has_column(inspector, "task_run_issue", "object_json"):
        op.drop_column("task_run_issue", "object_json", schema=OPS_SCHEMA)
