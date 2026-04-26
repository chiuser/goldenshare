"""drop sync_job_state and legacy freshness fields

Revision ID: 20260426_000076
Revises: 20260426_000075
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_000076"
down_revision = "20260426_000075"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
STATUS_RESET_TABLES = (
    "dataset_status_snapshot",
    "dataset_layer_snapshot_current",
    "dataset_layer_snapshot_history",
)
SYNC_JOB_STATE_COLUMNS = (
    ("job_name", sa.String(length=64), False, None),
    ("state_business_date", sa.Date(), True, None),
    ("business_date_source", sa.String(length=32), False, sa.text("'none'")),
    ("full_sync_done", sa.Boolean(), False, sa.text("false")),
)


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name, schema=OPS_SCHEMA)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name, schema=OPS_SCHEMA))


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {item["name"] for item in inspector.get_indexes(table_name, schema=OPS_SCHEMA)}


def _truncate_or_delete(table_names: tuple[str, ...]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [table_name for table_name in table_names if _has_table(inspector, table_name)]
    if not existing:
        return
    if bind.dialect.name == "postgresql":
        tables = ", ".join(f'"{OPS_SCHEMA}"."{table_name}"' for table_name in existing)
        op.execute(sa.text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        return
    for table_name in existing:
        op.execute(sa.text(f'DELETE FROM "{OPS_SCHEMA}"."{table_name}"'))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _truncate_or_delete(STATUS_RESET_TABLES)

    if _has_table(inspector, "dataset_status_snapshot"):
        if "ix_ops_dataset_status_snapshot_job_name" in _index_names(inspector, "dataset_status_snapshot"):
            op.drop_index("ix_ops_dataset_status_snapshot_job_name", table_name="dataset_status_snapshot", schema=OPS_SCHEMA)
        inspector = sa.inspect(bind)
        for column_name, _, _, _ in SYNC_JOB_STATE_COLUMNS:
            if _has_column(inspector, "dataset_status_snapshot", column_name):
                op.drop_column("dataset_status_snapshot", column_name, schema=OPS_SCHEMA)
                inspector = sa.inspect(bind)

    if _has_table(inspector, "sync_job_state"):
        op.drop_table("sync_job_state", schema=OPS_SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "sync_job_state"):
        op.create_table(
            "sync_job_state",
            sa.Column("job_name", sa.String(length=64), nullable=False),
            sa.Column("target_table", sa.String(length=128), nullable=False),
            sa.Column("last_success_date", sa.Date(), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_cursor", sa.String(length=128), nullable=True),
            sa.Column("full_sync_done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("job_name", name=op.f("pk_sync_job_state")),
            schema=OPS_SCHEMA,
        )

    if _has_table(inspector, "dataset_status_snapshot"):
        for column_name, column_type, nullable, server_default in SYNC_JOB_STATE_COLUMNS:
            if _has_column(inspector, "dataset_status_snapshot", column_name):
                continue
            op.add_column(
                "dataset_status_snapshot",
                sa.Column(column_name, column_type, nullable=nullable, server_default=server_default),
                schema=OPS_SCHEMA,
            )
        inspector = sa.inspect(bind)
        if "ix_ops_dataset_status_snapshot_job_name" not in _index_names(inspector, "dataset_status_snapshot"):
            op.create_index(
                "ix_ops_dataset_status_snapshot_job_name",
                "dataset_status_snapshot",
                ["job_name"],
                unique=False,
                schema=OPS_SCHEMA,
            )
