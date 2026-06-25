"""add probe run log schedule id

Revision ID: 20260625_000119
Revises: 20260620_000118
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260625_000119"
down_revision = "20260620_000118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("probe_run_log", sa.Column("schedule_id", sa.BigInteger(), nullable=True), schema="ops")
    op.create_index(
        "idx_probe_run_log_schedule_probed_at",
        "probe_run_log",
        ["schedule_id", "probed_at"],
        schema="ops",
    )
    op.execute(
        """
        UPDATE ops.probe_run_log AS log
        SET schedule_id = task_run.schedule_id
        FROM ops.task_run AS task_run
        WHERE log.triggered_task_run_id = task_run.id
          AND task_run.schedule_id IS NOT NULL
          AND log.schedule_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE ops.probe_run_log AS log
        SET schedule_id = rule.schedule_id
        FROM ops.probe_rule AS rule
        WHERE log.probe_rule_id = rule.id
          AND rule.schedule_id IS NOT NULL
          AND log.schedule_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_probe_run_log_schedule_probed_at", table_name="probe_run_log", schema="ops")
    op.drop_column("probe_run_log", "schedule_id", schema="ops")
