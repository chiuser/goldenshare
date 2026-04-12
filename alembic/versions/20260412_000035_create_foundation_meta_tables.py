"""create foundation meta tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_000035"
down_revision = "20260408_000034"
branch_labels = None
depends_on = None


TIMESTAMP_COLS = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS foundation")

    op.create_table(
        "source_registry",
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        *TIMESTAMP_COLS,
        schema="foundation",
    )
    op.create_index(
        "idx_source_registry_enabled_priority",
        "source_registry",
        ["enabled", "priority"],
        schema="foundation",
    )

    op.create_table(
        "dataset_resolution_policy",
        sa.Column("dataset_key", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("primary_source_key", sa.String(length=32), nullable=False),
        sa.Column("fallback_source_keys", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("field_rules_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *TIMESTAMP_COLS,
        schema="foundation",
    )

    op.create_table(
        "dataset_source_status",
        sa.Column("dataset_key", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("source_key", sa.String(length=32), nullable=False, primary_key=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default=sa.text("''")),
        *TIMESTAMP_COLS,
        schema="foundation",
    )
    op.create_index(
        "idx_dataset_source_status_active",
        "dataset_source_status",
        ["is_active"],
        schema="foundation",
    )


def downgrade() -> None:
    op.drop_index("idx_dataset_source_status_active", table_name="dataset_source_status", schema="foundation")
    op.drop_table("dataset_source_status", schema="foundation")

    op.drop_table("dataset_resolution_policy", schema="foundation")

    op.drop_index("idx_source_registry_enabled_priority", table_name="source_registry", schema="foundation")
    op.drop_table("source_registry", schema="foundation")
