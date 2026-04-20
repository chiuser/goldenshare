"""add sync v2 execution and projection fields

Revision ID: 20260421_000067
Revises: 20260417_000066
Create Date: 2026-04-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_000067"
down_revision = "20260417_000066"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"


def _has_table(inspector: sa.Inspector, table_name: str, *, schema: str) -> bool:
    return inspector.has_table(table_name, schema=schema)


def _column_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name, schema=schema)}


def _index_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name, schema=schema)}


def _ensure_index(inspector: sa.Inspector, *, table_name: str, index_name: str, columns: list[str]) -> None:
    if index_name in _index_names(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_index(index_name, table_name, columns, schema=OPS_SCHEMA)


def _ensure_column(
    inspector: sa.Inspector,
    *,
    table_name: str,
    column: sa.Column,
) -> None:
    if not _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    if column.name in _column_names(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.add_column(table_name, column, schema=OPS_SCHEMA)


def _create_job_execution_unit_table(inspector: sa.Inspector) -> None:
    table_name = "job_execution_unit"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("step_id", sa.BigInteger(), nullable=False),
        sa.Column("unit_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("rows_fetched", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_written", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("unit_payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("execution_id", "unit_id", name="uk_job_execution_unit_execution_unit"),
        schema=OPS_SCHEMA,
    )
    op.create_index("idx_job_execution_unit_step_status", table_name, ["step_id", "status"], schema=OPS_SCHEMA)
    op.create_index("idx_job_execution_unit_execution_status", table_name, ["execution_id", "status"], schema=OPS_SCHEMA)


def _upgrade_job_execution(inspector: sa.Inspector) -> None:
    table = "job_execution"
    if not _has_table(inspector, table, schema=OPS_SCHEMA):
        return
    _ensure_column(
        inspector,
        table_name=table,
        column=sa.Column("run_profile", sa.String(length=32), nullable=False, server_default=sa.text("'point_incremental'")),
    )
    _ensure_column(inspector, table_name=table, column=sa.Column("workflow_profile", sa.String(length=32)))
    _ensure_column(
        inspector,
        table_name=table,
        column=sa.Column("failure_policy_default", sa.String(length=32), nullable=False, server_default=sa.text("'fail_fast'")),
    )
    _ensure_column(
        inspector,
        table_name=table,
        column=sa.Column("correlation_id", sa.String(length=64), nullable=False, server_default=sa.text("'legacy'")),
    )
    _ensure_column(inspector, table_name=table, column=sa.Column("rerun_id", sa.String(length=64)))
    _ensure_column(inspector, table_name=table, column=sa.Column("resume_from_step_key", sa.String(length=128)))
    _ensure_column(inspector, table_name=table, column=sa.Column("status_reason_code", sa.String(length=64)))

    _ensure_index(
        inspector,
        table_name=table,
        index_name="idx_job_execution_correlation_requested_at",
        columns=["correlation_id", "requested_at"],
    )
    _ensure_index(
        inspector,
        table_name=table,
        index_name="idx_job_execution_run_profile_requested_at",
        columns=["run_profile", "requested_at"],
    )


def _upgrade_job_execution_step(inspector: sa.Inspector) -> None:
    table = "job_execution_step"
    if not _has_table(inspector, table, schema=OPS_SCHEMA):
        return
    _ensure_column(inspector, table_name=table, column=sa.Column("failure_policy_effective", sa.String(length=32)))
    _ensure_column(
        inspector,
        table_name=table,
        column=sa.Column("depends_on_step_keys_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    _ensure_column(inspector, table_name=table, column=sa.Column("blocked_by_step_key", sa.String(length=128)))
    _ensure_column(inspector, table_name=table, column=sa.Column("skip_reason_code", sa.String(length=64)))
    _ensure_column(
        inspector,
        table_name=table,
        column=sa.Column("unit_total", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    _ensure_column(
        inspector,
        table_name=table,
        column=sa.Column("unit_done", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    _ensure_column(
        inspector,
        table_name=table,
        column=sa.Column("unit_failed", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )


def _upgrade_job_execution_event(inspector: sa.Inspector) -> None:
    table = "job_execution_event"
    if not _has_table(inspector, table, schema=OPS_SCHEMA):
        return
    _ensure_column(inspector, table_name=table, column=sa.Column("event_id", sa.String(length=64)))
    _ensure_column(
        inspector,
        table_name=table,
        column=sa.Column("event_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    _ensure_column(inspector, table_name=table, column=sa.Column("correlation_id", sa.String(length=64)))
    _ensure_column(inspector, table_name=table, column=sa.Column("unit_id", sa.String(length=128)))
    _ensure_column(
        inspector,
        table_name=table,
        column=sa.Column("producer", sa.String(length=32), nullable=False, server_default=sa.text("'runtime'")),
    )
    _ensure_column(inspector, table_name=table, column=sa.Column("dedupe_key", sa.String(length=128)))

    bind = op.get_bind()
    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        op.execute(f"UPDATE {OPS_SCHEMA}.{table} SET event_id = ('legacy-' || id::text) WHERE event_id IS NULL")
    else:
        op.execute(f"UPDATE {OPS_SCHEMA}.{table} SET event_id = ('legacy-' || id) WHERE event_id IS NULL")

    op.alter_column(
        table,
        "event_id",
        schema=OPS_SCHEMA,
        nullable=False,
        existing_type=sa.String(length=64),
    )
    op.create_unique_constraint("uk_job_execution_event_event_id", table, ["event_id"], schema=OPS_SCHEMA)

    _ensure_index(
        inspector,
        table_name=table,
        index_name="idx_job_execution_event_correlation_occurred",
        columns=["correlation_id", "occurred_at"],
    )
    _ensure_index(
        inspector,
        table_name=table,
        index_name="idx_job_execution_event_execution_step_unit_occurred",
        columns=["execution_id", "step_id", "unit_id", "occurred_at"],
    )


def _upgrade_probe_models(inspector: sa.Inspector) -> None:
    rule_table = "probe_rule"
    if _has_table(inspector, rule_table, schema=OPS_SCHEMA):
        _ensure_column(
            inspector,
            table_name=rule_table,
            column=sa.Column("trigger_mode", sa.String(length=32), nullable=False, server_default=sa.text("'dataset_execution'")),
        )
        _ensure_column(inspector, table_name=rule_table, column=sa.Column("workflow_key", sa.String(length=128)))
        _ensure_column(inspector, table_name=rule_table, column=sa.Column("step_key", sa.String(length=128)))
        _ensure_column(
            inspector,
            table_name=rule_table,
            column=sa.Column("rule_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )

    run_log_table = "probe_run_log"
    if _has_table(inspector, run_log_table, schema=OPS_SCHEMA):
        _ensure_column(
            inspector,
            table_name=run_log_table,
            column=sa.Column("rule_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )
        _ensure_column(
            inspector,
            table_name=run_log_table,
            column=sa.Column("result_code", sa.String(length=32), nullable=False, server_default=sa.text("'miss'")),
        )
        _ensure_column(inspector, table_name=run_log_table, column=sa.Column("result_reason", sa.String(length=64)))
        _ensure_column(inspector, table_name=run_log_table, column=sa.Column("correlation_id", sa.String(length=64)))


def _upgrade_projection_models(inspector: sa.Inspector) -> None:
    current_table = "dataset_layer_snapshot_current"
    if _has_table(inspector, current_table, schema=OPS_SCHEMA):
        _ensure_column(
            inspector,
            table_name=current_table,
            column=sa.Column("state_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        _ensure_column(inspector, table_name=current_table, column=sa.Column("status_reason_code", sa.String(length=64)))
        _ensure_column(inspector, table_name=current_table, column=sa.Column("execution_id", sa.BigInteger()))
        _ensure_column(inspector, table_name=current_table, column=sa.Column("run_profile", sa.String(length=32)))

    history_table = "dataset_layer_snapshot_history"
    if _has_table(inspector, history_table, schema=OPS_SCHEMA):
        _ensure_column(
            inspector,
            table_name=history_table,
            column=sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        _ensure_column(inspector, table_name=history_table, column=sa.Column("execution_id", sa.BigInteger()))
        _ensure_column(inspector, table_name=history_table, column=sa.Column("status_reason_code", sa.String(length=64)))

    status_table = "dataset_status_snapshot"
    if _has_table(inspector, status_table, schema=OPS_SCHEMA):
        _ensure_column(
            inspector,
            table_name=status_table,
            column=sa.Column("pipeline_mode", sa.String(length=32), nullable=False, server_default=sa.text("'single_source_direct'")),
        )
        _ensure_column(inspector, table_name=status_table, column=sa.Column("raw_stage_status", sa.String(length=16)))
        _ensure_column(inspector, table_name=status_table, column=sa.Column("std_stage_status", sa.String(length=16)))
        _ensure_column(inspector, table_name=status_table, column=sa.Column("resolution_stage_status", sa.String(length=16)))
        _ensure_column(inspector, table_name=status_table, column=sa.Column("serving_stage_status", sa.String(length=16)))
        _ensure_column(
            inspector,
            table_name=status_table,
            column=sa.Column("state_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {OPS_SCHEMA}")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _upgrade_job_execution(inspector)
    _upgrade_job_execution_step(inspector)
    _upgrade_job_execution_event(inspector)
    _create_job_execution_unit_table(inspector)
    _upgrade_probe_models(inspector)
    _upgrade_projection_models(inspector)


def _drop_index_if_exists(inspector: sa.Inspector, *, table_name: str, index_name: str) -> None:
    if not _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    if index_name in _index_names(inspector, table_name, schema=OPS_SCHEMA):
        op.drop_index(index_name, table_name=table_name, schema=OPS_SCHEMA)


def _drop_column_if_exists(inspector: sa.Inspector, *, table_name: str, column_name: str) -> None:
    if not _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    if column_name in _column_names(inspector, table_name, schema=OPS_SCHEMA):
        op.drop_column(table_name, column_name, schema=OPS_SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "job_execution_unit", schema=OPS_SCHEMA):
        _drop_index_if_exists(inspector, table_name="job_execution_unit", index_name="idx_job_execution_unit_step_status")
        _drop_index_if_exists(inspector, table_name="job_execution_unit", index_name="idx_job_execution_unit_execution_status")
        op.drop_table("job_execution_unit", schema=OPS_SCHEMA)

    # job_execution_event
    if _has_table(inspector, "job_execution_event", schema=OPS_SCHEMA):
        _drop_index_if_exists(inspector, table_name="job_execution_event", index_name="idx_job_execution_event_correlation_occurred")
        _drop_index_if_exists(inspector, table_name="job_execution_event", index_name="idx_job_execution_event_execution_step_unit_occurred")
        try:
            op.drop_constraint("uk_job_execution_event_event_id", "job_execution_event", schema=OPS_SCHEMA, type_="unique")
        except Exception:
            pass
    for col in ("dedupe_key", "producer", "unit_id", "correlation_id", "event_version", "event_id"):
        _drop_column_if_exists(inspector, table_name="job_execution_event", column_name=col)

    # job_execution_step
    for col in (
        "unit_failed",
        "unit_done",
        "unit_total",
        "skip_reason_code",
        "blocked_by_step_key",
        "depends_on_step_keys_json",
        "failure_policy_effective",
    ):
        _drop_column_if_exists(inspector, table_name="job_execution_step", column_name=col)

    # job_execution
    _drop_index_if_exists(inspector, table_name="job_execution", index_name="idx_job_execution_correlation_requested_at")
    _drop_index_if_exists(inspector, table_name="job_execution", index_name="idx_job_execution_run_profile_requested_at")
    for col in (
        "status_reason_code",
        "resume_from_step_key",
        "rerun_id",
        "correlation_id",
        "failure_policy_default",
        "workflow_profile",
        "run_profile",
    ):
        _drop_column_if_exists(inspector, table_name="job_execution", column_name=col)

    # probe_rule/probe_run_log
    for col in ("rule_version", "step_key", "workflow_key", "trigger_mode"):
        _drop_column_if_exists(inspector, table_name="probe_rule", column_name=col)
    for col in ("correlation_id", "result_reason", "result_code", "rule_version"):
        _drop_column_if_exists(inspector, table_name="probe_run_log", column_name=col)

    # projection tables
    for col in ("run_profile", "execution_id", "status_reason_code", "state_updated_at"):
        _drop_column_if_exists(inspector, table_name="dataset_layer_snapshot_current", column_name=col)
    for col in ("status_reason_code", "execution_id", "snapshot_at"):
        _drop_column_if_exists(inspector, table_name="dataset_layer_snapshot_history", column_name=col)
    for col in (
        "state_updated_at",
        "serving_stage_status",
        "resolution_stage_status",
        "std_stage_status",
        "raw_stage_status",
        "pipeline_mode",
    ):
        _drop_column_if_exists(inspector, table_name="dataset_status_snapshot", column_name=col)
