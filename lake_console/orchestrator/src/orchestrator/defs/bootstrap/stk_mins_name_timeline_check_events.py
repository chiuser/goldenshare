from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import dagster as dg
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    load_stock_mins_expected_trade_dates,
)
from orchestrator.defs.checks.stk_mins_checks import (
    SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
)
from orchestrator.defs.duckdb_sql import (
    duckdb_string,
    historical_cny_stock_lifecycle_select,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    raw_stock_basic_path,
    silver_stk_mins_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    STK_MINS_SILVER_HISTORY_START_DATE,
)

TARGET_TS_CODE = "000638.SZ"
TARGET_LAST_TRADE_DATE = "2026-04-13"
MAX_TARGET_EVENT_COUNT = 13_460
SOURCE_CORRECTION_REASON = "000638_lifecycle_check_semantics_fix"
SILVER_STK_MINS_NAME_TIMELINE_ASSET_KEYS = {
    int(freq): dg.AssetKey(f"silver_stk_mins_{int(freq)}m")
    for freq in STK_MINS_FREQS
}

_TERMINAL_CHECK_STATUSES = {
    AssetCheckExecutionRecordStatus.SUCCEEDED,
    AssetCheckExecutionRecordStatus.FAILED,
}


@dataclass(frozen=True)
class SilverNameTimelineCandidate:
    freq: int
    partition_key: str
    asset_key: str
    file_path: str
    target_row_count: int

    def to_payload(self) -> dict[str, object]:
        return {
            "freq": self.freq,
            "partition_key": self.partition_key,
            "asset_key": self.asset_key,
            "file_path": self.file_path,
            "target_row_count": self.target_row_count,
        }


@dataclass(frozen=True)
class SilverNameTimelineLatestCheckState:
    freq: int
    partition_key: str
    asset_key: str
    status: str
    passed: bool | None
    blocking: bool | None
    run_id: str | None
    event_timestamp: float | None

    @property
    def is_latest_passed(self) -> bool:
        return self.status == "SUCCEEDED" and self.passed is True and self.blocking is True

    @property
    def is_latest_failed(self) -> bool:
        if self.status == "FAILED":
            return True
        return not self.is_latest_passed

    def to_payload(self) -> dict[str, object]:
        return {
            "freq": self.freq,
            "partition_key": self.partition_key,
            "asset_key": self.asset_key,
            "status": self.status,
            "passed": self.passed,
            "blocking": self.blocking,
            "run_id": self.run_id,
            "event_timestamp": self.event_timestamp,
        }


@dataclass(frozen=True)
class SilverNameTimelineCheckEventDryRunReport:
    ts_code: str
    check_name: str
    end_date: str
    max_expected_events: int
    candidate_event_count: int
    candidate_trade_date_count: int
    historical_failed_event_count: int
    historical_check_event_count: int
    existing_latest_passed_count: int
    latest_failed_candidate_count: int
    missing_check_event_count: int
    missing_target_materialization_count: int
    planned_new_event_count: int
    checked_event_history_record_count: int
    candidate_samples: tuple[SilverNameTimelineCandidate, ...]
    latest_failed_samples: tuple[SilverNameTimelineLatestCheckState, ...]
    missing_check_event_samples: tuple[SilverNameTimelineCandidate, ...]
    missing_target_materialization_samples: tuple[SilverNameTimelineCandidate, ...]
    stop_reasons: tuple[str, ...]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_payload(self) -> dict[str, object]:
        return {
            "ts_code": self.ts_code,
            "check_name": self.check_name,
            "end_date": self.end_date,
            "max_expected_events": self.max_expected_events,
            "candidate_event_count": self.candidate_event_count,
            "candidate_trade_date_count": self.candidate_trade_date_count,
            "historical_failed_event_count": self.historical_failed_event_count,
            "historical_check_event_count": self.historical_check_event_count,
            "existing_latest_passed_count": self.existing_latest_passed_count,
            "latest_failed_candidate_count": self.latest_failed_candidate_count,
            "missing_check_event_count": self.missing_check_event_count,
            "missing_target_materialization_count": (
                self.missing_target_materialization_count
            ),
            "planned_new_event_count": self.planned_new_event_count,
            "checked_event_history_record_count": (
                self.checked_event_history_record_count
            ),
            "candidate_samples": [
                candidate.to_payload() for candidate in self.candidate_samples
            ],
            "latest_failed_samples": [
                state.to_payload() for state in self.latest_failed_samples
            ],
            "missing_check_event_samples": [
                candidate.to_payload()
                for candidate in self.missing_check_event_samples
            ],
            "missing_target_materialization_samples": [
                candidate.to_payload()
                for candidate in self.missing_target_materialization_samples
            ],
            "stop_reasons": list(self.stop_reasons),
        }


def build_silver_name_timeline_correction_candidates(
    connection,
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    ts_code: str = TARGET_TS_CODE,
    end_date: str = TARGET_LAST_TRADE_DATE,
    max_expected_events: int = MAX_TARGET_EVENT_COUNT,
) -> tuple[SilverNameTimelineCandidate, ...]:
    _assert_allowed_target(ts_code=ts_code, max_expected_events=max_expected_events)
    end_date = _normalize_date(end_date, field_name="end_date")
    calendar_path = silver_trade_calendar_path(lake_root)
    stock_basic_path = raw_stock_basic_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver trade calendar file is missing: {calendar_path}")
    if not stock_basic_path.exists():
        raise FileNotFoundError(f"raw stock basic file is missing: {stock_basic_path}")

    expected_dates = tuple(
        trade_date
        for trade_date in load_stock_mins_expected_trade_dates(
            connection,
            calendar_path,
            min_trade_date=STK_MINS_SILVER_HISTORY_START_DATE,
            evaluated_at=datetime.combine(date.fromisoformat(end_date), time(23, 59, 59)),
        )
        if trade_date <= end_date
    )
    paths = _existing_silver_paths(lake_root, expected_dates)
    if not paths:
        return ()

    relation = _read_parquet_paths(tuple(path for _freq, _date, path in paths), filename=True)
    lifecycle_relation = historical_cny_stock_lifecycle_select(stock_basic_path)
    rows = connection.execute(
        f"""
        WITH target_rows AS (
          SELECT
            CAST(regexp_extract(filename, 'freq=([0-9]+)', 1) AS INTEGER) AS freq,
            regexp_extract(
              filename,
              'trade_date=([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})',
              1
            ) AS partition_key,
            filename AS file_path,
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date
          FROM {relation}
          WHERE CAST(ts_code AS VARCHAR) = ?
        ),
        stock_lifecycle AS (
          {lifecycle_relation}
        ),
        target_lifecycle AS (
          SELECT
            target_rows.freq,
            target_rows.partition_key,
            target_rows.file_path,
            count(*) AS target_row_count,
            sum(CASE WHEN stock_lifecycle.ts_code IS NULL THEN 1 ELSE 0 END)
              AS lifecycle_failure_count
          FROM target_rows
          LEFT JOIN stock_lifecycle
            ON stock_lifecycle.ts_code = target_rows.ts_code
           AND target_rows.trade_date >= stock_lifecycle.list_date
           AND (
             stock_lifecycle.delist_date IS NULL
             OR target_rows.trade_date <= stock_lifecycle.delist_date
           )
          GROUP BY 1, 2, 3
        )
        SELECT freq, partition_key, file_path, target_row_count, lifecycle_failure_count
        FROM target_lifecycle
        WHERE target_row_count > 0
        ORDER BY partition_key, freq
        """,
        [ts_code],
    ).fetchall()

    candidates: list[SilverNameTimelineCandidate] = []
    lifecycle_failures: list[tuple[int, str, int]] = []
    for freq, partition_key, file_path, row_count, failure_count in rows:
        if int(failure_count) > 0:
            lifecycle_failures.append((int(freq), str(partition_key), int(failure_count)))
            continue
        asset_key = SILVER_STK_MINS_NAME_TIMELINE_ASSET_KEYS[int(freq)].to_user_string()
        candidates.append(
            SilverNameTimelineCandidate(
                freq=int(freq),
                partition_key=str(partition_key),
                asset_key=asset_key,
                file_path=str(file_path),
                target_row_count=int(row_count),
            )
        )

    if lifecycle_failures:
        samples = ", ".join(
            f"{freq}:{partition_key}:{count}"
            for freq, partition_key, count in lifecycle_failures[:10]
        )
        raise ValueError(f"target lifecycle check failed for {ts_code}: {samples}")
    if len(candidates) > max_expected_events:
        raise ValueError(
            "silver name timeline correction candidates exceed max expected events: "
            f"{len(candidates)} > {max_expected_events}"
        )
    return tuple(candidates)


def dry_run_silver_name_timeline_check_event_correction(
    *,
    instance: dg.DagsterInstance,
    connection,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    ts_code: str = TARGET_TS_CODE,
    end_date: str = TARGET_LAST_TRADE_DATE,
    max_expected_events: int = MAX_TARGET_EVENT_COUNT,
    history_page_limit: int = 5_000,
    max_history_records_per_check_key: int = 100_000,
    sample_limit: int = 10,
) -> SilverNameTimelineCheckEventDryRunReport:
    _assert_allowed_target(ts_code=ts_code, max_expected_events=max_expected_events)
    candidates = build_silver_name_timeline_correction_candidates(
        connection,
        lake_root=lake_root,
        ts_code=ts_code,
        end_date=end_date,
        max_expected_events=max_expected_events,
    )
    candidate_by_key = {
        (candidate.freq, candidate.partition_key): candidate for candidate in candidates
    }
    materialized_keys = _materialized_candidate_keys(instance, candidates)
    check_audit = _audit_candidate_check_history(
        instance,
        candidates,
        history_page_limit=history_page_limit,
        max_history_records_per_check_key=max_history_records_per_check_key,
    )

    latest_states = check_audit["latest_states"]
    latest_passed = tuple(state for state in latest_states.values() if state.is_latest_passed)
    latest_failed = tuple(
        state
        for key, state in latest_states.items()
        if state.is_latest_failed and key in materialized_keys
    )
    missing_check_keys = tuple(
        key for key in candidate_by_key if key not in latest_states
    )
    missing_materialization_keys = tuple(
        key for key in candidate_by_key if key not in materialized_keys
    )

    stop_reasons: list[str] = []
    if len(candidates) > max_expected_events:
        stop_reasons.append("candidate_event_count_exceeds_max_expected_events")
    if missing_materialization_keys:
        stop_reasons.append("missing_target_materialization")
    if check_audit["history_record_limit_exceeded"]:
        stop_reasons.append("event_history_record_limit_exceeded")

    return SilverNameTimelineCheckEventDryRunReport(
        ts_code=ts_code,
        check_name=SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
        end_date=_normalize_date(end_date, field_name="end_date"),
        max_expected_events=max_expected_events,
        candidate_event_count=len(candidates),
        candidate_trade_date_count=len({candidate.partition_key for candidate in candidates}),
        historical_failed_event_count=int(check_audit["historical_failed_event_count"]),
        historical_check_event_count=int(check_audit["historical_check_event_count"]),
        existing_latest_passed_count=len(latest_passed),
        latest_failed_candidate_count=len(latest_failed),
        missing_check_event_count=len(missing_check_keys),
        missing_target_materialization_count=len(missing_materialization_keys),
        planned_new_event_count=len(latest_failed),
        checked_event_history_record_count=int(
            check_audit["checked_event_history_record_count"]
        ),
        candidate_samples=tuple(candidates[:sample_limit]),
        latest_failed_samples=tuple(latest_failed[:sample_limit]),
        missing_check_event_samples=tuple(
            candidate_by_key[key] for key in missing_check_keys[:sample_limit]
        ),
        missing_target_materialization_samples=tuple(
            candidate_by_key[key] for key in missing_materialization_keys[:sample_limit]
        ),
        stop_reasons=tuple(stop_reasons),
    )


def _assert_allowed_target(*, ts_code: str, max_expected_events: int) -> None:
    if ts_code != TARGET_TS_CODE:
        raise ValueError(f"Unsupported ts_code for this correction audit: {ts_code}")
    if max_expected_events > MAX_TARGET_EVENT_COUNT:
        raise ValueError(
            "max_expected_events must not exceed "
            f"{MAX_TARGET_EVENT_COUNT}: {max_expected_events}"
        )


def _normalize_date(value: str, *, field_name: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD: {value}") from exc


def _existing_silver_paths(
    lake_root: Path,
    expected_dates: Sequence[str],
) -> tuple[tuple[int, str, Path], ...]:
    paths: list[tuple[int, str, Path]] = []
    for trade_date in expected_dates:
        for freq in sorted(SILVER_STK_MINS_NAME_TIMELINE_ASSET_KEYS):
            path = silver_stk_mins_path(lake_root, freq, trade_date)
            if path.exists():
                paths.append((freq, trade_date, path))
    return tuple(paths)


def _read_parquet_paths(paths: Sequence[Path], *, filename: bool = False) -> str:
    if not paths:
        raise ValueError("read_parquet paths must not be empty.")
    path_list = ", ".join(duckdb_string(path) for path in paths)
    filename_clause = ", filename=true" if filename else ""
    return f"read_parquet([{path_list}], hive_partitioning=false, union_by_name=true{filename_clause})"


def _materialized_candidate_keys(
    instance: dg.DagsterInstance,
    candidates: Sequence[SilverNameTimelineCandidate],
) -> set[tuple[int, str]]:
    partitions_by_freq: dict[int, set[str]] = {}
    for candidate in candidates:
        partitions_by_freq.setdefault(candidate.freq, set()).add(candidate.partition_key)

    materialized_keys: set[tuple[int, str]] = set()
    for freq, candidate_partitions in partitions_by_freq.items():
        asset_key = SILVER_STK_MINS_NAME_TIMELINE_ASSET_KEYS[freq]
        materialized_partitions = instance.get_materialized_partitions(asset_key)
        for partition_key in candidate_partitions.intersection(materialized_partitions):
            materialized_keys.add((freq, partition_key))
    return materialized_keys


def _audit_candidate_check_history(
    instance: dg.DagsterInstance,
    candidates: Sequence[SilverNameTimelineCandidate],
    *,
    history_page_limit: int,
    max_history_records_per_check_key: int,
) -> Mapping[str, object]:
    candidate_partitions_by_freq: dict[int, set[str]] = {}
    for candidate in candidates:
        candidate_partitions_by_freq.setdefault(candidate.freq, set()).add(
            candidate.partition_key
        )

    latest_states: dict[
        tuple[int, str], SilverNameTimelineLatestCheckState
    ] = {}
    historical_failed_event_count = 0
    historical_check_event_count = 0
    checked_event_history_record_count = 0
    history_record_limit_exceeded = False

    for freq, candidate_partitions in sorted(candidate_partitions_by_freq.items()):
        check_key = dg.AssetCheckKey(
            SILVER_STK_MINS_NAME_TIMELINE_ASSET_KEYS[freq],
            SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
        )
        cursor: int | None = None
        check_key_record_count = 0
        while True:
            records = instance.event_log_storage.get_asset_check_execution_history(
                check_key,
                limit=history_page_limit,
                cursor=cursor,
                status=_TERMINAL_CHECK_STATUSES,
            )
            if not records:
                break
            for record in records:
                check_key_record_count += 1
                checked_event_history_record_count += 1
                partition_key = _check_record_partition(record)
                if partition_key not in candidate_partitions:
                    continue
                historical_check_event_count += 1
                status = _check_record_status(record)
                if status == "FAILED":
                    historical_failed_event_count += 1
                latest_states.setdefault(
                    (freq, partition_key),
                    _latest_state_from_record(freq=freq, record=record),
                )
            if check_key_record_count >= max_history_records_per_check_key:
                history_record_limit_exceeded = True
                break
            cursor = getattr(records[-1], "id", None)
            if cursor is None:
                break

    return {
        "latest_states": latest_states,
        "historical_failed_event_count": historical_failed_event_count,
        "historical_check_event_count": historical_check_event_count,
        "checked_event_history_record_count": checked_event_history_record_count,
        "history_record_limit_exceeded": history_record_limit_exceeded,
    }


def _latest_state_from_record(
    *,
    freq: int,
    record: object,
) -> SilverNameTimelineLatestCheckState:
    evaluation = _check_record_evaluation(record)
    event = _check_record_event(record)
    asset_key = SILVER_STK_MINS_NAME_TIMELINE_ASSET_KEYS[freq].to_user_string()
    return SilverNameTimelineLatestCheckState(
        freq=freq,
        partition_key=str(_check_record_partition(record)),
        asset_key=asset_key,
        status=_check_record_status(record),
        passed=getattr(evaluation, "passed", None),
        blocking=getattr(evaluation, "blocking", None),
        run_id=getattr(event, "run_id", None),
        event_timestamp=getattr(event, "timestamp", None),
    )


def _check_record_status(record: object) -> str:
    status = getattr(record, "status", None)
    if hasattr(status, "value"):
        return str(status.value)
    return str(status)


def _check_record_event(record: object) -> object | None:
    return getattr(record, "event", None) or getattr(record, "event_log_entry", None)


def _check_record_evaluation(record: object) -> object:
    event = _check_record_event(record)
    dagster_event = getattr(event, "dagster_event", None)
    return getattr(dagster_event, "event_specific_data", object())


def _check_record_partition(record: object) -> str | None:
    partition = getattr(record, "partition", None)
    if partition is not None:
        return str(partition)
    return getattr(_check_record_evaluation(record), "partition", None)


def correction_event_metadata() -> dict[str, Any]:
    return {
        "source_correction_reason": SOURCE_CORRECTION_REASON,
        "ts_code": TARGET_TS_CODE,
        "lifecycle_fact_source": "raw_stock_basic",
        "checked_code_date_freq_count": 1,
        "failed_code_date_freq_count": 0,
    }
