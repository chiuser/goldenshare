"""rebuild major news storage

Revision ID: 20260501_000089
Revises: 20260501_000088
Create Date: 2026-05-01
"""

from __future__ import annotations

from alembic import op


revision = "20260501_000089"
down_revision = "20260501_000088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving_light")
    op.execute("DROP VIEW IF EXISTS core_serving_light.major_news")
    op.execute("DROP TABLE IF EXISTS raw_tushare.major_news")
    op.execute(
        """
        CREATE TABLE raw_tushare.major_news (
            id BIGSERIAL PRIMARY KEY,
            src VARCHAR(64) NOT NULL,
            pub_time TIMESTAMPTZ NOT NULL,
            title TEXT,
            content TEXT,
            url TEXT,
            row_key_hash VARCHAR(64) NOT NULL,
            api_name VARCHAR(32) NOT NULL DEFAULT 'major_news',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_raw_tushare_major_news_row_key_hash
        ON raw_tushare.major_news (row_key_hash)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_raw_tushare_major_news_src_time
        ON raw_tushare.major_news (src, pub_time DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_raw_tushare_major_news_time
        ON raw_tushare.major_news (pub_time DESC)
        """
    )
    op.execute(
        """
        CREATE VIEW core_serving_light.major_news AS
        SELECT
            row_key_hash,
            src,
            pub_time,
            title,
            content,
            url,
            'tushare'::varchar(32) AS source,
            fetched_at
        FROM raw_tushare.major_news
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving_light.major_news")
    op.execute("DROP TABLE IF EXISTS raw_tushare.major_news")
