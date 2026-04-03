"""widen ths hot text columns"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_000027"
down_revision = "20260403_000026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("ths_hot", "concept", schema="raw", existing_type=sa.String(length=512), type_=sa.Text(), existing_nullable=True)
    op.alter_column("ths_hot", "rank_reason", schema="raw", existing_type=sa.String(length=512), type_=sa.Text(), existing_nullable=True)
    op.alter_column("ths_hot", "concept", schema="core", existing_type=sa.String(length=512), type_=sa.Text(), existing_nullable=True)
    op.alter_column("ths_hot", "rank_reason", schema="core", existing_type=sa.String(length=512), type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("ths_hot", "rank_reason", schema="core", existing_type=sa.Text(), type_=sa.String(length=512), existing_nullable=True)
    op.alter_column("ths_hot", "concept", schema="core", existing_type=sa.Text(), type_=sa.String(length=512), existing_nullable=True)
    op.alter_column("ths_hot", "rank_reason", schema="raw", existing_type=sa.Text(), type_=sa.String(length=512), existing_nullable=True)
    op.alter_column("ths_hot", "concept", schema="raw", existing_type=sa.Text(), type_=sa.String(length=512), existing_nullable=True)
