"""add bse_mapping and stock_company datasets

Revision ID: 20260505_000094
Revises: 20260503_000093
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op


revision = "20260505_000094"
down_revision = "20260503_000093"
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
        CREATE TABLE IF NOT EXISTS raw_tushare.bse_mapping (
            o_code VARCHAR(16) NOT NULL,
            n_code VARCHAR(16) NOT NULL,
            name VARCHAR(128),
            list_date DATE,
            api_name VARCHAR(32) NOT NULL DEFAULT 'bse_mapping',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT,
            PRIMARY KEY (o_code, n_code)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_bse_mapping_n_code
        ON raw_tushare.bse_mapping (n_code)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare.stock_company (
            ts_code VARCHAR(16) NOT NULL PRIMARY KEY,
            com_name VARCHAR(256),
            com_id VARCHAR(32),
            exchange VARCHAR(8) NOT NULL,
            chairman VARCHAR(128),
            manager VARCHAR(128),
            secretary VARCHAR(128),
            reg_capital DOUBLE PRECISION,
            setup_date DATE,
            province VARCHAR(64),
            city VARCHAR(64),
            introduction TEXT,
            website VARCHAR(256),
            email VARCHAR(256),
            office TEXT,
            employees INTEGER,
            main_business TEXT,
            business_scope TEXT,
            ann_date DATE,
            api_name VARCHAR(32) NOT NULL DEFAULT 'stock_company',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_stock_company_exchange
        ON raw_tushare.stock_company (exchange)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_tushare_stock_company_com_id
        ON raw_tushare.stock_company (com_id)
        """
    )

    op.execute("DROP VIEW IF EXISTS core_serving_light.bse_mapping")
    op.execute(
        """
        CREATE VIEW core_serving_light.bse_mapping AS
        SELECT
            o_code,
            n_code,
            name,
            list_date,
            fetched_at
        FROM raw_tushare.bse_mapping
        """
    )

    op.execute("DROP VIEW IF EXISTS core_serving_light.stock_company")
    op.execute(
        """
        CREATE VIEW core_serving_light.stock_company AS
        SELECT
            ts_code,
            com_name,
            com_id,
            exchange,
            chairman,
            manager,
            secretary,
            reg_capital,
            setup_date,
            province,
            city,
            introduction,
            website,
            email,
            office,
            employees,
            main_business,
            business_scope,
            ann_date,
            fetched_at
        FROM raw_tushare.stock_company
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving_light.stock_company")
    op.execute("DROP VIEW IF EXISTS core_serving_light.bse_mapping")
    op.execute("DROP TABLE IF EXISTS raw_tushare.stock_company")
    op.execute("DROP TABLE IF EXISTS raw_tushare.bse_mapping")
