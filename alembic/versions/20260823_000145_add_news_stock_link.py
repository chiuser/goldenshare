"""add materialized news to stock links

Revision ID: 20260823_000145
Revises: 20260823_000144
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op


revision = "20260823_000145"
down_revision = "20260823_000144"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS core_serving.news_stock_link (
            news_id VARCHAR(64) NOT NULL,
            ts_code VARCHAR(16) NOT NULL,
            match_method VARCHAR(32) NOT NULL,
            source_field VARCHAR(32) NOT NULL,
            rule_version VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_news_stock_link PRIMARY KEY (news_id, ts_code),
            CONSTRAINT ck_news_stock_link_match_method CHECK (
                match_method IN ('CODE_EXACT', 'FULL_NAME_EXACT', 'SHORT_NAME_EXACT')
            ),
            CONSTRAINT ck_news_stock_link_source_field CHECK (
                source_field IN ('title', 'content', 'title_and_content')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_news_stock_link_ts_code
        ON core_serving.news_stock_link (ts_code)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS core_serving.news_stock_link")
