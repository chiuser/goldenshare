"""add public fund B4 fund_share observed fact tables

Revision ID: 20260807_000128
Revises: 20260806_000127
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_000128"
down_revision = "20260806_000127"
branch_labels = None
depends_on = None


_TABLESPACE = "gs_raw_cold_hdd"
_SCHEMA = "core_serving"


def _assert_hdd_tablespace() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"),
        {"name": _TABLESPACE},
    ).scalar()
    if not exists:
        raise RuntimeError(
            f"B4 基金规模事实表要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD"
        )


def _create_fund_share_table(*, name: str, observation: bool) -> None:
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
        sa.Column("identity_basis", sa.Text(), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("fd_share", sa.Numeric(precision=30, scale=10), nullable=False),
        sa.Column("total_share", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("fund_type", sa.Text(), nullable=True),
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
    _create_fund_share_table(name="fund_share_current", observation=False)
    _create_fund_share_table(name="fund_share_observation", observation=True)
    _move_primary_key_to_hdd("fund_share_current")
    _move_primary_key_to_hdd("fund_share_observation")

    op.execute(
        "CREATE UNIQUE INDEX uq_fund_share_current_source_entity_key "
        "ON core_serving.fund_share_current (source_entity_key) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_share_current_date_market_code "
        "ON core_serving.fund_share_current (trade_date DESC, market, ts_code) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_share_current_code_date "
        "ON core_serving.fund_share_current (ts_code, trade_date DESC) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_share_observation_entity_last_observed "
        "ON core_serving.fund_share_observation (source_entity_key, last_observed_at DESC) "
        "TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_share_observation_date_market_code "
        "ON core_serving.fund_share_observation (trade_date DESC, market, ts_code) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_share_observation_code_date_last_observed "
        "ON core_serving.fund_share_observation (ts_code, trade_date DESC, last_observed_at DESC) "
        "TABLESPACE gs_raw_cold_hdd"
    )


def downgrade() -> None:
    raise RuntimeError("B4 基金规模表保存源事实，不支持自动 downgrade 删除数据。")
