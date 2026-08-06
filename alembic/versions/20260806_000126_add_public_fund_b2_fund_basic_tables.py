"""add public fund B2 fund_basic observed snapshot tables

Revision ID: 20260806_000126
Revises: 20260805_000125
Create Date: 2026-08-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260806_000126"
down_revision = "20260805_000125"
branch_labels = None
depends_on = None


_TABLESPACE = "gs_raw_cold_hdd"
_SCHEMA = "core_serving"


def _assert_hdd_tablespace() -> None:
    bind = op.get_bind()
    exists = bind.execute(sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"), {"name": _TABLESPACE}).scalar()
    if not exists:
        raise RuntimeError(f"B2 公募基金列表快照表要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD")


def _create_fund_basic_table(*, name: str, observation: bool) -> None:
    timestamp_columns: tuple[sa.Column[object], ...]
    if observation:
        timestamp_columns = (
            sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        )
    else:
        timestamp_columns = (sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),)
    op.create_table(
        name,
        sa.Column("source_entity_key", sa.Text(), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("identity_basis", sa.String(length=32), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("management", sa.Text(), nullable=True),
        sa.Column("custodian", sa.Text(), nullable=True),
        sa.Column("fund_type", sa.Text(), nullable=True),
        sa.Column("found_date", sa.String(length=8), nullable=True),
        sa.Column("due_date", sa.String(length=8), nullable=True),
        sa.Column("list_date", sa.String(length=8), nullable=True),
        sa.Column("issue_date", sa.String(length=8), nullable=True),
        sa.Column("delist_date", sa.String(length=8), nullable=True),
        sa.Column("issue_amount", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("m_fee", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("c_fee", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("duration_year", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("p_value", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("min_amount", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("exp_return", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("benchmark", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("invest_type", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("trustee", sa.Text(), nullable=True),
        sa.Column("purc_startdate", sa.String(length=8), nullable=True),
        sa.Column("redm_startdate", sa.String(length=8), nullable=True),
        sa.Column("market", sa.Text(), nullable=False),
        *timestamp_columns,
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("source_entity_key", "source_content_hash", name=f"pk_core_serving_{name}"),
        schema=_SCHEMA,
        postgresql_tablespace=_TABLESPACE,
    )


def _move_primary_key_to_hdd(table_name: str) -> None:
    op.execute(f"ALTER INDEX {_SCHEMA}.pk_core_serving_{table_name} SET TABLESPACE {_TABLESPACE}")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _assert_hdd_tablespace()
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")

    _create_fund_basic_table(name="fund_basic_current", observation=False)
    _create_fund_basic_table(name="fund_basic_observation", observation=True)

    _move_primary_key_to_hdd("fund_basic_current")
    _move_primary_key_to_hdd("fund_basic_observation")

    op.execute(
        "CREATE INDEX idx_fund_basic_current_source_entity_key "
        "ON core_serving.fund_basic_current (source_entity_key) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_basic_observation_entity_last_observed "
        "ON core_serving.fund_basic_observation (source_entity_key, last_observed_at DESC) TABLESPACE gs_raw_cold_hdd"
    )


def downgrade() -> None:
    raise RuntimeError("B2 公募基金列表快照保存源事实，不支持自动 downgrade 删除数据。")
