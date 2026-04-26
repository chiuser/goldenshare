"""holdernumber hash stage c repair and tighten"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from src.scripts.repair_holdernumber_hashes import repair_holdernumber_hashes_with_connection


revision = "20260325_000013"
down_revision = "20260325_000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    repair_holdernumber_hashes_with_connection(op.get_bind())
    op.alter_column("holdernumber", "row_key_hash", existing_type=sa.String(length=64), nullable=False, schema="raw")
    op.alter_column(
        "equity_holder_number", "row_key_hash", existing_type=sa.String(length=64), nullable=False, schema="core"
    )
    op.alter_column(
        "equity_holder_number", "event_key_hash", existing_type=sa.String(length=64), nullable=False, schema="core"
    )


def downgrade() -> None:
    op.alter_column(
        "equity_holder_number", "event_key_hash", existing_type=sa.String(length=64), nullable=True, schema="core"
    )
    op.alter_column(
        "equity_holder_number", "row_key_hash", existing_type=sa.String(length=64), nullable=True, schema="core"
    )
    op.alter_column("holdernumber", "row_key_hash", existing_type=sa.String(length=64), nullable=True, schema="raw")
