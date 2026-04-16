"""add rsv to indicator kdj tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000053"
down_revision = "20260416_000052"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, schema: str, table: str) -> bool:
    return schema in inspector.get_schema_names() and inspector.has_table(table, schema=schema)


def _ensure_rsv_column(
    inspector: sa.Inspector,
    *,
    schema: str,
    table: str,
) -> None:
    if not _has_table(inspector, schema, table):
        return
    columns = {column["name"] for column in inspector.get_columns(table, schema=schema)}
    if "rsv" in columns:
        return
    op.add_column(table, sa.Column("rsv", sa.Numeric(20, 8), nullable=True), schema=schema)


def _drop_rsv_column(
    inspector: sa.Inspector,
    *,
    schema: str,
    table: str,
) -> None:
    if not _has_table(inspector, schema, table):
        return
    columns = {column["name"] for column in inspector.get_columns(table, schema=schema)}
    if "rsv" not in columns:
        return
    op.drop_column(table, "rsv", schema=schema)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _ensure_rsv_column(inspector, schema="core", table="ind_kdj")
    _ensure_rsv_column(inspector, schema="core_serving", table="ind_kdj")
    _ensure_rsv_column(inspector, schema="core_multi", table="indicator_kdj_std")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _drop_rsv_column(inspector, schema="core_multi", table="indicator_kdj_std")
    _drop_rsv_column(inspector, schema="core_serving", table="ind_kdj")
    _drop_rsv_column(inspector, schema="core", table="ind_kdj")
