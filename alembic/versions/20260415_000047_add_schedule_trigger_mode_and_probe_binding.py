"""add schedule trigger mode and probe binding fields

Revision ID: 20260415_000047
Revises: 20260415_000046
Create Date: 2026-04-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260415_000047"
down_revision = "20260415_000046"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"


def _column_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name, schema=schema)}


def _index_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name, schema=schema)}


def _upgrade_job_schedule(inspector: sa.Inspector) -> None:
    table = "job_schedule"
    columns = _column_names(inspector, table, schema=OPS_SCHEMA)
    if "trigger_mode" not in columns:
        op.add_column(
            table,
            sa.Column("trigger_mode", sa.String(length=32), nullable=False, server_default=sa.text("'schedule'")),
            schema=OPS_SCHEMA,
        )
    if "probe_config_json" not in columns:
        op.add_column(
            table,
            sa.Column("probe_config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            schema=OPS_SCHEMA,
        )


def _upgrade_probe_rule(inspector: sa.Inspector) -> None:
    table = "probe_rule"
    columns = _column_names(inspector, table, schema=OPS_SCHEMA)
    if "schedule_id" not in columns:
        op.add_column(
            table,
            sa.Column("schedule_id", sa.BigInteger(), nullable=True),
            schema=OPS_SCHEMA,
        )
    indexes = _index_names(inspector, table, schema=OPS_SCHEMA)
    if "idx_probe_rule_schedule_id" not in indexes:
        op.create_index("idx_probe_rule_schedule_id", table, ["schedule_id"], schema=OPS_SCHEMA)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _upgrade_job_schedule(inspector)
    _upgrade_probe_rule(inspector)


def _downgrade_probe_rule(inspector: sa.Inspector) -> None:
    table = "probe_rule"
    if not inspector.has_table(table, schema=OPS_SCHEMA):
        return
    indexes = _index_names(inspector, table, schema=OPS_SCHEMA)
    if "idx_probe_rule_schedule_id" in indexes:
        op.drop_index("idx_probe_rule_schedule_id", table_name=table, schema=OPS_SCHEMA)
    columns = _column_names(inspector, table, schema=OPS_SCHEMA)
    if "schedule_id" in columns:
        op.drop_column(table, "schedule_id", schema=OPS_SCHEMA)


def _downgrade_job_schedule(inspector: sa.Inspector) -> None:
    table = "job_schedule"
    if not inspector.has_table(table, schema=OPS_SCHEMA):
        return
    columns = _column_names(inspector, table, schema=OPS_SCHEMA)
    if "probe_config_json" in columns:
        op.drop_column(table, "probe_config_json", schema=OPS_SCHEMA)
    if "trigger_mode" in columns:
        op.drop_column(table, "trigger_mode", schema=OPS_SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _downgrade_probe_rule(inspector)
    _downgrade_job_schedule(inspector)
