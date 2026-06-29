from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from psycopg2.extras import RealDictCursor

from orchestrator.defs.bootstrap.stk_mins_event_history_retention import (
    RUNNING_OR_QUEUED_STATUSES,
    _fetch_all,
    _fetch_one,
    _fetch_scalar,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
)


GOLD_STOCK_DAILY_QFQ_RESET_ASSET_KEY = json.dumps(
    ["gold_stock_daily_qfq"],
    separators=(",", ":"),
)
GOLD_STOCK_DAILY_QFQ_RESET_PROTECTED_CHECK_NAMES = (
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
)
GOLD_STOCK_DAILY_QFQ_RESET_SAMPLE_LIMIT = 20


@dataclass(frozen=True)
class GoldStockDailyQfqHistoryResetReport:
    lake_root: str
    asset_key: str
    protected_check_names: tuple[str, ...]
    backup_path: str | None
    apply: bool
    running_or_queued_run_count: int
    lake_file_candidates: tuple[dict[str, object], ...]
    lake_file_candidate_count: int
    lake_file_candidate_total_bytes: int
    event_candidate_counts: dict[str, object]
    protected_check_event_counts: tuple[dict[str, object], ...]
    event_candidate_samples: tuple[dict[str, object], ...]
    safety_assertions: tuple[dict[str, object], ...]
    delete_counts: tuple[dict[str, object], ...]
    deleted_lake_file_count: int
    committed: bool

    @property
    def should_stop(self) -> bool:
        return any(not bool(row["passed"]) for row in self.safety_assertions)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "gold_stock_daily_qfq_history_reset",
            "lake_root": self.lake_root,
            "asset_key": self.asset_key,
            "protected_check_names": list(self.protected_check_names),
            "backup_path": self.backup_path,
            "apply": self.apply,
            "running_or_queued_run_count": self.running_or_queued_run_count,
            "lake_file_candidate_count": self.lake_file_candidate_count,
            "lake_file_candidate_total_bytes": self.lake_file_candidate_total_bytes,
            "sample_lake_file_candidates": list(self.lake_file_candidates),
            "event_candidate_counts": self.event_candidate_counts,
            "protected_check_event_counts": list(self.protected_check_event_counts),
            "event_candidate_samples": list(self.event_candidate_samples),
            "safety_assertions": list(self.safety_assertions),
            "should_stop": self.should_stop,
            "delete_counts": list(self.delete_counts),
            "deleted_lake_file_count": self.deleted_lake_file_count,
            "committed": self.committed,
        }


def execute_gold_stock_daily_qfq_history_reset(
    connection,
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    apply: bool = False,
    confirm_reset: bool = False,
    backup_path: str | None = None,
    delete_lake_files: bool = False,
    delete_dagster_events: bool = False,
    sample_limit: int = GOLD_STOCK_DAILY_QFQ_RESET_SAMPLE_LIMIT,
    protected_check_names: Sequence[str] = (
        GOLD_STOCK_DAILY_QFQ_RESET_PROTECTED_CHECK_NAMES
    ),
) -> GoldStockDailyQfqHistoryResetReport:
    if sample_limit <= 0:
        raise ValueError("sample_limit must be positive")
    if not protected_check_names:
        raise ValueError("protected_check_names must not be empty")
    if apply:
        if not confirm_reset:
            raise ValueError("history reset apply requires --confirm-reset")
        if not backup_path:
            raise ValueError("history reset apply requires --backup-path")
        if not Path(backup_path).exists():
            raise FileNotFoundError(f"backup path does not exist: {backup_path}")
        if delete_lake_files == delete_dagster_events:
            raise ValueError(
                "history reset apply requires exactly one delete scope; run lake "
                "file and Dagster event deletes as separate approved steps"
            )

    lake_file_candidates = _discover_lake_file_candidates(lake_root, sample_limit)
    all_lake_file_paths = _discover_lake_file_paths(lake_root)
    params: dict[str, object] = {
        "asset_key": GOLD_STOCK_DAILY_QFQ_RESET_ASSET_KEY,
        "protected_check_names": list(protected_check_names),
        "sample_limit": sample_limit,
    }

    _set_session(connection, readonly=not apply)
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            running_or_queued_run_count = _fetch_scalar(
                cursor,
                _RESET_RUNNING_OR_QUEUED_RUN_COUNT_SQL,
            )
            event_candidate_counts = _fetch_one(
                cursor,
                _RESET_EVENT_CANDIDATE_COUNTS_SQL,
                params,
            )
            protected_check_event_counts = _fetch_all(
                cursor,
                _RESET_PROTECTED_CHECK_EVENT_COUNTS_SQL,
                params,
            )
            event_candidate_samples = _fetch_all(
                cursor,
                _RESET_EVENT_CANDIDATE_SAMPLES_SQL,
                params,
            )
            safety_counts = _fetch_one(cursor, _RESET_SAFETY_COUNTS_SQL, params)
            safety_assertions = _build_reset_safety_assertions(
                running_or_queued_run_count=running_or_queued_run_count,
                safety_counts=safety_counts,
            )
            if apply and any(not bool(row["passed"]) for row in safety_assertions):
                raise RuntimeError(
                    "gold_stock_daily_qfq history reset safety assertions failed: "
                    + ", ".join(
                        str(row["name"])
                        for row in safety_assertions
                        if not bool(row["passed"])
                    )
                )
            delete_counts = (
                tuple(_execute_delete_steps(cursor, params))
                if apply and delete_dagster_events
                else ()
            )

        deleted_lake_file_count = (
            _delete_lake_files(all_lake_file_paths)
            if apply and delete_lake_files
            else 0
        )
        if apply:
            connection.commit()
        committed = bool(apply)
    except Exception:
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            rollback()
        raise

    return GoldStockDailyQfqHistoryResetReport(
        lake_root=str(lake_root),
        asset_key=GOLD_STOCK_DAILY_QFQ_RESET_ASSET_KEY,
        protected_check_names=tuple(protected_check_names),
        backup_path=backup_path,
        apply=apply,
        running_or_queued_run_count=running_or_queued_run_count,
        lake_file_candidates=tuple(lake_file_candidates),
        lake_file_candidate_count=len(all_lake_file_paths),
        lake_file_candidate_total_bytes=sum(
            path.stat().st_size for path in all_lake_file_paths if path.exists()
        ),
        event_candidate_counts=event_candidate_counts,
        protected_check_event_counts=tuple(protected_check_event_counts),
        event_candidate_samples=tuple(event_candidate_samples),
        safety_assertions=tuple(safety_assertions),
        delete_counts=delete_counts,
        deleted_lake_file_count=deleted_lake_file_count,
        committed=committed,
    )


def gold_stock_daily_qfq_history_reset_sql_statements() -> tuple[str, ...]:
    return (
        _RESET_RUNNING_OR_QUEUED_RUN_COUNT_SQL,
        _RESET_EVENT_CANDIDATE_COUNTS_SQL,
        _RESET_PROTECTED_CHECK_EVENT_COUNTS_SQL,
        _RESET_EVENT_CANDIDATE_SAMPLES_SQL,
        _RESET_SAFETY_COUNTS_SQL,
    )


def gold_stock_daily_qfq_history_reset_delete_sql_statements() -> tuple[str, ...]:
    return tuple(sql for _name, sql in _RESET_DELETE_STEPS)


def _discover_lake_file_paths(lake_root: Path) -> tuple[Path, ...]:
    target_root = Path(lake_root) / "gold" / "quote" / "stock_daily_qfq"
    if not target_root.exists():
        return ()
    return tuple(
        sorted(
            path
            for path in target_root.glob("trade_date=*/part-000.parquet")
            if path.is_file()
        )
    )


def _discover_lake_file_candidates(
    lake_root: Path,
    sample_limit: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in _discover_lake_file_paths(lake_root)[:sample_limit]:
        rows.append(
            {
                "partition_key": path.parent.name.removeprefix("trade_date="),
                "file_path": str(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return rows


def _delete_lake_files(paths: Sequence[Path]) -> int:
    deleted_count = 0
    for path in paths:
        if not _is_gold_stock_daily_qfq_partition_file(path):
            raise RuntimeError(f"Refusing to delete unexpected lake path: {path}")
        if path.exists():
            path.unlink()
            deleted_count += 1
    return deleted_count


def _is_gold_stock_daily_qfq_partition_file(path: Path) -> bool:
    return (
        path.name == "part-000.parquet"
        and path.parent.name.startswith("trade_date=")
        and path.parent.parent.name == "stock_daily_qfq"
        and path.parent.parent.parent.name == "quote"
        and path.parent.parent.parent.parent.name == "gold"
    )


def _set_session(connection, *, readonly: bool) -> None:
    set_session = getattr(connection, "set_session", None)
    if callable(set_session):
        set_session(readonly=readonly, autocommit=False)


def _execute_delete_steps(
    cursor,
    params: Mapping[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for step_name, sql in _RESET_DELETE_STEPS:
        cursor.execute(sql, params)
        rows.append(
            {
                "step": step_name,
                "deleted_row_count": int(getattr(cursor, "rowcount", 0) or 0),
            }
        )
    return rows


def _build_reset_safety_assertions(
    *,
    running_or_queued_run_count: int,
    safety_counts: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    return (
        _assertion(
            "no_running_or_queued_runs",
            running_or_queued_run_count == 0,
            running_or_queued_run_count,
        ),
        _assertion(
            "candidate_checks_exclude_protected_status_checks",
            _int(safety_counts, "protected_check_candidate_count") == 0,
            _int(safety_counts, "protected_check_candidate_count"),
        ),
        _assertion(
            "candidate_checks_have_evaluation_events",
            _int(safety_counts, "check_event_type_mismatch_count") == 0,
            _int(safety_counts, "check_event_type_mismatch_count"),
        ),
        _assertion(
            "candidate_checks_have_partition",
            _int(safety_counts, "check_null_partition_candidate_count") == 0,
            _int(safety_counts, "check_null_partition_candidate_count"),
        ),
        _assertion(
            "candidate_materializations_have_partition",
            _int(safety_counts, "materialization_null_partition_candidate_count") == 0,
            _int(safety_counts, "materialization_null_partition_candidate_count"),
        ),
        _assertion(
            "candidate_events_are_scoped_to_gold_stock_daily_qfq",
            _int(safety_counts, "other_asset_candidate_count") == 0,
            _int(safety_counts, "other_asset_candidate_count"),
        ),
    )


def _assertion(name: str, passed: bool, observed_value: object) -> dict[str, object]:
    return {
        "name": name,
        "passed": passed,
        "observed_value": observed_value,
    }


def _int(row: Mapping[str, object], key: str) -> int:
    return int(row.get(key) or 0)


_RESET_COMMON_CANDIDATE_CTES = """
asset_scope AS (
  SELECT %(asset_key)s::text AS asset_key
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
  WHERE ace.partition IS NOT NULL
    AND ace.evaluation_event_storage_id IS NOT NULL
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
  WHERE el.dagster_event_type = 'ASSET_MATERIALIZATION'
    AND el.partition IS NOT NULL
)
"""

_RESET_RUNNING_OR_QUEUED_RUN_COUNT_SQL = """
-- query: reset_running_or_queued_run_count
SELECT count(*)::bigint AS running_or_queued_run_count
FROM runs
WHERE status IN ('QUEUED', 'STARTING', 'STARTED', 'CANCELING')
"""

_RESET_EVENT_CANDIDATE_COUNTS_SQL = f"""
-- query: reset_event_candidate_counts
WITH {_RESET_COMMON_CANDIDATE_CTES}
SELECT
  (SELECT count(*)::bigint FROM candidate_checks) AS check_candidate_count,
  (
    SELECT count(*)::bigint
    FROM event_logs e
    JOIN candidate_checks c
      ON c.evaluation_event_storage_id = e.id
  ) AS check_event_candidate_count,
  (
    SELECT count(*)::bigint
    FROM asset_event_tags t
    JOIN candidate_checks c
      ON c.evaluation_event_storage_id = t.event_id
  ) AS check_event_tag_candidate_count,
  (
    SELECT count(*)::bigint
    FROM candidate_materializations
  ) AS materialization_candidate_count,
  (
    SELECT count(*)::bigint
    FROM asset_event_tags t
    JOIN candidate_materializations m
      ON m.id = t.event_id
  ) AS materialization_event_tag_candidate_count
"""

_RESET_PROTECTED_CHECK_EVENT_COUNTS_SQL = """
-- query: reset_protected_check_event_counts
SELECT
  ace.asset_key::text AS asset_key,
  ace.check_name,
  count(*)::bigint AS check_event_count
FROM asset_check_executions ace
WHERE ace.asset_key::text = %(asset_key)s::text
  AND ace.check_name = ANY(%(protected_check_names)s)
GROUP BY ace.asset_key::text, ace.check_name
ORDER BY ace.asset_key::text, ace.check_name
"""

_RESET_EVENT_CANDIDATE_SAMPLES_SQL = f"""
-- query: reset_event_candidate_samples
WITH {_RESET_COMMON_CANDIDATE_CTES},
samples AS (
  SELECT
    'asset_check_execution' AS candidate_type,
    c.asset_key,
    c.check_name,
    c.partition,
    c.run_id,
    c.evaluation_event_storage_id AS event_storage_id,
    c.materialization_event_storage_id,
    c.evaluation_event_timestamp AS event_timestamp
  FROM candidate_checks c
  UNION ALL
  SELECT
    'asset_materialization' AS candidate_type,
    m.asset_key,
    NULL::text AS check_name,
    m.partition,
    m.run_id,
    m.id AS event_storage_id,
    NULL::bigint AS materialization_event_storage_id,
    m.timestamp AS event_timestamp
  FROM candidate_materializations m
)
SELECT *
FROM samples
ORDER BY candidate_type, partition, check_name NULLS LAST, event_storage_id
LIMIT %(sample_limit)s
"""

_RESET_SAFETY_COUNTS_SQL = f"""
-- query: reset_safety_counts
WITH {_RESET_COMMON_CANDIDATE_CTES},
protected_check_candidates AS (
  SELECT count(*)::bigint AS count
  FROM asset_check_executions ace
  WHERE ace.asset_key::text = %(asset_key)s::text
    AND ace.check_name = ANY(%(protected_check_names)s)
    AND ace.id IN (SELECT id FROM candidate_checks)
),
check_event_type_mismatches AS (
  SELECT count(*)::bigint AS count
  FROM candidate_checks c
  LEFT JOIN event_logs e
    ON e.id = c.evaluation_event_storage_id
  WHERE e.id IS NULL
     OR e.dagster_event_type <> 'ASSET_CHECK_EVALUATION'
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
other_asset_candidates AS (
  SELECT count(*)::bigint AS count
  FROM (
    SELECT asset_key FROM candidate_checks
    UNION ALL
    SELECT asset_key FROM candidate_materializations
  ) candidates
  WHERE candidates.asset_key <> %(asset_key)s::text
)
SELECT
  (SELECT count FROM protected_check_candidates)
    AS protected_check_candidate_count,
  (SELECT count FROM check_event_type_mismatches)
    AS check_event_type_mismatch_count,
  (SELECT count FROM null_partition_check_candidates)
    AS check_null_partition_candidate_count,
  (SELECT count FROM null_partition_materialization_candidates)
    AS materialization_null_partition_candidate_count,
  (SELECT count FROM other_asset_candidates)
    AS other_asset_candidate_count
"""

_RESET_DELETE_CHECK_EVENT_TAGS_SQL = f"""
-- query: reset_delete_check_event_tags
WITH {_RESET_COMMON_CANDIDATE_CTES}
DELETE FROM asset_event_tags t
USING candidate_checks c
WHERE t.event_id = c.evaluation_event_storage_id
"""

_RESET_DELETE_CHECK_EVENTS_SQL = f"""
-- query: reset_delete_check_events
WITH {_RESET_COMMON_CANDIDATE_CTES}
DELETE FROM event_logs e
USING candidate_checks c
WHERE e.id = c.evaluation_event_storage_id
  AND e.dagster_event_type = 'ASSET_CHECK_EVALUATION'
"""

_RESET_DELETE_CHECK_EXECUTIONS_SQL = f"""
-- query: reset_delete_check_executions
WITH {_RESET_COMMON_CANDIDATE_CTES}
DELETE FROM asset_check_executions ace
USING candidate_checks c
WHERE ace.id = c.id
"""

_RESET_DELETE_MATERIALIZATION_EVENT_TAGS_SQL = f"""
-- query: reset_delete_materialization_event_tags
WITH {_RESET_COMMON_CANDIDATE_CTES}
DELETE FROM asset_event_tags t
USING candidate_materializations m
WHERE t.event_id = m.id
"""

_RESET_DELETE_MATERIALIZATION_EVENTS_SQL = f"""
-- query: reset_delete_materialization_events
WITH {_RESET_COMMON_CANDIDATE_CTES}
DELETE FROM event_logs e
USING candidate_materializations m
WHERE e.id = m.id
  AND e.dagster_event_type = 'ASSET_MATERIALIZATION'
"""

_RESET_DELETE_STEPS = (
    ("delete_check_event_tags", _RESET_DELETE_CHECK_EVENT_TAGS_SQL),
    ("delete_check_events", _RESET_DELETE_CHECK_EVENTS_SQL),
    ("delete_check_executions", _RESET_DELETE_CHECK_EXECUTIONS_SQL),
    (
        "delete_materialization_event_tags",
        _RESET_DELETE_MATERIALIZATION_EVENT_TAGS_SQL,
    ),
    ("delete_materialization_events", _RESET_DELETE_MATERIALIZATION_EVENTS_SQL),
)
