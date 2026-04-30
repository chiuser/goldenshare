"""add independent date completeness audit tables

Revision ID: 20260430_000084
Revises: 20260428_000083
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260430_000084"
down_revision = "20260428_000083"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"


def upgrade() -> None:
    op.create_table(
        "dataset_date_completeness_run",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("dataset_key", sa.String(length=96), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("target_table", sa.String(length=160), nullable=False),
        sa.Column("run_mode", sa.String(length=16), nullable=False),
        sa.Column("run_status", sa.String(length=24), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("result_status", sa.String(length=24)),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("date_axis", sa.String(length=32), nullable=False),
        sa.Column("bucket_rule", sa.String(length=32), nullable=False),
        sa.Column("window_mode", sa.String(length=32), nullable=False),
        sa.Column("input_shape", sa.String(length=32), nullable=False),
        sa.Column("observed_field", sa.String(length=64), nullable=False),
        sa.Column("expected_bucket_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("actual_bucket_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("missing_bucket_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("gap_range_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("current_stage", sa.String(length=64)),
        sa.Column("operator_message", sa.Text()),
        sa.Column("technical_message", sa.Text()),
        sa.Column("requested_by_user_id", sa.BigInteger()),
        sa.Column("schedule_id", sa.BigInteger()),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("run_mode IN ('manual', 'scheduled')", name="ck_dataset_date_completeness_run_mode_allowed"),
        sa.CheckConstraint(
            "run_status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name="ck_dataset_date_completeness_run_status_allowed",
        ),
        sa.CheckConstraint(
            "(result_status IS NULL) OR (result_status IN ('passed', 'failed', 'error'))",
            name="ck_dataset_date_completeness_result_status_allowed",
        ),
        sa.CheckConstraint("start_date <= end_date", name="ck_dataset_date_completeness_run_range_valid"),
        sa.CheckConstraint("expected_bucket_count >= 0", name="ck_dataset_date_completeness_expected_non_negative"),
        sa.CheckConstraint("actual_bucket_count >= 0", name="ck_dataset_date_completeness_actual_non_negative"),
        sa.CheckConstraint("missing_bucket_count >= 0", name="ck_dataset_date_completeness_missing_non_negative"),
        sa.CheckConstraint("gap_range_count >= 0", name="ck_dataset_date_completeness_gap_range_non_negative"),
        sa.CheckConstraint(
            "(result_status <> 'passed') OR (missing_bucket_count = 0)",
            name="ck_dataset_date_completeness_passed_has_no_missing",
        ),
        sa.CheckConstraint(
            "(result_status <> 'failed') OR (missing_bucket_count > 0)",
            name="ck_dataset_date_completeness_failed_has_missing",
        ),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_date_completeness_run_status_requested",
        "dataset_date_completeness_run",
        ["run_status", "requested_at"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_date_completeness_run_dataset_requested",
        "dataset_date_completeness_run",
        ["dataset_key", "requested_at"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_date_completeness_run_result_finished",
        "dataset_date_completeness_run",
        ["result_status", "finished_at"],
        schema=OPS_SCHEMA,
    )

    op.create_table(
        "dataset_date_completeness_gap",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_key", sa.String(length=96), nullable=False),
        sa.Column("bucket_kind", sa.String(length=32), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=False),
        sa.Column("range_end", sa.Date(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("sample_values_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], [f"{OPS_SCHEMA}.dataset_date_completeness_run.id"], ondelete="CASCADE"),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_date_completeness_gap_run",
        "dataset_date_completeness_gap",
        ["run_id", "id"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_date_completeness_gap_dataset_range",
        "dataset_date_completeness_gap",
        ["dataset_key", "range_start", "range_end"],
        schema=OPS_SCHEMA,
    )

    op.create_table(
        "dataset_date_completeness_schedule",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("dataset_key", sa.String(length=96), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("window_mode", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("lookback_count", sa.Integer()),
        sa.Column("lookback_unit", sa.String(length=32)),
        sa.Column("calendar_scope", sa.String(length=32), nullable=False, server_default=sa.text("'default_cn_market'")),
        sa.Column("calendar_exchange", sa.String(length=32)),
        sa.Column("cron_expr", sa.String(length=64), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'Asia/Shanghai'")),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_id", sa.BigInteger()),
        sa.Column("created_by_user_id", sa.BigInteger()),
        sa.Column("updated_by_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active', 'paused')", name="ck_dataset_date_completeness_schedule_status_allowed"),
        sa.CheckConstraint(
            "window_mode IN ('fixed_range', 'rolling')",
            name="ck_dataset_date_completeness_schedule_window_mode_allowed",
        ),
        sa.CheckConstraint(
            "(window_mode <> 'fixed_range') OR (start_date IS NOT NULL AND end_date IS NOT NULL AND start_date <= end_date)",
            name="ck_dataset_date_completeness_schedule_fixed_range_valid",
        ),
        sa.CheckConstraint(
            "(window_mode <> 'rolling') OR (lookback_count IS NOT NULL AND lookback_count > 0 AND lookback_unit IS NOT NULL)",
            name="ck_dataset_date_completeness_schedule_rolling_window_valid",
        ),
        sa.CheckConstraint(
            "(lookback_unit IS NULL) OR (lookback_unit IN ('calendar_day', 'open_day', 'month'))",
            name="ck_dataset_date_completeness_schedule_lookback_unit_allowed",
        ),
        sa.CheckConstraint(
            "calendar_scope IN ('default_cn_market', 'cn_a_share', 'hk_market', 'custom_exchange')",
            name="ck_dataset_date_completeness_schedule_calendar_scope_allowed",
        ),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_date_completeness_schedule_status_next",
        "dataset_date_completeness_schedule",
        ["status", "next_run_at"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_date_completeness_schedule_dataset",
        "dataset_date_completeness_schedule",
        ["dataset_key"],
        schema=OPS_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("dataset_date_completeness_schedule", schema=OPS_SCHEMA)
    op.drop_table("dataset_date_completeness_gap", schema=OPS_SCHEMA)
    op.drop_table("dataset_date_completeness_run", schema=OPS_SCHEMA)
