"""stock basic multi-source and security serving cutover"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_000038"
down_revision = "20260412_000037"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "stock_basic",
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("symbol", sa.String(length=16)),
        sa.Column("name", sa.String(length=64)),
        sa.Column("area", sa.String(length=64)),
        sa.Column("industry", sa.String(length=64)),
        sa.Column("fullname", sa.String(length=128)),
        sa.Column("enname", sa.String(length=128)),
        sa.Column("cnspell", sa.String(length=32)),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("curr_type", sa.String(length=16)),
        sa.Column("list_status", sa.String(length=8)),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("is_hs", sa.String(length=8)),
        sa.Column("act_name", sa.String(length=128)),
        sa.Column("act_ent_type", sa.String(length=64)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'stock_basic'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_tushare",
    )
    op.create_table(
        "stock_basic",
        sa.Column("dm", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("mc", sa.String(length=64)),
        sa.Column("jys", sa.String(length=16)),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'stock_basic'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw_biying",
    )

    op.create_table(
        "security_std",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("ts_code", sa.String(length=16), nullable=False, primary_key=True),
        sa.Column("symbol", sa.String(length=16)),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("area", sa.String(length=64)),
        sa.Column("industry", sa.String(length=64)),
        sa.Column("fullname", sa.String(length=128)),
        sa.Column("enname", sa.String(length=128)),
        sa.Column("cnspell", sa.String(length=32)),
        sa.Column("exchange", sa.String(length=16)),
        sa.Column("curr_type", sa.String(length=16)),
        sa.Column("list_status", sa.String(length=8)),
        sa.Column("list_date", sa.Date()),
        sa.Column("delist_date", sa.Date()),
        sa.Column("is_hs", sa.String(length=8)),
        sa.Column("act_name", sa.String(length=128)),
        sa.Column("act_ent_type", sa.String(length=64)),
        sa.Column("security_type", sa.String(length=16), nullable=False, server_default=sa.text("'EQUITY'")),
        *TIMESTAMP_COLS,
        schema="core_multi",
    )
    op.create_index("idx_security_std_name", "security_std", ["name"], schema="core_multi")
    op.create_index("idx_security_std_source", "security_std", ["source_key"], schema="core_multi")

    op.rename_table("security", "security_serving", schema="core")
    op.execute("ALTER INDEX core.idx_security_name RENAME TO idx_security_serving_name")
    op.execute("ALTER INDEX core.idx_security_industry RENAME TO idx_security_serving_industry")
    op.execute("ALTER INDEX core.idx_security_list_status RENAME TO idx_security_serving_list_status")


def downgrade() -> None:
    op.execute("ALTER INDEX core.idx_security_serving_name RENAME TO idx_security_name")
    op.execute("ALTER INDEX core.idx_security_serving_industry RENAME TO idx_security_industry")
    op.execute("ALTER INDEX core.idx_security_serving_list_status RENAME TO idx_security_list_status")
    op.rename_table("security_serving", "security", schema="core")

    op.drop_index("idx_security_std_source", table_name="security_std", schema="core_multi")
    op.drop_index("idx_security_std_name", table_name="security_std", schema="core_multi")
    op.drop_table("security_std", schema="core_multi")

    op.drop_table("stock_basic", schema="raw_biying")
    op.drop_table("stock_basic", schema="raw_tushare")
