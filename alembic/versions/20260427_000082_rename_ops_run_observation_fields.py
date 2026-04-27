"""rename ops run observation fields

Revision ID: 20260427_000082
Revises: 20260427_000081
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_000082"
down_revision = "20260427_000081"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name, schema=OPS_SCHEMA)


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name, schema=OPS_SCHEMA)}


def _rename_column_if_needed(
    inspector: sa.Inspector,
    table_name: str,
    *,
    old_column: str,
    new_column: str,
) -> None:
    columns = _column_names(inspector, table_name)
    if new_column in columns:
        return
    if old_column in columns:
        op.alter_column(table_name, old_column, new_column_name=new_column, schema=OPS_SCHEMA)


def _update_probe_trigger_mode(old_value: str, new_value: str) -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("probe_rule", schema=OPS_SCHEMA):
        return
    op.execute(
        sa.text(
            f"""
            UPDATE {OPS_SCHEMA}.probe_rule
            SET trigger_mode = :new_value
            WHERE trigger_mode = :old_value
            """
        ).bindparams(old_value=old_value, new_value=new_value)
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    _rename_column_if_needed(
        inspector,
        "dataset_layer_snapshot_current",
        old_column="execution_id",
        new_column="task_run_id",
    )
    _rename_column_if_needed(
        inspector,
        "dataset_layer_snapshot_history",
        old_column="execution_id",
        new_column="task_run_id",
    )
    _rename_column_if_needed(
        inspector,
        "probe_run_log",
        old_column="triggered_execution_id",
        new_column="triggered_task_run_id",
    )
    _update_probe_trigger_mode("dataset_execution", "task_run")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    _update_probe_trigger_mode("task_run", "dataset_execution")
    _rename_column_if_needed(
        inspector,
        "probe_run_log",
        old_column="triggered_task_run_id",
        new_column="triggered_execution_id",
    )
    _rename_column_if_needed(
        inspector,
        "dataset_layer_snapshot_history",
        old_column="task_run_id",
        new_column="execution_id",
    )
    _rename_column_if_needed(
        inspector,
        "dataset_layer_snapshot_current",
        old_column="task_run_id",
        new_column="execution_id",
    )
