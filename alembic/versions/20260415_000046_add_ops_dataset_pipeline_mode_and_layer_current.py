"""add ops dataset pipeline mode and layer current snapshot

Revision ID: 20260415_000046
Revises: 20260414_000045
Create Date: 2026-04-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260415_000046"
down_revision = "20260414_000045"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"


def _has_table(inspector: sa.Inspector, table_name: str, *, schema: str) -> bool:
    return inspector.has_table(table_name, schema=schema)


def _index_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name, schema=schema)}


def _create_dataset_pipeline_mode(inspector: sa.Inspector) -> None:
    table_name = "dataset_pipeline_mode"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("dataset_key", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("source_scope", sa.String(length=64), nullable=False, server_default=sa.text("'tushare'")),
        sa.Column("raw_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("std_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolution_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("serving_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=OPS_SCHEMA,
    )
    op.create_index("idx_dataset_pipeline_mode_mode", table_name, ["mode"], schema=OPS_SCHEMA)
    op.create_index("idx_dataset_pipeline_mode_source_scope", table_name, ["source_scope"], schema=OPS_SCHEMA)


def _create_dataset_layer_snapshot_current(inspector: sa.Inspector) -> None:
    table_name = "dataset_layer_snapshot_current"
    if _has_table(inspector, table_name, schema=OPS_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=32), nullable=False, server_default=sa.text("'__all__'")),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rows_in", sa.BigInteger()),
        sa.Column("rows_out", sa.BigInteger()),
        sa.Column("error_count", sa.Integer()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("lag_seconds", sa.Integer()),
        sa.Column("message", sa.Text()),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("dataset_key", "source_key", "stage", name="pk_dataset_layer_snapshot_current"),
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_layer_snapshot_current_stage_status",
        table_name,
        ["stage", "status"],
        schema=OPS_SCHEMA,
    )
    op.create_index(
        "idx_dataset_layer_snapshot_current_calculated_at",
        table_name,
        ["calculated_at"],
        schema=OPS_SCHEMA,
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {OPS_SCHEMA}")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _create_dataset_pipeline_mode(inspector)
    _create_dataset_layer_snapshot_current(inspector)


def _drop_table_if_exists(inspector: sa.Inspector, table_name: str, *, schema: str, indexes: list[str]) -> None:
    if not _has_table(inspector, table_name, schema=schema):
        return
    existing = _index_names(inspector, table_name, schema=schema)
    for index_name in indexes:
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name, schema=schema)
    op.drop_table(table_name, schema=schema)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _drop_table_if_exists(
        inspector,
        "dataset_layer_snapshot_current",
        schema=OPS_SCHEMA,
        indexes=[
            "idx_dataset_layer_snapshot_current_stage_status",
            "idx_dataset_layer_snapshot_current_calculated_at",
        ],
    )
    _drop_table_if_exists(
        inspector,
        "dataset_pipeline_mode",
        schema=OPS_SCHEMA,
        indexes=[
            "idx_dataset_pipeline_mode_mode",
            "idx_dataset_pipeline_mode_source_scope",
        ],
    )
