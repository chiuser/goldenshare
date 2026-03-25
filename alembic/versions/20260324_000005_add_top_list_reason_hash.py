"""add top list reason hash column and unique index"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260324_000005"
down_revision = "20260324_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equity_top_list", sa.Column("reason_hash", sa.String(length=64), nullable=True), schema="core")
    op.create_index(
        "uq_equity_top_list_ts_code_trade_date_reason_hash",
        "equity_top_list",
        ["ts_code", "trade_date", "reason_hash"],
        unique=True,
        schema="core",
    )


def downgrade() -> None:
    op.drop_index("uq_equity_top_list_ts_code_trade_date_reason_hash", table_name="equity_top_list", schema="core")
    op.drop_column("equity_top_list", "reason_hash", schema="core")
