"""add income dataset on cold HDD storage

Revision ID: 20260830_000163
Revises: 20260830_000162
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from src.foundation.datasets.financial_statement_contracts import FINANCIAL_STATEMENT_IDENTITY_FIELDS
from src.foundation.datasets.income_contracts import INCOME_DECIMAL_FIELDS, INCOME_SOURCE_FIELDS


revision = "20260830_000163"
down_revision = "20260830_000162"
branch_labels = None
depends_on = None

_TABLESPACE = "gs_raw_cold_hdd"
_DECIMAL_FIELDS = INCOME_DECIMAL_FIELDS
_VIEW_COLUMNS = (*INCOME_SOURCE_FIELDS, "source_content_hash", "api_name", "fetched_at")


def _assert_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("利润表 HDD migration 只允许在 PostgreSQL 执行")


def _assert_hdd_tablespace() -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"),
        {"name": _TABLESPACE},
    ).scalar()
    if not exists:
        raise RuntimeError(f"利润表要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD")


def upgrade() -> None:
    _assert_postgresql()
    _assert_hdd_tablespace()
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.create_table(
        "income",
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("ann_date", sa.Date(), nullable=False),
        sa.Column("f_ann_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("report_type", sa.String(length=8), nullable=False),
        sa.Column("comp_type", sa.String(length=8), nullable=False),
        sa.Column("end_type", sa.String(length=8), nullable=False),
        *(sa.Column(field_name, sa.Numeric(), nullable=True) for field_name in _DECIMAL_FIELDS),
        sa.Column("update_flag", sa.String(length=8), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'income_vip'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint(*FINANCIAL_STATEMENT_IDENTITY_FIELDS, name="pk_raw_tushare_income"),
        schema="raw_tushare",
        postgresql_tablespace=_TABLESPACE,
    )
    op.execute("ALTER INDEX raw_tushare.pk_raw_tushare_income SET TABLESPACE gs_raw_cold_hdd")
    op.execute(
        "CREATE INDEX idx_raw_tushare_income_ann_report_code "
        "ON raw_tushare.income (ann_date, report_type, ts_code) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_raw_tushare_income_serving_rank ON raw_tushare.income "
        "(report_type, ts_code, end_date, update_flag DESC, f_ann_date DESC, ann_date DESC) "
        "TABLESPACE gs_raw_cold_hdd"
    )
    selected_columns = ",\n            ".join(_VIEW_COLUMNS)
    op.execute(
        f"""
        CREATE VIEW core_serving.equity_income AS
        SELECT DISTINCT ON (ts_code, end_date)
            {selected_columns}
        FROM raw_tushare.income
        WHERE report_type = '1'
        ORDER BY ts_code, end_date,
            CASE update_flag WHEN '1' THEN 0 ELSE 1 END,
            f_ann_date DESC, ann_date DESC, fetched_at DESC,
            comp_type DESC, end_type DESC, source_content_hash DESC
        """
    )


def downgrade() -> None:
    raise RuntimeError("利润表保存业务事实，不支持自动 downgrade 删除数据。")
