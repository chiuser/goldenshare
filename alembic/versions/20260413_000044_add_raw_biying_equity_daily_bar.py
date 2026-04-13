"""add raw_biying equity_daily_bar table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_000044"
down_revision = "20260413_000043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_biying")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("equity_daily_bar", schema="raw_biying"):
        return
    op.create_table(
        "equity_daily_bar",
        sa.Column("dm", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False, primary_key=True),
        sa.Column("adj_type", sa.String(length=8), nullable=False, primary_key=True),
        sa.Column("mc", sa.String(length=64)),
        sa.Column("quote_time", sa.DateTime(timezone=False)),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("pre_close", sa.Numeric(18, 4)),
        sa.Column("vol", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(24, 4)),
        sa.Column("suspend_flag", sa.Integer()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'hsstock_history'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_biying",
    )
    op.create_index(
        "idx_raw_biying_equity_daily_bar_trade_date",
        "equity_daily_bar",
        ["trade_date"],
        schema="raw_biying",
    )
    op.create_index(
        "idx_raw_biying_equity_daily_bar_dm_trade_date",
        "equity_daily_bar",
        ["dm", "trade_date"],
        schema="raw_biying",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("equity_daily_bar", schema="raw_biying"):
        return
    op.drop_index("idx_raw_biying_equity_daily_bar_dm_trade_date", table_name="equity_daily_bar", schema="raw_biying")
    op.drop_index("idx_raw_biying_equity_daily_bar_trade_date", table_name="equity_daily_bar", schema="raw_biying")
    op.drop_table("equity_daily_bar", schema="raw_biying")
