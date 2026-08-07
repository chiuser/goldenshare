"""add public fund B4 fund_div immutable fact table

Revision ID: 20260807_000130
Revises: 20260807_000129
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_000130"
down_revision = "20260807_000129"
branch_labels = None
depends_on = None


_TABLESPACE = "gs_raw_cold_hdd"
_SCHEMA = "core_serving"


def _assert_hdd_tablespace() -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"),
        {"name": _TABLESPACE},
    ).scalar()
    if not exists:
        raise RuntimeError(f"B4 基金分红事实表要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _assert_hdd_tablespace()
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    op.create_table(
        "fund_div",
        sa.Column("source_entity_key", sa.Text(), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("identity_basis", sa.Text(), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("ann_date", sa.Date(), nullable=False),
        sa.Column("imp_anndate", sa.Date(), nullable=True),
        sa.Column("base_date", sa.Date(), nullable=True),
        sa.Column("div_proc", sa.Text(), nullable=True),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("ex_date", sa.Date(), nullable=True),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("earpay_date", sa.Date(), nullable=True),
        sa.Column("net_ex_date", sa.Date(), nullable=True),
        sa.Column("div_cash", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("base_unit", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("ear_distr", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("ear_amount", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("account_date", sa.Date(), nullable=True),
        sa.Column("base_year", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("source_entity_key", name="pk_core_serving_fund_div"),
        schema=_SCHEMA,
        postgresql_tablespace=_TABLESPACE,
    )
    op.execute("ALTER INDEX core_serving.pk_core_serving_fund_div SET TABLESPACE gs_raw_cold_hdd")
    op.execute(
        "CREATE INDEX idx_fund_div_ann_date_ts_code "
        "ON core_serving.fund_div (ann_date DESC, ts_code) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_div_ts_code_ann_date "
        "ON core_serving.fund_div (ts_code, ann_date DESC) TABLESPACE gs_raw_cold_hdd"
    )


def downgrade() -> None:
    raise RuntimeError("B4 基金分红表保存不可变源事实，不支持自动 downgrade 删除数据。")
