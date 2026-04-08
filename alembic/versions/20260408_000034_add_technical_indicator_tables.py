"""add technical indicator tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260408_000034"
down_revision = "20260407_000033"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "indicator_meta",
        sa.Column("indicator_name", sa.String(length=32), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("params_json", sa.JSON(), nullable=False),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index(
        "idx_indicator_meta_indicator_updated",
        "indicator_meta",
        ["indicator_name", "updated_at"],
        schema="core",
    )

    op.create_table(
        "indicator_state",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("adjustment", sa.String(length=16), primary_key=True),
        sa.Column("indicator_name", sa.String(length=32), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("last_trade_date", sa.Date(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index(
        "idx_indicator_state_trade_date",
        "indicator_state",
        ["last_trade_date"],
        schema="core",
    )

    op.create_table(
        "ind_macd",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("adjustment", sa.String(length=16), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("dif", sa.Numeric(20, 8)),
        sa.Column("dea", sa.Numeric(20, 8)),
        sa.Column("macd_bar", sa.Numeric(20, 8)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_ind_macd_trade_date", "ind_macd", ["trade_date"], schema="core")
    op.create_index("idx_ind_macd_adj_trade_date", "ind_macd", ["adjustment", "trade_date"], schema="core")

    op.create_table(
        "ind_kdj",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("adjustment", sa.String(length=16), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("k", sa.Numeric(20, 8)),
        sa.Column("d", sa.Numeric(20, 8)),
        sa.Column("j", sa.Numeric(20, 8)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_ind_kdj_trade_date", "ind_kdj", ["trade_date"], schema="core")
    op.create_index("idx_ind_kdj_adj_trade_date", "ind_kdj", ["adjustment", "trade_date"], schema="core")

    op.create_table(
        "ind_rsi",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("adjustment", sa.String(length=16), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("rsi_6", sa.Numeric(20, 8)),
        sa.Column("rsi_12", sa.Numeric(20, 8)),
        sa.Column("rsi_24", sa.Numeric(20, 8)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_ind_rsi_trade_date", "ind_rsi", ["trade_date"], schema="core")
    op.create_index("idx_ind_rsi_adj_trade_date", "ind_rsi", ["adjustment", "trade_date"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_ind_rsi_adj_trade_date", table_name="ind_rsi", schema="core")
    op.drop_index("idx_ind_rsi_trade_date", table_name="ind_rsi", schema="core")
    op.drop_table("ind_rsi", schema="core")

    op.drop_index("idx_ind_kdj_adj_trade_date", table_name="ind_kdj", schema="core")
    op.drop_index("idx_ind_kdj_trade_date", table_name="ind_kdj", schema="core")
    op.drop_table("ind_kdj", schema="core")

    op.drop_index("idx_ind_macd_adj_trade_date", table_name="ind_macd", schema="core")
    op.drop_index("idx_ind_macd_trade_date", table_name="ind_macd", schema="core")
    op.drop_table("ind_macd", schema="core")

    op.drop_index("idx_indicator_state_trade_date", table_name="indicator_state", schema="core")
    op.drop_table("indicator_state", schema="core")

    op.drop_index("idx_indicator_meta_indicator_updated", table_name="indicator_meta", schema="core")
    op.drop_table("indicator_meta", schema="core")

