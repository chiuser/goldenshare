"""add dataset status snapshot

Revision ID: 20260401_000020
Revises: 20260401_000019
Create Date: 2026-04-01 19:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260401_000020"
down_revision = "20260401_000019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_status_snapshot",
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("resource_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("domain_key", sa.String(length=64), nullable=False),
        sa.Column("domain_display_name", sa.String(length=64), nullable=False),
        sa.Column("job_name", sa.String(length=64), nullable=False),
        sa.Column("target_table", sa.String(length=128), nullable=False),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("state_business_date", sa.Date(), nullable=True),
        sa.Column("earliest_business_date", sa.Date(), nullable=True),
        sa.Column("observed_business_date", sa.Date(), nullable=True),
        sa.Column("latest_business_date", sa.Date(), nullable=True),
        sa.Column("business_date_source", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("freshness_note", sa.Text(), nullable=True),
        sa.Column("latest_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_date", sa.Date(), nullable=True),
        sa.Column("expected_business_date", sa.Date(), nullable=True),
        sa.Column("lag_days", sa.Integer(), nullable=True),
        sa.Column("freshness_status", sa.String(length=16), nullable=False),
        sa.Column("recent_failure_message", sa.Text(), nullable=True),
        sa.Column("recent_failure_summary", sa.String(length=255), nullable=True),
        sa.Column("recent_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primary_execution_spec_key", sa.String(length=128), nullable=True),
        sa.Column("full_sync_done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("last_calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("dataset_key", name=op.f("pk_dataset_status_snapshot")),
        schema="ops",
    )
    op.create_index(op.f("ix_ops_dataset_status_snapshot_domain_key"), "dataset_status_snapshot", ["domain_key"], unique=False, schema="ops")
    op.create_index(op.f("ix_ops_dataset_status_snapshot_freshness_status"), "dataset_status_snapshot", ["freshness_status"], unique=False, schema="ops")
    op.create_index(op.f("ix_ops_dataset_status_snapshot_job_name"), "dataset_status_snapshot", ["job_name"], unique=False, schema="ops")


def downgrade() -> None:
    op.drop_index(op.f("ix_ops_dataset_status_snapshot_job_name"), table_name="dataset_status_snapshot", schema="ops")
    op.drop_index(op.f("ix_ops_dataset_status_snapshot_freshness_status"), table_name="dataset_status_snapshot", schema="ops")
    op.drop_index(op.f("ix_ops_dataset_status_snapshot_domain_key"), table_name="dataset_status_snapshot", schema="ops")
    op.drop_table("dataset_status_snapshot", schema="ops")
