"""Preserve the source decimal turnover for newly written stock minute bars."""

from alembic import op
import sqlalchemy as sa


revision = "20261125_000191"
down_revision = "20261116_000190"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stk_mins", sa.Column("amount_precise", sa.Numeric(), nullable=True), schema="raw_tushare"
    )
    op.execute("DROP VIEW core_serving.equity_minute_bar RESTRICT")
    op.execute(
        """
        CREATE VIEW core_serving.equity_minute_bar AS
        SELECT ts_code, freq, trade_time, trade_time::date AS trade_date,
               open, close, high, low, vol,
               COALESCE(amount_precise, amount::double precision::numeric) AS amount,
               'tushare'::varchar(32) AS source
        FROM raw_tushare.stk_mins
        """
    )


def downgrade() -> None:
    raise RuntimeError("Preserve amount_precise and use a release that can read it.")
