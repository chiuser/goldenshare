from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from psycopg2.extras import RealDictCursor

from orchestrator.defs.bootstrap.stk_mins_event_history_retention import (
    STK_MINS_RETENTION_ASSET_KEYS,
    STK_MINS_RETENTION_KEEP_PARTITION_SET_NAME,
    STK_MINS_RETENTION_KEEP_TRADE_DAY_COUNT,
    STK_MINS_RETENTION_PROTECTED_CHECK_NAMES,
    _build_safety_assertions,
    _candidate_totals,
    _fetch_all,
    _fetch_one,
    _fetch_scalar,
    _normalize_asset_keys,
    _normalize_row,
)


STK_MINS_RETENTION_DEFAULT_SAMPLE_DELETE_ASSET = (
    "gold_stk_mins_qfq_macd_kdj_state_120m"
)


@dataclass(frozen=True)
class StkMinsEventHistoryRetentionSampleDeleteReport:
    sample_asset_key: str
    keep_partition_set_name: str
    keep_trade_day_count: int
    protected_check_names: tuple[str, ...]
    running_or_queued_run_count: int
    keep_partitions: tuple[dict[str, object], ...]
    candidate_totals: dict[str, object]
    candidate_check_counts_by_asset: tuple[dict[str, object], ...]
    candidate_materialization_counts_by_asset: tuple[dict[str, object], ...]
    latest_state_summary_by_asset: tuple[dict[str, object], ...]
    safety_assertions: tuple[dict[str, object], ...]
    delete_counts: tuple[dict[str, object], ...]
    committed: bool

    @property
    def should_stop(self) -> bool:
        return any(not bool(row["passed"]) for row in self.safety_assertions)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "stk_mins_event_history_retention_sample_delete",
            "sample_asset_key": self.sample_asset_key,
            "keep_partition_set_name": self.keep_partition_set_name,
            "keep_trade_day_count": self.keep_trade_day_count,
            "protected_check_names": list(self.protected_check_names),
            "running_or_queued_run_count": self.running_or_queued_run_count,
            "keep_partitions": list(self.keep_partitions),
            "candidate_totals": self.candidate_totals,
            "candidate_check_counts_by_asset": list(
                self.candidate_check_counts_by_asset
            ),
            "candidate_materialization_counts_by_asset": list(
                self.candidate_materialization_counts_by_asset
            ),
            "latest_state_summary_by_asset": list(
                self.latest_state_summary_by_asset
            ),
            "safety_assertions": list(self.safety_assertions),
            "delete_counts": list(self.delete_counts),
            "committed": self.committed,
            "should_stop": self.should_stop,
        }


def execute_stk_mins_event_history_retention_sample_delete(
    connection,
    *,
    sample_asset: str | Sequence[str] = STK_MINS_RETENTION_DEFAULT_SAMPLE_DELETE_ASSET,
    confirm_sample_delete: bool,
    keep_trade_day_count: int = STK_MINS_RETENTION_KEEP_TRADE_DAY_COUNT,
    keep_partition_set_name: str = STK_MINS_RETENTION_KEEP_PARTITION_SET_NAME,
    protected_check_names: Sequence[str] = STK_MINS_RETENTION_PROTECTED_CHECK_NAMES,
) -> StkMinsEventHistoryRetentionSampleDeleteReport:
    if not confirm_sample_delete:
        raise ValueError("sample-delete requires --confirm-sample-delete")
    if keep_trade_day_count <= 0:
        raise ValueError("keep_trade_day_count must be positive")
    if not protected_check_names:
        raise ValueError("protected_check_names must not be empty")

    sample_asset_key = _normalize_single_sample_asset(sample_asset)
    if sample_asset_key not in STK_MINS_RETENTION_ASSET_KEYS:
        raise ValueError(
            f"sample asset is not in stock-mins retention whitelist: {sample_asset_key}"
        )

    _set_write_session(connection)
    params: dict[str, object] = {
        "asset_keys": [sample_asset_key],
        "protected_check_names": list(protected_check_names),
        "keep_partition_set_name": keep_partition_set_name,
        "keep_trade_day_count": keep_trade_day_count,
    }

    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            running_or_queued_run_count = _fetch_scalar(
                cursor,
                _SAMPLE_DELETE_RUNNING_OR_QUEUED_RUN_COUNT_SQL,
            )
            keep_partitions = _fetch_all(
                cursor,
                _SAMPLE_DELETE_KEEP_PARTITIONS_SQL,
                params,
            )
            candidate_check_counts_by_asset = _fetch_all(
                cursor,
                _SAMPLE_DELETE_CANDIDATE_CHECK_COUNTS_BY_ASSET_SQL,
                params,
            )
            candidate_materialization_counts_by_asset = _fetch_all(
                cursor,
                _SAMPLE_DELETE_CANDIDATE_MATERIALIZATION_COUNTS_BY_ASSET_SQL,
                params,
            )
            latest_state_summary_by_asset = _fetch_all(
                cursor,
                _SAMPLE_DELETE_LATEST_STATE_SUMMARY_BY_ASSET_SQL,
                params,
            )
            safety_counts = _fetch_one(
                cursor,
                _SAMPLE_DELETE_SAFETY_COUNTS_SQL,
                params,
            )
            safety_assertions = _build_safety_assertions(
                running_or_queued_run_count=running_or_queued_run_count,
                keep_trade_day_count=keep_trade_day_count,
                keep_partitions=keep_partitions,
                latest_state_summary_by_asset=latest_state_summary_by_asset,
                asset_count=1,
                safety_counts=safety_counts,
            )
            if any(not bool(row["passed"]) for row in safety_assertions):
                raise RuntimeError(
                    "sample-delete safety assertions failed: "
                    + ", ".join(
                        str(row["name"])
                        for row in safety_assertions
                        if not bool(row["passed"])
                    )
                )

            delete_counts = tuple(_execute_delete_steps(cursor, params))

        connection.commit()
        committed = True
    except Exception:
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            rollback()
        raise

    return StkMinsEventHistoryRetentionSampleDeleteReport(
        sample_asset_key=sample_asset_key,
        keep_partition_set_name=keep_partition_set_name,
        keep_trade_day_count=keep_trade_day_count,
        protected_check_names=tuple(protected_check_names),
        running_or_queued_run_count=running_or_queued_run_count,
        keep_partitions=tuple(keep_partitions),
        candidate_totals=_candidate_totals(
            candidate_check_counts_by_asset,
            candidate_materialization_counts_by_asset,
        ),
        candidate_check_counts_by_asset=tuple(candidate_check_counts_by_asset),
        candidate_materialization_counts_by_asset=tuple(
            candidate_materialization_counts_by_asset
        ),
        latest_state_summary_by_asset=tuple(latest_state_summary_by_asset),
        safety_assertions=tuple(safety_assertions),
        delete_counts=delete_counts,
        committed=committed,
    )


def stk_mins_event_history_retention_sample_delete_sql_statements() -> tuple[str, ...]:
    return tuple(sql for _name, sql in _SAMPLE_DELETE_STEPS)


def _normalize_single_sample_asset(sample_asset: str | Sequence[str]) -> str:
    if isinstance(sample_asset, str):
        raw_asset_keys = (sample_asset,)
    else:
        raw_asset_keys = tuple(sample_asset)
    normalized = _normalize_asset_keys(raw_asset_keys)
    if len(normalized) != 1:
        raise ValueError("sample-delete requires exactly one sample asset")
    return normalized[0]


def _set_write_session(connection) -> None:
    set_session = getattr(connection, "set_session", None)
    if callable(set_session):
        set_session(readonly=False, autocommit=False)


def _execute_delete_steps(
    cursor,
    params: Mapping[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for step_name, sql in _SAMPLE_DELETE_STEPS:
        cursor.execute(sql, params)
        rows.append(
            {
                "step": step_name,
                "deleted_row_count": int(getattr(cursor, "rowcount", 0) or 0),
            }
        )
    return rows


def _fetch_delete_preview_all(
    cursor,
    sql: str,
    params: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    cursor.execute(sql, params or {})
    return [_normalize_row(row) for row in cursor.fetchall()]


_SAMPLE_DELETE_COMMON_CANDIDATE_CTES = """
asset_scope AS (
  SELECT unnest(%(asset_keys)s::text[]) AS asset_key
),
keep_partitions AS (
  SELECT partition
  FROM dynamic_partitions
  WHERE partitions_def_name = %(keep_partition_set_name)s
  ORDER BY partition DESC
  LIMIT %(keep_trade_day_count)s
),
latest_materializations AS (
  SELECT
    el.asset_key::text AS asset_key,
    max(el.id) AS latest_materialization_id
  FROM event_logs el
  JOIN asset_scope s
    ON s.asset_key = el.asset_key::text
  WHERE el.dagster_event_type = 'ASSET_MATERIALIZATION'
  GROUP BY el.asset_key::text
),
candidate_checks AS (
  SELECT
    ace.id,
    ace.asset_key::text AS asset_key,
    ace.check_name,
    ace.partition,
    ace.run_id,
    ace.execution_status,
    ace.evaluation_event_storage_id,
    ace.materialization_event_storage_id,
    ace.evaluation_event_timestamp
  FROM asset_check_executions ace
  JOIN asset_scope s
    ON s.asset_key = ace.asset_key::text
  LEFT JOIN keep_partitions k
    ON k.partition = ace.partition
  LEFT JOIN latest_materializations lm
    ON lm.latest_materialization_id = ace.materialization_event_storage_id
  WHERE ace.partition IS NOT NULL
    AND k.partition IS NULL
    AND lm.latest_materialization_id IS NULL
    AND ace.check_name <> ALL(%(protected_check_names)s)
),
candidate_materializations AS (
  SELECT
    el.id,
    el.asset_key::text AS asset_key,
    el.partition,
    el.run_id,
    el.timestamp
  FROM event_logs el
  JOIN asset_scope s
    ON s.asset_key = el.asset_key::text
  LEFT JOIN keep_partitions k
    ON k.partition = el.partition
  LEFT JOIN latest_materializations lm
    ON lm.latest_materialization_id = el.id
  WHERE el.dagster_event_type = 'ASSET_MATERIALIZATION'
    AND el.partition IS NOT NULL
    AND k.partition IS NULL
    AND lm.latest_materialization_id IS NULL
)
"""

_SAMPLE_DELETE_RUNNING_OR_QUEUED_RUN_COUNT_SQL = """
-- query: sample_delete_running_or_queued_run_count
SELECT count(*)::bigint AS running_or_queued_run_count
FROM runs
WHERE status IN ('QUEUED', 'STARTING', 'STARTED', 'CANCELING')
"""

_SAMPLE_DELETE_KEEP_PARTITIONS_SQL = """
-- query: sample_delete_keep_partitions
WITH keep_partitions AS (
  SELECT partition
  FROM dynamic_partitions
  WHERE partitions_def_name = %(keep_partition_set_name)s
  ORDER BY partition DESC
  LIMIT %(keep_trade_day_count)s
)
SELECT partition
FROM keep_partitions
ORDER BY partition
"""

_SAMPLE_DELETE_CANDIDATE_CHECK_COUNTS_BY_ASSET_SQL = f"""
-- query: sample_delete_candidate_check_counts_by_asset
WITH {_SAMPLE_DELETE_COMMON_CANDIDATE_CTES}
SELECT
  c.asset_key,
  count(*)::bigint AS check_candidate_count,
  count(e.id)::bigint AS check_event_candidate_count,
  count(t.id)::bigint AS check_event_tag_candidate_count
FROM candidate_checks c
LEFT JOIN event_logs e
  ON e.id = c.evaluation_event_storage_id
LEFT JOIN asset_event_tags t
  ON t.event_id = c.evaluation_event_storage_id
GROUP BY c.asset_key
ORDER BY c.asset_key
"""

_SAMPLE_DELETE_CANDIDATE_MATERIALIZATION_COUNTS_BY_ASSET_SQL = f"""
-- query: sample_delete_candidate_materialization_counts_by_asset
WITH {_SAMPLE_DELETE_COMMON_CANDIDATE_CTES}
SELECT
  m.asset_key,
  count(*)::bigint AS materialization_candidate_count,
  count(t.id)::bigint AS materialization_event_tag_candidate_count
FROM candidate_materializations m
LEFT JOIN asset_event_tags t
  ON t.event_id = m.id
GROUP BY m.asset_key
ORDER BY m.asset_key
"""

_SAMPLE_DELETE_LATEST_STATE_SUMMARY_BY_ASSET_SQL = """
-- query: sample_delete_latest_state_summary_by_asset
WITH
asset_scope AS (
  SELECT unnest(%(asset_keys)s::text[]) AS asset_key
),
latest_materializations AS (
  SELECT DISTINCT ON (el.asset_key::text)
    el.asset_key::text AS asset_key,
    el.id AS latest_materialization_id,
    el.partition AS latest_partition,
    el.run_id AS latest_run_id,
    el.timestamp AS latest_timestamp
  FROM event_logs el
  JOIN asset_scope s
    ON s.asset_key = el.asset_key::text
  WHERE el.dagster_event_type = 'ASSET_MATERIALIZATION'
  ORDER BY el.asset_key::text, el.id DESC
),
latest_checks AS (
  SELECT
    ace.asset_key::text AS asset_key,
    ace.materialization_event_storage_id,
    count(*)::bigint AS latest_check_count,
    count(*) FILTER (WHERE ace.execution_status = 'SUCCEEDED')::bigint
      AS latest_succeeded_check_count,
    count(*) FILTER (WHERE ace.execution_status <> 'SUCCEEDED')::bigint
      AS latest_non_succeeded_check_count
  FROM asset_check_executions ace
  JOIN latest_materializations lm
    ON lm.latest_materialization_id = ace.materialization_event_storage_id
  GROUP BY ace.asset_key::text, ace.materialization_event_storage_id
)
SELECT
  s.asset_key,
  lm.latest_materialization_id,
  lm.latest_partition,
  lm.latest_run_id,
  lm.latest_timestamp,
  COALESCE(lc.latest_check_count, 0)::bigint AS latest_check_count,
  COALESCE(lc.latest_succeeded_check_count, 0)::bigint
    AS latest_succeeded_check_count,
  COALESCE(lc.latest_non_succeeded_check_count, 0)::bigint
    AS latest_non_succeeded_check_count
FROM asset_scope s
LEFT JOIN latest_materializations lm
  ON lm.asset_key = s.asset_key
LEFT JOIN latest_checks lc
  ON lc.asset_key = s.asset_key
 AND lc.materialization_event_storage_id = lm.latest_materialization_id
ORDER BY s.asset_key
"""

_SAMPLE_DELETE_SAFETY_COUNTS_SQL = f"""
-- query: sample_delete_safety_counts
WITH {_SAMPLE_DELETE_COMMON_CANDIDATE_CTES},
keep_collision_checks AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  JOIN keep_partitions k
    ON k.partition = c.partition
),
keep_collision_materializations AS (
  SELECT count(*)::bigint AS count
  FROM candidate_materializations m
  JOIN keep_partitions k
    ON k.partition = m.partition
),
latest_collision_checks AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  JOIN latest_materializations lm
    ON lm.latest_materialization_id = c.materialization_event_storage_id
),
latest_collision_materializations AS (
  SELECT count(*)::bigint AS count
  FROM candidate_materializations m
  JOIN latest_materializations lm
    ON lm.latest_materialization_id = m.id
),
protected_check_candidates AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  WHERE c.check_name = ANY(%(protected_check_names)s)
),
null_partition_check_candidates AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  WHERE c.partition IS NULL
),
null_partition_materialization_candidates AS (
  SELECT count(*)::bigint AS count
  FROM candidate_materializations m
  WHERE m.partition IS NULL
),
check_event_type_mismatches AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  LEFT JOIN event_logs e
    ON e.id = c.evaluation_event_storage_id
  WHERE e.id IS NULL
     OR e.dagster_event_type <> 'ASSET_CHECK_EVALUATION'
)
SELECT
  (SELECT count FROM keep_collision_checks)
    AS check_keep_partition_collision_count,
  (SELECT count FROM keep_collision_materializations)
    AS materialization_keep_partition_collision_count,
  (SELECT count FROM latest_collision_checks)
    AS check_latest_state_collision_count,
  (SELECT count FROM latest_collision_materializations)
    AS materialization_latest_state_collision_count,
  (SELECT count FROM protected_check_candidates)
    AS protected_check_candidate_count,
  (SELECT count FROM null_partition_check_candidates)
    AS check_null_partition_candidate_count,
  (SELECT count FROM null_partition_materialization_candidates)
    AS materialization_null_partition_candidate_count,
  (SELECT count FROM check_event_type_mismatches)
    AS check_event_type_mismatch_count
"""

_DELETE_CHECK_EVENT_TAGS_SQL = f"""
-- query: delete_check_event_tags
WITH {_SAMPLE_DELETE_COMMON_CANDIDATE_CTES}
DELETE FROM asset_event_tags t
USING candidate_checks c
WHERE t.event_id = c.evaluation_event_storage_id
"""

_DELETE_CHECK_EVENTS_SQL = f"""
-- query: delete_check_events
WITH {_SAMPLE_DELETE_COMMON_CANDIDATE_CTES}
DELETE FROM event_logs e
USING candidate_checks c
WHERE e.id = c.evaluation_event_storage_id
  AND e.dagster_event_type = 'ASSET_CHECK_EVALUATION'
"""

_DELETE_CHECK_EXECUTIONS_SQL = f"""
-- query: delete_check_executions
WITH {_SAMPLE_DELETE_COMMON_CANDIDATE_CTES}
DELETE FROM asset_check_executions ace
USING candidate_checks c
WHERE ace.id = c.id
"""

_DELETE_MATERIALIZATION_EVENT_TAGS_SQL = f"""
-- query: delete_materialization_event_tags
WITH {_SAMPLE_DELETE_COMMON_CANDIDATE_CTES}
DELETE FROM asset_event_tags t
USING candidate_materializations m
WHERE t.event_id = m.id
"""

_DELETE_MATERIALIZATION_EVENTS_SQL = f"""
-- query: delete_materialization_events
WITH {_SAMPLE_DELETE_COMMON_CANDIDATE_CTES}
DELETE FROM event_logs e
USING candidate_materializations m
WHERE e.id = m.id
  AND e.dagster_event_type = 'ASSET_MATERIALIZATION'
"""

_SAMPLE_DELETE_STEPS = (
    ("delete_check_event_tags", _DELETE_CHECK_EVENT_TAGS_SQL),
    ("delete_check_events", _DELETE_CHECK_EVENTS_SQL),
    ("delete_check_executions", _DELETE_CHECK_EXECUTIONS_SQL),
    ("delete_materialization_event_tags", _DELETE_MATERIALIZATION_EVENT_TAGS_SQL),
    ("delete_materialization_events", _DELETE_MATERIALIZATION_EVENTS_SQL),
)
