"""rename ops schedule target contract

Revision ID: 20260426_000078
Revises: 20260426_000077
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_000078"
down_revision = "20260426_000077"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
OLD_TABLE = "job_schedule"
NEW_TABLE = "schedule"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name, schema=OPS_SCHEMA)


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name, schema=OPS_SCHEMA)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {item["name"] for item in inspector.get_indexes(table_name, schema=OPS_SCHEMA)}


def _check_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    try:
        checks = inspector.get_check_constraints(table_name, schema=OPS_SCHEMA)
    except NotImplementedError:
        return set()
    return {item["name"] for item in checks if item.get("name")}


def _rename_table_if_needed(inspector: sa.Inspector, *, upgrade_mode: bool) -> None:
    source = OLD_TABLE if upgrade_mode else NEW_TABLE
    target = NEW_TABLE if upgrade_mode else OLD_TABLE
    if _has_table(inspector, target):
        return
    if _has_table(inspector, source):
        op.rename_table(source, target, schema=OPS_SCHEMA)


def _drop_index_if_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> None:
    if index_name in _index_names(inspector, table_name):
        op.drop_index(index_name, table_name=table_name, schema=OPS_SCHEMA)


def _create_index_if_missing(inspector: sa.Inspector, table_name: str, index_name: str, columns: list[str]) -> None:
    if index_name not in _index_names(inspector, table_name):
        op.create_index(index_name, table_name, columns, schema=OPS_SCHEMA)


def _drop_check_if_exists(inspector: sa.Inspector, table_name: str, constraint_name: str) -> None:
    if constraint_name in _check_names(inspector, table_name):
        op.drop_constraint(op.f(constraint_name), table_name, type_="check", schema=OPS_SCHEMA)


def _create_check_if_missing(inspector: sa.Inspector, table_name: str, constraint_name: str, condition: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    if constraint_name not in _check_names(inspector, table_name):
        op.create_check_constraint(op.f(constraint_name), table_name, condition, schema=OPS_SCHEMA)


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


def _update_config_revision_json_to_target() -> None:
    if op.get_bind().dialect.name != "postgresql":
        op.execute(sa.text(f"UPDATE {OPS_SCHEMA}.config_revision SET object_type = 'schedule' WHERE object_type = 'job_schedule'"))
        return
    op.execute(
        sa.text(
            f"""
            UPDATE {OPS_SCHEMA}.config_revision
            SET object_type = 'schedule',
                before_json = CASE
                  WHEN before_json IS NULL THEN NULL
                  ELSE (
                    before_json::jsonb - 'spec_type' - 'spec_key'
                    || jsonb_build_object(
                      'target_type',
                      CASE
                        WHEN before_json->>'spec_type' = 'job' THEN 'maintenance_action'
                        ELSE before_json->>'spec_type'
                      END,
                      'target_key',
                      before_json->>'spec_key'
                    )
                  )::json
                END,
                after_json = CASE
                  WHEN after_json IS NULL THEN NULL
                  ELSE (
                    after_json::jsonb - 'spec_type' - 'spec_key'
                    || jsonb_build_object(
                      'target_type',
                      CASE
                        WHEN after_json->>'spec_type' = 'job' THEN 'maintenance_action'
                        ELSE after_json->>'spec_type'
                      END,
                      'target_key',
                      after_json->>'spec_key'
                    )
                  )::json
                END
            WHERE object_type = 'job_schedule'
            """
        )
    )


def _update_config_revision_json_to_spec() -> None:
    if op.get_bind().dialect.name != "postgresql":
        op.execute(sa.text(f"UPDATE {OPS_SCHEMA}.config_revision SET object_type = 'job_schedule' WHERE object_type = 'schedule'"))
        return
    op.execute(
        sa.text(
            f"""
            UPDATE {OPS_SCHEMA}.config_revision
            SET object_type = 'job_schedule',
                before_json = CASE
                  WHEN before_json IS NULL THEN NULL
                  ELSE (
                    before_json::jsonb - 'target_type' - 'target_key'
                    || jsonb_build_object(
                      'spec_type',
                      CASE
                        WHEN before_json->>'target_type' = 'maintenance_action' THEN 'job'
                        ELSE before_json->>'target_type'
                      END,
                      'spec_key',
                      before_json->>'target_key'
                    )
                  )::json
                END,
                after_json = CASE
                  WHEN after_json IS NULL THEN NULL
                  ELSE (
                    after_json::jsonb - 'target_type' - 'target_key'
                    || jsonb_build_object(
                      'spec_type',
                      CASE
                        WHEN after_json->>'target_type' = 'maintenance_action' THEN 'job'
                        ELSE after_json->>'target_type'
                      END,
                      'spec_key',
                      after_json->>'target_key'
                    )
                  )::json
                END
            WHERE object_type = 'schedule'
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _rename_table_if_needed(inspector, upgrade_mode=True)

    inspector = sa.inspect(bind)
    if not _has_table(inspector, NEW_TABLE):
        return

    for index_name in ("idx_job_schedule_status_next_run_at", "idx_job_schedule_spec_type_spec_key"):
        _drop_index_if_exists(inspector, NEW_TABLE, index_name)

    for constraint_name in (
        "ck_job_schedule_dataset_action_spec_key_maintain",
        "ck_job_schedule_spec_key_no_legacy_prefix",
    ):
        _drop_check_if_exists(inspector, NEW_TABLE, constraint_name)

    inspector = sa.inspect(bind)
    _rename_column_if_needed(inspector, NEW_TABLE, old_column="spec_type", new_column="target_type")
    inspector = sa.inspect(bind)
    _rename_column_if_needed(inspector, NEW_TABLE, old_column="spec_key", new_column="target_key")

    inspector = sa.inspect(bind)
    if {"target_type", "target_key"}.issubset(_column_names(inspector, NEW_TABLE)):
        op.execute(sa.text(f"UPDATE {OPS_SCHEMA}.{NEW_TABLE} SET target_type = 'maintenance_action' WHERE target_type = 'job'"))

    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, NEW_TABLE, "idx_ops_schedule_status_next_run_at", ["status", "next_run_at"])
    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, NEW_TABLE, "idx_ops_schedule_target_type_target_key", ["target_type", "target_key"])
    inspector = sa.inspect(bind)
    _create_check_if_missing(
        inspector,
        NEW_TABLE,
        "ck_ops_schedule_target_type_allowed",
        "target_type IN ('dataset_action', 'workflow', 'maintenance_action')",
    )
    inspector = sa.inspect(bind)
    _create_check_if_missing(
        inspector,
        NEW_TABLE,
        "ck_ops_schedule_dataset_action_target_key_maintain",
        "(target_type <> 'dataset_action') OR (target_key LIKE '%.maintain')",
    )
    _update_config_revision_json_to_target()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, NEW_TABLE):
        return

    for constraint_name in (
        "ck_ops_schedule_dataset_action_target_key_maintain",
        "ck_ops_schedule_target_type_allowed",
    ):
        _drop_check_if_exists(inspector, NEW_TABLE, constraint_name)

    for index_name in ("idx_ops_schedule_target_type_target_key", "idx_ops_schedule_status_next_run_at"):
        _drop_index_if_exists(inspector, NEW_TABLE, index_name)

    if "target_type" in _column_names(inspector, NEW_TABLE):
        op.execute(sa.text(f"UPDATE {OPS_SCHEMA}.{NEW_TABLE} SET target_type = 'job' WHERE target_type = 'maintenance_action'"))

    inspector = sa.inspect(bind)
    _rename_column_if_needed(inspector, NEW_TABLE, old_column="target_type", new_column="spec_type")
    inspector = sa.inspect(bind)
    _rename_column_if_needed(inspector, NEW_TABLE, old_column="target_key", new_column="spec_key")

    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, NEW_TABLE, "idx_job_schedule_status_next_run_at", ["status", "next_run_at"])
    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, NEW_TABLE, "idx_job_schedule_spec_type_spec_key", ["spec_type", "spec_key"])
    _update_config_revision_json_to_spec()

    inspector = sa.inspect(bind)
    _rename_table_if_needed(inspector, upgrade_mode=False)
