"""Add the source closing limit status to both daily-basic tables."""

import sqlalchemy as sa

from alembic import op

revision = "20261112_000188"
down_revision = "20261031_000187"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("daily_basic", sa.Column("limit_status", sa.Integer(), nullable=True), schema="raw_tushare")
    op.add_column("equity_daily_basic", sa.Column("limit_status", sa.Integer(), nullable=True), schema="core_serving")


def downgrade():
    op.drop_column("equity_daily_basic", "limit_status", schema="core_serving")
    op.drop_column("daily_basic", "limit_status", schema="raw_tushare")
