"""add ops v2.1 base objects

Revision ID: 20260414_000045
Revises: 20260413_000044
Create Date: 2026-04-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260414_000045"
down_revision = "20260413_000044"
branch_labels = None
depends_on = None


OPS_SCHEMA = "ops"
JOB_EXECUTION_TABLE = "job_execution"


def _has_table(inspector: sa.Inspector, table_name: str, *, schema: str) -> bool:
    return inspector.has_table(table_name, schema=schema)


def _column_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name, schema=schema)}


def _index_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name, schema=schema)}


def _ensure_index(
    inspector: sa.Inspector,
    *,
    index_name: str,
    table_name: str,
    columns: list[str],
    schema: str,
) -> None:
    if index_name in _index_names(inspector, table_name, schema=schema):
        return
    op.create_index(index_name, table_name, columns, schema=schema)


def _ensure_job_execution_columns(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, JOB_EXECUTION_TABLE, schema=OPS_SCHEMA):
        return
    columns = _column_names(inspector, JOB_EXECUTION_TABLE, schema=OPS_SCHEMA)
    if "dataset_key" not in columns:
        op.add_column(JOB_EXECUTION_TABLE, sa.Column("dataset_key", sa.String(length=64)), schema=OPS_SCHEMA)
    if "source_key" not in columns:
        op.add_column(JOB_EXECUTION_TABLE, sa.Column("source_key", sa.String(length=32)), schema=OPS_SCHEMA)
    if "stage" not in columns:
        op.add_column(JOB_EXECUTION_TABLE, sa.Column("stage", sa.String(length=16)), schema=OPS_SCHEMA)
    if "policy_version" not in columns:
        op.add_column(JOB_EXECUTION_TABLE, sa.Column("policy_version", sa.Integer()), schema=OPS_SCHEMA)
    if "run_scope" not in columns:
        op.add_column(JOB_EXECUTION_TABLE, sa.Column("run_scope", sa.String(length=32)), schema=OPS_SCHEMA)

    _ensure_index(
        inspector,
        index_name="idx_job_execution_dataset_requested_at",
        table_name=JOB_EXECUTION_TABLE,
        columns=["dataset_key", "requested_at"],
        schema=OPS_SCHEMA,
    )
    _ensure_index(
        inspector,
        index_name="idx_job_execution_source_stage_requested_at",
        table_name=JOB_EXECUTION_TABLE,
        columns=["source_key", "stage", "requested_at"],
        schema=OPS_SCHEMA,
    )


def _create_dataset_layer_snapshot_history(inspector: sa.Inspector) -> None:
    table_name = "dataset_layer_snapshot_history"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=32)),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rows_in", sa.BigInteger()),
        sa.Column("rows_out", sa.BigInteger()),
        sa.Column("error_count", sa.Integer()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("lag_seconds", sa.Integer()),
        sa.Column("message", sa.Text()),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_layer_snapshot_history_snapshot_date",
        table_name,
        ["snapshot_date"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_layer_snapshot_history_dataset_stage",
        table_name,
        ["dataset_key", "stage", "snapshot_date"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_layer_snapshot_history_source_stage",
        table_name,
        ["source_key", "stage", "snapshot_date"],
        schema=OPS_SCHEMA,
    )


def _create_probe_rule(inspector: sa.Inspector) -> None:
    table_name = "probe_rule"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=32)),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("window_start", sa.String(length=16)),
        sa.Column("window_end", sa.String(length=16)),
        sa.Column("probe_interval_seconds", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("probe_condition_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("on_success_action_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("max_triggers_per_day", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("timezone_name", sa.String(length=64), nullable=False, server_default=sa.text("'Asia/Shanghai'")),
        sa.Column("last_probed_at", sa.DateTime(timezone=True)),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.BigInteger()),
        sa.Column("updated_by_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=OPS_SCHEMA,
    )
    op.create_index("idx_probe_rule_status_dataset", table_name, ["status", "dataset_key"], schema=OPS_SCHEMA)
    op.create_index("idx_probe_rule_dataset_source", table_name, ["dataset_key", "source_key"], schema=OPS_SCHEMA)


def _create_probe_run_log(inspector: sa.Inspector) -> None:
    table_name = "probe_run_log"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("probe_rule_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("condition_matched", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("message", sa.Text()),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("probed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("triggered_execution_id", sa.BigInteger()),
        sa.Column("duration_ms", sa.Integer()),
        schema=OPS_SCHEMA,
    )
    op.create_index("idx_probe_run_log_rule_probed_at", table_name, ["probe_rule_id", "probed_at"], schema=OPS_SCHEMA)
    op.create_index("idx_probe_run_log_status_probed_at", table_name, ["status", "probed_at"], schema=OPS_SCHEMA)


def _create_resolution_release(inspector: sa.Inspector) -> None:
    table_name = "resolution_release"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("target_policy_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'previewing'")),
        sa.Column("triggered_by_user_id", sa.BigInteger()),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("rollback_to_release_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_resolution_release_dataset_triggered_at",
        table_name,
        ["dataset_key", "triggered_at"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_resolution_release_status_triggered_at",
        table_name,
        ["status", "triggered_at"],
        schema=OPS_SCHEMA,
    )


def _create_resolution_release_stage_status(inspector: sa.Inspector) -> None:
    table_name = "resolution_release_stage_status"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("release_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=32)),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rows_in", sa.BigInteger()),
        sa.Column("rows_out", sa.BigInteger()),
        sa.Column("message", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_resolution_release_stage_status_release",
        table_name,
        ["release_id", "stage"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_resolution_release_stage_status_dataset_source",
        table_name,
        ["dataset_key", "source_key", "stage"],
        schema=OPS_SCHEMA,
    )


def _create_std_mapping_rule(inspector: sa.Inspector) -> None:
    table_name = "std_mapping_rule"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=32), nullable=False),
        sa.Column("src_field", sa.String(length=64), nullable=False),
        sa.Column("std_field", sa.String(length=64), nullable=False),
        sa.Column("src_type", sa.String(length=32)),
        sa.Column("std_type", sa.String(length=32)),
        sa.Column("transform_fn", sa.String(length=64)),
        sa.Column("lineage_preserved", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("rule_set_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by_user_id", sa.BigInteger()),
        sa.Column("updated_by_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_std_mapping_rule_dataset_source_status",
        table_name,
        ["dataset_key", "source_key", "status"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_std_mapping_rule_rule_set_version",
        table_name,
        ["dataset_key", "source_key", "rule_set_version"],
        schema=OPS_SCHEMA,
    )


def _create_std_cleansing_rule(inspector: sa.Inspector) -> None:
    table_name = "std_cleansing_rule"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=32), nullable=False),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("target_fields_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("condition_expr", sa.Text()),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("rule_set_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by_user_id", sa.BigInteger()),
        sa.Column("updated_by_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_std_cleansing_rule_dataset_source_status",
        table_name,
        ["dataset_key", "source_key", "status"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_std_cleansing_rule_rule_set_version",
        table_name,
        ["dataset_key", "source_key", "rule_set_version"],
        schema=OPS_SCHEMA,
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {OPS_SCHEMA}")
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _ensure_job_execution_columns(inspector)
    _create_dataset_layer_snapshot_history(inspector)
    _create_probe_rule(inspector)
    _create_probe_run_log(inspector)
    _create_resolution_release(inspector)
    _create_resolution_release_stage_status(inspector)
    _create_std_mapping_rule(inspector)
    _create_std_cleansing_rule(inspector)


def _drop_table_if_exists(inspector: sa.Inspector, table_name: str, *, schema: str, indexes: list[str]) -> None:
    if not _has_table(inspector, table_name, schema=schema):
        return
    existing_indexes = _index_names(inspector, table_name, schema=schema)
    for index_name in indexes:
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=table_name, schema=schema)
    op.drop_table(table_name, schema=schema)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _drop_table_if_exists(
        inspector,
        "std_cleansing_rule",
        schema=OPS_SCHEMA,
        indexes=[
            "idx_std_cleansing_rule_dataset_source_status",
            "idx_std_cleansing_rule_rule_set_version",
        ],
    )
    _drop_table_if_exists(
        inspector,
        "std_mapping_rule",
        schema=OPS_SCHEMA,
        indexes=[
            "idx_std_mapping_rule_dataset_source_status",
            "idx_std_mapping_rule_rule_set_version",
        ],
    )
    _drop_table_if_exists(
        inspector,
        "resolution_release_stage_status",
        schema=OPS_SCHEMA,
        indexes=[
            "idx_resolution_release_stage_status_release",
            "idx_resolution_release_stage_status_dataset_source",
        ],
    )
    _drop_table_if_exists(
        inspector,
        "resolution_release",
        schema=OPS_SCHEMA,
        indexes=[
            "idx_resolution_release_dataset_triggered_at",
            "idx_resolution_release_status_triggered_at",
        ],
    )
    _drop_table_if_exists(
        inspector,
        "probe_run_log",
        schema=OPS_SCHEMA,
        indexes=[
            "idx_probe_run_log_rule_probed_at",
            "idx_probe_run_log_status_probed_at",
        ],
    )
    _drop_table_if_exists(
        inspector,
        "probe_rule",
        schema=OPS_SCHEMA,
        indexes=[
            "idx_probe_rule_status_dataset",
            "idx_probe_rule_dataset_source",
        ],
    )
    _drop_table_if_exists(
        inspector,
        "dataset_layer_snapshot_history",
        schema=OPS_SCHEMA,
        indexes=[
            "idx_dataset_layer_snapshot_history_snapshot_date",
            "idx_dataset_layer_snapshot_history_dataset_stage",
            "idx_dataset_layer_snapshot_history_source_stage",
        ],
    )

    if _has_table(inspector, JOB_EXECUTION_TABLE, schema=OPS_SCHEMA):
        columns = _column_names(inspector, JOB_EXECUTION_TABLE, schema=OPS_SCHEMA)
        index_names = _index_names(inspector, JOB_EXECUTION_TABLE, schema=OPS_SCHEMA)
        if "idx_job_execution_source_stage_requested_at" in index_names:
            op.drop_index(
                "idx_job_execution_source_stage_requested_at",
                table_name=JOB_EXECUTION_TABLE,
                schema=OPS_SCHEMA,
            )
        if "idx_job_execution_dataset_requested_at" in index_names:
            op.drop_index(
                "idx_job_execution_dataset_requested_at",
                table_name=JOB_EXECUTION_TABLE,
                schema=OPS_SCHEMA,
            )
        if "run_scope" in columns:
            op.drop_column(JOB_EXECUTION_TABLE, "run_scope", schema=OPS_SCHEMA)
        if "policy_version" in columns:
            op.drop_column(JOB_EXECUTION_TABLE, "policy_version", schema=OPS_SCHEMA)
        if "stage" in columns:
            op.drop_column(JOB_EXECUTION_TABLE, "stage", schema=OPS_SCHEMA)
        if "source_key" in columns:
            op.drop_column(JOB_EXECUTION_TABLE, "source_key", schema=OPS_SCHEMA)
        if "dataset_key" in columns:
            op.drop_column(JOB_EXECUTION_TABLE, "dataset_key", schema=OPS_SCHEMA)
