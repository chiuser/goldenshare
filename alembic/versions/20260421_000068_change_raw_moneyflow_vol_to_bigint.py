"""change raw_tushare.moneyflow volume columns to bigint

Revision ID: 20260421_000068
Revises: 20260421_000067
Create Date: 2026-04-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_000068"
down_revision = "20260421_000067"
branch_labels = None
depends_on = None

RAW_SCHEMA = "raw_tushare"
TABLE_NAME = "moneyflow"
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


def _existing_volume_columns(inspector: sa.Inspector) -> tuple[str, ...]:
    """Return the historical columns that are present in this database.

    ``raw_tushare.moneyflow`` existed in pre-consolidation deployments but is
    not created by the clean migration baseline.  Keep the type correction for
    those deployments without making a clean install depend on that legacy
    table.
    """

    if not inspector.has_table(TABLE_NAME, schema=RAW_SCHEMA):
        return ()

    present_columns = {
        column["name"] for column in inspector.get_columns(TABLE_NAME, schema=RAW_SCHEMA)
    }
    return tuple(column for column in VOLUME_COLUMNS if column in present_columns)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for column in _existing_volume_columns(inspector):
        op.alter_column(
            TABLE_NAME,
            column,
            schema=RAW_SCHEMA,
            existing_type=sa.Numeric(20, 4),
            type_=sa.BigInteger(),
            postgresql_using=f"{column}::bigint",
            existing_nullable=True,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for column in _existing_volume_columns(inspector):
        op.alter_column(
            TABLE_NAME,
            column,
            schema=RAW_SCHEMA,
            existing_type=sa.BigInteger(),
            type_=sa.Numeric(20, 4),
            postgresql_using=f"{column}::numeric(20,4)",
            existing_nullable=True,
        )
