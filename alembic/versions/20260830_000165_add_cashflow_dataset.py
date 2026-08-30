"""add cashflow dataset on cold HDD storage

Revision ID: 20260830_000165
Revises: 20260830_000164
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from src.foundation.datasets.cashflow_contracts import CASHFLOW_DECIMAL_FIELDS, CASHFLOW_SOURCE_FIELDS


revision = "20260830_000165"
down_revision = "20260830_000164"
branch_labels = None
depends_on = None

_TABLESPACE = "gs_raw_cold_hdd"
_DECIMAL_FIELDS = CASHFLOW_DECIMAL_FIELDS
_VIEW_COLUMNS = (*CASHFLOW_SOURCE_FIELDS, "source_content_hash", "api_name", "fetched_at")
_ORIGINAL_IDENTITY_FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "update_flag",
)


def _assert_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("现金流量表 HDD migration 只允许在 PostgreSQL 执行")


def _assert_hdd_tablespace() -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"),
        {"name": _TABLESPACE},
    ).scalar()
    if not exists:
        raise RuntimeError(f"现金流量表要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD")


def upgrade() -> None:
    _assert_postgresql()
    _assert_hdd_tablespace()
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.create_table(
        "cashflow",
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("ann_date", sa.Date(), nullable=False),
        sa.Column("f_ann_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("comp_type", sa.String(length=8), nullable=False),
        sa.Column("report_type", sa.String(length=8), nullable=False),
        sa.Column("end_type", sa.String(length=8), nullable=False),
        *(sa.Column(field_name, sa.Numeric(), nullable=True) for field_name in _DECIMAL_FIELDS),
        sa.Column("update_flag", sa.String(length=8), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'cashflow_vip'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint(*_ORIGINAL_IDENTITY_FIELDS, name="pk_raw_tushare_cashflow"),
        schema="raw_tushare",
        postgresql_tablespace=_TABLESPACE,
    )
    op.execute("ALTER INDEX raw_tushare.pk_raw_tushare_cashflow SET TABLESPACE gs_raw_cold_hdd")
    op.execute(
        "CREATE INDEX idx_raw_tushare_cashflow_ann_report_code "
        "ON raw_tushare.cashflow (ann_date, report_type, ts_code) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_raw_tushare_cashflow_serving_rank ON raw_tushare.cashflow "
        "(report_type, ts_code, end_date, update_flag DESC, f_ann_date DESC, ann_date DESC) "
        "TABLESPACE gs_raw_cold_hdd"
    )
    selected_columns = ",\n            ".join(_VIEW_COLUMNS)
    op.execute(
        f"""
        CREATE VIEW core_serving.equity_cashflow AS
        SELECT DISTINCT ON (ts_code, end_date)
            {selected_columns}
        FROM raw_tushare.cashflow
        WHERE report_type = '1'
        ORDER BY ts_code, end_date,
            CASE update_flag WHEN '1' THEN 0 ELSE 1 END,
            f_ann_date DESC, ann_date DESC, fetched_at DESC,
            comp_type DESC, end_type DESC, source_content_hash DESC
        """
    )


def downgrade() -> None:
    raise RuntimeError("现金流量表保存业务事实，不支持自动 downgrade 删除数据。")
