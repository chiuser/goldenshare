"""add etf sh cons dataset

Revision ID: 20260620_000118
Revises: 20260618_000117
Create Date: 2026-06-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260620_000118"
down_revision = "20260618_000117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    op.create_table(
        "etf_sh_cons",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("con_code", sa.String(length=16), nullable=False),
        sa.Column("con_name", sa.String(length=128), nullable=True),
        sa.Column("qty", sa.Numeric(24, 6), nullable=True),
        sa.Column("sub_flag", sa.String(length=16), nullable=True),
        sa.Column("cpr", sa.String(length=32), nullable=True),
        sa.Column("rdr", sa.String(length=32), nullable=True),
        sa.Column("sca", sa.String(length=32), nullable=True),
        sa.Column("exchange", sa.String(length=16), nullable=True),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'etf_sh_cons'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("trade_date", "ts_code", "con_code", name="pk_raw_tushare_etf_sh_cons"),
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_etf_sh_cons_trade_date",
        "etf_sh_cons",
        ["trade_date"],
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_etf_sh_cons_ts_code_trade_date",
        "etf_sh_cons",
        ["ts_code", "trade_date"],
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_etf_sh_cons_con_code",
        "etf_sh_cons",
        ["con_code"],
        schema="raw_tushare",
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving.etf_sh_cons AS
        SELECT
            trade_date,
            ts_code,
            con_code,
            con_name,
            qty,
            sub_flag,
            cpr,
            rdr,
            sca,
            exchange,
            api_name,
            fetched_at,
            raw_payload
        FROM raw_tushare.etf_sh_cons
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core_serving.etf_sh_cons")
    op.drop_index("idx_raw_tushare_etf_sh_cons_con_code", table_name="etf_sh_cons", schema="raw_tushare")
    op.drop_index("idx_raw_tushare_etf_sh_cons_ts_code_trade_date", table_name="etf_sh_cons", schema="raw_tushare")
    op.drop_index("idx_raw_tushare_etf_sh_cons_trade_date", table_name="etf_sh_cons", schema="raw_tushare")
    op.drop_table("etf_sh_cons", schema="raw_tushare")
