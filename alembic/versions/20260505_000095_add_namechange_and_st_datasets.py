"""add namechange and st datasets

Revision ID: 20260505_000095
Revises: 20260505_000094
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op


revision = "20260505_000095"
down_revision = "20260505_000094"
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
        CREATE TABLE IF NOT EXISTS raw_tushare.namechange (
            id BIGSERIAL PRIMARY KEY,
            row_key_hash VARCHAR(64) NOT NULL,
            ts_code VARCHAR(16) NOT NULL,
            name VARCHAR(128) NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE,
            ann_date DATE,
            change_reason TEXT,
            api_name VARCHAR(32) NOT NULL DEFAULT 'namechange',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_tushare_namechange_row_key_hash
        ON raw_tushare.namechange (row_key_hash)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_namechange_ts_code
        ON raw_tushare.namechange (ts_code)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_namechange_ann_date
        ON raw_tushare.namechange (ann_date)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare.st (
            id BIGSERIAL PRIMARY KEY,
            row_key_hash VARCHAR(64) NOT NULL,
            ts_code VARCHAR(16) NOT NULL,
            name VARCHAR(128),
            pub_date DATE NOT NULL,
            imp_date DATE,
            st_tpye VARCHAR(64) NOT NULL,
            st_reason TEXT,
            st_explain TEXT,
            api_name VARCHAR(32) NOT NULL DEFAULT 'st',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_tushare_st_row_key_hash
        ON raw_tushare.st (row_key_hash)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_st_ts_code
        ON raw_tushare.st (ts_code)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_st_pub_date
        ON raw_tushare.st (pub_date)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_st_imp_date
        ON raw_tushare.st (imp_date)
        """
    )

    op.execute("DROP VIEW IF EXISTS core_serving_light.namechange")
    op.execute(
        """
        CREATE VIEW core_serving_light.namechange AS
        SELECT
            row_key_hash,
            ts_code,
            name,
            start_date,
            end_date,
            ann_date,
            change_reason,
            fetched_at
        FROM raw_tushare.namechange
        """
    )

    op.execute("DROP VIEW IF EXISTS core_serving_light.st")
    op.execute(
        """
        CREATE VIEW core_serving_light.st AS
        SELECT
            row_key_hash,
            ts_code,
            name,
            pub_date,
            imp_date,
            st_tpye,
            st_reason,
            st_explain,
            fetched_at
        FROM raw_tushare.st
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving_light.st")
    op.execute("DROP VIEW IF EXISTS core_serving_light.namechange")
    op.execute("DROP TABLE IF EXISTS raw_tushare.st")
    op.execute("DROP TABLE IF EXISTS raw_tushare.namechange")
