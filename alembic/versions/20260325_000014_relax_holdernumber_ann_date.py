"""relax holdernumber ann_date nullability"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260325_000014"
down_revision = "20260325_000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("equity_holder_number", "ann_date", existing_type=sa.Date(), nullable=True, schema="core")


def downgrade() -> None:
    op.alter_column("equity_holder_number", "ann_date", existing_type=sa.Date(), nullable=False, schema="core")
