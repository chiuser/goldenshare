"""add public fund B7 fund_portfolio staged immutable facts

Revision ID: 20260810_000131
Revises: 20260807_000130
Create Date: 2026-08-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260810_000131"
down_revision = "20260807_000130"
branch_labels = None
depends_on = None


_TABLESPACE = "gs_raw_cold_hdd"
_PARTITION_COUNT = 32


def _assert_hdd_tablespace() -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"),
        {"name": _TABLESPACE},
    ).scalar()
    if not exists:
        raise RuntimeError(f"B7 基金持仓要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD")


def _move_partition_indexes_to_hdd(partition_name: str) -> None:
    bind = op.get_bind()
    index_names = bind.execute(
        sa.text(
            "SELECT quote_ident(ns.nspname) || '.' || quote_ident(idx.relname) "
            "FROM pg_index i "
            "JOIN pg_class tbl ON tbl.oid = i.indrelid "
            "JOIN pg_namespace tbl_ns ON tbl_ns.oid = tbl.relnamespace "
            "JOIN pg_class idx ON idx.oid = i.indexrelid "
            "JOIN pg_namespace ns ON ns.oid = idx.relnamespace "
            "WHERE tbl_ns.nspname = 'core_serving' AND tbl.relname = :partition_name"
        ),
        {"partition_name": partition_name},
    ).scalars()
    for index_name in index_names:
        op.execute(f"ALTER INDEX {index_name} SET TABLESPACE {_TABLESPACE}")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _assert_hdd_tablespace()
    op.execute("CREATE SCHEMA IF NOT EXISTS foundation")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.execute(
        """
        CREATE TABLE core_serving.fund_portfolio (
            ts_code TEXT NOT NULL,
            ann_date DATE NOT NULL,
            end_date DATE NOT NULL,
            symbol TEXT NOT NULL,
            mkv NUMERIC NULL,
            amount NUMERIC NULL,
            stk_mkv_ratio NUMERIC NULL,
            stk_float_ratio NUMERIC NULL,
            source_content_hash CHAR(64) NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_core_serving_fund_portfolio
                PRIMARY KEY (end_date, ts_code, ann_date, symbol)
                USING INDEX TABLESPACE gs_raw_cold_hdd
        ) PARTITION BY HASH (end_date)
        TABLESPACE gs_raw_cold_hdd
        """
    )
    op.execute(
        "CREATE INDEX idx_fund_portfolio_ts_code_period "
        "ON core_serving.fund_portfolio (ts_code, end_date DESC, ann_date DESC, symbol) "
        "TABLESPACE gs_raw_cold_hdd"
    )
    for remainder in range(_PARTITION_COUNT):
        partition_name = f"fund_portfolio_p{remainder:02d}"
        op.execute(
            f"CREATE TABLE core_serving.{partition_name} "
            "PARTITION OF core_serving.fund_portfolio "
            f"FOR VALUES WITH (MODULUS {_PARTITION_COUNT}, REMAINDER {remainder}) "
            f"TABLESPACE {_TABLESPACE}"
        )
        _move_partition_indexes_to_hdd(partition_name)

    op.execute(
        """
        CREATE UNLOGGED TABLE foundation.fund_portfolio_stage (
            stage_run_id UUID NOT NULL,
            ts_code TEXT NOT NULL,
            ann_date DATE NOT NULL,
            end_date DATE NOT NULL,
            symbol TEXT NOT NULL,
            mkv NUMERIC NULL,
            amount NUMERIC NULL,
            stk_mkv_ratio NUMERIC NULL,
            stk_float_ratio NUMERIC NULL,
            source_content_hash CHAR(64) NOT NULL,
            staged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_foundation_fund_portfolio_stage
                PRIMARY KEY (stage_run_id, end_date, ts_code, ann_date, symbol)
                USING INDEX TABLESPACE gs_raw_cold_hdd
        ) TABLESPACE gs_raw_cold_hdd
        """
    )
    op.execute(
        "CREATE INDEX idx_fund_portfolio_stage_period_run "
        "ON foundation.fund_portfolio_stage (end_date, stage_run_id) "
        "TABLESPACE gs_raw_cold_hdd"
    )


def downgrade() -> None:
    raise RuntimeError("B7 基金持仓表保存不可变源事实，不支持自动 downgrade 删除数据。")
