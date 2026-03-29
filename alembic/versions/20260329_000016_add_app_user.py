"""add app user for web platform"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260329_000016"
down_revision = "20260329_000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=128)),
        sa.Column("email", sa.String(length=255)),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("username", name="uq_app_user_username"),
        schema="app",
    )
    op.create_index("idx_app_user_is_active", "app_user", ["is_active"], schema="app")


def downgrade() -> None:
    op.drop_index("idx_app_user_is_active", table_name="app_user", schema="app")
    op.drop_table("app_user", schema="app")
    op.execute("DROP SCHEMA IF EXISTS app")
