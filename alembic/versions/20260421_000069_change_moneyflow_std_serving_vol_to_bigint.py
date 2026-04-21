"""change moneyflow std/serving volume columns to bigint

Revision ID: 20260421_000069
Revises: 20260421_000068
Create Date: 2026-04-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_000069"
down_revision = "20260421_000068"
branch_labels = None
depends_on = None

TARGETS = (
    ("core_multi", "moneyflow_std"),
    ("core_serving", "equity_moneyflow"),
)

VOLUME_COLUMNS = (
    "buy_sm_vol",
    "sell_sm_vol",
    "buy_md_vol",
    "sell_md_vol",
    "buy_lg_vol",
    "sell_lg_vol",
    "buy_elg_vol",
    "sell_elg_vol",
    "net_mf_vol",
)


def upgrade() -> None:
    for schema_name, table_name in TARGETS:
        for column in VOLUME_COLUMNS:
            op.alter_column(
                table_name,
                column,
                schema=schema_name,
                existing_type=sa.Numeric(20, 4),
                type_=sa.BigInteger(),
                postgresql_using=f"{column}::bigint",
                existing_nullable=True,
            )


def downgrade() -> None:
    for schema_name, table_name in TARGETS:
        for column in VOLUME_COLUMNS:
            op.alter_column(
                table_name,
                column,
                schema=schema_name,
                existing_type=sa.BigInteger(),
                type_=sa.Numeric(20, 4),
                postgresql_using=f"{column}::numeric(20,4)",
                existing_nullable=True,
            )
