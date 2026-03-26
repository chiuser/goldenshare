"""dividend hash stage a structure switch"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260325_000010"
down_revision = "20260325_000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE raw.dividend RENAME COLUMN row_hash TO row_key_hash")
    op.execute("ALTER INDEX IF EXISTS raw.uq_raw_dividend_row_hash RENAME TO uq_raw_dividend_row_key_hash")

    op.add_column("equity_dividend", sa.Column("id", sa.BigInteger(), nullable=True), schema="core")
    op.execute("CREATE SEQUENCE IF NOT EXISTS core.equity_dividend_id_seq")
    op.execute("ALTER TABLE core.equity_dividend ALTER COLUMN id SET DEFAULT nextval('core.equity_dividend_id_seq')")
    op.execute("UPDATE core.equity_dividend SET id = nextval('core.equity_dividend_id_seq') WHERE id IS NULL")
    op.execute("SELECT setval('core.equity_dividend_id_seq', COALESCE((SELECT max(id) FROM core.equity_dividend), 1), true)")
    op.alter_column("equity_dividend", "id", existing_type=sa.BigInteger(), nullable=False, schema="core")
    op.add_column("equity_dividend", sa.Column("row_key_hash", sa.String(length=64), nullable=True), schema="core")
    op.add_column("equity_dividend", sa.Column("event_key_hash", sa.String(length=64), nullable=True), schema="core")

    op.execute(
        """
        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT c.conname INTO constraint_name
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'core' AND t.relname = 'equity_dividend' AND c.contype = 'p';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE core.equity_dividend DROP CONSTRAINT %I', constraint_name);
            END IF;
        END $$;
        """
    )
    op.create_primary_key("equity_dividend_pkey", "equity_dividend", ["id"], schema="core")
    op.create_index("uq_equity_dividend_row_key_hash", "equity_dividend", ["row_key_hash"], unique=True, schema="core")
    op.create_index("idx_equity_dividend_event_key_hash", "equity_dividend", ["event_key_hash"], unique=False, schema="core")


def downgrade() -> None:
    op.drop_index("idx_equity_dividend_event_key_hash", table_name="equity_dividend", schema="core")
    op.drop_index("uq_equity_dividend_row_key_hash", table_name="equity_dividend", schema="core")
    op.execute("ALTER TABLE core.equity_dividend DROP CONSTRAINT IF EXISTS equity_dividend_pkey")
    op.create_primary_key(
        "equity_dividend_pkey",
        "equity_dividend",
        ["ts_code", "end_date", "ann_date", "div_proc"],
        schema="core",
    )
    op.drop_column("equity_dividend", "event_key_hash", schema="core")
    op.drop_column("equity_dividend", "row_key_hash", schema="core")
    op.execute("ALTER TABLE core.equity_dividend ALTER COLUMN id DROP DEFAULT")
    op.drop_column("equity_dividend", "id", schema="core")
    op.execute("DROP SEQUENCE IF EXISTS core.equity_dividend_id_seq")

    op.execute("ALTER INDEX IF EXISTS raw.uq_raw_dividend_row_key_hash RENAME TO uq_raw_dividend_row_hash")
    op.execute("ALTER TABLE raw.dividend RENAME COLUMN row_key_hash TO row_hash")
