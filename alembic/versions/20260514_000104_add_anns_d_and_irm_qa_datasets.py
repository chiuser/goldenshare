"""add anns_d and irm qa datasets

Revision ID: 20260514_000104
Revises: 20260510_000103
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op


revision = "20260514_000104"
down_revision = "20260510_000103"
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
        CREATE TABLE IF NOT EXISTS raw_tushare.anns_d (
            id BIGSERIAL PRIMARY KEY,
            ann_date DATE NOT NULL,
            ts_code VARCHAR(32) NOT NULL,
            name VARCHAR(128),
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            rec_time TIMESTAMPTZ NOT NULL,
            row_key_hash VARCHAR(64) NOT NULL,
            api_name VARCHAR(32) NOT NULL DEFAULT 'anns_d',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_tushare_anns_d_row_key_hash ON raw_tushare.anns_d (row_key_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_tushare_anns_d_ann_date ON raw_tushare.anns_d (ann_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_tushare_anns_d_ts_code_date ON raw_tushare.anns_d (ts_code, ann_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_tushare_anns_d_rec_time ON raw_tushare.anns_d (rec_time)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare.irm_qa_sh (
            id BIGSERIAL PRIMARY KEY,
            ts_code VARCHAR(32) NOT NULL,
            name VARCHAR(128),
            trade_date DATE NOT NULL,
            q TEXT NOT NULL,
            a TEXT NOT NULL,
            pub_time TIMESTAMPTZ,
            row_key_hash VARCHAR(64) NOT NULL,
            api_name VARCHAR(32) NOT NULL DEFAULT 'irm_qa_sh',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_tushare_irm_qa_sh_row_key_hash ON raw_tushare.irm_qa_sh (row_key_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_tushare_irm_qa_sh_trade_date ON raw_tushare.irm_qa_sh (trade_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_tushare_irm_qa_sh_ts_code_date ON raw_tushare.irm_qa_sh (ts_code, trade_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_tushare_irm_qa_sh_pub_time ON raw_tushare.irm_qa_sh (pub_time)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare.irm_qa_sz (
            id BIGSERIAL PRIMARY KEY,
            ts_code VARCHAR(32) NOT NULL,
            name VARCHAR(128),
            trade_date DATE NOT NULL,
            q TEXT NOT NULL,
            a TEXT NOT NULL,
            pub_time TIMESTAMPTZ,
            industry VARCHAR(128),
            row_key_hash VARCHAR(64) NOT NULL,
            api_name VARCHAR(32) NOT NULL DEFAULT 'irm_qa_sz',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_tushare_irm_qa_sz_row_key_hash ON raw_tushare.irm_qa_sz (row_key_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_tushare_irm_qa_sz_trade_date ON raw_tushare.irm_qa_sz (trade_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_tushare_irm_qa_sz_ts_code_date ON raw_tushare.irm_qa_sz (ts_code, trade_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_raw_tushare_irm_qa_sz_pub_time ON raw_tushare.irm_qa_sz (pub_time)")

    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving_light.anns_d AS
        SELECT
            row_key_hash,
            ann_date,
            ts_code,
            name,
            title,
            url,
            rec_time,
            'tushare'::varchar(32) AS source,
            fetched_at
        FROM raw_tushare.anns_d
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving_light.irm_qa_sh AS
        SELECT
            row_key_hash,
            ts_code,
            name,
            trade_date,
            q,
            a,
            pub_time,
            'tushare'::varchar(32) AS source,
            fetched_at
        FROM raw_tushare.irm_qa_sh
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving_light.irm_qa_sz AS
        SELECT
            row_key_hash,
            ts_code,
            name,
            trade_date,
            q,
            a,
            pub_time,
            industry,
            'tushare'::varchar(32) AS source,
            fetched_at
        FROM raw_tushare.irm_qa_sz
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving_light.irm_qa_sz")
    op.execute("DROP VIEW IF EXISTS core_serving_light.irm_qa_sh")
    op.execute("DROP VIEW IF EXISTS core_serving_light.anns_d")
    op.execute("DROP TABLE IF EXISTS raw_tushare.irm_qa_sz")
    op.execute("DROP TABLE IF EXISTS raw_tushare.irm_qa_sh")
    op.execute("DROP TABLE IF EXISTS raw_tushare.anns_d")
