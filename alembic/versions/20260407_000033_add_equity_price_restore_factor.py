"""add equity_price_restore_factor table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260407_000033"
down_revision = "20260406_000032"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "equity_price_restore_factor",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("cum_factor", sa.Numeric(20, 8), nullable=False),
        sa.Column("single_factor", sa.Numeric(20, 8)),
        sa.Column("event_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("event_ex_date", sa.Date()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index(
        "idx_equity_price_restore_factor_trade_date",
        "equity_price_restore_factor",
        ["trade_date"],
        schema="core",
    )
    op.create_index(
        "idx_equity_price_restore_factor_updated_at",
        "equity_price_restore_factor",
        ["updated_at"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_index("idx_equity_price_restore_factor_updated_at", table_name="equity_price_restore_factor", schema="core")
    op.drop_index("idx_equity_price_restore_factor_trade_date", table_name="equity_price_restore_factor", schema="core")
    op.drop_table("equity_price_restore_factor", schema="core")
