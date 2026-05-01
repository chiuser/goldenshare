"""add major news url

Revision ID: 20260430_000087
Revises: 20260430_000086
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op


revision = "20260430_000087"
down_revision = "20260430_000086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE raw_tushare.major_news ADD COLUMN IF NOT EXISTS url TEXT")
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving_light.major_news AS
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

    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving_light.major_news AS
        SELECT
            row_key_hash,
            src,
            pub_time,
            title,
            content,
            'tushare'::varchar(32) AS source,
            fetched_at
        FROM raw_tushare.major_news
        """
    )
    op.execute("ALTER TABLE raw_tushare.major_news DROP COLUMN IF EXISTS url")
