"""dividend hash stage c backfill and tighten"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from src.scripts.backfill_dividend_hashes import backfill_dividend_hashes_with_connection


revision = "20260325_000011"
down_revision = "20260325_000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    backfill_dividend_hashes_with_connection(op.get_bind())
    op.alter_column("dividend", "row_key_hash", existing_type=sa.String(length=64), nullable=False, schema="raw")
    op.alter_column("equity_dividend", "row_key_hash", existing_type=sa.String(length=64), nullable=False, schema="core")
    op.alter_column("equity_dividend", "event_key_hash", existing_type=sa.String(length=64), nullable=False, schema="core")


def downgrade() -> None:
    op.alter_column("equity_dividend", "event_key_hash", existing_type=sa.String(length=64), nullable=True, schema="core")
    op.alter_column("equity_dividend", "row_key_hash", existing_type=sa.String(length=64), nullable=True, schema="core")
    op.alter_column("dividend", "row_key_hash", existing_type=sa.String(length=64), nullable=True, schema="raw")
