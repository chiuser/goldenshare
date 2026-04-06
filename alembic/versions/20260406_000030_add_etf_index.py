"""add etf index resource"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260406_000030"
down_revision = "20260404_000029"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "etf_index",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("indx_name", sa.String(length=128)),
        sa.Column("indx_csname", sa.String(length=128)),
        sa.Column("pub_party_name", sa.String(length=128)),
        sa.Column("pub_date", sa.Date()),
        sa.Column("base_date", sa.Date()),
        sa.Column("bp", sa.Numeric(12, 6)),
        sa.Column("adj_circle", sa.String(length=64)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="etf_index"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "etf_index",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("indx_name", sa.String(length=128)),
        sa.Column("indx_csname", sa.String(length=128)),
        sa.Column("pub_party_name", sa.String(length=128)),
        sa.Column("pub_date", sa.Date()),
        sa.Column("base_date", sa.Date()),
        sa.Column("bp", sa.Numeric(12, 6)),
        sa.Column("adj_circle", sa.String(length=64)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_etf_index_pub_date", "etf_index", ["pub_date"], schema="core")
    op.create_index("idx_etf_index_base_date", "etf_index", ["base_date"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_etf_index_base_date", table_name="etf_index", schema="core")
    op.drop_index("idx_etf_index_pub_date", table_name="etf_index", schema="core")
    op.drop_table("etf_index", schema="core")
    op.drop_table("etf_index", schema="raw")
