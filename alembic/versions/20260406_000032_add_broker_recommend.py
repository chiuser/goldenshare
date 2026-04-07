"""add broker_recommend resource"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260406_000032"
down_revision = "20260406_000031"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.create_table(
        "broker_recommend",
        sa.Column("month", sa.String(length=6), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("broker", sa.String(length=128), primary_key=True),
        sa.Column("currency", sa.String(length=16)),
        sa.Column("name", sa.String(length=128)),
        sa.Column("trade_date", sa.Date()),
        sa.Column("close", sa.Numeric(20, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("target_price", sa.Numeric(20, 4)),
        sa.Column("industry", sa.String(length=128)),
        sa.Column("broker_mkt", sa.String(length=64)),
        sa.Column("author", sa.String(length=128)),
        sa.Column("recom_type", sa.String(length=64)),
        sa.Column("reason", sa.Text()),
        sa.Column("offset", sa.Integer()),
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default="broker_recommend"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text()),
        schema="raw",
    )

    op.create_table(
        "broker_recommend",
        sa.Column("month", sa.String(length=6), primary_key=True),
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("broker", sa.String(length=128), primary_key=True),
        sa.Column("currency", sa.String(length=16)),
        sa.Column("name", sa.String(length=128)),
        sa.Column("trade_date", sa.Date()),
        sa.Column("close", sa.Numeric(20, 4)),
        sa.Column("pct_change", sa.Numeric(10, 4)),
        sa.Column("target_price", sa.Numeric(20, 4)),
        sa.Column("industry", sa.String(length=128)),
        sa.Column("broker_mkt", sa.String(length=64)),
        sa.Column("author", sa.String(length=128)),
        sa.Column("recom_type", sa.String(length=64)),
        sa.Column("reason", sa.Text()),
        sa.Column("offset", sa.Integer()),
        *TIMESTAMP_COLS,
        schema="core",
    )
    op.create_index("idx_broker_recommend_month", "broker_recommend", ["month"], schema="core")
    op.create_index("idx_broker_recommend_trade_date", "broker_recommend", ["trade_date"], schema="core")
    op.create_index("idx_broker_recommend_ts_code_month", "broker_recommend", ["ts_code", "month"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_broker_recommend_ts_code_month", table_name="broker_recommend", schema="core")
    op.drop_index("idx_broker_recommend_trade_date", table_name="broker_recommend", schema="core")
    op.drop_index("idx_broker_recommend_month", table_name="broker_recommend", schema="core")
    op.drop_table("broker_recommend", schema="core")
    op.drop_table("broker_recommend", schema="raw")
