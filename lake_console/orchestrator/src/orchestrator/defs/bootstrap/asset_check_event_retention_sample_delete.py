from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from psycopg2.extras import RealDictCursor

from orchestrator.defs.bootstrap.asset_check_event_retention import (
    ASSET_CHECK_RETENTION_ASSET_KEYS,
    ASSET_CHECK_RETENTION_KEEP_PARTITION_SET_BY_KEY,
    ASSET_CHECK_RETENTION_KEEP_TRADE_DAY_COUNT,
    ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES,
    _COMMON_CANDIDATE_CTES,
    _CANDIDATE_EVENT_COUNT_BY_ASSET_SQL,
    _KEEP_WINDOWS_SQL,
    _LATEST_STATE_SUMMARY_BY_ASSET_SQL,
    _RUNNING_OR_QUEUED_RUN_COUNT_SQL,
    _SAFETY_COUNTS_SQL,
    _build_safety_assertions,
    _candidate_totals,
    _fetch_all,
    _fetch_one,
    _fetch_scalar,
    _normalize_asset_keys,
    _query_params,
)


@dataclass(frozen=True)
class AssetCheckEventRetentionSampleDeleteReport:
    sample_asset_key: str
    keep_partition_set_name: str
    keep_trade_day_count: int
    protected_check_names: tuple[str, ...]
    running_or_queued_run_count: int
    keep_windows: tuple[dict[str, object], ...]
    candidate_totals: dict[str, object]
    candidate_event_count_by_asset: tuple[dict[str, object], ...]
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
            "mode": "asset_check_event_retention_sample_delete",
            "sample_asset_key": self.sample_asset_key,
            "keep_partition_set_name": self.keep_partition_set_name,
            "keep_trade_day_count": self.keep_trade_day_count,
            "protected_check_names": list(self.protected_check_names),
            "running_or_queued_run_count": self.running_or_queued_run_count,
            "keep_windows": list(self.keep_windows),
            "candidate_totals": self.candidate_totals,
            "candidate_event_count_by_asset": list(
                self.candidate_event_count_by_asset
            ),
            "latest_state_summary_by_asset": list(
                self.latest_state_summary_by_asset
            ),
            "safety_assertions": list(self.safety_assertions),
            "delete_counts": list(self.delete_counts),
            "committed": self.committed,
            "should_stop": self.should_stop,
        }


def execute_asset_check_event_retention_sample_delete(
    connection,
    *,
    sample_asset: str | Sequence[str],
    confirm_sample_delete: bool,
    keep_trade_day_count: int = ASSET_CHECK_RETENTION_KEEP_TRADE_DAY_COUNT,
    protected_check_names: Sequence[str] = (
        ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES
    ),
) -> AssetCheckEventRetentionSampleDeleteReport:
    if not confirm_sample_delete:
        raise ValueError("sample-delete requires --confirm-sample-delete")
    if keep_trade_day_count <= 0:
        raise ValueError("keep_trade_day_count must be positive")
    if not protected_check_names:
        raise ValueError("protected_check_names must not be empty")

    sample_asset_key = _normalize_single_sample_asset(sample_asset)
    if sample_asset_key not in ASSET_CHECK_RETENTION_ASSET_KEYS:
        raise ValueError(
            "sample asset is not in non-stock-mins retention whitelist: "
            f"{sample_asset_key}"
        )

    keep_partition_set_name = ASSET_CHECK_RETENTION_KEEP_PARTITION_SET_BY_KEY[
        sample_asset_key
    ]
    if keep_partition_set_name is None:
        raise ValueError(
            "sample-delete requires a partitioned retention asset with a keep "
            f"partition set: {sample_asset_key}"
        )

    _set_write_session(connection)
    params = _query_params(
        [sample_asset_key],
        protected_check_names=protected_check_names,
        keep_trade_day_count=keep_trade_day_count,
        sample_limit=1,
    )

    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            running_or_queued_run_count = _fetch_scalar(
                cursor,
                _RUNNING_OR_QUEUED_RUN_COUNT_SQL,
            )
            keep_windows = _fetch_all(cursor, _KEEP_WINDOWS_SQL, params)
            candidate_event_count_by_asset = _fetch_all(
                cursor,
                _CANDIDATE_EVENT_COUNT_BY_ASSET_SQL,
                params,
            )
            latest_state_summary_by_asset = _fetch_all(
                cursor,
                _LATEST_STATE_SUMMARY_BY_ASSET_SQL,
                params,
            )
            safety_counts = _fetch_one(cursor, _SAFETY_COUNTS_SQL, params)
            safety_assertions = _build_sample_delete_safety_assertions(
                running_or_queued_run_count=running_or_queued_run_count,
                keep_trade_day_count=keep_trade_day_count,
                keep_windows=keep_windows,
                latest_state_summary_by_asset=latest_state_summary_by_asset,
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

    return AssetCheckEventRetentionSampleDeleteReport(
        sample_asset_key=sample_asset_key,
        keep_partition_set_name=keep_partition_set_name,
        keep_trade_day_count=keep_trade_day_count,
        protected_check_names=tuple(protected_check_names),
        running_or_queued_run_count=running_or_queued_run_count,
        keep_windows=tuple(keep_windows),
        candidate_totals=_candidate_totals(candidate_event_count_by_asset),
        candidate_event_count_by_asset=tuple(candidate_event_count_by_asset),
        latest_state_summary_by_asset=tuple(latest_state_summary_by_asset),
        safety_assertions=tuple(safety_assertions),
        delete_counts=delete_counts,
        committed=committed,
    )


def asset_check_event_retention_sample_delete_sql_statements() -> tuple[str, ...]:
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


def _build_sample_delete_safety_assertions(
    *,
    running_or_queued_run_count: int,
    keep_trade_day_count: int,
    keep_windows: Sequence[Mapping[str, object]],
    latest_state_summary_by_asset: Sequence[Mapping[str, object]],
    safety_counts: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    base_assertions = _build_safety_assertions(
        running_or_queued_run_count=running_or_queued_run_count,
        keep_trade_day_count=keep_trade_day_count,
        keep_windows=keep_windows,
        safety_counts=safety_counts,
    )
    latest_materialization_count = sum(
        1
        for row in latest_state_summary_by_asset
        if row.get("latest_materialization_id") is not None
    )
    latest_check_count = sum(
        1
        for row in latest_state_summary_by_asset
        if _int(row, "latest_check_count") > 0
    )
    latest_materializations_without_checks = sum(
        1
        for row in latest_state_summary_by_asset
        if row.get("latest_materialization_id") is not None
        and _int(row, "latest_check_count") == 0
    )
    return (
        *base_assertions,
        _safety_assertion(
            "sample_asset_has_latest_materialization_state",
            latest_materialization_count == 1,
            latest_materialization_count,
        ),
        _safety_assertion(
            "sample_asset_has_latest_check_state",
            latest_check_count == 1,
            latest_check_count,
        ),
        _safety_assertion(
            "sample_latest_materialization_has_latest_check_state",
            latest_materializations_without_checks == 0,
            latest_materializations_without_checks,
        ),
    )


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


def _safety_assertion(name: str, passed: bool, observed_count: int) -> dict[str, object]:
    return {
        "name": name,
        "passed": passed,
        "observed_count": observed_count,
    }


def _int(row: Mapping[str, object], key: str) -> int:
    return int(row.get(key) or 0)


_DELETE_CHECK_EVENT_TAGS_SQL = f"""
-- query: delete_check_event_tags
WITH {_COMMON_CANDIDATE_CTES}
DELETE FROM asset_event_tags t
USING candidate_checks c
WHERE t.event_id = c.evaluation_event_storage_id
"""

_DELETE_CHECK_EVENTS_SQL = f"""
-- query: delete_check_events
WITH {_COMMON_CANDIDATE_CTES}
DELETE FROM event_logs e
USING candidate_checks c
WHERE e.id = c.evaluation_event_storage_id
  AND e.dagster_event_type = 'ASSET_CHECK_EVALUATION'
"""

_DELETE_CHECK_EXECUTIONS_SQL = f"""
-- query: delete_check_executions
WITH {_COMMON_CANDIDATE_CTES}
DELETE FROM asset_check_executions ace
USING candidate_checks c
WHERE ace.id = c.id
"""

_DELETE_MATERIALIZATION_EVENT_TAGS_SQL = f"""
-- query: delete_materialization_event_tags
WITH {_COMMON_CANDIDATE_CTES}
DELETE FROM asset_event_tags t
USING candidate_materializations m
WHERE t.event_id = m.id
"""

_DELETE_MATERIALIZATION_EVENTS_SQL = f"""
-- query: delete_materialization_events
WITH {_COMMON_CANDIDATE_CTES}
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
