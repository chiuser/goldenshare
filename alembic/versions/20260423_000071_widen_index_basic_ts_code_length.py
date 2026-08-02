"""widen index_basic ts_code length

Revision ID: 20260423_000071
Revises: 20260423_000070
Create Date: 2026-04-23 14:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260423_000071"
down_revision = "20260423_000070"
branch_labels = None
depends_on = None

TARGETS = (
    ("raw_tushare", "index_basic"),
    ("core_serving", "index_basic"),
)


def _existing_targets(inspector: sa.Inspector) -> tuple[tuple[str, str], ...]:
    """Keep widening legacy targets without breaking a clean baseline install."""

    return tuple(
        (schema_name, table_name)
        for schema_name, table_name in TARGETS
        if inspector.has_table(table_name, schema=schema_name)
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for schema_name, table_name in _existing_targets(inspector):
        op.alter_column(
            table_name,
            "ts_code",
            schema=schema_name,
            existing_type=sa.String(length=16),
            type_=sa.String(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for schema_name, table_name in reversed(_existing_targets(inspector)):
        op.alter_column(
            table_name,
            "ts_code",
            schema=schema_name,
            existing_type=sa.String(length=32),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
