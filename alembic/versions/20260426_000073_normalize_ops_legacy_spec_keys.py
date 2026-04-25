"""normalize ops legacy spec keys and add strict spec constraints

Revision ID: 20260426_000073
Revises: 20260424_000072
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_000073"
down_revision = "20260424_000072"
branch_labels = None
depends_on = None

OPS_SCHEMA = "ops"
LEGACY_PREFIX_GROUP = (
    "(?:sync_daily|sync_history|sync_minute_history|backfill_trade_cal|"
    "backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|"
    "backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)"
)
LEGACY_SPEC_PATTERN = rf"^{LEGACY_PREFIX_GROUP}\.([A-Za-z0-9_]+)$"
LEGACY_PREFIX_PATTERN = rf"^{LEGACY_PREFIX_GROUP}\."
LEGACY_UNIT_PATTERN = rf"^{LEGACY_PREFIX_GROUP}\.([A-Za-z0-9_]+)(:.*)?$"

CHECK_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    (
        "job_execution",
        "ck_job_execution_dataset_action_spec_key_maintain",
        f"(spec_type <> 'dataset_action') OR (spec_key LIKE '%.maintain' AND spec_key !~ '{LEGACY_PREFIX_PATTERN}')",
    ),
    (
        "job_execution",
        "ck_job_execution_spec_key_no_legacy_prefix",
        f"spec_key !~ '{LEGACY_PREFIX_PATTERN}'",
    ),
    (
        "job_schedule",
        "ck_job_schedule_dataset_action_spec_key_maintain",
        f"(spec_type <> 'dataset_action') OR (spec_key LIKE '%.maintain' AND spec_key !~ '{LEGACY_PREFIX_PATTERN}')",
    ),
    (
        "job_schedule",
        "ck_job_schedule_spec_key_no_legacy_prefix",
        f"spec_key !~ '{LEGACY_PREFIX_PATTERN}'",
    ),
    (
        "dataset_status_snapshot",
        "ck_dataset_status_snapshot_primary_spec_key_maintain",
        (
            "primary_execution_spec_key IS NULL OR "
            f"(primary_execution_spec_key LIKE '%.maintain' AND primary_execution_spec_key !~ '{LEGACY_PREFIX_PATTERN}')"
        ),
    ),
    (
        "job_execution_step",
        "ck_job_execution_step_step_key_no_legacy_prefix",
        f"step_key !~ '{LEGACY_PREFIX_PATTERN}'",
    ),
    (
        "job_execution_step",
        "ck_job_execution_step_blocked_key_no_legacy_prefix",
        f"blocked_by_step_key IS NULL OR blocked_by_step_key !~ '{LEGACY_PREFIX_PATTERN}'",
    ),
    (
        "job_execution_unit",
        "ck_job_execution_unit_unit_id_no_legacy_prefix",
        f"unit_id !~ '{LEGACY_PREFIX_PATTERN}'",
    ),
    (
        "job_execution_event",
        "ck_job_execution_event_unit_id_no_legacy_prefix",
        f"unit_id IS NULL OR unit_id !~ '{LEGACY_PREFIX_PATTERN}'",
    ),
)


def _has_table(inspector: sa.Inspector, table_name: str, *, schema: str) -> bool:
    return inspector.has_table(table_name, schema=schema)


def _column_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name, schema=schema)}


def _check_names(inspector: sa.Inspector, table_name: str, *, schema: str) -> set[str]:
    try:
        checks = inspector.get_check_constraints(table_name, schema=schema)
    except NotImplementedError:
        return set()
    return {item["name"] for item in checks if item.get("name")}


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str, *, schema: str) -> bool:
    if not _has_table(inspector, table_name, schema=schema):
        return False
    return column_name in _column_names(inspector, table_name, schema=schema)


def _normalize_legacy_spec_data(inspector: sa.Inspector) -> None:
    if _has_column(inspector, "job_execution", "spec_key", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.job_execution
                SET
                  spec_type = 'dataset_action',
                  spec_key = regexp_replace(spec_key, '{LEGACY_SPEC_PATTERN}', '\\1.maintain'),
                  dataset_key = regexp_replace(spec_key, '{LEGACY_SPEC_PATTERN}', '\\1')
                WHERE spec_key ~ '{LEGACY_SPEC_PATTERN}'
                """
            )
        )

    if _has_column(inspector, "job_schedule", "spec_key", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.job_schedule
                SET
                  spec_type = 'dataset_action',
                  spec_key = regexp_replace(spec_key, '{LEGACY_SPEC_PATTERN}', '\\1.maintain')
                WHERE spec_key ~ '{LEGACY_SPEC_PATTERN}'
                """
            )
        )

    if _has_column(inspector, "dataset_status_snapshot", "primary_execution_spec_key", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.dataset_status_snapshot
                SET primary_execution_spec_key = regexp_replace(primary_execution_spec_key, '{LEGACY_SPEC_PATTERN}', '\\1.maintain')
                WHERE primary_execution_spec_key ~ '{LEGACY_SPEC_PATTERN}'
                """
            )
        )

    if _has_column(inspector, "job_execution_step", "step_key", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.job_execution_step
                SET step_key = regexp_replace(step_key, '{LEGACY_SPEC_PATTERN}', '\\1.maintain')
                WHERE step_key ~ '{LEGACY_SPEC_PATTERN}'
                """
            )
        )
    if _has_column(inspector, "job_execution_step", "blocked_by_step_key", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.job_execution_step
                SET blocked_by_step_key = regexp_replace(blocked_by_step_key, '{LEGACY_SPEC_PATTERN}', '\\1.maintain')
                WHERE blocked_by_step_key ~ '{LEGACY_SPEC_PATTERN}'
                """
            )
        )
    if _has_column(inspector, "job_execution_step", "depends_on_step_keys_json", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.job_execution_step AS s
                SET depends_on_step_keys_json = (
                  SELECT COALESCE(
                    jsonb_agg(
                      CASE
                        WHEN item.value ~ '{LEGACY_SPEC_PATTERN}'
                          THEN regexp_replace(item.value, '{LEGACY_SPEC_PATTERN}', '\\1.maintain')
                        ELSE item.value
                      END
                    ),
                    '[]'::jsonb
                  )::json
                  FROM jsonb_array_elements_text(COALESCE(s.depends_on_step_keys_json::jsonb, '[]'::jsonb)) AS item(value)
                )
                WHERE EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(COALESCE(s.depends_on_step_keys_json::jsonb, '[]'::jsonb)) AS item(value)
                  WHERE item.value ~ '{LEGACY_SPEC_PATTERN}'
                )
                """
            )
        )

    if _has_column(inspector, "job_execution_unit", "unit_id", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.job_execution_unit
                SET unit_id = regexp_replace(unit_id, '{LEGACY_UNIT_PATTERN}', '\\1.maintain\\2')
                WHERE unit_id ~ '{LEGACY_PREFIX_PATTERN}'
                """
            )
        )

    if _has_column(inspector, "job_execution_event", "unit_id", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.job_execution_event
                SET unit_id = regexp_replace(unit_id, '{LEGACY_UNIT_PATTERN}', '\\1.maintain\\2')
                WHERE unit_id ~ '{LEGACY_PREFIX_PATTERN}'
                """
            )
        )

    if _has_column(inspector, "config_revision", "before_json", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.config_revision
                SET before_json = jsonb_set(
                  jsonb_set(
                    before_json::jsonb,
                    '{{spec_key}}',
                    to_jsonb(regexp_replace(before_json->>'spec_key', '{LEGACY_SPEC_PATTERN}', '\\1.maintain')),
                    false
                  ),
                  '{{spec_type}}',
                  to_jsonb('dataset_action'::text),
                  true
                )::json
                WHERE object_type = 'job_schedule'
                  AND before_json IS NOT NULL
                  AND COALESCE(before_json->>'spec_key', '') ~ '{LEGACY_SPEC_PATTERN}'
                """
            )
        )
    if _has_column(inspector, "config_revision", "after_json", schema=OPS_SCHEMA):
        op.execute(
            sa.text(
                f"""
                UPDATE {OPS_SCHEMA}.config_revision
                SET after_json = jsonb_set(
                  jsonb_set(
                    after_json::jsonb,
                    '{{spec_key}}',
                    to_jsonb(regexp_replace(after_json->>'spec_key', '{LEGACY_SPEC_PATTERN}', '\\1.maintain')),
                    false
                  ),
                  '{{spec_type}}',
                  to_jsonb('dataset_action'::text),
                  true
                )::json
                WHERE object_type = 'job_schedule'
                  AND after_json IS NOT NULL
                  AND COALESCE(after_json->>'spec_key', '') ~ '{LEGACY_SPEC_PATTERN}'
                """
            )
        )

    checks: tuple[tuple[str, str], ...] = (
        ("job_execution", "spec_key"),
        ("job_schedule", "spec_key"),
        ("dataset_status_snapshot", "primary_execution_spec_key"),
        ("job_execution_step", "step_key"),
        ("job_execution_step", "blocked_by_step_key"),
        ("job_execution_unit", "unit_id"),
        ("job_execution_event", "unit_id"),
    )
    for table_name, column_name in checks:
        if not _has_column(inspector, table_name, column_name, schema=OPS_SCHEMA):
            continue
        value = op.get_bind().execute(
            sa.text(
                f"""
                SELECT count(*)
                FROM {OPS_SCHEMA}.{table_name}
                WHERE {column_name} IS NOT NULL
                  AND {column_name} ~ '{LEGACY_PREFIX_PATTERN}'
                """
            )
        ).scalar_one()
        if int(value or 0) > 0:
            raise RuntimeError(f"legacy spec_key cleanup incomplete: {OPS_SCHEMA}.{table_name}.{column_name}")


def _add_constraints(inspector: sa.Inspector) -> None:
    for table_name, constraint_name, expression in CHECK_CONSTRAINTS:
        if not _has_table(inspector, table_name, schema=OPS_SCHEMA):
            continue
        if constraint_name in _check_names(inspector, table_name, schema=OPS_SCHEMA):
            continue
        op.create_check_constraint(
            constraint_name,
            table_name,
            expression,
            schema=OPS_SCHEMA,
        )


def _drop_constraints(inspector: sa.Inspector) -> None:
    for table_name, constraint_name, _ in CHECK_CONSTRAINTS:
        if not _has_table(inspector, table_name, schema=OPS_SCHEMA):
            continue
        if constraint_name not in _check_names(inspector, table_name, schema=OPS_SCHEMA):
            continue
        op.drop_constraint(
            constraint_name,
            table_name,
            type_="check",
            schema=OPS_SCHEMA,
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    _normalize_legacy_spec_data(inspector)
    _add_constraints(inspector)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    _drop_constraints(inspector)
