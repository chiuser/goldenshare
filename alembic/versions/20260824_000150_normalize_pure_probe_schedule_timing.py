"""normalize pure probe schedule timing

Revision ID: 20260824_000150
Revises: 20260824_000149
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260824_000150"
down_revision = "20260824_000149"
branch_labels = None
depends_on = None

_SCHEMA = "ops"
_TABLE = "schedule"
_CONSTRAINT = "ck_ops_schedule_pure_probe_has_no_schedule_timing"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        sa.text(
            """
            UPDATE ops.schedule
            SET schedule_type = 'cron',
                cron_expr = NULL,
                next_run_at = NULL
            WHERE trigger_mode = 'probe'
              AND (
                  schedule_type <> 'cron'
                  OR cron_expr IS NOT NULL
                  OR next_run_at IS NOT NULL
              )
            """
        )
    )
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "(trigger_mode <> 'probe') OR "
        "(schedule_type = 'cron' AND cron_expr IS NULL AND next_run_at IS NULL)",
        schema=_SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_constraint(_CONSTRAINT, _TABLE, schema=_SCHEMA, type_="check")
