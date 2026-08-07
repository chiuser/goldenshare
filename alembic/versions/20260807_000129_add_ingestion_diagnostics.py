"""add bounded ingestion diagnostics to TaskRun

Revision ID: 20260807_000129
Revises: 20260807_000128
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_000129"
down_revision = "20260807_000128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table_name in ("task_run", "task_run_node"):
        op.add_column(
            table_name,
            sa.Column("rows_deduplicated", sa.BigInteger(), nullable=False, server_default="0"),
            schema="ops",
        )
        op.add_column(
            table_name,
            sa.Column(
                "ingestion_diagnostics_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            schema="ops",
        )


def downgrade() -> None:
    raise RuntimeError("TaskRun ingestion diagnostics are part of the audit contract and do not support automatic downgrade.")
