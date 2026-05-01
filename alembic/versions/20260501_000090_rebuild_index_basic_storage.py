"""rebuild index basic storage

Revision ID: 20260501_000090
Revises: 20260501_000089
Create Date: 2026-05-01
"""

from __future__ import annotations

from alembic import op


revision = "20260501_000090"
down_revision = "20260501_000089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.execute("DROP TABLE IF EXISTS raw_tushare.index_basic")
    op.execute("DROP TABLE IF EXISTS core_serving.index_basic")
    op.execute(
        """
        CREATE TABLE raw_tushare.index_basic (
            ts_code VARCHAR(32) PRIMARY KEY,
            name VARCHAR(128),
            fullname VARCHAR(256),
            market VARCHAR(32),
            publisher VARCHAR(128),
            index_type VARCHAR(32),
            category VARCHAR(64),
            base_date VARCHAR(16),
            base_point NUMERIC(20, 4),
            list_date VARCHAR(16),
            weight_rule VARCHAR(128),
            "desc" TEXT,
            exp_date VARCHAR(16),
            api_name VARCHAR(32) NOT NULL DEFAULT 'index_basic',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_payload TEXT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE core_serving.index_basic (
            ts_code VARCHAR(32) PRIMARY KEY,
            name VARCHAR(128),
            fullname VARCHAR(256),
            market VARCHAR(32),
            publisher VARCHAR(128),
            index_type VARCHAR(32),
            category VARCHAR(64),
            base_date DATE,
            base_point NUMERIC(20, 4),
            list_date DATE,
            weight_rule VARCHAR(128),
            "desc" TEXT,
            exp_date DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_index_basic_market ON core_serving.index_basic (market)")
    op.execute("CREATE INDEX idx_index_basic_publisher ON core_serving.index_basic (publisher)")
    op.execute("CREATE INDEX idx_index_basic_category ON core_serving.index_basic (category)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP TABLE IF EXISTS core_serving.index_basic")
    op.execute("DROP TABLE IF EXISTS raw_tushare.index_basic")
