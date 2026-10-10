"""Add only the Raw weekly date index; concurrent DDL must be applied alone.

A failed concurrent build can leave an invalid index. Stop for inspection; do
not drop or rebuild it automatically. Serving already has date-leading indexes.
"""

from alembic import op

revision = "20261010_000186"
down_revision = "20261010_000185"
branch_labels = depends_on = None
_INDEX = "idx_raw_stk_period_bar_adj_week_date_code"
_DEFINITION = (
    f"CREATE INDEX {_INDEX} ON raw_tushare.stk_period_bar_adj USING btree "
    "(trade_date, ts_code) WHERE ((freq)::text = 'week'::text)"
)


def _check_index(*, allow_missing):
    missing = (
        "RETURN;" if allow_missing else "RAISE EXCEPTION 'weekly date index missing';"
    )
    # Dollar quoted expected definition avoids changing the predicate's quoting.
    op.execute(f"""DO $$ BEGIN
        IF to_regclass('raw_tushare.{_INDEX}') IS NULL THEN {missing} END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_index i
            WHERE i.indexrelid = to_regclass('raw_tushare.{_INDEX}')
            AND i.indrelid = 'raw_tushare.stk_period_bar_adj'::regclass
            AND i.indisvalid AND i.indisready AND i.indislive
            AND NOT i.indisunique AND NOT i.indisprimary
            AND pg_get_indexdef(i.indexrelid) = $expected${_DEFINITION}$expected$)
        THEN RAISE EXCEPTION 'weekly date index invalid or mismatched; inspect before retry'; END IF;
    END $$""")


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '15s'")
        op.execute("SET statement_timeout = '15min'")
        _check_index(allow_missing=True)
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
            "ON raw_tushare.stk_period_bar_adj (trade_date, ts_code) WHERE freq = 'week'"
        )
        _check_index(allow_missing=False)
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade():
    raise RuntimeError(
        "Removing the weekly index requires a separately reviewed operation"
    )
