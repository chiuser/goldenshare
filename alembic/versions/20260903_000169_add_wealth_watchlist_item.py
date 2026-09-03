"""Add user-owned Wealth watchlist items."""

from alembic import op
import sqlalchemy as sa

revision = "20260903_000169"
down_revision = "20260831_000168"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wealth_watchlist_item",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ts_code", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app.app_user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "ts_code", name="uq_wealth_watchlist_item_user_stock"
        ),
        schema="app",
    )
    op.create_index(
        "idx_wealth_watchlist_item_user_id_id",
        "wealth_watchlist_item",
        ["user_id", "id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("wealth_watchlist_item", schema="app")
