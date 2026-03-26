"""add raw dividend row hash and surrogate key"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260325_000009"
down_revision = "20260325_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dividend", sa.Column("id", sa.BigInteger(), nullable=True), schema="raw")
    op.execute("CREATE SEQUENCE IF NOT EXISTS raw.dividend_id_seq")
    op.execute("ALTER TABLE raw.dividend ALTER COLUMN id SET DEFAULT nextval('raw.dividend_id_seq')")
    op.execute("UPDATE raw.dividend SET id = nextval('raw.dividend_id_seq') WHERE id IS NULL")
    op.execute("SELECT setval('raw.dividend_id_seq', COALESCE((SELECT max(id) FROM raw.dividend), 1), true)")
    op.alter_column("dividend", "id", existing_type=sa.BigInteger(), nullable=False, schema="raw")
    op.add_column("dividend", sa.Column("row_hash", sa.String(length=64), nullable=True), schema="raw")

    op.execute(
        """
        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT c.conname INTO constraint_name
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'raw' AND t.relname = 'dividend' AND c.contype = 'p';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE raw.dividend DROP CONSTRAINT %I', constraint_name);
            END IF;
        END $$;
        """
    )
    op.alter_column("dividend", "ts_code", existing_type=sa.String(length=16), nullable=True, schema="raw")
    op.alter_column("dividend", "end_date", existing_type=sa.Date(), nullable=True, schema="raw")
    op.alter_column("dividend", "ann_date", existing_type=sa.Date(), nullable=True, schema="raw")
    op.alter_column("dividend", "div_proc", existing_type=sa.String(length=32), nullable=True, schema="raw")
    op.create_primary_key("dividend_pkey", "dividend", ["id"], schema="raw")
    op.create_index("uq_raw_dividend_row_hash", "dividend", ["row_hash"], unique=True, schema="raw")


def downgrade() -> None:
    op.drop_index("uq_raw_dividend_row_hash", table_name="dividend", schema="raw")
    op.execute("ALTER TABLE raw.dividend DROP CONSTRAINT IF EXISTS dividend_pkey")
    op.alter_column("dividend", "div_proc", existing_type=sa.String(length=32), nullable=False, schema="raw")
    op.alter_column("dividend", "ann_date", existing_type=sa.Date(), nullable=False, schema="raw")
    op.alter_column("dividend", "end_date", existing_type=sa.Date(), nullable=False, schema="raw")
    op.alter_column("dividend", "ts_code", existing_type=sa.String(length=16), nullable=False, schema="raw")
    op.create_primary_key("dividend_pkey", "dividend", ["ts_code", "end_date", "ann_date", "div_proc"], schema="raw")
    op.drop_column("dividend", "row_hash", schema="raw")
    op.execute("ALTER TABLE raw.dividend ALTER COLUMN id DROP DEFAULT")
    op.drop_column("dividend", "id", schema="raw")
    op.execute("DROP SEQUENCE IF EXISTS raw.dividend_id_seq")
