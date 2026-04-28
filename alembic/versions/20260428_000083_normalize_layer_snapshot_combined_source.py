"""normalize layer snapshot combined source

Revision ID: 20260428_000083
Revises: 20260427_000082
Create Date: 2026-04-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_000083"
down_revision = "20260427_000082"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name, schema=OPS_SCHEMA)


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name, schema=OPS_SCHEMA)}


def _normalize_source_values(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "source_key" not in _column_names(inspector, table_name):
        return
    op.execute(
        sa.text(
            f"""
            UPDATE {OPS_SCHEMA}.{table_name}
            SET source_key = 'combined'
            WHERE source_key = '__all__'
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _normalize_source_values("dataset_layer_snapshot_current")
    _normalize_source_values("dataset_layer_snapshot_history")
    if _has_table(inspector, "dataset_layer_snapshot_current"):
        op.alter_column(
            "dataset_layer_snapshot_current",
            "source_key",
            schema=OPS_SCHEMA,
            server_default=sa.text("'combined'"),
            existing_type=sa.String(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "dataset_layer_snapshot_current"):
        op.alter_column(
            "dataset_layer_snapshot_current",
            "source_key",
            schema=OPS_SCHEMA,
            server_default=None,
            existing_type=sa.String(length=32),
            existing_nullable=False,
        )
