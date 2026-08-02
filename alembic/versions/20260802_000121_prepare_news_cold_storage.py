"""prepare empty partitioned news storage

Revision ID: 20260802_000121
Revises: 20260801_000120
Create Date: 2026-08-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_000121"
down_revision = "20260801_000120"
branch_labels = None
depends_on = None


_COLD_TABLESPACE = "gs_raw_cold_hdd"
_COLD_YEARS = range(2022, 2026)
_ALL_YEARS = range(2022, 2031)


def _tablespace_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(bind.execute(sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"), {"name": name}).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    has_cold_tablespace = _tablespace_exists(_COLD_TABLESPACE)
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute(
        """
        CREATE TABLE raw_tushare.news_partitioned_stage (
            src VARCHAR(32) NOT NULL,
            news_time TIMESTAMPTZ NOT NULL,
            title TEXT,
            content TEXT,
            channels TEXT,
            score TEXT,
            row_key_hash VARCHAR(64) NOT NULL,
            api_name VARCHAR(32) NOT NULL DEFAULT 'news',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT,
            CONSTRAINT pk_raw_tushare_news_partitioned_stage
                PRIMARY KEY (news_time, row_key_hash)
        ) PARTITION BY RANGE (news_time)
        """
    )

    for year in _ALL_YEARS:
        partition_name = f"news_p{year}"
        end_year = year + 1
        is_cold = has_cold_tablespace and year in _COLD_YEARS
        tablespace_clause = f" TABLESPACE {_COLD_TABLESPACE}" if is_cold else ""
        op.execute(
            f"""
            CREATE TABLE raw_tushare.{partition_name}
            PARTITION OF raw_tushare.news_partitioned_stage
            FOR VALUES FROM ('{year}-01-01 00:00:00+00') TO ('{end_year}-01-01 00:00:00+00')
            {tablespace_clause}
            """
        )
        if is_cold:
            op.execute(f"ALTER INDEX raw_tushare.{partition_name}_pkey SET TABLESPACE {_COLD_TABLESPACE}")
        op.execute(
            f"""
            CREATE INDEX idx_raw_tushare_{partition_name}_time
            ON raw_tushare.{partition_name} (news_time DESC)
            {tablespace_clause}
            """
        )
        op.execute(
            f"""
            CREATE INDEX idx_raw_tushare_{partition_name}_src_time
            ON raw_tushare.{partition_name} (src, news_time DESC)
            {tablespace_clause}
            """
        )


def downgrade() -> None:
    raise RuntimeError("新闻快讯冷热分层 stage 不支持自动 downgrade，禁止删除已复制数据。")
