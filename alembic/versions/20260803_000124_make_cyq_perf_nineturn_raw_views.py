"""make cyq perf and nine turn serving raw-backed views

Revision ID: 20260803_000124
Revises: 20260802_000123
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op


revision = "20260803_000124"
down_revision = "20260802_000123"
branch_labels = None
depends_on = None


_PREFLIGHT_RELATIONS = """
DO $$
DECLARE
    relation_name text;
    relation_kind char;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['cyq_perf', 'stk_nineturn']
    LOOP
        SELECT c.relkind INTO relation_kind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'raw_tushare'
          AND c.relname = relation_name;

        IF relation_kind IS DISTINCT FROM 'r' THEN
            RAISE EXCEPTION 'Expected raw_tushare.% to be a physical table, found relation kind %', relation_name, relation_kind;
        END IF;
    END LOOP;

    FOREACH relation_name IN ARRAY ARRAY['equity_cyq_perf', 'equity_nineturn']
    LOOP
        SELECT c.relkind INTO relation_kind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'core_serving'
          AND c.relname = relation_name;

        IF relation_kind IS DISTINCT FROM 'r' THEN
            RAISE EXCEPTION 'Expected core_serving.% to be a physical table, found relation kind %', relation_name, relation_kind;
        END IF;
    END LOOP;
END $$;
"""


_CREATE_EQUITY_CYQ_PERF_VIEW = """
CREATE VIEW core_serving.equity_cyq_perf AS
SELECT
    ts_code,
    trade_date,
    his_low,
    his_high,
    cost_5pct,
    cost_15pct,
    cost_50pct,
    cost_85pct,
    cost_95pct,
    weight_avg,
    winner_rate,
    fetched_at AS created_at,
    fetched_at AS updated_at
FROM raw_tushare.cyq_perf
"""


_CREATE_EQUITY_NINETURN_VIEW = """
CREATE VIEW core_serving.equity_nineturn AS
SELECT
    ts_code,
    trade_date,
    freq,
    open,
    high,
    low,
    close,
    vol,
    amount,
    up_count,
    down_count,
    nine_up_turn,
    nine_down_turn,
    fetched_at AS created_at,
    fetched_at AS updated_at
FROM raw_tushare.stk_nineturn
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(_PREFLIGHT_RELATIONS)
    # No CASCADE: unexpected downstream dependencies must stop the release.
    op.execute("DROP TABLE core_serving.equity_cyq_perf")
    op.execute("DROP TABLE core_serving.equity_nineturn")
    op.execute(_CREATE_EQUITY_CYQ_PERF_VIEW)
    op.execute(_CREATE_EQUITY_NINETURN_VIEW)


def downgrade() -> None:
    raise RuntimeError(
        "Recreating physical core tables requires an explicit approved migration; automatic downgrade is forbidden."
    )
