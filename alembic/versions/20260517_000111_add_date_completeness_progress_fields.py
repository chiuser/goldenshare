"""add date completeness progress fields

Revision ID: 20260517_000111
Revises: 20260516_000110
Create Date: 2026-05-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260517_000111"
down_revision = "20260516_000110"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
RUN_TABLE = "dataset_date_completeness_run"
PROCESSED_CHECK = "ck_dataset_date_completeness_processed_non_negative"


def upgrade() -> None:
    op.add_column(
        RUN_TABLE,
        sa.Column("processed_bucket_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema=OPS_SCHEMA,
    )
    op.add_column(RUN_TABLE, sa.Column("current_bucket_value", sa.Date()), schema=OPS_SCHEMA)
    op.add_column(RUN_TABLE, sa.Column("current_bucket_label", sa.String(length=64)), schema=OPS_SCHEMA)
    op.add_column(RUN_TABLE, sa.Column("progress_message", sa.Text()), schema=OPS_SCHEMA)
    op.add_column(RUN_TABLE, sa.Column("heartbeat_at", sa.DateTime(timezone=True)), schema=OPS_SCHEMA)
    op.execute(
        sa.text(
            f'ALTER TABLE "{OPS_SCHEMA}"."{RUN_TABLE}" '
            f'ADD CONSTRAINT "{PROCESSED_CHECK}" CHECK (processed_bucket_count >= 0)'
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f'ALTER TABLE "{OPS_SCHEMA}"."{RUN_TABLE}" DROP CONSTRAINT IF EXISTS "{PROCESSED_CHECK}"'))
    op.drop_column(RUN_TABLE, "heartbeat_at", schema=OPS_SCHEMA)
    op.drop_column(RUN_TABLE, "progress_message", schema=OPS_SCHEMA)
    op.drop_column(RUN_TABLE, "current_bucket_label", schema=OPS_SCHEMA)
    op.drop_column(RUN_TABLE, "current_bucket_value", schema=OPS_SCHEMA)
    op.drop_column(RUN_TABLE, "processed_bucket_count", schema=OPS_SCHEMA)
