"""fix dividend business key"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260325_000007"
down_revision = "20260325_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.alter_column("dividend", "end_date", existing_type=sa.Date(), nullable=False, schema="raw")
    op.alter_column("dividend", "ann_date", existing_type=sa.Date(), nullable=False, schema="raw")
    op.alter_column("dividend", "div_proc", existing_type=sa.String(length=32), nullable=False, schema="raw")
    op.create_primary_key("dividend_pkey", "dividend", ["ts_code", "end_date", "ann_date", "div_proc"], schema="raw")

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
    op.alter_column("equity_dividend", "end_date", existing_type=sa.Date(), nullable=False, schema="core")
    op.alter_column("equity_dividend", "ann_date", existing_type=sa.Date(), nullable=False, schema="core")
    op.alter_column("equity_dividend", "div_proc", existing_type=sa.String(length=32), nullable=False, schema="core")
    op.create_primary_key(
        "equity_dividend_pkey",
        "equity_dividend",
        ["ts_code", "end_date", "ann_date", "div_proc"],
        schema="core",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE core.equity_dividend DROP CONSTRAINT IF EXISTS equity_dividend_pkey")
    op.alter_column("equity_dividend", "div_proc", existing_type=sa.String(length=32), nullable=True, schema="core")
    op.alter_column("equity_dividend", "ann_date", existing_type=sa.Date(), nullable=False, schema="core")
    op.alter_column("equity_dividend", "end_date", existing_type=sa.Date(), nullable=True, schema="core")
    op.create_primary_key(
        "equity_dividend_pkey",
        "equity_dividend",
        ["ts_code", "ann_date", "record_date", "ex_date"],
        schema="core",
    )

    op.execute("ALTER TABLE raw.dividend DROP CONSTRAINT IF EXISTS dividend_pkey")
    op.alter_column("dividend", "div_proc", existing_type=sa.String(length=32), nullable=True, schema="raw")
    op.alter_column("dividend", "ann_date", existing_type=sa.Date(), nullable=True, schema="raw")
    op.alter_column("dividend", "end_date", existing_type=sa.Date(), nullable=True, schema="raw")
    op.create_primary_key("dividend_pkey", "dividend", ["ts_code", "ann_date", "record_date", "ex_date"], schema="raw")
