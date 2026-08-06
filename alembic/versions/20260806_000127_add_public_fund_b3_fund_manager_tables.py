"""add public fund B3 fund_manager observed snapshot tables

Revision ID: 20260806_000127
Revises: 20260806_000126
Create Date: 2026-08-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260806_000127"
down_revision = "20260806_000126"
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
            f"B3 基金经理快照表要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD"
        )


def _create_fund_manager_table(*, name: str, observation: bool) -> None:
    timestamp_columns: tuple[sa.Column[object], ...]
    if observation:
        timestamp_columns = (
            sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        )
    else:
        timestamp_columns = (
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        )
    op.create_table(
        name,
        sa.Column("source_entity_key", sa.Text(), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("identity_basis", sa.String(length=32), nullable=False),
        sa.Column("manager_identity_key", sa.Text(), nullable=True),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("ann_date", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("gender", sa.Text(), nullable=True),
        sa.Column("birth_year", sa.Text(), nullable=True),
        sa.Column("edu", sa.Text(), nullable=True),
        sa.Column("nationality", sa.Text(), nullable=True),
        sa.Column("begin_date", sa.Text(), nullable=True),
        sa.Column("end_date", sa.Text(), nullable=True),
        sa.Column("resume", sa.Text(), nullable=True),
        *timestamp_columns,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "source_entity_key", "source_content_hash", name=f"pk_core_serving_{name}"
        ),
        schema=_SCHEMA,
        postgresql_tablespace=_TABLESPACE,
    )


def _move_primary_key_to_hdd(table_name: str) -> None:
    op.execute(
        f"ALTER INDEX {_SCHEMA}.pk_core_serving_{table_name} SET TABLESPACE {_TABLESPACE}"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _assert_hdd_tablespace()
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")

    _create_fund_manager_table(name="fund_manager_current", observation=False)
    _create_fund_manager_table(name="fund_manager_observation", observation=True)

    _move_primary_key_to_hdd("fund_manager_current")
    _move_primary_key_to_hdd("fund_manager_observation")

    op.execute(
        "CREATE UNIQUE INDEX uq_fund_manager_current_source_entity_key "
        "ON core_serving.fund_manager_current (source_entity_key) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_manager_current_ts_code "
        "ON core_serving.fund_manager_current (ts_code) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_manager_current_manager_identity_key "
        "ON core_serving.fund_manager_current (manager_identity_key) TABLESPACE gs_raw_cold_hdd "
        "WHERE manager_identity_key IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_fund_manager_observation_entity_last_observed "
        "ON core_serving.fund_manager_observation (source_entity_key, last_observed_at DESC) "
        "TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_manager_observation_ts_code_last_observed "
        "ON core_serving.fund_manager_observation (ts_code, last_observed_at DESC) "
        "TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_fund_manager_observation_manager_last_observed "
        "ON core_serving.fund_manager_observation (manager_identity_key, last_observed_at DESC) "
        "TABLESPACE gs_raw_cold_hdd WHERE manager_identity_key IS NOT NULL"
    )


def downgrade() -> None:
    raise RuntimeError("B3 基金经理快照保存源事实，不支持自动 downgrade 删除数据。")
