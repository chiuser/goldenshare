"""enforce canonical financial statement end_type

Revision ID: 20260830_000167
Revises: 20260830_000166
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260830_000167"
down_revision = "20260830_000166"
branch_labels = None
depends_on = None

_TABLES = ("income", "balancesheet", "cashflow")
_IDENTITY_FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "update_flag",
)
_END_TYPE_BY_MONTH_DAY = {
    "0331": "1",
    "0630": "2",
    "0930": "3",
    "1231": "4",
}
_EXPECTED_END_TYPE_SQL = (
    "CASE to_char(end_date, 'MMDD') "
    "WHEN '0331' THEN '1' "
    "WHEN '0630' THEN '2' "
    "WHEN '0930' THEN '3' "
    "WHEN '1231' THEN '4' "
    "END"
)


def _assert_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("财务报表 end_type 规范化 migration 只允许在 PostgreSQL 执行")


def _assert_tables_exist() -> None:
    for table_name in _TABLES:
        exists = op.get_bind().execute(
            sa.text("SELECT to_regclass(:relation_name)"),
            {"relation_name": f"raw_tushare.{table_name}"},
        ).scalar()
        if not exists:
            raise RuntimeError(f"财务报表 end_type 规范化缺少 raw_tushare.{table_name}")


def _assert_primary_keys() -> None:
    expected = ",".join(_IDENTITY_FIELDS)
    for table_name in _TABLES:
        actual = op.get_bind().execute(
            sa.text(
                "SELECT string_agg(kcu.column_name, ',' ORDER BY kcu.ordinal_position) "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON kcu.constraint_schema = tc.constraint_schema "
                "AND kcu.constraint_name = tc.constraint_name "
                "WHERE tc.constraint_schema = 'raw_tushare' "
                "AND tc.table_name = :table_name "
                "AND tc.constraint_type = 'PRIMARY KEY'"
            ),
            {"table_name": table_name},
        ).scalar()
        if actual != expected:
            raise RuntimeError(
                f"raw_tushare.{table_name} 主键不是 20260830_000166 定义的七字段身份"
            )


def _count(table_name: str, predicate_sql: str) -> int:
    value = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM raw_tushare.{table_name} WHERE {predicate_sql}")
    ).scalar()
    return int(value or 0)


def _assert_existing_values_are_canonical() -> None:
    for table_name in _TABLES:
        invalid_period_count = _count(
            table_name,
            "to_char(end_date, 'MMDD') NOT IN ('0331', '0630', '0930', '1231')",
        )
        if invalid_period_count:
            raise RuntimeError(
                f"raw_tushare.{table_name} 存在 {invalid_period_count} 行非季度末 end_date，禁止自动修正"
            )

        invalid_end_type_count = _count(
            table_name,
            "end_type IS NOT NULL AND end_type NOT IN ('1', '2', '3', '4')",
        )
        if invalid_end_type_count:
            raise RuntimeError(
                f"raw_tushare.{table_name} 存在 {invalid_end_type_count} 行非法 end_type，禁止自动修正"
            )

        mismatched_end_type_count = _count(
            table_name,
            f"end_type IS NOT NULL AND end_type <> ({_EXPECTED_END_TYPE_SQL})",
        )
        if mismatched_end_type_count:
            raise RuntimeError(
                f"raw_tushare.{table_name} 存在 {mismatched_end_type_count} 行 end_type 与 end_date 矛盾，禁止自动覆盖"
            )


def _backfill_null_end_types() -> None:
    for table_name in _TABLES:
        op.execute(
            f"UPDATE raw_tushare.{table_name} "
            f"SET end_type = {_EXPECTED_END_TYPE_SQL} "
            "WHERE end_type IS NULL"
        )


def _assert_no_null_end_types() -> None:
    for table_name in _TABLES:
        null_count = _count(table_name, "end_type IS NULL")
        if null_count:
            raise RuntimeError(
                f"raw_tushare.{table_name} 规范化后仍有 {null_count} 行 end_type 为空"
            )


def _enforce_not_null() -> None:
    for table_name in _TABLES:
        op.execute(
            f"ALTER TABLE raw_tushare.{table_name} ALTER COLUMN end_type SET NOT NULL"
        )


def upgrade() -> None:
    _assert_postgresql()
    _assert_tables_exist()
    _assert_primary_keys()
    _assert_existing_values_are_canonical()
    _backfill_null_end_types()
    _assert_no_null_end_types()
    _assert_existing_values_are_canonical()
    _enforce_not_null()


def downgrade() -> None:
    raise RuntimeError("财务报表 end_type 规范化约束不支持自动 downgrade。")
