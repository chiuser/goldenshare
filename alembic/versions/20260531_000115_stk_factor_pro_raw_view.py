"""make stk_factor_pro serving a raw-backed view

Revision ID: 20260531_000115
Revises: 20260530_000114
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op


revision = "20260531_000115"
down_revision = "20260530_000114"
branch_labels = None
depends_on = None


_DROP_EQUITY_FACTOR_PRO_RELATION = """
DO $$
DECLARE
    relation_kind char;
BEGIN
    SELECT c.relkind INTO relation_kind
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'core_serving'
      AND c.relname = 'equity_factor_pro';

    IF relation_kind = 'v' THEN
        EXECUTE 'DROP VIEW core_serving.equity_factor_pro';
    ELSIF relation_kind = 'r' THEN
        EXECUTE 'DROP TABLE core_serving.equity_factor_pro';
    ELSIF relation_kind IS NOT NULL THEN
        RAISE EXCEPTION 'Unsupported relation kind for core_serving.equity_factor_pro: %', relation_kind;
    END IF;
END $$;
"""


_CREATE_EQUITY_FACTOR_PRO_VIEW = """
DO $$
DECLARE
    columns_sql text;
BEGIN
    SELECT string_agg(format('%I', column_name), ', ' ORDER BY ordinal_position)
    INTO columns_sql
    FROM information_schema.columns
    WHERE table_schema = 'raw_tushare'
      AND table_name = 'stk_factor_pro'
      AND column_name NOT IN ('api_name', 'fetched_at', 'raw_payload');

    IF columns_sql IS NULL THEN
        RAISE EXCEPTION 'raw_tushare.stk_factor_pro does not exist or has no projected columns';
    END IF;

    EXECUTE format(
        'CREATE VIEW core_serving.equity_factor_pro AS
         SELECT %s,
                %L::varchar(32) AS source,
                fetched_at AS created_at,
                fetched_at AS updated_at
         FROM raw_tushare.stk_factor_pro',
        columns_sql,
        'tushare'
    );
END $$;
"""


_CREATE_EMPTY_EQUITY_FACTOR_PRO_TABLE = """
DO $$
DECLARE
    columns_sql text;
BEGIN
    SELECT string_agg(format('%I', column_name), ', ' ORDER BY ordinal_position)
    INTO columns_sql
    FROM information_schema.columns
    WHERE table_schema = 'raw_tushare'
      AND table_name = 'stk_factor_pro'
      AND column_name NOT IN ('api_name', 'fetched_at', 'raw_payload');

    IF columns_sql IS NULL THEN
        RAISE EXCEPTION 'raw_tushare.stk_factor_pro does not exist or has no projected columns';
    END IF;

    EXECUTE format(
        'CREATE TABLE core_serving.equity_factor_pro AS
         SELECT %s,
                %L::varchar(32) AS source,
                fetched_at AS created_at,
                fetched_at AS updated_at
         FROM raw_tushare.stk_factor_pro
         WITH NO DATA',
        columns_sql,
        'tushare'
    );
END $$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.execute(_DROP_EQUITY_FACTOR_PRO_RELATION)
    op.execute(_CREATE_EQUITY_FACTOR_PRO_VIEW)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(_DROP_EQUITY_FACTOR_PRO_RELATION)
    op.execute(_CREATE_EMPTY_EQUITY_FACTOR_PRO_TABLE)
    op.execute("ALTER TABLE core_serving.equity_factor_pro ADD PRIMARY KEY (ts_code, trade_date)")
    op.execute(
        """
        CREATE INDEX idx_equity_factor_pro_trade_date
        ON core_serving.equity_factor_pro (trade_date)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_equity_factor_pro_ts_code_trade_date
        ON core_serving.equity_factor_pro (ts_code, trade_date)
        """
    )
