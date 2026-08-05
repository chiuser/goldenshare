"""add public fund B1 observed snapshot serving tables

Revision ID: 20260805_000125
Revises: 20260803_000124
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260805_000125"
down_revision = "20260803_000124"
branch_labels = None
depends_on = None


_TABLESPACE = "gs_raw_cold_hdd"
_SCHEMA = "core_serving"


def _assert_hdd_tablespace() -> None:
    bind = op.get_bind()
    exists = bind.execute(sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"), {"name": _TABLESPACE}).scalar()
    if not exists:
        raise RuntimeError(f"B1 公募基金快照表要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD")


def _create_fund_company_table(*, name: str, observation: bool) -> None:
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
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("shortname", sa.Text(), nullable=True),
        sa.Column("short_enname", sa.Text(), nullable=True),
        sa.Column("province", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("office", sa.Text(), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("chairman", sa.Text(), nullable=True),
        sa.Column("manager", sa.Text(), nullable=True),
        sa.Column("reg_capital", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("setup_date", sa.String(length=8), nullable=True),
        sa.Column("end_date", sa.String(length=8), nullable=True),
        sa.Column("employees", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("main_business", sa.Text(), nullable=True),
        sa.Column("org_code", sa.Text(), nullable=True),
        sa.Column("credit_code", sa.Text(), nullable=True),
        *timestamp_columns,
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("source_entity_key", "source_content_hash", name=f"pk_core_serving_{name}"),
        schema=_SCHEMA,
        postgresql_tablespace=_TABLESPACE,
    )


def _create_mkt_idx_bmk_table(*, name: str, observation: bool) -> None:
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
        sa.Column("ts_code", sa.Text(), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("fullname", sa.Text(), nullable=True),
        sa.Column("bmk_level", sa.Text(), nullable=True),
        sa.Column("bmk_type", sa.Text(), nullable=True),
        sa.Column("bmk_src", sa.Text(), nullable=True),
        sa.Column("idx_type", sa.Text(), nullable=True),
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

    _create_fund_company_table(name="fund_company_current", observation=False)
    _create_fund_company_table(name="fund_company_observation", observation=True)
    _create_mkt_idx_bmk_table(name="mkt_idx_bmk_current", observation=False)
    _create_mkt_idx_bmk_table(name="mkt_idx_bmk_observation", observation=True)

    for table_name in (
        "fund_company_current",
        "fund_company_observation",
        "mkt_idx_bmk_current",
        "mkt_idx_bmk_observation",
    ):
        _move_primary_key_to_hdd(table_name)

    op.execute(
        "CREATE INDEX idx_fund_company_current_source_entity_key "
        "ON core_serving.fund_company_current (source_entity_key) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_company_observation_entity_last_observed "
        "ON core_serving.fund_company_observation (source_entity_key, last_observed_at DESC) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_mkt_idx_bmk_current_source_entity_key "
        "ON core_serving.mkt_idx_bmk_current (source_entity_key) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_mkt_idx_bmk_observation_entity_last_observed "
        "ON core_serving.mkt_idx_bmk_observation (source_entity_key, last_observed_at DESC) TABLESPACE gs_raw_cold_hdd"
    )


def downgrade() -> None:
    raise RuntimeError("B1 公募基金快照保存源事实，不支持自动 downgrade 删除数据。")
