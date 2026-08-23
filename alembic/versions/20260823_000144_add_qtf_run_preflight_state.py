"""add QTF input preflight and experiment run state

Revision ID: 20260823_000144
Revises: 20260822_000143
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260823_000144"
down_revision = "20260822_000143"
branch_labels = None
depends_on = None

_SCHEMA = "qtf"


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.create_table(
        "input_preflight",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("preflight_key", sa.String(length=96), nullable=False),
        sa.Column("request_key", sa.String(length=96), nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column("draft_hash", sa.String(length=64), nullable=True),
        sa.Column("phase", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("source_kind", sa.String(length=16), server_default="PROD", nullable=False),
        sa.Column("source_contract_hash", sa.String(length=64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_start_date", sa.Date(), nullable=False),
        sa.Column("requested_end_date", sa.Date(), nullable=False),
        sa.Column("effective_start_date", sa.Date(), nullable=True),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("dataset_evidence_json", sa.JSON(), nullable=False),
        sa.Column("universe_count", sa.Integer(), nullable=False),
        sa.Column("group_count", sa.Integer(), nullable=False),
        sa.Column("valid_group_day_count", sa.BigInteger(), nullable=False),
        sa.Column("excluded_group_day_count", sa.BigInteger(), nullable=False),
        sa.Column("plan_estimate_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("phase in ('DRAFT_PREVIEW', 'RUN_PREFLIGHT')", name="ck_qtf_input_preflight_phase_valid"),
        sa.CheckConstraint("status in ('PASS', 'BLOCKED')", name="ck_qtf_input_preflight_status_valid"),
        sa.CheckConstraint("source_kind = 'PROD'", name="ck_qtf_input_preflight_source_prod"),
        sa.CheckConstraint(
            "length(source_contract_hash) = 64 and source_contract_hash = lower(source_contract_hash)",
            name="ck_qtf_input_preflight_source_hash_shape",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64 and content_hash = lower(content_hash)",
            name="ck_qtf_input_preflight_content_hash_shape",
        ),
        sa.CheckConstraint("requested_start_date <= requested_end_date", name="ck_qtf_input_preflight_requested_range_valid"),
        sa.CheckConstraint(
            "(effective_start_date is null and effective_end_date is null) or "
            "(effective_start_date is not null and effective_end_date is not null "
            "and effective_start_date <= effective_end_date)",
            name="ck_qtf_input_preflight_effective_range_valid",
        ),
        sa.CheckConstraint(
            "universe_count >= 0 and group_count >= 0 and valid_group_day_count >= 0 "
            "and excluded_group_day_count >= 0",
            name="ck_qtf_input_preflight_counts_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["qtf.experiment_revision.id"],
            name="fk_qtf_input_preflight_revision_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qtf_input_preflight"),
        sa.UniqueConstraint("preflight_key", name="uq_qtf_input_preflight_preflight_key"),
        sa.UniqueConstraint("request_key", name="uq_qtf_input_preflight_request_key"),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_input_preflight_revision_phase",
        "input_preflight",
        ["revision_id", "phase"],
        schema=_SCHEMA,
    )

    op.create_table(
        "input_preflight_issue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("preflight_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=96), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("dataset_key", sa.String(length=96), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("field_name", sa.String(length=96), nullable=True),
        sa.Column("object_key", sa.String(length=160), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("remediation_owner", sa.String(length=16), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("remediation_owner in ('PROD', 'LAKE')", name="ck_qtf_input_preflight_issue_owner_valid"),
        sa.CheckConstraint("severity in ('ERROR', 'WARN')", name="ck_qtf_input_preflight_issue_severity_valid"),
        sa.ForeignKeyConstraint(
            ["preflight_id"],
            ["qtf.input_preflight.id"],
            name="fk_qtf_input_preflight_issue_preflight_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qtf_input_preflight_issue"),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_input_preflight_issue_preflight",
        "input_preflight_issue",
        ["preflight_id", "id"],
        schema=_SCHEMA,
    )

    op.create_table(
        "experiment_run",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_key", sa.String(length=96), nullable=False),
        sa.Column("request_key", sa.String(length=96), nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column("input_preflight_id", sa.BigInteger(), nullable=True),
        sa.Column("task_run_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="PLANNED", nullable=False),
        sa.Column("validation_status", sa.String(length=24), server_default="PENDING", nullable=False),
        sa.Column("code_commit", sa.String(length=40), nullable=True),
        sa.Column("runtime_fingerprint_json", sa.JSON(), nullable=False),
        sa.Column("formula_version", sa.String(length=96), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=True),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("completed_parameter_set_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status in ('PLANNED', 'QUEUED', 'EXECUTING', 'COMPLETED', 'FAILED', 'CANCELED', 'BLOCKED')",
            name="ck_qtf_experiment_run_status_valid",
        ),
        sa.CheckConstraint(
            "validation_status in ('PENDING', 'VALID', 'INVALID', 'INSUFFICIENT', 'BLOCKED')",
            name="ck_qtf_experiment_run_validation_status_valid",
        ),
        sa.CheckConstraint(
            "code_commit is null or (length(code_commit) = 40 and code_commit = lower(code_commit))",
            name="ck_qtf_experiment_run_commit_shape",
        ),
        sa.CheckConstraint(
            "source_content_hash is null or (length(source_content_hash) = 64 and source_content_hash = lower(source_content_hash))",
            name="ck_qtf_experiment_run_source_hash_shape",
        ),
        sa.CheckConstraint(
            "result_hash is null or (length(result_hash) = 64 and result_hash = lower(result_hash))",
            name="ck_qtf_experiment_run_result_hash_shape",
        ),
        sa.CheckConstraint("completed_parameter_set_count >= 0", name="ck_qtf_experiment_run_completed_count_non_negative"),
        sa.ForeignKeyConstraint(
            ["input_preflight_id"],
            ["qtf.input_preflight.id"],
            name="fk_qtf_experiment_run_input_preflight_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["qtf.experiment_revision.id"],
            name="fk_qtf_experiment_run_revision_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qtf_experiment_run"),
        sa.UniqueConstraint("run_key", name="uq_qtf_experiment_run_run_key"),
        sa.UniqueConstraint("request_key", name="uq_qtf_experiment_run_request_key"),
        sa.UniqueConstraint("task_run_id", name="uq_qtf_experiment_run_task_run_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_experiment_run_revision_created",
        "experiment_run",
        ["revision_id", "created_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_experiment_run_status_created",
        "experiment_run",
        ["status", "created_at"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_index("idx_qtf_experiment_run_status_created", table_name="experiment_run", schema=_SCHEMA)
    op.drop_index("idx_qtf_experiment_run_revision_created", table_name="experiment_run", schema=_SCHEMA)
    op.drop_table("experiment_run", schema=_SCHEMA)
    op.drop_index("idx_qtf_input_preflight_issue_preflight", table_name="input_preflight_issue", schema=_SCHEMA)
    op.drop_table("input_preflight_issue", schema=_SCHEMA)
    op.drop_index("idx_qtf_input_preflight_revision_phase", table_name="input_preflight", schema=_SCHEMA)
    op.drop_table("input_preflight", schema=_SCHEMA)
