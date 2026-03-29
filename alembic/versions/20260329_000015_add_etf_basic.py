"""add etf basic resource"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260329_000015"
down_revision = "20260325_000014"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "etf_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("csname", sa.String(length=128)),
        sa.Column("extname", sa.String(length=256)),
        sa.Column("cname", sa.String(length=256)),
        sa.Column("index_code", sa.String(length=16)),
        sa.Column("index_name", sa.String(length=128)),
        sa.Column("setup_date", sa.Date()),
        sa.Column("list_date", sa.Date()),
        sa.Column("list_status", sa.String(length=8)),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("mgr_name", sa.String(length=128)),
        sa.Column("custod_name", sa.String(length=128)),
        sa.Column("mgt_fee", sa.Numeric(12, 6)),
        sa.Column("etf_type", sa.String(length=64)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="etf_basic"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "etf_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("csname", sa.String(length=128)),
        sa.Column("extname", sa.String(length=256)),
        sa.Column("cname", sa.String(length=256)),
        sa.Column("index_code", sa.String(length=16)),
        sa.Column("index_name", sa.String(length=128)),
        sa.Column("setup_date", sa.Date()),
        sa.Column("list_date", sa.Date()),
        sa.Column("list_status", sa.String(length=8)),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("mgr_name", sa.String(length=128)),
        sa.Column("custod_name", sa.String(length=128)),
        sa.Column("mgt_fee", sa.Numeric(12, 6)),
        sa.Column("etf_type", sa.String(length=64)),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_etf_basic_index_code", "etf_basic", ["index_code"], schema="core")
    op.create_index("idx_etf_basic_exchange", "etf_basic", ["exchange"], schema="core")
    op.create_index("idx_etf_basic_mgr_name", "etf_basic", ["mgr_name"], schema="core")
    op.create_index("idx_etf_basic_list_status", "etf_basic", ["list_status"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_etf_basic_list_status", table_name="etf_basic", schema="core")
    op.drop_index("idx_etf_basic_mgr_name", table_name="etf_basic", schema="core")
    op.drop_index("idx_etf_basic_exchange", table_name="etf_basic", schema="core")
    op.drop_index("idx_etf_basic_index_code", table_name="etf_basic", schema="core")
    op.drop_table("etf_basic", schema="core")
    op.drop_table("etf_basic", schema="raw")
