"""add job execution structured progress fields"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260331_000018"
down_revision = "20260330_000017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_execution", sa.Column("progress_current", sa.BigInteger()), schema="ops")
    op.add_column("job_execution", sa.Column("progress_total", sa.BigInteger()), schema="ops")
    op.add_column("job_execution", sa.Column("progress_percent", sa.Integer()), schema="ops")
    op.add_column("job_execution", sa.Column("progress_message", sa.Text()), schema="ops")
    op.add_column("job_execution", sa.Column("last_progress_at", sa.DateTime(timezone=True)), schema="ops")


def downgrade() -> None:
    op.drop_column("job_execution", "last_progress_at", schema="ops")
    op.drop_column("job_execution", "progress_message", schema="ops")
    op.drop_column("job_execution", "progress_percent", schema="ops")
    op.drop_column("job_execution", "progress_total", schema="ops")
    op.drop_column("job_execution", "progress_current", schema="ops")
