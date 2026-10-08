"""Add the approved date-leading moneyflow index without changing business rows.

Concurrent DDL commits independently of the revision update. A complete, exact
existing index can be adopted on resume; an invalid or different index blocks.
Apply this revision alone from 20261002_000183 after the documented preflight.
"""

from alembic import op

revision = "20261008_000184"
down_revision = "20261002_000183"
branch_labels = depends_on = None

_INDEX = "idx_raw_tushare_moneyflow_trade_date_ts_code"
_DEFINITION = (
    f"CREATE INDEX {_INDEX} ON raw_tushare.moneyflow "
    "USING btree (trade_date, ts_code)"
)


def _check_index(*, allow_missing: bool) -> None:
    missing = "RETURN;" if allow_missing else "RAISE EXCEPTION 'moneyflow date index missing';"
    op.execute(
        f"""DO $$ BEGIN
            IF to_regclass('raw_tushare.{_INDEX}') IS NULL THEN
                {missing}
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_index i
                WHERE i.indexrelid = to_regclass('raw_tushare.{_INDEX}')
                  AND i.indrelid = 'raw_tushare.moneyflow'::regclass
                  AND i.indisvalid AND i.indisready AND i.indislive
                  AND NOT i.indisunique AND NOT i.indisprimary
                  AND pg_get_indexdef(i.indexrelid) = '{_DEFINITION}'
            ) THEN
                RAISE EXCEPTION 'moneyflow date index invalid or mismatched; stop for inspection';
            END IF;
        END $$"""
    )


def upgrade() -> None:
    # The surrounding Alembic transaction cannot contain concurrent index DDL.
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '15s'")
        op.execute("SET statement_timeout = '15min'")
        _check_index(allow_missing=True)
        op.create_index(
            _INDEX,
            "moneyflow",
            ["trade_date", "ts_code"],
            schema="raw_tushare",
            unique=False,
            if_not_exists=True,
            postgresql_concurrently=True,
        )
        # IF NOT EXISTS alone would also accept an invalid or wrong index.
        _check_index(allow_missing=False)
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    raise RuntimeError("Removing the approved moneyflow date index requires a separate reviewed operation")
