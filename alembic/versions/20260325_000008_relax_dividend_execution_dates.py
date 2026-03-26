"""relax dividend execution date nullability"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260325_000008"
down_revision = "20260325_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("dividend", "record_date", existing_type=sa.Date(), nullable=True, schema="raw")
    op.alter_column("dividend", "ex_date", existing_type=sa.Date(), nullable=True, schema="raw")
    op.alter_column("equity_dividend", "record_date", existing_type=sa.Date(), nullable=True, schema="core")
    op.alter_column("equity_dividend", "ex_date", existing_type=sa.Date(), nullable=True, schema="core")


def downgrade() -> None:
    op.alter_column("equity_dividend", "ex_date", existing_type=sa.Date(), nullable=False, schema="core")
    op.alter_column("equity_dividend", "record_date", existing_type=sa.Date(), nullable=False, schema="core")
    op.alter_column("dividend", "ex_date", existing_type=sa.Date(), nullable=False, schema="raw")
    op.alter_column("dividend", "record_date", existing_type=sa.Date(), nullable=False, schema="raw")
