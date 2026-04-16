"""add is_valid to indicator macd tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000051"
down_revision = "20260416_000050"
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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _ensure_is_valid_column(inspector, schema="core", table="ind_macd")
    _ensure_is_valid_column(inspector, schema="core_serving", table="ind_macd")
    _ensure_is_valid_column(inspector, schema="core_multi", table="indicator_macd_std")

    _ensure_partial_index(
        inspector,
        schema="core",
        table="ind_macd",
        index_name="idx_ind_macd_valid_trade_date",
        columns=["trade_date", "ts_code"],
        where_clause="is_valid = true",
    )
    _ensure_partial_index(
        inspector,
        schema="core_serving",
        table="ind_macd",
        index_name="idx_ind_macd_valid_trade_date",
        columns=["trade_date", "ts_code"],
        where_clause="is_valid = true",
    )
    _ensure_partial_index(
        inspector,
        schema="core_multi",
        table="indicator_macd_std",
        index_name="idx_indicator_macd_std_valid_trade_date",
        columns=["source_key", "trade_date"],
        where_clause="is_valid = true",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _drop_index(
        inspector,
        schema="core_multi",
        table="indicator_macd_std",
        index_name="idx_indicator_macd_std_valid_trade_date",
    )
    _drop_index(
        inspector,
        schema="core_serving",
        table="ind_macd",
        index_name="idx_ind_macd_valid_trade_date",
    )
    _drop_index(
        inspector,
        schema="core",
        table="ind_macd",
        index_name="idx_ind_macd_valid_trade_date",
    )

    _drop_is_valid_column(inspector, schema="core_multi", table="indicator_macd_std")
    _drop_is_valid_column(inspector, schema="core_serving", table="ind_macd")
    _drop_is_valid_column(inspector, schema="core", table="ind_macd")
