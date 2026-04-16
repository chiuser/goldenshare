"""add is_valid to indicator kdj/rsi tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000052"
down_revision = "20260416_000051"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, schema: str, table: str) -> bool:
    return schema in inspector.get_schema_names() and inspector.has_table(table, schema=schema)


def _ensure_is_valid_column(inspector: sa.Inspector, *, schema: str, table: str) -> None:
    if not _has_table(inspector, schema, table):
        return
    columns = {column["name"] for column in inspector.get_columns(table, schema=schema)}
    if "is_valid" in columns:
        return
    op.add_column(
        table,
        sa.Column("is_valid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema=schema,
    )
    op.alter_column(table, "is_valid", schema=schema, server_default=None)


def _drop_is_valid_column(inspector: sa.Inspector, *, schema: str, table: str) -> None:
    if not _has_table(inspector, schema, table):
        return
    columns = {column["name"] for column in inspector.get_columns(table, schema=schema)}
    if "is_valid" not in columns:
        return
    op.drop_column(table, "is_valid", schema=schema)


def _ensure_partial_index(
    inspector: sa.Inspector,
    *,
    schema: str,
    table: str,
    index_name: str,
    columns: list[str],
    where_clause: str,
) -> None:
    if not _has_table(inspector, schema, table):
        return
    index_names = {index["name"] for index in inspector.get_indexes(table, schema=schema)}
    if index_name in index_names:
        return
    op.create_index(
        index_name,
        table,
        columns,
        schema=schema,
        postgresql_where=sa.text(where_clause),
    )


def _drop_index(inspector: sa.Inspector, *, schema: str, table: str, index_name: str) -> None:
    if not _has_table(inspector, schema, table):
        return
    index_names = {index["name"] for index in inspector.get_indexes(table, schema=schema)}
    if index_name not in index_names:
        return
    op.drop_index(index_name, table_name=table, schema=schema)


def _upgrade_indicator(inspector: sa.Inspector, *, short_name: str) -> None:
    core_table = f"ind_{short_name}"
    std_table = f"indicator_{short_name}_std"
    core_valid_idx = f"idx_ind_{short_name}_valid_trade_date"
    std_valid_idx = f"idx_indicator_{short_name}_std_valid_trade_date"

    _ensure_is_valid_column(inspector, schema="core", table=core_table)
    _ensure_is_valid_column(inspector, schema="core_serving", table=core_table)
    _ensure_is_valid_column(inspector, schema="core_multi", table=std_table)

    _ensure_partial_index(
        inspector,
        schema="core",
        table=core_table,
        index_name=core_valid_idx,
        columns=["trade_date", "ts_code"],
        where_clause="is_valid = true",
    )
    _ensure_partial_index(
        inspector,
        schema="core_serving",
        table=core_table,
        index_name=core_valid_idx,
        columns=["trade_date", "ts_code"],
        where_clause="is_valid = true",
    )
    _ensure_partial_index(
        inspector,
        schema="core_multi",
        table=std_table,
        index_name=std_valid_idx,
        columns=["source_key", "trade_date"],
        where_clause="is_valid = true",
    )


def _downgrade_indicator(inspector: sa.Inspector, *, short_name: str) -> None:
    core_table = f"ind_{short_name}"
    std_table = f"indicator_{short_name}_std"
    core_valid_idx = f"idx_ind_{short_name}_valid_trade_date"
    std_valid_idx = f"idx_indicator_{short_name}_std_valid_trade_date"

    _drop_index(
        inspector,
        schema="core_multi",
        table=std_table,
        index_name=std_valid_idx,
    )
    _drop_index(
        inspector,
        schema="core_serving",
        table=core_table,
        index_name=core_valid_idx,
    )
    _drop_index(
        inspector,
        schema="core",
        table=core_table,
        index_name=core_valid_idx,
    )

    _drop_is_valid_column(inspector, schema="core_multi", table=std_table)
    _drop_is_valid_column(inspector, schema="core_serving", table=core_table)
    _drop_is_valid_column(inspector, schema="core", table=core_table)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _upgrade_indicator(inspector, short_name="kdj")
    _upgrade_indicator(inspector, short_name="rsi")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _downgrade_indicator(inspector, short_name="rsi")
    _downgrade_indicator(inspector, short_name="kdj")
