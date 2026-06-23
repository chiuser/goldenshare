from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from psycopg2.extras import RealDictCursor


PROTECTED_STATUS_CHECK_NAMES = (
    "gold_stk_mins_qfq_factor_repair_plan_evaluated",
    "gold_stk_mins_qfq_macd_kdj_repair_completed_check",
)
DEFAULT_RETIRED_CHECK_NAME_CANDIDATES = (
    "silver_stock_daily_current_listed_only",
)
DEFAULT_SAMPLE_ASSET_KEYS = (
    "ch_share_fact_market_breadth_daily",
    "gold_stock_return_distribution",
    "prod_ch_share_fact_market_breadth_daily",
)
HIGH_VALUE_TABLE_NAMES = (
    "event_logs",
    "asset_check_executions",
    "asset_event_tags",
    "runs",
    "run_tags",
    "dynamic_partitions",
    "instigators",
)
RUNNING_OR_QUEUED_STATUSES = (
    "QUEUED",
    "STARTING",
    "STARTED",
    "CANCELING",
)


@dataclass(frozen=True)
class EventHistoryRetentionDryRunReport:
    table_counts: tuple[dict[str, object], ...]
    table_sizes: tuple[dict[str, object], ...]
    run_status_counts: tuple[dict[str, object], ...]
    running_or_queued_run_count: int
    old_check_candidates_by_asset: tuple[dict[str, object], ...]
    old_materialization_candidates_by_asset: tuple[dict[str, object], ...]
    no_target_check_counts_by_asset: tuple[dict[str, object], ...]
    retired_check_name_candidates: tuple[dict[str, object], ...]
    protected_check_event_counts: tuple[dict[str, object], ...]
    old_check_samples: tuple[dict[str, object], ...]
    old_materialization_samples: tuple[dict[str, object], ...]
    safety_assertions: tuple[dict[str, object], ...]

    @property
    def should_stop(self) -> bool:
        return any(not bool(row["passed"]) for row in self.safety_assertions)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "dry_run_only",
            "should_stop": self.should_stop,
            "table_counts": list(self.table_counts),
            "table_sizes": list(self.table_sizes),
            "run_status_counts": list(self.run_status_counts),
            "running_or_queued_run_count": self.running_or_queued_run_count,
            "old_check_candidates_by_asset": list(
                self.old_check_candidates_by_asset
            ),
            "old_materialization_candidates_by_asset": list(
                self.old_materialization_candidates_by_asset
            ),
            "no_target_check_counts_by_asset": list(
                self.no_target_check_counts_by_asset
            ),
            "retired_check_name_candidates": list(
                self.retired_check_name_candidates
            ),
            "protected_check_event_counts": list(self.protected_check_event_counts),
            "old_check_samples": list(self.old_check_samples),
            "old_materialization_samples": list(self.old_materialization_samples),
            "safety_assertions": list(self.safety_assertions),
        }


@dataclass(frozen=True)
class EventHistoryRetentionSampleDryRunReport:
    asset_keys: tuple[str, ...]
    running_or_queued_run_count: int
    candidate_counts_by_asset: tuple[dict[str, object], ...]
    latest_materialization_samples: tuple[dict[str, object], ...]
    latest_check_samples: tuple[dict[str, object], ...]
    latest_state_summary_by_asset: tuple[dict[str, object], ...]
    no_target_check_counts_by_asset: tuple[dict[str, object], ...]
    protected_check_event_counts: tuple[dict[str, object], ...]
    safety_assertions: tuple[dict[str, object], ...]

    @property
    def should_stop(self) -> bool:
        return any(not bool(row["passed"]) for row in self.safety_assertions)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "sample_dry_run_only",
            "should_stop": self.should_stop,
            "asset_keys": list(self.asset_keys),
            "running_or_queued_run_count": self.running_or_queued_run_count,
            "candidate_counts_by_asset": list(self.candidate_counts_by_asset),
            "latest_materialization_samples": list(
                self.latest_materialization_samples
            ),
            "latest_check_samples": list(self.latest_check_samples),
            "latest_state_summary_by_asset": list(
                self.latest_state_summary_by_asset
            ),
            "no_target_check_counts_by_asset": list(
                self.no_target_check_counts_by_asset
            ),
            "protected_check_event_counts": list(self.protected_check_event_counts),
            "safety_assertions": list(self.safety_assertions),
        }


def collect_event_history_retention_dry_run(
    connection,
    *,
    sample_limit: int = 20,
    protected_check_names: Sequence[str] = PROTECTED_STATUS_CHECK_NAMES,
    retired_check_name_candidates: Sequence[str] = (
        DEFAULT_RETIRED_CHECK_NAME_CANDIDATES
    ),
) -> EventHistoryRetentionDryRunReport:
    if sample_limit <= 0:
        raise ValueError("sample_limit must be positive")
    if not protected_check_names:
        raise ValueError("protected_check_names must not be empty")

    _set_read_only_session(connection)
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        table_counts = _fetch_all(cursor, _TABLE_COUNTS_SQL)
        table_sizes = _fetch_all(cursor, _TABLE_SIZES_SQL)
        run_status_counts = _fetch_all(cursor, _RUN_STATUS_COUNTS_SQL)
        running_or_queued_run_count = _fetch_scalar(
            cursor,
            _RUNNING_OR_QUEUED_RUN_COUNT_SQL,
        )
        old_check_candidates_by_asset = _fetch_all(
            cursor,
            _OLD_CHECK_CANDIDATES_BY_ASSET_SQL,
            {"protected_check_names": list(protected_check_names)},
        )
        old_materialization_candidates_by_asset = _fetch_all(
            cursor,
            _OLD_MATERIALIZATION_CANDIDATES_BY_ASSET_SQL,
        )
        no_target_check_counts_by_asset = _fetch_all(
            cursor,
            _NO_TARGET_CHECK_COUNTS_BY_ASSET_SQL,
        )
        retired_check_candidates = _fetch_all(
            cursor,
            _RETIRED_CHECK_NAME_CANDIDATES_SQL,
            {"retired_check_names": list(retired_check_name_candidates)},
        )
        protected_check_event_counts = _fetch_all(
            cursor,
            _PROTECTED_CHECK_EVENT_COUNTS_SQL,
            {"protected_check_names": list(protected_check_names)},
        )
        old_check_samples = _fetch_all(
            cursor,
            _OLD_CHECK_SAMPLES_SQL,
            {
                "protected_check_names": list(protected_check_names),
                "sample_limit": sample_limit,
            },
        )
        old_materialization_samples = _fetch_all(
            cursor,
            _OLD_MATERIALIZATION_SAMPLES_SQL,
            {"sample_limit": sample_limit},
        )
        safety_assertions = _build_safety_assertions(
            cursor,
            protected_check_names=protected_check_names,
            running_or_queued_run_count=running_or_queued_run_count,
        )
    return EventHistoryRetentionDryRunReport(
        table_counts=tuple(table_counts),
        table_sizes=tuple(table_sizes),
        run_status_counts=tuple(run_status_counts),
        running_or_queued_run_count=running_or_queued_run_count,
        old_check_candidates_by_asset=tuple(old_check_candidates_by_asset),
        old_materialization_candidates_by_asset=tuple(
            old_materialization_candidates_by_asset
        ),
        no_target_check_counts_by_asset=tuple(no_target_check_counts_by_asset),
        retired_check_name_candidates=tuple(retired_check_candidates),
        protected_check_event_counts=tuple(protected_check_event_counts),
        old_check_samples=tuple(old_check_samples),
        old_materialization_samples=tuple(old_materialization_samples),
        safety_assertions=tuple(safety_assertions),
    )


def collect_event_history_retention_sample_dry_run(
    connection,
    *,
    asset_keys: Sequence[str] = DEFAULT_SAMPLE_ASSET_KEYS,
    sample_limit: int = 20,
    protected_check_names: Sequence[str] = PROTECTED_STATUS_CHECK_NAMES,
) -> EventHistoryRetentionSampleDryRunReport:
    if sample_limit <= 0:
        raise ValueError("sample_limit must be positive")
    if not protected_check_names:
        raise ValueError("protected_check_names must not be empty")
    normalized_asset_keys = _normalize_asset_keys(asset_keys)
    if not normalized_asset_keys:
        raise ValueError("asset_keys must not be empty")

    _set_read_only_session(connection)
    params: dict[str, object] = {
        "asset_keys": list(normalized_asset_keys),
        "protected_check_names": list(protected_check_names),
        "sample_limit": sample_limit,
    }
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        running_or_queued_run_count = _fetch_scalar(
            cursor,
            _RUNNING_OR_QUEUED_RUN_COUNT_SQL,
        )
        candidate_counts_by_asset = _fetch_all(
            cursor,
            _SAMPLE_CANDIDATE_COUNTS_BY_ASSET_SQL,
            params,
        )
        latest_materialization_samples = _fetch_all(
            cursor,
            _SAMPLE_LATEST_MATERIALIZATION_SAMPLES_SQL,
            params,
        )
        latest_check_samples = _fetch_all(
            cursor,
            _SAMPLE_LATEST_CHECK_SAMPLES_SQL,
            params,
        )
        latest_state_summary_by_asset = _fetch_all(
            cursor,
            _SAMPLE_LATEST_STATE_SUMMARY_BY_ASSET_SQL,
            params,
        )
        no_target_check_counts_by_asset = _fetch_all(
            cursor,
            _SAMPLE_NO_TARGET_CHECK_COUNTS_BY_ASSET_SQL,
            params,
        )
        protected_check_event_counts = _fetch_all(
            cursor,
            _SAMPLE_PROTECTED_CHECK_EVENT_COUNTS_SQL,
            params,
        )
        safety_assertions = _build_sample_safety_assertions(
            cursor,
            running_or_queued_run_count=running_or_queued_run_count,
            params=params,
        )
    return EventHistoryRetentionSampleDryRunReport(
        asset_keys=normalized_asset_keys,
        running_or_queued_run_count=running_or_queued_run_count,
        candidate_counts_by_asset=tuple(candidate_counts_by_asset),
        latest_materialization_samples=tuple(latest_materialization_samples),
        latest_check_samples=tuple(latest_check_samples),
        latest_state_summary_by_asset=tuple(latest_state_summary_by_asset),
        no_target_check_counts_by_asset=tuple(no_target_check_counts_by_asset),
        protected_check_event_counts=tuple(protected_check_event_counts),
        safety_assertions=tuple(safety_assertions),
    )


def _normalize_asset_keys(asset_keys: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for asset_key in asset_keys:
        value = asset_key.strip()
        if not value:
            continue
        if value.startswith("["):
            parsed = json.loads(value)
            if not isinstance(parsed, list) or not all(
                isinstance(part, str) for part in parsed
            ):
                raise ValueError(f"Invalid Dagster asset key JSON: {asset_key}")
            normalized.append(json.dumps(parsed, separators=(",", ":")))
        else:
            normalized.append(json.dumps([value], separators=(",", ":")))
    return tuple(dict.fromkeys(normalized))


def _set_read_only_session(connection) -> None:
    set_session = getattr(connection, "set_session", None)
    if callable(set_session):
        set_session(readonly=True, autocommit=False)


def _fetch_all(cursor, sql: str, params: Mapping[str, object] | None = None) -> list[dict[str, object]]:
    _assert_select_only_sql(sql)
    cursor.execute(sql, params or {})
    return [_normalize_row(row) for row in cursor.fetchall()]


def _fetch_scalar(cursor, sql: str, params: Mapping[str, object] | None = None) -> int:
    rows = _fetch_all(cursor, sql, params)
    if len(rows) != 1:
        raise RuntimeError(f"Expected one row, got {len(rows)}")
    value = next(iter(rows[0].values()))
    return int(value or 0)


def _normalize_row(row: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_safe(value) for key, value in dict(row).items()}


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _build_safety_assertions(
    cursor,
    *,
    protected_check_names: Sequence[str],
    running_or_queued_run_count: int,
) -> tuple[dict[str, object], ...]:
    latest_collision_count = _fetch_scalar(
        cursor,
        _OLD_CHECK_LATEST_STATE_COLLISION_COUNT_SQL,
        {"protected_check_names": list(protected_check_names)},
    )
    old_materialization_collision_count = _fetch_scalar(
        cursor,
        _OLD_MATERIALIZATION_LATEST_STATE_COLLISION_COUNT_SQL,
    )
    protected_check_candidate_count = _fetch_scalar(
        cursor,
        _PROTECTED_CHECK_CANDIDATE_COUNT_SQL,
        {"protected_check_names": list(protected_check_names)},
    )
    no_target_selected_count = _fetch_scalar(
        cursor,
        _NO_TARGET_CHECK_SELECTED_COUNT_SQL,
        {"protected_check_names": list(protected_check_names)},
    )
    return (
        _safety_assertion(
            "no_running_or_queued_runs",
            running_or_queued_run_count == 0,
            running_or_queued_run_count,
        ),
        _safety_assertion(
            "old_check_candidates_do_not_reference_latest_materialization",
            latest_collision_count == 0,
            latest_collision_count,
        ),
        _safety_assertion(
            "old_materialization_candidates_do_not_include_latest_materialization",
            old_materialization_collision_count == 0,
            old_materialization_collision_count,
        ),
        _safety_assertion(
            "protected_status_checks_are_excluded_from_candidates",
            protected_check_candidate_count == 0,
            protected_check_candidate_count,
        ),
        _safety_assertion(
            "checks_without_materialization_target_are_not_selected",
            no_target_selected_count == 0,
            no_target_selected_count,
        ),
    )


def _build_sample_safety_assertions(
    cursor,
    *,
    running_or_queued_run_count: int,
    params: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    latest_collision_count = _fetch_scalar(
        cursor,
        _SAMPLE_OLD_CHECK_LATEST_STATE_COLLISION_COUNT_SQL,
        params,
    )
    old_materialization_collision_count = _fetch_scalar(
        cursor,
        _SAMPLE_OLD_MATERIALIZATION_LATEST_STATE_COLLISION_COUNT_SQL,
        params,
    )
    protected_check_candidate_count = _fetch_scalar(
        cursor,
        _SAMPLE_PROTECTED_CHECK_CANDIDATE_COUNT_SQL,
        params,
    )
    no_target_selected_count = _fetch_scalar(
        cursor,
        _SAMPLE_NO_TARGET_CHECK_SELECTED_COUNT_SQL,
        params,
    )
    scoped_candidate_count = _fetch_scalar(
        cursor,
        _SAMPLE_SCOPED_CANDIDATE_COUNT_SQL,
        params,
    )
    unscoped_candidate_count = _fetch_scalar(
        cursor,
        _SAMPLE_UNSCOPED_CANDIDATE_COUNT_SQL,
        params,
    )
    assets_with_latest_materialization_count = _fetch_scalar(
        cursor,
        _SAMPLE_ASSETS_WITH_LATEST_MATERIALIZATION_COUNT_SQL,
        params,
    )
    assets_with_latest_check_count = _fetch_scalar(
        cursor,
        _SAMPLE_ASSETS_WITH_LATEST_CHECK_COUNT_SQL,
        params,
    )
    latest_materialization_without_check_count = _fetch_scalar(
        cursor,
        _SAMPLE_LATEST_MATERIALIZATION_WITHOUT_CHECK_COUNT_SQL,
        params,
    )
    requested_asset_count = len(params["asset_keys"])  # type: ignore[arg-type]
    return (
        _safety_assertion(
            "no_running_or_queued_runs",
            running_or_queued_run_count == 0,
            running_or_queued_run_count,
        ),
        _safety_assertion(
            "sample_old_check_candidates_do_not_reference_latest_materialization",
            latest_collision_count == 0,
            latest_collision_count,
        ),
        _safety_assertion(
            "sample_old_materialization_candidates_do_not_include_latest_materialization",
            old_materialization_collision_count == 0,
            old_materialization_collision_count,
        ),
        _safety_assertion(
            "sample_protected_status_checks_are_excluded_from_candidates",
            protected_check_candidate_count == 0,
            protected_check_candidate_count,
        ),
        _safety_assertion(
            "sample_checks_without_materialization_target_are_not_selected",
            no_target_selected_count == 0,
            no_target_selected_count,
        ),
        _safety_assertion(
            "sample_candidates_are_scoped_to_requested_assets",
            scoped_candidate_count == unscoped_candidate_count,
            unscoped_candidate_count - scoped_candidate_count,
        ),
        _safety_assertion(
            "sample_assets_have_latest_materialization_state",
            assets_with_latest_materialization_count == requested_asset_count,
            assets_with_latest_materialization_count,
        ),
        _safety_assertion(
            "sample_assets_have_latest_check_state",
            assets_with_latest_check_count == requested_asset_count,
            assets_with_latest_check_count,
        ),
        _safety_assertion(
            "sample_latest_materializations_all_have_latest_check_state",
            latest_materialization_without_check_count == 0,
            latest_materialization_without_check_count,
        ),
    )


def _safety_assertion(name: str, passed: bool, observed_count: int) -> dict[str, object]:
    return {
        "name": name,
        "passed": passed,
        "observed_count": observed_count,
    }


def _assert_select_only_sql(sql: str) -> None:
    upper = " ".join(sql.upper().split())
    forbidden_tokens = (
        " DELETE ",
        " UPDATE ",
        " INSERT ",
        " UPSERT ",
        " MERGE ",
        " DROP ",
        " ALTER ",
        " TRUNCATE ",
        " VACUUM ",
        " ANALYZE ",
        " CREATE ",
        " GRANT ",
        " REVOKE ",
    )
    padded = f" {upper} "
    for token in forbidden_tokens:
        if token in padded:
            raise ValueError(f"Dry-run SQL must be read-only; found {token.strip()}")


_TABLE_COUNTS_SQL = """
-- query: table_counts
SELECT 'event_logs' AS table_name, count(*)::bigint AS row_count FROM event_logs
UNION ALL
SELECT 'asset_check_executions', count(*)::bigint FROM asset_check_executions
UNION ALL
SELECT 'asset_event_tags', count(*)::bigint FROM asset_event_tags
UNION ALL
SELECT 'runs', count(*)::bigint FROM runs
UNION ALL
SELECT 'run_tags', count(*)::bigint FROM run_tags
UNION ALL
SELECT 'dynamic_partitions', count(*)::bigint FROM dynamic_partitions
UNION ALL
SELECT 'instigators', count(*)::bigint FROM instigators
ORDER BY table_name
"""

_TABLE_SIZES_SQL = """
-- query: table_sizes
SELECT
  relname AS table_name,
  pg_total_relation_size(relid)::bigint AS total_bytes,
  pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
WHERE relname IN (
  'event_logs',
  'asset_check_executions',
  'asset_event_tags',
  'runs',
  'run_tags',
  'dynamic_partitions',
  'instigators'
)
ORDER BY pg_total_relation_size(relid) DESC
"""

_RUN_STATUS_COUNTS_SQL = """
-- query: run_status_counts
SELECT status, count(*)::bigint AS run_count
FROM runs
GROUP BY status
ORDER BY status
"""

_RUNNING_OR_QUEUED_RUN_COUNT_SQL = """
-- query: running_or_queued_run_count
SELECT count(*)::bigint AS running_or_queued_run_count
FROM runs
WHERE status IN ('QUEUED', 'STARTING', 'STARTED', 'CANCELING')
"""

_LATEST_MATERIALIZATIONS_CTE = """
latest_materializations AS (
  SELECT
    asset_key,
    COALESCE(partition, '') AS partition_key,
    max(id) AS latest_materialization_id
  FROM event_logs
  WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
    AND asset_key IS NOT NULL
  GROUP BY asset_key, COALESCE(partition, '')
)
"""

_OLD_CHECK_CANDIDATES_CTE = f"""
{_LATEST_MATERIALIZATIONS_CTE},
old_check_candidates AS (
  SELECT
    ace.id,
    ace.asset_key,
    ace.check_name,
    ace.partition,
    ace.run_id,
    ace.execution_status,
    ace.evaluation_event_storage_id,
    ace.materialization_event_storage_id,
    ace.evaluation_event_timestamp
  FROM asset_check_executions ace
  WHERE ace.materialization_event_storage_id IS NOT NULL
    AND ace.check_name <> ALL(%(protected_check_names)s)
    AND NOT EXISTS (
      SELECT 1
      FROM latest_materializations lm
      WHERE lm.latest_materialization_id = ace.materialization_event_storage_id
    )
)
"""

_SAMPLE_LATEST_MATERIALIZATIONS_CTE = """
sample_latest_materializations AS (
  SELECT
    asset_key,
    COALESCE(partition, '') AS partition_key,
    max(id) AS latest_materialization_id
  FROM event_logs
  WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
    AND asset_key = ANY(%(asset_keys)s)
  GROUP BY asset_key, COALESCE(partition, '')
)
"""

_SAMPLE_OLD_CHECK_CANDIDATES_CTE = f"""
{_SAMPLE_LATEST_MATERIALIZATIONS_CTE},
sample_old_check_candidates AS (
  SELECT
    ace.id,
    ace.asset_key,
    ace.check_name,
    ace.partition,
    ace.run_id,
    ace.execution_status,
    ace.evaluation_event_storage_id,
    ace.materialization_event_storage_id,
    ace.evaluation_event_timestamp
  FROM asset_check_executions ace
  LEFT JOIN sample_latest_materializations lm
    ON lm.latest_materialization_id = ace.materialization_event_storage_id
  WHERE ace.asset_key = ANY(%(asset_keys)s)
    AND ace.materialization_event_storage_id IS NOT NULL
    AND ace.check_name <> ALL(%(protected_check_names)s)
    AND lm.latest_materialization_id IS NULL
)
"""

_OLD_CHECK_CANDIDATES_BY_ASSET_SQL = f"""
-- query: old_check_candidates_by_asset
WITH {_OLD_CHECK_CANDIDATES_CTE}
SELECT
  c.asset_key,
  count(*)::bigint AS old_check_count,
  count(e.id)::bigint AS old_check_event_log_count,
  count(t.id)::bigint AS old_check_event_tag_count
FROM old_check_candidates c
LEFT JOIN event_logs e
  ON e.id = c.evaluation_event_storage_id
LEFT JOIN asset_event_tags t
  ON t.event_id = c.evaluation_event_storage_id
GROUP BY c.asset_key
ORDER BY old_check_count DESC, c.asset_key
"""

_SAMPLE_CANDIDATE_COUNTS_BY_ASSET_SQL = f"""
-- query: sample_candidate_counts_by_asset
WITH
{_SAMPLE_OLD_CHECK_CANDIDATES_CTE},
ranked_materializations AS (
  SELECT
    id,
    asset_key,
    partition,
    run_id,
    timestamp,
    row_number() OVER (
      PARTITION BY asset_key, COALESCE(partition, '')
      ORDER BY id DESC
    ) AS rn
  FROM event_logs
  WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
    AND asset_key = ANY(%(asset_keys)s)
),
sample_old_materialization_candidates AS (
  SELECT *
  FROM ranked_materializations
  WHERE rn > 1
),
old_check_counts AS (
  SELECT
    asset_key,
    count(*)::bigint AS old_check_count
  FROM sample_old_check_candidates
  GROUP BY asset_key
),
old_check_event_log_counts AS (
  SELECT
    c.asset_key,
    count(e.id)::bigint AS old_check_event_log_count
  FROM sample_old_check_candidates c
  JOIN event_logs e
    ON e.id = c.evaluation_event_storage_id
  GROUP BY c.asset_key
),
old_check_tag_counts AS (
  SELECT
    c.asset_key,
    count(t.id)::bigint AS old_check_event_tag_count
  FROM sample_old_check_candidates c
  JOIN asset_event_tags t
    ON t.event_id = c.evaluation_event_storage_id
  GROUP BY c.asset_key
),
old_materialization_counts AS (
  SELECT
    asset_key,
    count(*)::bigint AS old_materialization_count
  FROM sample_old_materialization_candidates
  GROUP BY asset_key
),
old_materialization_tag_counts AS (
  SELECT
    m.asset_key,
    count(t.id)::bigint AS old_materialization_event_tag_count
  FROM sample_old_materialization_candidates m
  JOIN asset_event_tags t
    ON t.event_id = m.id
  GROUP BY m.asset_key
),
sample_assets AS (
  SELECT unnest(%(asset_keys)s::text[]) AS asset_key
)
SELECT
  a.asset_key,
  COALESCE(oc.old_check_count, 0)::bigint AS old_check_count,
  COALESCE(oce.old_check_event_log_count, 0)::bigint
    AS old_check_event_log_count,
  COALESCE(oct.old_check_event_tag_count, 0)::bigint AS old_check_event_tag_count,
  COALESCE(om.old_materialization_count, 0)::bigint
    AS old_materialization_count,
  COALESCE(omt.old_materialization_event_tag_count, 0)::bigint
    AS old_materialization_event_tag_count
FROM sample_assets a
LEFT JOIN old_check_counts oc
  ON oc.asset_key = a.asset_key
LEFT JOIN old_check_event_log_counts oce
  ON oce.asset_key = a.asset_key
LEFT JOIN old_check_tag_counts oct
  ON oct.asset_key = a.asset_key
LEFT JOIN old_materialization_counts om
  ON om.asset_key = a.asset_key
LEFT JOIN old_materialization_tag_counts omt
  ON omt.asset_key = a.asset_key
ORDER BY a.asset_key
"""

_OLD_MATERIALIZATION_CANDIDATES_CTE = """
ranked_materializations AS (
  SELECT
    id,
    asset_key,
    partition,
    run_id,
    timestamp,
    row_number() OVER (
      PARTITION BY asset_key, COALESCE(partition, '')
      ORDER BY id DESC
    ) AS rn
  FROM event_logs
  WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
    AND asset_key IS NOT NULL
)
"""

_SAMPLE_LATEST_MATERIALIZATION_SAMPLES_SQL = f"""
-- query: sample_latest_materialization_samples
WITH {_SAMPLE_LATEST_MATERIALIZATIONS_CTE},
sample_latest_materialization_rows AS (
  SELECT
    base.asset_key,
    NULLIF(base.partition_key, '') AS partition,
    base.latest_materialization_id,
    e.run_id,
    e.timestamp,
    row_number() OVER (
      PARTITION BY base.asset_key
      ORDER BY base.latest_materialization_id DESC
    ) AS rn
  FROM sample_latest_materializations base
  JOIN event_logs e
    ON e.id = base.latest_materialization_id
)
SELECT
  asset_key,
  partition,
  latest_materialization_id,
  run_id,
  timestamp
FROM sample_latest_materialization_rows
WHERE rn <= %(sample_limit)s
ORDER BY asset_key, latest_materialization_id DESC
"""

_SAMPLE_LATEST_CHECK_SAMPLES_SQL = f"""
-- query: sample_latest_check_samples
WITH {_SAMPLE_LATEST_MATERIALIZATIONS_CTE},
latest_check_rows AS (
  SELECT
    ace.asset_key,
    ace.check_name,
    ace.partition,
    ace.run_id,
    ace.execution_status,
    ace.evaluation_event_storage_id,
    ace.materialization_event_storage_id,
    ace.evaluation_event_timestamp,
    row_number() OVER (
      PARTITION BY ace.asset_key, ace.check_name, COALESCE(ace.partition, '')
      ORDER BY ace.evaluation_event_storage_id DESC NULLS LAST, ace.id DESC
    ) AS latest_check_rn,
    row_number() OVER (
      PARTITION BY ace.asset_key
      ORDER BY ace.evaluation_event_storage_id DESC NULLS LAST, ace.id DESC
    ) AS sample_rn
  FROM asset_check_executions ace
  JOIN sample_latest_materializations lm
    ON lm.latest_materialization_id = ace.materialization_event_storage_id
)
SELECT
  asset_key,
  check_name,
  partition,
  run_id,
  execution_status,
  evaluation_event_storage_id,
  materialization_event_storage_id,
  evaluation_event_timestamp
FROM latest_check_rows
WHERE latest_check_rn = 1
  AND sample_rn <= %(sample_limit)s
ORDER BY asset_key, evaluation_event_storage_id DESC NULLS LAST
"""

_SAMPLE_LATEST_STATE_SUMMARY_BY_ASSET_SQL = f"""
-- query: sample_latest_state_summary_by_asset
WITH {_SAMPLE_LATEST_MATERIALIZATIONS_CTE},
latest_check_rows AS (
  SELECT
    ace.asset_key,
    ace.check_name,
    ace.execution_status,
    ace.evaluation_event_storage_id,
    ace.materialization_event_storage_id,
    row_number() OVER (
      PARTITION BY ace.materialization_event_storage_id, ace.check_name
      ORDER BY ace.evaluation_event_storage_id DESC NULLS LAST, ace.id DESC
    ) AS rn
  FROM asset_check_executions ace
  JOIN sample_latest_materializations lm
    ON lm.latest_materialization_id = ace.materialization_event_storage_id
)
SELECT
  lm.asset_key,
  count(DISTINCT lm.latest_materialization_id)::bigint
    AS latest_materialization_count,
  count(DISTINCT c.materialization_event_storage_id)
    FILTER (WHERE c.rn = 1)
    AS latest_materialization_with_check_count,
  (
    count(DISTINCT lm.latest_materialization_id)
    - count(DISTINCT c.materialization_event_storage_id)
      FILTER (WHERE c.rn = 1)
  )::bigint AS latest_materialization_without_check_count,
  count(c.evaluation_event_storage_id)
    FILTER (WHERE c.rn = 1)
    AS latest_check_count,
  count(c.evaluation_event_storage_id)
    FILTER (WHERE c.rn = 1 AND c.execution_status = 'SUCCEEDED')
    AS latest_succeeded_check_count,
  count(c.evaluation_event_storage_id)
    FILTER (WHERE c.rn = 1 AND c.execution_status <> 'SUCCEEDED')
    AS latest_non_succeeded_check_count
FROM sample_latest_materializations lm
LEFT JOIN latest_check_rows c
  ON c.asset_key = lm.asset_key
  AND c.materialization_event_storage_id = lm.latest_materialization_id
GROUP BY lm.asset_key
ORDER BY lm.asset_key
"""

_OLD_MATERIALIZATION_CANDIDATES_BY_ASSET_SQL = f"""
-- query: old_materialization_candidates_by_asset
WITH {_OLD_MATERIALIZATION_CANDIDATES_CTE}
SELECT
  m.asset_key,
  count(*)::bigint AS old_materialization_count,
  count(t.id)::bigint AS old_materialization_event_tag_count
FROM ranked_materializations m
LEFT JOIN asset_event_tags t
  ON t.event_id = m.id
WHERE m.rn > 1
GROUP BY m.asset_key
ORDER BY old_materialization_count DESC, m.asset_key
"""

_SAMPLE_NO_TARGET_CHECK_COUNTS_BY_ASSET_SQL = """
-- query: sample_no_target_check_counts_by_asset
SELECT
  asset_key,
  count(*)::bigint AS no_target_check_count
FROM asset_check_executions
WHERE materialization_event_storage_id IS NULL
  AND asset_key = ANY(%(asset_keys)s)
GROUP BY asset_key
ORDER BY no_target_check_count DESC, asset_key
"""

_SAMPLE_PROTECTED_CHECK_EVENT_COUNTS_SQL = """
-- query: sample_protected_check_event_counts
SELECT
  check_name,
  asset_key,
  count(*)::bigint AS check_event_count,
  min(evaluation_event_timestamp) AS first_seen_at,
  max(evaluation_event_timestamp) AS last_seen_at
FROM asset_check_executions
WHERE check_name = ANY(%(protected_check_names)s)
  AND asset_key = ANY(%(asset_keys)s)
GROUP BY check_name, asset_key
ORDER BY check_name, asset_key
"""

_NO_TARGET_CHECK_COUNTS_BY_ASSET_SQL = """
-- query: no_target_check_counts_by_asset
SELECT
  asset_key,
  count(*)::bigint AS no_target_check_count
FROM asset_check_executions
WHERE materialization_event_storage_id IS NULL
GROUP BY asset_key
ORDER BY no_target_check_count DESC, asset_key
"""

_RETIRED_CHECK_NAME_CANDIDATES_SQL = """
-- query: retired_check_name_candidates
SELECT
  check_name,
  asset_key,
  count(*)::bigint AS check_event_count,
  min(evaluation_event_timestamp) AS first_seen_at,
  max(evaluation_event_timestamp) AS last_seen_at
FROM asset_check_executions
WHERE check_name = ANY(%(retired_check_names)s)
GROUP BY check_name, asset_key
ORDER BY check_event_count DESC, check_name, asset_key
"""

_PROTECTED_CHECK_EVENT_COUNTS_SQL = """
-- query: protected_check_event_counts
SELECT
  check_name,
  asset_key,
  count(*)::bigint AS check_event_count,
  min(evaluation_event_timestamp) AS first_seen_at,
  max(evaluation_event_timestamp) AS last_seen_at
FROM asset_check_executions
WHERE check_name = ANY(%(protected_check_names)s)
GROUP BY check_name, asset_key
ORDER BY check_name, asset_key
"""

_OLD_CHECK_SAMPLES_SQL = f"""
-- query: old_check_samples
WITH {_OLD_CHECK_CANDIDATES_CTE}
SELECT
  asset_key,
  check_name,
  partition,
  run_id,
  execution_status,
  evaluation_event_storage_id,
  materialization_event_storage_id,
  evaluation_event_timestamp
FROM old_check_candidates
ORDER BY evaluation_event_storage_id DESC NULLS LAST, id DESC
LIMIT %(sample_limit)s
"""

_OLD_MATERIALIZATION_SAMPLES_SQL = f"""
-- query: old_materialization_samples
WITH {_OLD_MATERIALIZATION_CANDIDATES_CTE}
SELECT
  asset_key,
  partition,
  run_id,
  id AS event_storage_id,
  timestamp
FROM ranked_materializations
WHERE rn > 1
ORDER BY id DESC
LIMIT %(sample_limit)s
"""

_OLD_CHECK_LATEST_STATE_COLLISION_COUNT_SQL = f"""
-- query: old_check_latest_state_collision_count
WITH {_OLD_CHECK_CANDIDATES_CTE}
SELECT count(*)::bigint AS collision_count
FROM old_check_candidates c
JOIN latest_materializations lm
  ON lm.latest_materialization_id = c.materialization_event_storage_id
"""

_OLD_MATERIALIZATION_LATEST_STATE_COLLISION_COUNT_SQL = f"""
-- query: old_materialization_latest_state_collision_count
WITH {_OLD_MATERIALIZATION_CANDIDATES_CTE}
SELECT count(*)::bigint AS collision_count
FROM ranked_materializations
WHERE rn > 1
  AND id IN (
    SELECT max(id)
    FROM event_logs
    WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
      AND asset_key IS NOT NULL
    GROUP BY asset_key, COALESCE(partition, '')
  )
"""

_PROTECTED_CHECK_CANDIDATE_COUNT_SQL = f"""
-- query: protected_check_candidate_count
WITH {_OLD_CHECK_CANDIDATES_CTE}
SELECT count(*)::bigint AS protected_check_candidate_count
FROM old_check_candidates
WHERE check_name = ANY(%(protected_check_names)s)
"""

_NO_TARGET_CHECK_SELECTED_COUNT_SQL = f"""
-- query: no_target_check_selected_count
WITH {_OLD_CHECK_CANDIDATES_CTE}
SELECT count(*)::bigint AS no_target_selected_count
FROM old_check_candidates
WHERE materialization_event_storage_id IS NULL
"""

_SAMPLE_OLD_CHECK_LATEST_STATE_COLLISION_COUNT_SQL = f"""
-- query: sample_old_check_latest_state_collision_count
WITH {_SAMPLE_OLD_CHECK_CANDIDATES_CTE}
SELECT count(*)::bigint AS collision_count
FROM sample_old_check_candidates c
JOIN sample_latest_materializations lm
  ON lm.latest_materialization_id = c.materialization_event_storage_id
"""

_SAMPLE_OLD_MATERIALIZATION_LATEST_STATE_COLLISION_COUNT_SQL = f"""
-- query: sample_old_materialization_latest_state_collision_count
WITH {_OLD_MATERIALIZATION_CANDIDATES_CTE}
SELECT count(*)::bigint AS collision_count
FROM ranked_materializations
WHERE asset_key = ANY(%(asset_keys)s)
  AND rn > 1
  AND id IN (
    SELECT max(id)
    FROM event_logs
    WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
      AND asset_key = ANY(%(asset_keys)s)
    GROUP BY asset_key, COALESCE(partition, '')
  )
"""

_SAMPLE_PROTECTED_CHECK_CANDIDATE_COUNT_SQL = f"""
-- query: sample_protected_check_candidate_count
WITH {_SAMPLE_OLD_CHECK_CANDIDATES_CTE}
SELECT count(*)::bigint AS protected_check_candidate_count
FROM sample_old_check_candidates
WHERE check_name = ANY(%(protected_check_names)s)
"""

_SAMPLE_NO_TARGET_CHECK_SELECTED_COUNT_SQL = f"""
-- query: sample_no_target_check_selected_count
WITH {_SAMPLE_OLD_CHECK_CANDIDATES_CTE}
SELECT count(*)::bigint AS no_target_selected_count
FROM sample_old_check_candidates
WHERE materialization_event_storage_id IS NULL
"""

_SAMPLE_SCOPED_CANDIDATE_COUNT_SQL = f"""
-- query: sample_scoped_candidate_count
WITH {_SAMPLE_OLD_CHECK_CANDIDATES_CTE}
SELECT count(*)::bigint AS scoped_candidate_count
FROM sample_old_check_candidates
"""

_SAMPLE_UNSCOPED_CANDIDATE_COUNT_SQL = f"""
-- query: sample_unscoped_candidate_count
WITH {_OLD_CHECK_CANDIDATES_CTE}
SELECT count(*)::bigint AS unscoped_candidate_count
FROM old_check_candidates
WHERE asset_key = ANY(%(asset_keys)s)
"""

_SAMPLE_ASSETS_WITH_LATEST_MATERIALIZATION_COUNT_SQL = f"""
-- query: sample_assets_with_latest_materialization_count
WITH {_SAMPLE_LATEST_MATERIALIZATIONS_CTE}
SELECT count(DISTINCT asset_key)::bigint AS assets_with_latest_materialization_count
FROM sample_latest_materializations
"""

_SAMPLE_ASSETS_WITH_LATEST_CHECK_COUNT_SQL = f"""
-- query: sample_assets_with_latest_check_count
WITH {_SAMPLE_LATEST_MATERIALIZATIONS_CTE}
SELECT count(DISTINCT ace.asset_key)::bigint AS assets_with_latest_check_count
FROM asset_check_executions ace
JOIN sample_latest_materializations lm
  ON lm.latest_materialization_id = ace.materialization_event_storage_id
"""

_SAMPLE_LATEST_MATERIALIZATION_WITHOUT_CHECK_COUNT_SQL = f"""
-- query: sample_latest_materialization_without_check_count
WITH {_SAMPLE_LATEST_MATERIALIZATIONS_CTE}
SELECT count(*)::bigint AS latest_materialization_without_check_count
FROM sample_latest_materializations lm
WHERE NOT EXISTS (
  SELECT 1
  FROM asset_check_executions ace
  WHERE ace.materialization_event_storage_id = lm.latest_materialization_id
)
"""


def dry_run_sql_statements() -> tuple[str, ...]:
    return (
        _TABLE_COUNTS_SQL,
        _TABLE_SIZES_SQL,
        _RUN_STATUS_COUNTS_SQL,
        _RUNNING_OR_QUEUED_RUN_COUNT_SQL,
        _OLD_CHECK_CANDIDATES_BY_ASSET_SQL,
        _OLD_MATERIALIZATION_CANDIDATES_BY_ASSET_SQL,
        _NO_TARGET_CHECK_COUNTS_BY_ASSET_SQL,
        _RETIRED_CHECK_NAME_CANDIDATES_SQL,
        _PROTECTED_CHECK_EVENT_COUNTS_SQL,
        _OLD_CHECK_SAMPLES_SQL,
        _OLD_MATERIALIZATION_SAMPLES_SQL,
        _OLD_CHECK_LATEST_STATE_COLLISION_COUNT_SQL,
        _OLD_MATERIALIZATION_LATEST_STATE_COLLISION_COUNT_SQL,
        _PROTECTED_CHECK_CANDIDATE_COUNT_SQL,
        _NO_TARGET_CHECK_SELECTED_COUNT_SQL,
    )


def sample_dry_run_sql_statements() -> tuple[str, ...]:
    return (
        _RUNNING_OR_QUEUED_RUN_COUNT_SQL,
        _SAMPLE_CANDIDATE_COUNTS_BY_ASSET_SQL,
        _SAMPLE_LATEST_MATERIALIZATION_SAMPLES_SQL,
        _SAMPLE_LATEST_CHECK_SAMPLES_SQL,
        _SAMPLE_LATEST_STATE_SUMMARY_BY_ASSET_SQL,
        _SAMPLE_NO_TARGET_CHECK_COUNTS_BY_ASSET_SQL,
        _SAMPLE_PROTECTED_CHECK_EVENT_COUNTS_SQL,
        _SAMPLE_OLD_CHECK_LATEST_STATE_COLLISION_COUNT_SQL,
        _SAMPLE_OLD_MATERIALIZATION_LATEST_STATE_COLLISION_COUNT_SQL,
        _SAMPLE_PROTECTED_CHECK_CANDIDATE_COUNT_SQL,
        _SAMPLE_NO_TARGET_CHECK_SELECTED_COUNT_SQL,
        _SAMPLE_SCOPED_CANDIDATE_COUNT_SQL,
        _SAMPLE_UNSCOPED_CANDIDATE_COUNT_SQL,
        _SAMPLE_ASSETS_WITH_LATEST_MATERIALIZATION_COUNT_SQL,
        _SAMPLE_ASSETS_WITH_LATEST_CHECK_COUNT_SQL,
        _SAMPLE_LATEST_MATERIALIZATION_WITHOUT_CHECK_COUNT_SQL,
    )
