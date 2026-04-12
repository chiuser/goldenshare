"""create core multi std tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_000037"
down_revision = "20260412_000036"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core_multi")

    op.create_table(
        "equity_daily_bar_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("change_amount", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        *TIMESTAMP_COLS,
        schema="core_multi",
    )
    op.create_index(
        "idx_equity_daily_bar_std_trade_date",
        "equity_daily_bar_std",
        ["trade_date"],
        schema="core_multi",
    )
    op.create_index(
        "idx_equity_daily_bar_std_source_trade_date",
        "equity_daily_bar_std",
        ["source_key", "trade_date"],
        schema="core_multi",
    )

    op.create_table(
        "equity_adj_factor_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("adj_factor", sa.Numeric(20, 8), nullable=False),
        *TIMESTAMP_COLS,
        schema="core_multi",
    )
    op.create_index(
        "idx_equity_adj_factor_std_trade_date",
        "equity_adj_factor_std",
        ["trade_date"],
        schema="core_multi",
    )
    op.create_index(
        "idx_equity_adj_factor_std_source_trade_date",
        "equity_adj_factor_std",
        ["source_key", "trade_date"],
        schema="core_multi",
    )

    op.create_table(
        "equity_daily_basic_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("turnover_rate", sa.Numeric(12, 4)),
        sa.Column("turnover_rate_f", sa.Numeric(12, 4)),
        sa.Column("volume_ratio", sa.Numeric(12, 4)),
        sa.Column("pe", sa.Numeric(18, 4)),
        sa.Column("pe_ttm", sa.Numeric(18, 4)),
        sa.Column("pb", sa.Numeric(18, 4)),
        sa.Column("ps", sa.Numeric(18, 4)),
        sa.Column("ps_ttm", sa.Numeric(18, 4)),
        sa.Column("dv_ratio", sa.Numeric(12, 4)),
        sa.Column("dv_ttm", sa.Numeric(12, 4)),
        sa.Column("total_share", sa.Numeric(20, 4)),
        sa.Column("float_share", sa.Numeric(20, 4)),
        sa.Column("free_share", sa.Numeric(20, 4)),
        sa.Column("total_mv", sa.Numeric(20, 4)),
        sa.Column("circ_mv", sa.Numeric(20, 4)),
        *TIMESTAMP_COLS,
        schema="core_multi",
    )
    op.create_index(
        "idx_equity_daily_basic_std_trade_date",
        "equity_daily_basic_std",
        ["trade_date"],
        schema="core_multi",
    )
    op.create_index(
        "idx_equity_daily_basic_std_source_trade_date",
        "equity_daily_basic_std",
        ["source_key", "trade_date"],
        schema="core_multi",
    )

    op.create_table(
        "stk_period_bar_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("freq", sa.String(length=8), nullable=False, primary_key=True),
        sa.Column("end_date", sa.Date()),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("change_amount", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        *TIMESTAMP_COLS,
        schema="core_multi",
    )
    op.create_index(
        "idx_stk_period_bar_std_freq_trade_date",
        "stk_period_bar_std",
        ["freq", "trade_date"],
        schema="core_multi",
    )
    op.create_index(
        "idx_stk_period_bar_std_source_freq_trade_date",
        "stk_period_bar_std",
        ["source_key", "freq", "trade_date"],
        schema="core_multi",
    )

    op.create_table(
        "stk_period_bar_adj_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("freq", sa.String(length=8), nullable=False, primary_key=True),
        sa.Column("end_date", sa.Date()),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("open_qfq", sa.Numeric(18, 4)),
        sa.Column("high_qfq", sa.Numeric(18, 4)),
        sa.Column("low_qfq", sa.Numeric(18, 4)),
        sa.Column("close_qfq", sa.Numeric(18, 4)),
        sa.Column("open_hfq", sa.Numeric(18, 4)),
        sa.Column("high_hfq", sa.Numeric(18, 4)),
        sa.Column("low_hfq", sa.Numeric(18, 4)),
        sa.Column("close_hfq", sa.Numeric(18, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("change_amount", sa.Numeric(18, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        *TIMESTAMP_COLS,
        schema="core_multi",
    )
    op.create_index(
        "idx_stk_period_bar_adj_std_freq_trade_date",
        "stk_period_bar_adj_std",
        ["freq", "trade_date"],
        schema="core_multi",
    )
    op.create_index(
        "idx_stk_period_bar_adj_std_source_freq_trade_date",
        "stk_period_bar_adj_std",
        ["source_key", "freq", "trade_date"],
        schema="core_multi",
    )


def downgrade() -> None:
    op.drop_index("idx_stk_period_bar_adj_std_source_freq_trade_date", table_name="stk_period_bar_adj_std", schema="core_multi")
    op.drop_index("idx_stk_period_bar_adj_std_freq_trade_date", table_name="stk_period_bar_adj_std", schema="core_multi")
    op.drop_table("stk_period_bar_adj_std", schema="core_multi")

    op.drop_index("idx_stk_period_bar_std_source_freq_trade_date", table_name="stk_period_bar_std", schema="core_multi")
    op.drop_index("idx_stk_period_bar_std_freq_trade_date", table_name="stk_period_bar_std", schema="core_multi")
    op.drop_table("stk_period_bar_std", schema="core_multi")

    op.drop_index("idx_equity_daily_basic_std_source_trade_date", table_name="equity_daily_basic_std", schema="core_multi")
    op.drop_index("idx_equity_daily_basic_std_trade_date", table_name="equity_daily_basic_std", schema="core_multi")
    op.drop_table("equity_daily_basic_std", schema="core_multi")

    op.drop_index("idx_equity_adj_factor_std_source_trade_date", table_name="equity_adj_factor_std", schema="core_multi")
    op.drop_index("idx_equity_adj_factor_std_trade_date", table_name="equity_adj_factor_std", schema="core_multi")
    op.drop_table("equity_adj_factor_std", schema="core_multi")

    op.drop_index("idx_equity_daily_bar_std_source_trade_date", table_name="equity_daily_bar_std", schema="core_multi")
    op.drop_index("idx_equity_daily_bar_std_trade_date", table_name="equity_daily_bar_std", schema="core_multi")
    op.drop_table("equity_daily_bar_std", schema="core_multi")
