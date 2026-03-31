"""add operations control plane foundation"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260330_000017"
down_revision = "20260329_000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    op.create_table(
        "job_schedule",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("spec_type", sa.String(length=32), nullable=False),
        sa.Column("spec_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("schedule_type", sa.String(length=32), nullable=False),
        sa.Column("cron_expr", sa.String(length=64)),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'Asia/Shanghai'")),
        sa.Column("calendar_policy", sa.String(length=32)),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("retry_policy_json", sa.JSON(), nullable=False),
        sa.Column("concurrency_policy_json", sa.JSON(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.BigInteger()),
        sa.Column("updated_by_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="ops",
    )
    op.create_index("idx_job_schedule_status_next_run_at", "job_schedule", ["status", "next_run_at"], schema="ops")
    op.create_index("idx_job_schedule_spec_type_spec_key", "job_schedule", ["spec_type", "spec_key"], schema="ops")

    op.create_table(
        "job_execution",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("schedule_id", sa.BigInteger()),
        sa.Column("spec_type", sa.String(length=32), nullable=False),
        sa.Column("spec_key", sa.String(length=128), nullable=False),
        sa.Column("trigger_source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("requested_by_user_id", sa.BigInteger()),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("summary_message", sa.Text()),
        sa.Column("rows_fetched", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_written", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("canceled_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="ops",
    )
    op.create_index("idx_job_execution_status_requested_at", "job_execution", ["status", "requested_at"], schema="ops")
    op.create_index(
        "idx_job_execution_schedule_id_requested_at",
        "job_execution",
        ["schedule_id", "requested_at"],
        schema="ops",
    )
    op.create_index(
        "idx_job_execution_spec_requested_at",
        "job_execution",
        ["spec_type", "spec_key", "requested_at"],
        schema="ops",
    )

    op.create_table(
        "job_execution_step",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("step_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("unit_kind", sa.String(length=32)),
        sa.Column("unit_value", sa.String(length=128)),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("rows_fetched", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_written", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="ops",
    )
    op.create_index(
        "idx_job_execution_step_execution_sequence",
        "job_execution_step",
        ["execution_id", "sequence_no"],
        schema="ops",
    )
    op.create_index(
        "idx_job_execution_step_execution_status",
        "job_execution_step",
        ["execution_id", "status"],
        schema="ops",
    )

    op.create_table(
        "job_execution_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("step_id", sa.BigInteger()),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default=sa.text("'INFO'")),
        sa.Column("message", sa.Text()),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        schema="ops",
    )
    op.create_index(
        "idx_job_execution_event_execution_occurred_at",
        "job_execution_event",
        ["execution_id", "occurred_at"],
        schema="ops",
    )
    op.create_index(
        "idx_job_execution_event_step_occurred_at",
        "job_execution_event",
        ["step_id", "occurred_at"],
        schema="ops",
    )

    op.create_table(
        "config_revision",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_json", sa.JSON()),
        sa.Column("after_json", sa.JSON()),
        sa.Column("changed_by_user_id", sa.BigInteger()),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        schema="ops",
    )
    op.create_index(
        "idx_config_revision_object_changed_at",
        "config_revision",
        ["object_type", "object_id", "changed_at"],
        schema="ops",
    )

    op.add_column("sync_run_log", sa.Column("execution_id", sa.BigInteger()), schema="ops")
    op.create_index("idx_sync_run_log_execution_id", "sync_run_log", ["execution_id"], schema="ops")


def downgrade() -> None:
    op.drop_index("idx_sync_run_log_execution_id", table_name="sync_run_log", schema="ops")
    op.drop_column("sync_run_log", "execution_id", schema="ops")

    op.drop_index("idx_config_revision_object_changed_at", table_name="config_revision", schema="ops")
    op.drop_table("config_revision", schema="ops")

    op.drop_index("idx_job_execution_event_step_occurred_at", table_name="job_execution_event", schema="ops")
    op.drop_index("idx_job_execution_event_execution_occurred_at", table_name="job_execution_event", schema="ops")
    op.drop_table("job_execution_event", schema="ops")

    op.drop_index("idx_job_execution_step_execution_status", table_name="job_execution_step", schema="ops")
    op.drop_index("idx_job_execution_step_execution_sequence", table_name="job_execution_step", schema="ops")
    op.drop_table("job_execution_step", schema="ops")

    op.drop_index("idx_job_execution_spec_requested_at", table_name="job_execution", schema="ops")
    op.drop_index("idx_job_execution_schedule_id_requested_at", table_name="job_execution", schema="ops")
    op.drop_index("idx_job_execution_status_requested_at", table_name="job_execution", schema="ops")
    op.drop_table("job_execution", schema="ops")

    op.drop_index("idx_job_schedule_spec_type_spec_key", table_name="job_schedule", schema="ops")
    op.drop_index("idx_job_schedule_status_next_run_at", table_name="job_schedule", schema="ops")
    op.drop_table("job_schedule", schema="ops")
