"""add cctv news dataset

Revision ID: 20260430_000085
Revises: 20260430_000084
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260430_000085"
down_revision = "20260430_000084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving_light")
    inspector = sa.inspect(bind)
    if not inspector.has_table("cctv_news", schema="raw_tushare"):
        op.execute(
            """
            CREATE TABLE raw_tushare.cctv_news (
                id BIGSERIAL PRIMARY KEY,
                date DATE NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                row_key_hash VARCHAR(64) NOT NULL,
                api_name VARCHAR(32) NOT NULL DEFAULT 'cctv_news',
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                raw_payload TEXT
            )
            """
        )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_tushare_cctv_news_row_key_hash
        ON raw_tushare.cctv_news (row_key_hash)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_cctv_news_date
        ON raw_tushare.cctv_news (date DESC)
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving_light.cctv_news AS
        SELECT
            row_key_hash,
            date,
            title,
            content,
            'tushare'::varchar(32) AS source,
            fetched_at
        FROM raw_tushare.cctv_news
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving_light.cctv_news")
    op.execute("DROP TABLE IF EXISTS raw_tushare.cctv_news")
