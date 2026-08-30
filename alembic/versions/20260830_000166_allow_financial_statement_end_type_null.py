"""allow nullable financial statement end_type

Revision ID: 20260830_000166
Revises: 20260830_000165
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260830_000166"
down_revision = "20260830_000165"
branch_labels = None
depends_on = None

_TABLESPACE = "gs_raw_cold_hdd"
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


def _assert_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("财务报表身份修正 migration 只允许在 PostgreSQL 执行")


def _assert_hdd_tablespace() -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"),
        {"name": _TABLESPACE},
    ).scalar()
    if not exists:
        raise RuntimeError(f"财务报表要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD")


def _assert_tables_exist() -> None:
    for table_name in _TABLES:
        exists = op.get_bind().execute(
            sa.text("SELECT to_regclass(:relation_name)"),
            {"relation_name": f"raw_tushare.{table_name}"},
        ).scalar()
        if not exists:
            raise RuntimeError(f"财务报表身份修正缺少 raw_tushare.{table_name}")


def _assert_reduced_identity_is_unique() -> None:
    identity_sql = ", ".join(_IDENTITY_FIELDS)
    for table_name in _TABLES:
        conflict_count = op.get_bind().execute(
            sa.text(
                f"SELECT count(*) FROM ("
                f"SELECT {identity_sql} FROM raw_tushare.{table_name} "
                f"GROUP BY {identity_sql} HAVING count(*) > 1"
                ") conflicts"
            )
        ).scalar()
        if conflict_count:
            raise RuntimeError(
                f"raw_tushare.{table_name} 存在 {conflict_count} 组七字段身份冲突，禁止修改主键"
            )


def _rebuild_primary_key(table_name: str) -> None:
    constraint_name = f"pk_raw_tushare_{table_name}"
    identity_sql = ", ".join(_IDENTITY_FIELDS)
    op.execute(
        f"ALTER TABLE raw_tushare.{table_name} DROP CONSTRAINT {constraint_name}"
    )
    op.execute(
        f"ALTER TABLE raw_tushare.{table_name} ALTER COLUMN end_type DROP NOT NULL"
    )
    op.execute(
        f"CREATE UNIQUE INDEX {constraint_name} ON raw_tushare.{table_name} "
        f"({identity_sql}) TABLESPACE {_TABLESPACE}"
    )
    op.execute(
        f"ALTER TABLE raw_tushare.{table_name} ADD CONSTRAINT {constraint_name} "
        f"PRIMARY KEY USING INDEX {constraint_name}"
    )


def upgrade() -> None:
    _assert_postgresql()
    _assert_hdd_tablespace()
    _assert_tables_exist()
    _assert_reduced_identity_is_unique()
    for table_name in _TABLES:
        _rebuild_primary_key(table_name)


def downgrade() -> None:
    raise RuntimeError("财务报表 end_type 可能已保存 NULL，不支持自动 downgrade。")
