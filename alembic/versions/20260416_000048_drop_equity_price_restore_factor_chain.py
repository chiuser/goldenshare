"""drop equity_price_restore_factor dataset chain

Revision ID: 20260416_000048
Revises: 20260415_000047
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_000048"
down_revision = "20260415_000047"
branch_labels = None
depends_on = None


CORE_SCHEMA = "core"
OPS_SCHEMA = "ops"
FOUNDATION_SCHEMA = "foundation"

DATASET_KEY = "equity_price_restore_factor"
RESOURCE_KEY = "equity_price_restore_factor"
JOB_NAME = "sync" + "_equity_price_restore_factor"
TARGET_TABLE = "core.equity_price_restore_factor"
SPEC_KEYS = (
    "sync" + "_daily.equity_price_restore_factor",
    "sync" + "_history.equity_price_restore_factor",
    "maintenance.rebuild_equity_price_restore_factor",
)


def _has_table(inspector: sa.Inspector, table_name: str, *, schema: str) -> bool:
    return inspector.has_table(table_name, schema=schema)


def _column_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name, schema=schema)}


def _index_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name, schema=schema)}


def _execute_delete(
    *,
    schema: str,
    table_name: str,
    where_clause: str,
    params: dict[str, object],
    expanding_params: tuple[str, ...] = (),
) -> None:
    bind = op.get_bind()
    statement = sa.text(f"DELETE FROM {schema}.{table_name} WHERE {where_clause}")
    if expanding_params:
        statement = statement.bindparams(
            *(sa.bindparam(name, expanding=True) for name in expanding_params),
        )
    bind.execute(statement, params)


def _cleanup_job_execution_related(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, "job_execution", schema=OPS_SCHEMA):
        return
    columns = _column_names(inspector, "job_execution", schema=OPS_SCHEMA)
    where_parts: list[str] = []
    params: dict[str, object] = {"spec_keys": list(SPEC_KEYS)}
    expanding = ("spec_keys",)
    if "dataset_key" in columns:
        where_parts.append("dataset_key = :dataset_key")
        params["dataset_key"] = DATASET_KEY
    if "spec_key" in columns:
        where_parts.append("spec_key IN :spec_keys")
    if not where_parts:
        return
    where_clause = " OR ".join(where_parts)

    subquery = f"SELECT id FROM {OPS_SCHEMA}.job_execution WHERE {where_clause}"
    if _has_table(inspector, "job_execution_event", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="job_execution_event",
            where_clause=f"execution_id IN ({subquery})",
            params=params,
            expanding_params=expanding,
        )
    if _has_table(inspector, "job_execution_step", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="job_execution_step",
            where_clause=f"execution_id IN ({subquery})",
            params=params,
            expanding_params=expanding,
        )
    _execute_delete(
        schema=OPS_SCHEMA,
        table_name="job_execution",
        where_clause=where_clause,
        params=params,
        expanding_params=expanding,
    )


def _cleanup_probe_related(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, "probe_rule", schema=OPS_SCHEMA):
        return
    probe_columns = _column_names(inspector, "probe_rule", schema=OPS_SCHEMA)
    has_schedule = "schedule_id" in probe_columns and _has_table(inspector, "job_schedule", schema=OPS_SCHEMA)
    where_clause = "dataset_key = :dataset_key"
    params: dict[str, object] = {"dataset_key": DATASET_KEY, "spec_keys": list(SPEC_KEYS)}
    expanding = ("spec_keys",)
    if has_schedule:
        where_clause = (
            "dataset_key = :dataset_key OR schedule_id IN "
            f"(SELECT id FROM {OPS_SCHEMA}.job_schedule WHERE spec_key IN :spec_keys)"
        )
    if _has_table(inspector, "probe_run_log", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="probe_run_log",
            where_clause=f"probe_rule_id IN (SELECT id FROM {OPS_SCHEMA}.probe_rule WHERE {where_clause})",
            params=params,
            expanding_params=expanding if has_schedule else (),
        )
    _execute_delete(
        schema=OPS_SCHEMA,
        table_name="probe_rule",
        where_clause=where_clause,
        params=params,
        expanding_params=expanding if has_schedule else (),
    )


def _cleanup_job_schedule_related(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, "job_schedule", schema=OPS_SCHEMA):
        return
    _execute_delete(
        schema=OPS_SCHEMA,
        table_name="job_schedule",
        where_clause="spec_key IN :spec_keys",
        params={"spec_keys": list(SPEC_KEYS)},
        expanding_params=("spec_keys",),
    )


def _cleanup_status_and_observability(inspector: sa.Inspector) -> None:
    if _has_table(inspector, "sync_job_state", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="sync_job_state",
            where_clause="job_name = :job_name OR target_table = :target_table",
            params={"job_name": JOB_NAME, "target_table": TARGET_TABLE},
        )
    if _has_table(inspector, "sync_run_log", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="sync_run_log",
            where_clause="job_name = :job_name",
            params={"job_name": JOB_NAME},
        )
    if _has_table(inspector, "dataset_status_snapshot", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="dataset_status_snapshot",
            where_clause=(
                "dataset_key = :dataset_key OR resource_key = :resource_key "
                "OR job_name = :job_name OR target_table = :target_table"
            ),
            params={
                "dataset_key": DATASET_KEY,
                "resource_key": RESOURCE_KEY,
                "job_name": JOB_NAME,
                "target_table": TARGET_TABLE,
            },
        )
    if _has_table(inspector, "dataset_pipeline_mode", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="dataset_pipeline_mode",
            where_clause="dataset_key = :dataset_key",
            params={"dataset_key": DATASET_KEY},
        )
    if _has_table(inspector, "dataset_layer_snapshot_current", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="dataset_layer_snapshot_current",
            where_clause="dataset_key = :dataset_key",
            params={"dataset_key": DATASET_KEY},
        )
    if _has_table(inspector, "dataset_layer_snapshot_history", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="dataset_layer_snapshot_history",
            where_clause="dataset_key = :dataset_key",
            params={"dataset_key": DATASET_KEY},
        )


def _cleanup_rule_tables(inspector: sa.Inspector) -> None:
    if _has_table(inspector, "std_mapping_rule", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="std_mapping_rule",
            where_clause="dataset_key = :dataset_key",
            params={"dataset_key": DATASET_KEY},
        )
    if _has_table(inspector, "std_cleansing_rule", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="std_cleansing_rule",
            where_clause="dataset_key = :dataset_key",
            params={"dataset_key": DATASET_KEY},
        )
    if _has_table(inspector, "resolution_release_stage_status", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="resolution_release_stage_status",
            where_clause=(
                "dataset_key = :dataset_key OR release_id IN "
                f"(SELECT id FROM {OPS_SCHEMA}.resolution_release WHERE dataset_key = :dataset_key)"
            ),
            params={"dataset_key": DATASET_KEY},
        )
    if _has_table(inspector, "resolution_release", schema=OPS_SCHEMA):
        _execute_delete(
            schema=OPS_SCHEMA,
            table_name="resolution_release",
            where_clause="dataset_key = :dataset_key",
            params={"dataset_key": DATASET_KEY},
        )


def _cleanup_foundation_meta(inspector: sa.Inspector) -> None:
    if _has_table(inspector, "dataset_resolution_policy", schema=FOUNDATION_SCHEMA):
        _execute_delete(
            schema=FOUNDATION_SCHEMA,
            table_name="dataset_resolution_policy",
            where_clause="dataset_key = :dataset_key",
            params={"dataset_key": DATASET_KEY},
        )
    if _has_table(inspector, "dataset_source_status", schema=FOUNDATION_SCHEMA):
        _execute_delete(
            schema=FOUNDATION_SCHEMA,
            table_name="dataset_source_status",
            where_clause="dataset_key = :dataset_key",
            params={"dataset_key": DATASET_KEY},
        )


def _drop_factor_table(inspector: sa.Inspector) -> None:
    table_name = "equity_price_restore_factor"
    if not _has_table(inspector, table_name, schema=CORE_SCHEMA):
        return
    index_names = _index_names(inspector, table_name, schema=CORE_SCHEMA)
    if "idx_equity_price_restore_factor_updated_at" in index_names:
        op.drop_index("idx_equity_price_restore_factor_updated_at", table_name=table_name, schema=CORE_SCHEMA)
    if "idx_equity_price_restore_factor_trade_date" in index_names:
        op.drop_index("idx_equity_price_restore_factor_trade_date", table_name=table_name, schema=CORE_SCHEMA)
    op.drop_table(table_name, schema=CORE_SCHEMA)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _cleanup_probe_related(inspector)
    _cleanup_job_schedule_related(inspector)
    _cleanup_job_execution_related(inspector)
    _cleanup_status_and_observability(inspector)
    _cleanup_rule_tables(inspector)
    _cleanup_foundation_meta(inspector)
    _drop_factor_table(inspector)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "equity_price_restore_factor"
    if _has_table(inspector, table_name, schema=CORE_SCHEMA):
        return
    op.create_table(
        table_name,
        sa.Column("ts_code", sa.String(length=16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("cum_factor", sa.Numeric(20, 8), nullable=False),
        sa.Column("single_factor", sa.Numeric(20, 8)),
        sa.Column("event_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("event_ex_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=CORE_SCHEMA,
    )
    op.create_index(
        "idx_equity_price_restore_factor_trade_date",
        table_name,
        ["trade_date"],
        schema=CORE_SCHEMA,
    )
    op.create_index(
        "idx_equity_price_restore_factor_updated_at",
        table_name,
        ["updated_at"],
        schema=CORE_SCHEMA,
    )
