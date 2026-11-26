"""Retire the unused index minute ingestion auxiliary table."""

from alembic import op


revision = "20261126_000193"
down_revision = "20261126_000192"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE raw_tushare.index_mins_volume_evidence IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM raw_tushare.index_mins_volume_evidence) THEN
                RAISE EXCEPTION 'Index minute volume evidence must be empty before retirement';
            END IF;
        END $$;
    """)
    op.drop_table("index_mins_volume_evidence", schema="raw_tushare")


def downgrade() -> None:
    raise RuntimeError("Use the share-based index minute writer after retiring the auxiliary table.")
