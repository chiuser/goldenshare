"""add news dataset

Revision ID: 20260503_000091
Revises: 20260501_000090
Create Date: 2026-05-03
"""

from __future__ import annotations

from alembic import op


revision = "20260503_000091"
down_revision = "20260501_000090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving_light")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare.news (
            id BIGSERIAL PRIMARY KEY,
            src VARCHAR(32) NOT NULL,
            news_time TIMESTAMPTZ NOT NULL,
            title TEXT,
            content TEXT,
            channels TEXT,
            score TEXT,
            row_key_hash VARCHAR(64) NOT NULL,
            api_name VARCHAR(32) NOT NULL DEFAULT 'news',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_tushare_news_row_key_hash
        ON raw_tushare.news (row_key_hash)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_news_src_time
        ON raw_tushare.news (src, news_time DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_news_time
        ON raw_tushare.news (news_time DESC)
        """
    )
    op.execute("DROP VIEW IF EXISTS core_serving_light.news")
    op.execute(
        """
        CREATE VIEW core_serving_light.news AS
        SELECT
            row_key_hash,
            src,
            news_time,
            title,
            content,
            channels,
            score,
            'tushare'::varchar(32) AS source,
            fetched_at
        FROM raw_tushare.news
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving_light.news")
    op.execute("DROP TABLE IF EXISTS raw_tushare.news")
