"""create indicator std tables in core_multi"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_000043"
down_revision = "20260413_000042"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core_multi")

    op.create_table(
        "indicator_macd_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("adjustment", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("dif", sa.Numeric(20, 8)),
        sa.Column("dea", sa.Numeric(20, 8)),
        sa.Column("macd_bar", sa.Numeric(20, 8)),
        *TIMESTAMP_COLS,
        schema="core_multi",
    )
    op.create_index(
        "idx_indicator_macd_std_trade_date",
        "indicator_macd_std",
        ["trade_date"],
        schema="core_multi",
    )
    op.create_index(
        "idx_indicator_macd_std_source_trade_date",
        "indicator_macd_std",
        ["source_key", "trade_date"],
        schema="core_multi",
    )

    op.create_table(
        "indicator_kdj_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("adjustment", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("k", sa.Numeric(20, 8)),
        sa.Column("d", sa.Numeric(20, 8)),
        sa.Column("j", sa.Numeric(20, 8)),
        *TIMESTAMP_COLS,
        schema="core_multi",
    )
    op.create_index(
        "idx_indicator_kdj_std_trade_date",
        "indicator_kdj_std",
        ["trade_date"],
        schema="core_multi",
    )
    op.create_index(
        "idx_indicator_kdj_std_source_trade_date",
        "indicator_kdj_std",
        ["source_key", "trade_date"],
        schema="core_multi",
    )

    op.create_table(
        "indicator_rsi_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("adjustment", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("rsi_6", sa.Numeric(20, 8)),
        sa.Column("rsi_12", sa.Numeric(20, 8)),
        sa.Column("rsi_24", sa.Numeric(20, 8)),
        *TIMESTAMP_COLS,
        schema="core_multi",
    )
    op.create_index(
        "idx_indicator_rsi_std_trade_date",
        "indicator_rsi_std",
        ["trade_date"],
        schema="core_multi",
    )
    op.create_index(
        "idx_indicator_rsi_std_source_trade_date",
        "indicator_rsi_std",
        ["source_key", "trade_date"],
        schema="core_multi",
    )


def downgrade() -> None:
    op.drop_index("idx_indicator_rsi_std_source_trade_date", table_name="indicator_rsi_std", schema="core_multi")
    op.drop_index("idx_indicator_rsi_std_trade_date", table_name="indicator_rsi_std", schema="core_multi")
    op.drop_table("indicator_rsi_std", schema="core_multi")

    op.drop_index("idx_indicator_kdj_std_source_trade_date", table_name="indicator_kdj_std", schema="core_multi")
    op.drop_index("idx_indicator_kdj_std_trade_date", table_name="indicator_kdj_std", schema="core_multi")
    op.drop_table("indicator_kdj_std", schema="core_multi")

    op.drop_index("idx_indicator_macd_std_source_trade_date", table_name="indicator_macd_std", schema="core_multi")
    op.drop_index("idx_indicator_macd_std_trade_date", table_name="indicator_macd_std", schema="core_multi")
    op.drop_table("indicator_macd_std", schema="core_multi")
