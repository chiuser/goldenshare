"""add date completeness exclusions

Revision ID: 20260503_000093
Revises: 20260503_000092
Create Date: 2026-05-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_000093"
down_revision = "20260503_000092"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"


def upgrade() -> None:
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("bucket_window_rule", sa.String(length=32), nullable=False, server_default=sa.text("'none'")),
        schema=OPS_SCHEMA,
    )
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("bucket_applicability_rule", sa.String(length=64), nullable=False, server_default=sa.text("'always'")),
        schema=OPS_SCHEMA,
    )
    op.add_column(
        "dataset_date_completeness_run",
        sa.Column("excluded_bucket_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema=OPS_SCHEMA,
    )
    op.create_check_constraint(
        "ck_dataset_date_completeness_excluded_non_negative",
        "dataset_date_completeness_run",
        "excluded_bucket_count >= 0",
        schema=OPS_SCHEMA,
    )

    op.create_table(
        "dataset_date_completeness_exclusion",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_key", sa.String(length=96), nullable=False),
        sa.Column("bucket_kind", sa.String(length=32), nullable=False),
        sa.Column("bucket_value", sa.Date(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], [f"{OPS_SCHEMA}.dataset_date_completeness_run.id"], ondelete="CASCADE"),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_date_completeness_exclusion_run",
        "dataset_date_completeness_exclusion",
        ["run_id", "id"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_date_completeness_exclusion_dataset_bucket",
        "dataset_date_completeness_exclusion",
        ["dataset_key", "bucket_value"],
        schema=OPS_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("idx_dataset_date_completeness_exclusion_dataset_bucket", table_name="dataset_date_completeness_exclusion", schema=OPS_SCHEMA)
    op.drop_index("idx_dataset_date_completeness_exclusion_run", table_name="dataset_date_completeness_exclusion", schema=OPS_SCHEMA)
    op.drop_table("dataset_date_completeness_exclusion", schema=OPS_SCHEMA)
    op.drop_constraint("ck_dataset_date_completeness_excluded_non_negative", "dataset_date_completeness_run", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "excluded_bucket_count", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "bucket_applicability_rule", schema=OPS_SCHEMA)
    op.drop_column("dataset_date_completeness_run", "bucket_window_rule", schema=OPS_SCHEMA)
