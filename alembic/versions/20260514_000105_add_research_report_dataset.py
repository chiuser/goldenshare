"""add research report dataset

Revision ID: 20260514_000105
Revises: 20260514_000104
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op


revision = "20260514_000105"
down_revision = "20260514_000104"
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
        CREATE TABLE IF NOT EXISTS raw_tushare.research_report (
            id BIGSERIAL PRIMARY KEY,
            row_key_hash VARCHAR(64) NOT NULL,
            report_code VARCHAR(64),
            trade_date DATE NOT NULL,
            abstr TEXT,
            title TEXT NOT NULL,
            report_type VARCHAR(32) NOT NULL,
            author TEXT,
            name VARCHAR(128),
            ts_code VARCHAR(32),
            inst_csname VARCHAR(128) NOT NULL,
            ind_name VARCHAR(128),
            url TEXT NOT NULL,
            api_name VARCHAR(32) NOT NULL DEFAULT 'research_report',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_tushare_research_report_row_key_hash "
        "ON raw_tushare.research_report (row_key_hash)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_tushare_research_report_report_code "
        "ON raw_tushare.research_report (report_code) WHERE report_code IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_tushare_research_report_trade_date "
        "ON raw_tushare.research_report (trade_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_tushare_research_report_ts_code_date "
        "ON raw_tushare.research_report (ts_code, trade_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_tushare_research_report_inst_date "
        "ON raw_tushare.research_report (inst_csname, trade_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_tushare_research_report_type_date "
        "ON raw_tushare.research_report (report_type, trade_date)"
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving_light.research_report AS
        SELECT
            row_key_hash,
            report_code,
            trade_date,
            abstr,
            title,
            report_type,
            author,
            name,
            ts_code,
            inst_csname,
            ind_name,
            url,
            'tushare'::varchar(32) AS source,
            fetched_at
        FROM raw_tushare.research_report
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving_light.research_report")
    op.execute("DROP TABLE IF EXISTS raw_tushare.research_report")
