"""replace ops execution observability with task_run tables

Revision ID: 20260426_000074
Revises: 20260426_000073
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_000074"
down_revision = "20260426_000073"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"

OLD_DROP_TABLES = (
    "job_execution_event",
    "job_execution_unit",
    "job_execution_step",
    "sync_run_log",
    "job_execution",
    "legacy_spec_backup_20260426_040441_config_revision",
    "legacy_spec_backup_20260426_040441_dataset_status_snapshot",
    "legacy_spec_backup_20260426_040441_job_execution_event",
    "legacy_spec_backup_20260426_040441_job_execution_step",
    "legacy_spec_backup_20260426_040441_job_execution_unit",
    "legacy_spec_backup_20260426_040441_job_execution",
    "legacy_spec_backup_20260426_040441_job_schedule",
)

RESET_TABLES = (
    "sync_job_state",
    "dataset_status_snapshot",
    "dataset_layer_snapshot_current",
    "dataset_layer_snapshot_history",
    "probe_run_log",
    "config_revision",
    "job_schedule",
    "dataset_pipeline_mode",
    "std_cleansing_rule",
    "std_mapping_rule",
    "index_series_active",
    "probe_rule",
    "resolution_release_stage_status",
    "resolution_release",
)


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name, schema=OPS_SCHEMA)


def _drop_if_exists(inspector: sa.Inspector, table_name: str) -> None:
    if _has_table(inspector, table_name):
        op.drop_table(table_name, schema=OPS_SCHEMA)


def _clear_if_exists(inspector: sa.Inspector, table_name: str) -> None:
    if not _has_table(inspector, table_name):
        return
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(f'TRUNCATE TABLE "{OPS_SCHEMA}"."{table_name}" RESTART IDENTITY CASCADE'))
    else:
        op.execute(sa.text(f'DELETE FROM "{OPS_SCHEMA}"."{table_name}"'))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "task_run"):
        op.create_table(
            "task_run",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("task_type", sa.String(length=32), nullable=False),
            sa.Column("resource_key", sa.String(length=96)),
            sa.Column("action", sa.String(length=32), nullable=False, server_default=sa.text("'maintain'")),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("trigger_source", sa.String(length=32), nullable=False),
            sa.Column("requested_by_user_id", sa.BigInteger()),
            sa.Column("schedule_id", sa.BigInteger()),
            sa.Column("status", sa.String(length=24), nullable=False, server_default=sa.text("'queued'")),
            sa.Column("status_reason_code", sa.String(length=64)),
            sa.Column("time_input_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("filters_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("request_payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("plan_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("unit_total", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("unit_done", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("unit_failed", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("progress_percent", sa.Integer()),
            sa.Column("current_node_id", sa.BigInteger()),
            sa.Column("current_context_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("rows_fetched", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("rows_saved", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("rows_rejected", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("primary_issue_id", sa.BigInteger()),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("queued_at", sa.DateTime(timezone=True)),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("ended_at", sa.DateTime(timezone=True)),
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
            sa.Column("canceled_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            schema=OPS_SCHEMA,
        )
        op.create_index("idx_task_run_status_requested_at", "task_run", ["status", "requested_at"], schema=OPS_SCHEMA)
        op.create_index("idx_task_run_resource_requested_at", "task_run", ["resource_key", "requested_at"], schema=OPS_SCHEMA)
        op.create_index("idx_task_run_schedule_requested_at", "task_run", ["schedule_id", "requested_at"], schema=OPS_SCHEMA)

    if not _has_table(inspector, "task_run_node"):
        op.create_table(
            "task_run_node",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("task_run_id", sa.BigInteger(), nullable=False),
            sa.Column("parent_node_id", sa.BigInteger()),
            sa.Column("node_key", sa.String(length=160), nullable=False),
            sa.Column("node_type", sa.String(length=32), nullable=False),
            sa.Column("sequence_no", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("resource_key", sa.String(length=96)),
            sa.Column("status", sa.String(length=24), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("time_input_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("context_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("rows_fetched", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("rows_saved", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("rows_rejected", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("issue_id", sa.BigInteger()),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("ended_at", sa.DateTime(timezone=True)),
            sa.Column("duration_ms", sa.Integer()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("task_run_id", "node_key", name="uk_task_run_node_run_node_key"),
            sa.ForeignKeyConstraint(["task_run_id"], [f"{OPS_SCHEMA}.task_run.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["parent_node_id"], [f"{OPS_SCHEMA}.task_run_node.id"], ondelete="CASCADE"),
            schema=OPS_SCHEMA,
        )
        op.create_index("idx_task_run_node_run_sequence", "task_run_node", ["task_run_id", "sequence_no", "id"], schema=OPS_SCHEMA)
        op.create_index("idx_task_run_node_run_status", "task_run_node", ["task_run_id", "status"], schema=OPS_SCHEMA)

    if not _has_table(inspector, "task_run_issue"):
        op.create_table(
            "task_run_issue",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("task_run_id", sa.BigInteger(), nullable=False),
            sa.Column("node_id", sa.BigInteger()),
            sa.Column("severity", sa.String(length=16), nullable=False),
            sa.Column("code", sa.String(length=96), nullable=False),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("operator_message", sa.Text()),
            sa.Column("suggested_action", sa.Text()),
            sa.Column("technical_message", sa.Text()),
            sa.Column("technical_payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("source_phase", sa.String(length=32)),
            sa.Column("fingerprint", sa.String(length=128), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("task_run_id", "fingerprint", name="uk_task_run_issue_run_fingerprint"),
            sa.ForeignKeyConstraint(["task_run_id"], [f"{OPS_SCHEMA}.task_run.id"], ondelete="CASCADE"),
            schema=OPS_SCHEMA,
        )
        op.create_index("idx_task_run_issue_run_occurred", "task_run_issue", ["task_run_id", "occurred_at"], schema=OPS_SCHEMA)
        op.create_index("idx_task_run_issue_code_occurred", "task_run_issue", ["code", "occurred_at"], schema=OPS_SCHEMA)

    inspector = sa.inspect(bind)
    for table_name in OLD_DROP_TABLES:
        _drop_if_exists(inspector, table_name)
    inspector = sa.inspect(bind)
    for table_name in RESET_TABLES:
        _clear_if_exists(inspector, table_name)


def downgrade() -> None:
    op.drop_table("task_run_issue", schema=OPS_SCHEMA)
    op.drop_table("task_run_node", schema=OPS_SCHEMA)
    op.drop_table("task_run", schema=OPS_SCHEMA)
