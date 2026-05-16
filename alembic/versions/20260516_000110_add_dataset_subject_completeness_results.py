"""add dataset subject completeness result tables

Revision ID: 20260516_000110
Revises: 20260516_000109
Create Date: 2026-05-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260516_000110"
down_revision = "20260516_000109"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
RUN_TABLE = "dataset_date_completeness_run"


def _drop_run_constraint_if_exists(name: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{OPS_SCHEMA}"."{RUN_TABLE}" DROP CONSTRAINT IF EXISTS "{name}"'))


def _drop_run_result_status_constraint_variants(result_status: str, *names: str) -> None:
    """Drop old result-status check constraints regardless of SQLAlchemy naming-convention shape."""

    quoted_names = ", ".join(f"'{name}'" for name in names)
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE constraint_to_drop text;
            BEGIN
                FOR constraint_to_drop IN
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = '{OPS_SCHEMA}.{RUN_TABLE}'::regclass
                      AND contype = 'c'
                      AND (
                          conname IN ({quoted_names})
                          OR (
                              pg_get_constraintdef(oid) ILIKE '%result_status%'
                              AND pg_get_constraintdef(oid) ILIKE '%{result_status}%'
                              AND pg_get_constraintdef(oid) ILIKE '%missing_bucket_count%'
                          )
                      )
                LOOP
                    EXECUTE format(
                        'ALTER TABLE %I.%I DROP CONSTRAINT IF EXISTS %I',
                        '{OPS_SCHEMA}',
                        '{RUN_TABLE}',
                        constraint_to_drop
                    );
                END LOOP;
            END $$;
            """
        )
    )


def upgrade() -> None:
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("audit_scope", sa.String(length=32), nullable=False, server_default=sa.text("'date_bucket'")),
        schema=OPS_SCHEMA,
    )
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("subject_kind", sa.String(length=32)),
        schema=OPS_SCHEMA,
    )
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("expected_cell_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        schema=OPS_SCHEMA,
    )
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("actual_cell_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        schema=OPS_SCHEMA,
    )
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("missing_cell_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        schema=OPS_SCHEMA,
    )
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("affected_bucket_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema=OPS_SCHEMA,
    )
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("affected_subject_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema=OPS_SCHEMA,
    )
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("detail_truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=OPS_SCHEMA,
    )

    op.create_check_constraint(
        "ck_dataset_date_completeness_audit_scope_allowed",
        "dataset_date_completeness_run",
        "audit_scope IN ('date_bucket', 'date_subject_matrix')",
        schema=OPS_SCHEMA,
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_expected_cell_non_negative",
        "dataset_date_completeness_run",
        "expected_cell_count >= 0",
        schema=OPS_SCHEMA,
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_actual_cell_non_negative",
        "dataset_date_completeness_run",
        "actual_cell_count >= 0",
        schema=OPS_SCHEMA,
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_missing_cell_non_negative",
        "dataset_date_completeness_run",
        "missing_cell_count >= 0",
        schema=OPS_SCHEMA,
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_affected_bucket_non_negative",
        "dataset_date_completeness_run",
        "affected_bucket_count >= 0",
        schema=OPS_SCHEMA,
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_affected_subject_non_negative",
        "dataset_date_completeness_run",
        "affected_subject_count >= 0",
        schema=OPS_SCHEMA,
    )
    _drop_run_result_status_constraint_variants(
        "passed",
        "ck_dataset_date_completeness_passed_has_no_missing",
        "dataset_date_completeness_passed_has_no_missing",
        "ck_dataset_date_completeness_run_ck_dataset_date_comple_b204",
    )
    _drop_run_result_status_constraint_variants(
        "failed",
        "ck_dataset_date_completeness_failed_has_missing",
        "dataset_date_completeness_failed_has_missing",
        "ck_dataset_date_completeness_run_ck_dataset_date_comple_c359",
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_passed_has_no_missing",
        "dataset_date_completeness_run",
        "(result_status <> 'passed') OR (missing_bucket_count = 0 AND missing_cell_count = 0)",
        schema=OPS_SCHEMA,
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_failed_has_missing",
        "dataset_date_completeness_run",
        "(result_status <> 'failed') OR (missing_bucket_count > 0 OR missing_cell_count > 0)",
        schema=OPS_SCHEMA,
    )

    op.create_table(
        "dataset_subject_completeness_gap",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_key", sa.String(length=96), nullable=False),
        sa.Column("bucket_kind", sa.String(length=32), nullable=False),
        sa.Column("bucket_value", sa.Date(), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_key_fields_json", sa.JSON(), nullable=False),
        sa.Column("actual_key_fields_json", sa.JSON(), nullable=False),
        sa.Column("missing_cell_count", sa.BigInteger(), nullable=False),
        sa.Column("affected_subject_count", sa.Integer(), nullable=False),
        sa.Column("sample_subjects_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], [f"{OPS_SCHEMA}.dataset_date_completeness_run.id"], ondelete="CASCADE"),
        sa.CheckConstraint("missing_cell_count >= 0", name="ck_dataset_subject_completeness_gap_missing_non_negative"),
        sa.CheckConstraint("affected_subject_count >= 0", name="ck_dataset_subject_completeness_gap_subject_non_negative"),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_subject_completeness_gap_run",
        "dataset_subject_completeness_gap",
        ["run_id", "id"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_subject_completeness_gap_dataset_bucket",
        "dataset_subject_completeness_gap",
        ["dataset_key", "bucket_value"],
        schema=OPS_SCHEMA,
    )

    op.create_table(
        "dataset_subject_completeness_gap_detail",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("gap_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_key", sa.String(length=96), nullable=False),
        sa.Column("bucket_kind", sa.String(length=32), nullable=False),
        sa.Column("bucket_value", sa.Date(), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_key", sa.String(length=96), nullable=False),
        sa.Column("subject_name", sa.String(length=160)),
        sa.Column("subject_key_json", sa.JSON(), nullable=False),
        sa.Column("actual_key_json", sa.JSON(), nullable=False),
        sa.Column("lifecycle_start", sa.Date()),
        sa.Column("lifecycle_end", sa.Date()),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_message", sa.Text(), nullable=False),
        sa.Column("target_table", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], [f"{OPS_SCHEMA}.dataset_date_completeness_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["gap_id"], [f"{OPS_SCHEMA}.dataset_subject_completeness_gap.id"], ondelete="CASCADE"),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_subject_completeness_detail_run",
        "dataset_subject_completeness_gap_detail",
        ["run_id", "id"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_subject_completeness_detail_gap",
        "dataset_subject_completeness_gap_detail",
        ["gap_id", "id"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_subject_completeness_detail_dataset_bucket",
        "dataset_subject_completeness_gap_detail",
        ["dataset_key", "bucket_value"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_subject_completeness_detail_subject",
        "dataset_subject_completeness_gap_detail",
        ["dataset_key", "subject_kind", "subject_key"],
        schema=OPS_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("idx_dataset_subject_completeness_detail_subject", table_name="dataset_subject_completeness_gap_detail", schema=OPS_SCHEMA)
    op.drop_index("idx_dataset_subject_completeness_detail_dataset_bucket", table_name="dataset_subject_completeness_gap_detail", schema=OPS_SCHEMA)
    op.drop_index("idx_dataset_subject_completeness_detail_gap", table_name="dataset_subject_completeness_gap_detail", schema=OPS_SCHEMA)
    op.drop_index("idx_dataset_subject_completeness_detail_run", table_name="dataset_subject_completeness_gap_detail", schema=OPS_SCHEMA)
    op.drop_table("dataset_subject_completeness_gap_detail", schema=OPS_SCHEMA)

    op.drop_index("idx_dataset_subject_completeness_gap_dataset_bucket", table_name="dataset_subject_completeness_gap", schema=OPS_SCHEMA)
    op.drop_index("idx_dataset_subject_completeness_gap_run", table_name="dataset_subject_completeness_gap", schema=OPS_SCHEMA)
    op.drop_table("dataset_subject_completeness_gap", schema=OPS_SCHEMA)

    _drop_run_result_status_constraint_variants(
        "failed",
        "ck_dataset_date_completeness_failed_has_missing",
        "dataset_date_completeness_failed_has_missing",
        "ck_dataset_date_completeness_run_ck_dataset_date_comple_c359",
    )
    _drop_run_result_status_constraint_variants(
        "passed",
        "ck_dataset_date_completeness_passed_has_no_missing",
        "dataset_date_completeness_passed_has_no_missing",
        "ck_dataset_date_completeness_run_ck_dataset_date_comple_b204",
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_passed_has_no_missing",
        "dataset_date_completeness_run",
        "(result_status <> 'passed') OR (missing_bucket_count = 0)",
        schema=OPS_SCHEMA,
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_failed_has_missing",
        "dataset_date_completeness_run",
        "(result_status <> 'failed') OR (missing_bucket_count > 0)",
        schema=OPS_SCHEMA,
    )
    _drop_run_constraint_if_exists("ck_dataset_date_completeness_affected_subject_non_negative")
    _drop_run_constraint_if_exists("ck_dataset_date_completeness_affected_bucket_non_negative")
    _drop_run_constraint_if_exists("ck_dataset_date_completeness_missing_cell_non_negative")
    _drop_run_constraint_if_exists("ck_dataset_date_completeness_actual_cell_non_negative")
    _drop_run_constraint_if_exists("ck_dataset_date_completeness_expected_cell_non_negative")
    _drop_run_constraint_if_exists("ck_dataset_date_completeness_audit_scope_allowed")

    op.drop_column("dataset_date_completeness_run", "detail_truncated", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "affected_subject_count", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "affected_bucket_count", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "missing_cell_count", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "actual_cell_count", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "expected_cell_count", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "subject_kind", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "audit_scope", schema=OPS_SCHEMA)
