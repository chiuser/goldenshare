"""holdernumber hash stage a structure switch"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260325_000012"
down_revision = "20260325_000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("holdernumber", sa.Column("id", sa.BigInteger(), nullable=True), schema="raw")
    op.execute("CREATE SEQUENCE IF NOT EXISTS raw.holdernumber_id_seq")
    op.execute("ALTER TABLE raw.holdernumber ALTER COLUMN id SET DEFAULT nextval('raw.holdernumber_id_seq')")
    op.execute("UPDATE raw.holdernumber SET id = nextval('raw.holdernumber_id_seq') WHERE id IS NULL")
    op.execute("SELECT setval('raw.holdernumber_id_seq', COALESCE((SELECT max(id) FROM raw.holdernumber), 1), true)")
    op.alter_column("holdernumber", "id", existing_type=sa.BigInteger(), nullable=False, schema="raw")
    op.add_column("holdernumber", sa.Column("row_key_hash", sa.String(length=64), nullable=True), schema="raw")
    op.execute(
        """
        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT c.conname INTO constraint_name
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'raw' AND t.relname = 'holdernumber' AND c.contype = 'p';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE raw.holdernumber DROP CONSTRAINT %I', constraint_name);
            END IF;
        END $$;
        """
    )
    op.alter_column("holdernumber", "ts_code", existing_type=sa.String(length=16), nullable=True, schema="raw")
    op.alter_column("holdernumber", "ann_date", existing_type=sa.Date(), nullable=True, schema="raw")
    op.create_primary_key("holdernumber_pkey", "holdernumber", ["id"], schema="raw")
    op.create_index("uq_raw_holdernumber_row_key_hash", "holdernumber", ["row_key_hash"], unique=True, schema="raw")

    op.add_column("equity_holder_number", sa.Column("id", sa.BigInteger(), nullable=True), schema="core")
    op.execute("CREATE SEQUENCE IF NOT EXISTS core.equity_holder_number_id_seq")
    op.execute(
        "ALTER TABLE core.equity_holder_number ALTER COLUMN id SET DEFAULT nextval('core.equity_holder_number_id_seq')"
    )
    op.execute("UPDATE core.equity_holder_number SET id = nextval('core.equity_holder_number_id_seq') WHERE id IS NULL")
    op.execute(
        "SELECT setval('core.equity_holder_number_id_seq', COALESCE((SELECT max(id) FROM core.equity_holder_number), 1), true)"
    )
    op.alter_column("equity_holder_number", "id", existing_type=sa.BigInteger(), nullable=False, schema="core")
    op.add_column("equity_holder_number", sa.Column("row_key_hash", sa.String(length=64), nullable=True), schema="core")
    op.add_column(
        "equity_holder_number", sa.Column("event_key_hash", sa.String(length=64), nullable=True), schema="core"
    )
    op.execute(
        """
        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT c.conname INTO constraint_name
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'core' AND t.relname = 'equity_holder_number' AND c.contype = 'p';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE core.equity_holder_number DROP CONSTRAINT %I', constraint_name);
            END IF;
        END $$;
        """
    )
    op.create_primary_key("equity_holder_number_pkey", "equity_holder_number", ["id"], schema="core")
    op.create_index(
        "uq_equity_holder_number_row_key_hash", "equity_holder_number", ["row_key_hash"], unique=True, schema="core"
    )
    op.create_index(
        "idx_equity_holder_number_event_key_hash",
        "equity_holder_number",
        ["event_key_hash"],
        unique=False,
        schema="core",
    )


def downgrade() -> None:
    op.drop_index("idx_equity_holder_number_event_key_hash", table_name="equity_holder_number", schema="core")
    op.drop_index("uq_equity_holder_number_row_key_hash", table_name="equity_holder_number", schema="core")
    op.execute("ALTER TABLE core.equity_holder_number DROP CONSTRAINT IF EXISTS equity_holder_number_pkey")
    op.create_primary_key(
        "equity_holder_number_pkey",
        "equity_holder_number",
        ["ts_code", "ann_date"],
        schema="core",
    )
    op.drop_column("equity_holder_number", "event_key_hash", schema="core")
    op.drop_column("equity_holder_number", "row_key_hash", schema="core")
    op.execute("ALTER TABLE core.equity_holder_number ALTER COLUMN id DROP DEFAULT")
    op.drop_column("equity_holder_number", "id", schema="core")
    op.execute("DROP SEQUENCE IF EXISTS core.equity_holder_number_id_seq")

    op.drop_index("uq_raw_holdernumber_row_key_hash", table_name="holdernumber", schema="raw")
    op.execute("ALTER TABLE raw.holdernumber DROP CONSTRAINT IF EXISTS holdernumber_pkey")
    op.alter_column("holdernumber", "ann_date", existing_type=sa.Date(), nullable=False, schema="raw")
    op.alter_column("holdernumber", "ts_code", existing_type=sa.String(length=16), nullable=False, schema="raw")
    op.create_primary_key("holdernumber_pkey", "holdernumber", ["ts_code", "ann_date"], schema="raw")
    op.drop_column("holdernumber", "row_key_hash", schema="raw")
    op.execute("ALTER TABLE raw.holdernumber ALTER COLUMN id DROP DEFAULT")
    op.drop_column("holdernumber", "id", schema="raw")
    op.execute("DROP SEQUENCE IF EXISTS raw.holdernumber_id_seq")
