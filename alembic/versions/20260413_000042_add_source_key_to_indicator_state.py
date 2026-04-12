"""add source_key to indicator_state primary key"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_000042"
down_revision = "20260412_000041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("indicator_state", schema="core")}
    if "source_key" not in columns:
        op.add_column(
            "indicator_state",
            sa.Column("source_key", sa.String(length=32), nullable=False, server_default=sa.text("'tushare'")),
            schema="core",
        )

    index_names = {index["name"] for index in inspector.get_indexes("indicator_state", schema="core")}
    if "idx_indicator_state_source_key" not in index_names:
        op.create_index(
            "idx_indicator_state_source_key",
            "indicator_state",
            ["source_key"],
            schema="core",
        )

    pk = inspector.get_pk_constraint("indicator_state", schema="core")
    current_pk_name = pk.get("name")
    current_pk_cols = pk.get("constrained_columns") or []
    target_pk_cols = ["ts_code", "source_key", "adjustment", "indicator_name", "version"]
    if current_pk_cols != target_pk_cols:
        if current_pk_name:
            op.drop_constraint(current_pk_name, "indicator_state", schema="core", type_="primary")
        op.create_primary_key(
            "indicator_state_pkey",
            "indicator_state",
            target_pk_cols,
            schema="core",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    pk = inspector.get_pk_constraint("indicator_state", schema="core")
    current_pk_name = pk.get("name")
    current_pk_cols = pk.get("constrained_columns") or []
    target_pk_cols = ["ts_code", "adjustment", "indicator_name", "version"]
    if current_pk_cols != target_pk_cols:
        if current_pk_name:
            op.drop_constraint(current_pk_name, "indicator_state", schema="core", type_="primary")
        op.create_primary_key(
            "indicator_state_pkey",
            "indicator_state",
            target_pk_cols,
            schema="core",
        )

    index_names = {index["name"] for index in inspector.get_indexes("indicator_state", schema="core")}
    if "idx_indicator_state_source_key" in index_names:
        op.drop_index("idx_indicator_state_source_key", table_name="indicator_state", schema="core")

    columns = {col["name"] for col in inspector.get_columns("indicator_state", schema="core")}
    if "source_key" in columns:
        op.drop_column("indicator_state", "source_key", schema="core")
