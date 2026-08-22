"""drop ETF realtime monitor pool display order

Revision ID: 20260822_000142
Revises: 20260822_000141
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260822_000142"
down_revision = "20260822_000141"
branch_labels = None
depends_on = None

_SCHEMA = "ops"
_TABLE = "etf_realtime_monitor_pool"
_INDEX = "idx_etf_realtime_monitor_pool_enabled_order"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_index(_INDEX, table_name=_TABLE, schema=_SCHEMA)
    op.drop_column(_TABLE, "display_order", schema=_SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.add_column(
        _TABLE,
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        schema=_SCHEMA,
    )
    op.create_index(_INDEX, _TABLE, ["enabled", "display_order"], unique=False, schema=_SCHEMA)
