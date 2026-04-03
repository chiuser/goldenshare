"""add hk/us basic resources"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_000025"
down_revision = "20260402_000024"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "hk_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("fullname", sa.String(length=256)),
        sa.Column("enname", sa.String(length=256)),
        sa.Column("cn_spell", sa.String(length=64)),
        sa.Column("market", sa.String(length=32)),
        sa.Column("list_status", sa.String(length=8)),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("trade_unit", sa.Integer()),
        sa.Column("isin", sa.String(length=32)),
        sa.Column("curr_type", sa.String(length=16)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="hk_basic"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "hk_security",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("fullname", sa.String(length=256)),
        sa.Column("enname", sa.String(length=256)),
        sa.Column("cn_spell", sa.String(length=64)),
        sa.Column("market", sa.String(length=32)),
        sa.Column("list_status", sa.String(length=8)),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("trade_unit", sa.Integer()),
        sa.Column("isin", sa.String(length=32)),
        sa.Column("curr_type", sa.String(length=16)),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="tushare"),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_hk_security_name", "hk_security", ["name"], schema="core")
    op.create_index("idx_hk_security_market", "hk_security", ["market"], schema="core")
    op.create_index("idx_hk_security_list_status", "hk_security", ["list_status"], schema="core")

    op.create_table(
        "us_basic",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("enname", sa.String(length=256)),
        sa.Column("classify", sa.String(length=16)),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="us_basic"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "us_security",
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("name", sa.String(length=128)),
        sa.Column("enname", sa.String(length=256)),
        sa.Column("classify", sa.String(length=16)),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="tushare"),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_us_security_name", "us_security", ["name"], schema="core")
    op.create_index("idx_us_security_classify", "us_security", ["classify"], schema="core")
    op.create_index("idx_us_security_list_date", "us_security", ["list_date"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_us_security_list_date", table_name="us_security", schema="core")
    op.drop_index("idx_us_security_classify", table_name="us_security", schema="core")
    op.drop_index("idx_us_security_name", table_name="us_security", schema="core")
    op.drop_table("us_security", schema="core")
    op.drop_table("us_basic", schema="raw")

    op.drop_index("idx_hk_security_list_status", table_name="hk_security", schema="core")
    op.drop_index("idx_hk_security_market", table_name="hk_security", schema="core")
    op.drop_index("idx_hk_security_name", table_name="hk_security", schema="core")
    op.drop_table("hk_security", schema="core")
    op.drop_table("hk_basic", schema="raw")
