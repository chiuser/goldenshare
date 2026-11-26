"""Store the source volume and unit used by index minute ingestion."""

from alembic import op
import sqlalchemy as sa


revision = "20261126_000192"
down_revision = "20261125_000191"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "index_mins_volume_evidence",
        sa.Column("ts_code", sa.String(32), nullable=False),
        sa.Column("freq", sa.String(16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source_vol", sa.Float(53), nullable=False),
        sa.Column("source_unit", sa.String(5), nullable=False),
        sa.PrimaryKeyConstraint("ts_code", "freq", "trade_date"),
        sa.CheckConstraint("source_unit IN ('share', 'lot')", name="ck_index_mins_volume_source_unit"),
        schema="raw_tushare",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve the index minute volume evidence when rolling back application code.")
