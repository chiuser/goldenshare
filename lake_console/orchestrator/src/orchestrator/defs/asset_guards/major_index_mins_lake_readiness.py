"""Bounded lake readiness for major-index minute Raw and Silver partitions."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.major_index_mins_quality import (
    prepare_major_index_mins_raw_expected_tables,
    prepare_major_index_mins_silver_expected_tables,
    validate_major_index_mins_raw_relation,
    validate_major_index_mins_silver_relation,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_DAILY_PROBE_WINDOW_LIMIT,
    MAJOR_INDEX_MINS_RAW_CHECKS,
    MAJOR_INDEX_MINS_SILVER_CHECKS,
    MAJOR_INDEX_MINS_SILVER_FREQS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
    effective_raw_request_codes_for_date,
    effective_silver_codes_for_date,
    major_index_mins_historical_fallback_rule,
)


def _bounded_dates(values: Sequence[str]) -> tuple[str, ...]:
    dates = tuple(str(value) for value in values)
    if len(dates) > MAJOR_INDEX_MINS_DAILY_PROBE_WINDOW_LIMIT:
        raise ValueError(
            "major_index_mins readiness window exceeds the bounded limit: "
            f"max={MAJOR_INDEX_MINS_DAILY_PROBE_WINDOW_LIMIT}, actual={len(dates)}."
        )
    return dates


def _missing_status(
    *, trade_date: str, layer: str, check_names: Sequence[str], paths: Sequence[Path]
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason=f"major_index_mins {layer} files are missing for {trade_date}",
        missing_check_names=tuple(check_names),
        missing_file_paths=tuple(str(path) for path in paths[:20]),
        summary={
            "layer": layer,
            "reason_code": "file_missing",
            "missing_file_count": len(paths),
        },
    )


def _failure_status(
    *,
    trade_date: str,
    layer: str,
    check_names: Sequence[str],
    failed_rules: Sequence[str],
    scanned_file_count: int,
    error: Exception | None = None,
) -> ContinuityDateReadiness:
    summary: dict[str, object] = {
        "layer": layer,
        "reason_code": "scan_error" if error else "core_check_failed",
        "failed_rules": list(dict.fromkeys(failed_rules)),
        "failed_row_count": len(failed_rules),
        "scanned_file_count": scanned_file_count,
    }
    if error is not None:
        summary["scan_error_type"] = type(error).__name__
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason=(
            f"major_index_mins {layer} readiness scan failed for {trade_date}"
            if error
            else f"major_index_mins {layer} core checks failed for {trade_date}"
        ),
        failed_check_names=tuple(check_names),
        summary=summary,
    )


def _ready_status(
    *, trade_date: str, layer: str, checked_rows: int, scanned_files: int
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason=f"major_index_mins {layer} ready for {trade_date}",
        summary={
            "layer": layer,
            "reason_code": "ready",
            "checked_row_count": checked_rows,
            "failed_row_count": 0,
            "scanned_file_count": scanned_files,
        },
    )


@dataclass(slots=True)
class _DateScanState:
    paths: tuple[Path, ...]
    missing_paths: tuple[Path, ...]
    scanned_file_count: int
    checked_row_count: int = 0
    failed_rules: list[str] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    scan_error: Exception | None = None


def _batch_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    layer: str,
) -> ContinuityBatchReadiness:
    del registered_trade_days
    started_at = perf_counter()
    expected = _bounded_dates(expected_trade_dates)
    frequencies = (
        MAJOR_INDEX_MINS_SOURCE_FREQS
        if layer == "raw"
        else MAJOR_INDEX_MINS_SILVER_FREQS
    )
    check_names = (
        MAJOR_INDEX_MINS_RAW_CHECKS
        if layer == "raw"
        else MAJOR_INDEX_MINS_SILVER_CHECKS
    )
    path_builder = (
        raw_major_index_mins_path if layer == "raw" else silver_major_index_mins_path
    )
    states: dict[str, _DateScanState] = {}
    for trade_date in expected:
        paths = tuple(
            path_builder(lake_root, frequency, trade_date) for frequency in frequencies
        )
        missing_paths = tuple(path for path in paths if not path.exists())
        states[trade_date] = _DateScanState(
            paths=paths,
            missing_paths=missing_paths,
            scanned_file_count=len(paths) - len(missing_paths),
        )

    for frequency_index, (frequency, check_name) in enumerate(
        zip(frequencies, check_names, strict=True)
    ):
        grouped_dates: dict[tuple[tuple[str, ...], tuple[str, ...]], list[str]] = {}
        for trade_date, state in states.items():
            if state.paths[frequency_index].exists() and state.scan_error is None:
                expected_codes = (
                    effective_raw_request_codes_for_date(trade_date)
                    if layer == "raw"
                    else effective_silver_codes_for_date(trade_date)
                )
                fallback = (
                    major_index_mins_historical_fallback_rule(
                        trade_date=trade_date,
                        target_freq=frequency,
                    )
                    if layer == "raw"
                    else None
                )
                grouped_dates.setdefault(
                    (expected_codes, fallback.target_codes if fallback else ()), []
                ).append(trade_date)
        for (expected_codes, _relaxed_codes), trade_dates in grouped_dates.items():
            if layer == "raw":
                prepare_major_index_mins_raw_expected_tables(
                    connection,
                    expected_codes=expected_codes,
                    frequency=frequency,
                    partition_key=trade_dates[0],
                )
            else:
                prepare_major_index_mins_silver_expected_tables(
                    connection,
                    expected_codes=expected_codes,
                    frequency=frequency,
                )
            for trade_date in trade_dates:
                state = states[trade_date]
                try:
                    relation_sql = read_parquet(
                        state.paths[frequency_index],
                        hive_partitioning=False,
                    )
                    validation = (
                        validate_major_index_mins_raw_relation(
                            connection,
                            relation_sql=relation_sql,
                            expected_codes=expected_codes,
                            frequency=frequency,
                            partition_key=trade_date,
                        )
                        if layer == "raw"
                        else validate_major_index_mins_silver_relation(
                            connection,
                            relation_sql=relation_sql,
                            expected_codes=expected_codes,
                            frequency=frequency,
                            partition_key=trade_date,
                            require_null_vwap=frequency in {"90min", "120min"},
                        )
                    )
                    state.checked_row_count += validation.row_count
                    if validation.errors:
                        state.failed_checks.append(check_name)
                        state.failed_rules.extend(
                            f"{frequency}:{rule}" for rule in validation.errors
                        )
                except Exception as error:  # noqa: BLE001 - readiness fails closed.
                    state.failed_checks.append(check_name)
                    state.failed_rules.append(
                        f"{frequency}:parquet_schema_and_contract"
                    )
                    state.scan_error = error

    statuses: dict[str, ContinuityDateReadiness] = {}
    for trade_date, state in states.items():
        if state.failed_rules:
            statuses[trade_date] = _failure_status(
                trade_date=trade_date,
                layer=layer,
                check_names=state.failed_checks or check_names,
                failed_rules=state.failed_rules,
                scanned_file_count=state.scanned_file_count,
                error=state.scan_error,
            )
            continue
        if state.missing_paths:
            statuses[trade_date] = _missing_status(
                trade_date=trade_date,
                layer=layer,
                check_names=tuple(
                    check_name
                    for check_name, path in zip(check_names, state.paths, strict=True)
                    if not path.exists()
                ),
                paths=state.missing_paths,
            )
            continue
        statuses[trade_date] = _ready_status(
            trade_date=trade_date,
            layer=layer,
            checked_rows=state.checked_row_count,
            scanned_files=state.scanned_file_count,
        )
    return ContinuityBatchReadiness(
        expected_trade_dates=expected,
        statuses_by_trade_date=statuses,
        elapsed_ms=round((perf_counter() - started_at) * 1000),
        scanned_file_count=sum(state.scanned_file_count for state in states.values()),
    )


def batch_raw_major_index_mins_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
) -> ContinuityBatchReadiness:
    return _batch_readiness(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        layer="raw",
    )


def batch_silver_major_index_mins_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
) -> ContinuityBatchReadiness:
    return _batch_readiness(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        layer="silver",
    )


__all__ = [
    "batch_raw_major_index_mins_lake_readiness",
    "batch_silver_major_index_mins_lake_readiness",
]
