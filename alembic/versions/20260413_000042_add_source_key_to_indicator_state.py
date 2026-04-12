"""add source_key to indicator_state primary key"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_000042"
down_revision = "20260412_000041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "indicator_state",
        sa.Column("source_key", sa.String(length=32), nullable=False, server_default=sa.text("'tushare'")),
        schema="core",
    )
    op.create_index(
        "idx_indicator_state_source_key",
        "indicator_state",
        ["source_key"],
        schema="core",
    )
    op.drop_constraint("indicator_state_pkey", "indicator_state", schema="core", type_="primary")
    op.create_primary_key(
        "indicator_state_pkey",
        "indicator_state",
        ["ts_code", "source_key", "adjustment", "indicator_name", "version"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_constraint("indicator_state_pkey", "indicator_state", schema="core", type_="primary")
    op.create_primary_key(
        "indicator_state_pkey",
        "indicator_state",
        ["ts_code", "adjustment", "indicator_name", "version"],
        schema="core",
    )
    op.drop_index("idx_indicator_state_source_key", table_name="indicator_state", schema="core")
    op.drop_column("indicator_state", "source_key", schema="core")
