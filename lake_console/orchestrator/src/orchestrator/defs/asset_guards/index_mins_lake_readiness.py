"""Bounded Lake readiness for index minute Raw and Silver sensors."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from orchestrator.defs.assets.index_mins_silver import (
    _assert_schema,
    _derived_diagnostics,
    _native_source_sql,
    _validate_relation,
)
from orchestrator.defs.checks.index_mins_checks import (
    _raw_invalid_predicate,
    _schema_matches,
)
from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import raw_index_mins_path, silver_index_mins_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_MINS_SCHEMA,
    SILVER_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_ASSET_FREQS,
    INDEX_MINS_SENSOR_WINDOW_LIMIT,
    INDEX_MINS_SILVER_FREQS,
    INDEX_MINS_SOURCE_FREQ_BY_ASSET_FREQ,
    source_freq_for_index_mins_derived_freq,
)
_RAW_CHECK_NAMES = tuple(
    f"raw_index_mins_{frequency}m_core_check"
    for frequency in INDEX_MINS_ASSET_FREQS
)
_SILVER_CHECK_NAMES = tuple(
    f"silver_index_mins_{frequency}m_core_check"
    for frequency in INDEX_MINS_SILVER_FREQS
)


def _bounded_expected_dates(expected_trade_dates: Sequence[str]) -> tuple[str, ...]:
    expected = tuple(str(value) for value in expected_trade_dates)
    if len(expected) > INDEX_MINS_SENSOR_WINDOW_LIMIT:
        raise ValueError(
            "index_mins readiness window exceeds the bounded sensor limit: "
            f"max={INDEX_MINS_SENSOR_WINDOW_LIMIT}, actual={len(expected)}."
        )
    return expected


def _missing_status(
    *,
    trade_date: str,
    check_names: Sequence[str],
    missing_paths: Sequence[Path],
    layer: str,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason=f"index_mins {layer} files are missing for {trade_date}",
        missing_check_names=tuple(check_names),
        missing_file_paths=tuple(str(path) for path in missing_paths[:20]),
        summary={
            "layer": layer,
            "reason_code": "file_missing",
            "missing_file_count": len(missing_paths),
        },
    )


def _failure_status(
    *,
    trade_date: str,
    check_names: Sequence[str],
    failed_rules: Sequence[str],
    failed_row_count: int,
    scanned_file_count: int,
    layer: str,
    error: Exception | None = None,
) -> ContinuityDateReadiness:
    summary: dict[str, object] = {
        "layer": layer,
        "reason_code": "scan_error" if error else "core_check_failed",
        "failed_rules": list(dict.fromkeys(failed_rules)),
        "checked_row_count": 0,
        "failed_row_count": failed_row_count,
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
            f"index_mins {layer} readiness scan failed for {trade_date}"
            if error
            else f"index_mins {layer} core checks failed for {trade_date}"
        ),
        failed_check_names=tuple(check_names),
        summary=summary,
    )


def _ready_status(
    *,
    trade_date: str,
    layer: str,
    checked_row_count: int,
    scanned_file_count: int,
    extra: dict[str, object] | None = None,
) -> ContinuityDateReadiness:
    summary: dict[str, object] = {
        "layer": layer,
        "reason_code": "ready",
        "checked_row_count": checked_row_count,
        "failed_row_count": 0,
        "scanned_file_count": scanned_file_count,
    }
    if extra:
        summary.update(extra)
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason=f"index_mins {layer} ready for {trade_date}",
        summary=summary,
    )


def _raw_status_for_trade_date(
    *,
    connection,
    lake_root: Path,
    trade_date: str,
) -> tuple[ContinuityDateReadiness, int]:
    paths = tuple(
        raw_index_mins_path(
            lake_root,
            INDEX_MINS_SOURCE_FREQ_BY_ASSET_FREQ[frequency],
            trade_date,
        )
        for frequency in INDEX_MINS_ASSET_FREQS
    )
    missing = tuple(path for path in paths if not path.exists())
    if missing:
        missing_checks = tuple(
            _RAW_CHECK_NAMES[index]
            for index, path in enumerate(paths)
            if path in missing
        )
        return (
            _missing_status(
                trade_date=trade_date,
                check_names=missing_checks,
                missing_paths=missing,
                layer="raw",
            ),
            len(paths) - len(missing),
        )

    failed_rules: list[str] = []
    failed_checks: list[str] = []
    checked_row_count = 0
    for index, frequency in enumerate(INDEX_MINS_ASSET_FREQS):
        path = paths[index]
        source_freq = INDEX_MINS_SOURCE_FREQ_BY_ASSET_FREQ[frequency]
        try:
            if not _schema_matches(connection, path, RAW_INDEX_MINS_SCHEMA):
                failed_rules.append(f"{frequency}m:schema_matches_contract")
            relation = read_parquet(path, hive_partitioning=False)
            row_count = int(connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0])
            checked_row_count += row_count
            invalid_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {relation} WHERE "
                    f"{_raw_invalid_predicate(partition_key=trade_date, source_freq=source_freq)}"
                ).fetchone()[0]
            )
            duplicate_count = int(
                connection.execute(
                    f"SELECT count(*) - count(DISTINCT (ts_code, freq, trade_time)) FROM {relation}"
                ).fetchone()[0]
            )
            if row_count <= 0:
                failed_rules.append(f"{frequency}m:row_count_positive")
            if invalid_count:
                failed_rules.append(f"{frequency}m:identity_partition_value_domain")
            if duplicate_count:
                failed_rules.append(f"{frequency}m:business_key_unique")
            if invalid_count or duplicate_count or row_count <= 0:
                failed_checks.append(_RAW_CHECK_NAMES[index])
        except Exception as error:  # noqa: BLE001 - readiness must fail closed.
            return (
                _failure_status(
                    trade_date=trade_date,
                    check_names=(_RAW_CHECK_NAMES[index],),
                    failed_rules=(f"{frequency}m:parquet_readable",),
                    failed_row_count=0,
                    scanned_file_count=len(paths),
                    layer="raw",
                    error=error,
                ),
                len(paths),
            )
    if failed_rules:
        return (
            _failure_status(
                trade_date=trade_date,
                check_names=failed_checks or _RAW_CHECK_NAMES,
                failed_rules=failed_rules,
                failed_row_count=len(failed_rules),
                scanned_file_count=len(paths),
                layer="raw",
            ),
            len(paths),
        )
    return (
        _ready_status(
            trade_date=trade_date,
            layer="raw",
            checked_row_count=checked_row_count,
            scanned_file_count=len(paths),
        ),
        len(paths),
    )


def batch_raw_index_mins_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
) -> ContinuityBatchReadiness:
    """Read the five Raw frequencies for at most the sensor window in one connection."""

    del registered_trade_days  # Registration is gated by the sensor before this scan.
    started_at = perf_counter()
    expected = _bounded_expected_dates(expected_trade_dates)
    statuses: dict[str, ContinuityDateReadiness] = {}
    scanned_file_count = 0
    for trade_date in expected:
        status, file_count = _raw_status_for_trade_date(
            connection=connection,
            lake_root=lake_root,
            trade_date=trade_date,
        )
        statuses[trade_date] = status
        scanned_file_count += file_count
    return ContinuityBatchReadiness(
        expected_trade_dates=expected,
        statuses_by_trade_date=statuses,
        elapsed_ms=round((perf_counter() - started_at) * 1000),
        scanned_file_count=scanned_file_count,
    )


def _silver_status_for_trade_date(
    *,
    connection,
    lake_root: Path,
    trade_date: str,
) -> tuple[ContinuityDateReadiness, int]:
    target_paths = tuple(
        silver_index_mins_path(lake_root, frequency, trade_date)
        for frequency in INDEX_MINS_SILVER_FREQS
    )
    missing = tuple(path for path in target_paths if not path.exists())
    existing = tuple(path for path in target_paths if path.exists())
    if missing and not existing:
        return (
            _missing_status(
                trade_date=trade_date,
                check_names=_SILVER_CHECK_NAMES,
                missing_paths=missing,
                layer="silver",
            ),
            0,
        )

    failed_rules: list[str] = []
    failed_checks: list[str] = []
    checked_row_count = 0
    scanned_file_count = len(existing)
    for index, silver_frequency in enumerate(INDEX_MINS_SILVER_FREQS):
        target_path = target_paths[index]
        if not target_path.exists():
            continue
        normalized_frequency = f"{silver_frequency}min"
        derived = silver_frequency in (90, 120)
        source_frequency = (
            source_freq_for_index_mins_derived_freq(normalized_frequency)
            if derived
            else normalized_frequency
        )
        source_path = (
            silver_index_mins_path(lake_root, source_frequency, trade_date)
            if derived
            else raw_index_mins_path(lake_root, source_frequency, trade_date)
        )
        if source_path.exists():
            scanned_file_count += 1
        try:
            _assert_schema(
                connection,
                target_path,
                SILVER_INDEX_MINS_SCHEMA,
                label="index_mins Silver target",
            )
            target_relation = read_parquet(target_path, hive_partitioning=False)
            expected_row_count: int | None = None
            if not source_path.exists():
                failed_rules.append(f"{silver_frequency}m:source_file_exists")
            else:
                source_schema = SILVER_INDEX_MINS_SCHEMA if derived else RAW_INDEX_MINS_SCHEMA
                _assert_schema(
                    connection,
                    source_path,
                    source_schema,
                    label="index_mins Silver source",
                )
                source_relation = read_parquet(source_path, hive_partitioning=False)
                source_sql = _native_source_sql(source_relation)
                source_validation = _validate_relation(
                    connection,
                    relation_sql=source_sql,
                    expected_freq=source_frequency,
                    partition_key=trade_date,
                    require_null_vwap=False,
                )
                if source_validation.row_count <= 0:
                    failed_rules.append(f"{silver_frequency}m:source_row_count_positive")
                if source_validation.invalid_row_count:
                    failed_rules.append(f"{silver_frequency}m:source_value_domain")
                if source_validation.duplicate_key_count:
                    failed_rules.append(f"{silver_frequency}m:source_business_key_unique")
                if derived:
                    diagnostics = _derived_diagnostics(
                        connection,
                        source_sql=source_sql,
                        silver_freq=normalized_frequency,
                        partition_key=trade_date,
                    )
                    expected_row_count = int(diagnostics["generated_window_count"])
                    if diagnostics["incomplete_window_count"]:
                        failed_rules.append(f"{silver_frequency}m:derived_window_complete")
                    if diagnostics["exchange_mismatch_window_count"]:
                        failed_rules.append(f"{silver_frequency}m:derived_exchange_unique")
                    if diagnostics["generated_window_count"] <= 0:
                        failed_rules.append(f"{silver_frequency}m:derived_window_generated")
                else:
                    expected_row_count = source_validation.row_count
            target_validation = _validate_relation(
                connection,
                relation_sql=target_relation,
                expected_freq=normalized_frequency,
                partition_key=trade_date,
                require_null_vwap=derived,
            )
            checked_row_count += target_validation.row_count
            if target_validation.row_count <= 0:
                failed_rules.append(f"{silver_frequency}m:row_count_positive")
            if expected_row_count is not None and target_validation.row_count != expected_row_count:
                failed_rules.append(f"{silver_frequency}m:output_row_count_matches_source_or_windows")
            if target_validation.invalid_row_count:
                failed_rules.append(f"{silver_frequency}m:output_value_domain")
            if target_validation.duplicate_key_count:
                failed_rules.append(f"{silver_frequency}m:output_business_key_unique")
            if derived and target_validation.non_null_vwap_count:
                failed_rules.append(f"{silver_frequency}m:derived_vwap_is_null")
        except Exception:  # noqa: BLE001 - readiness must fail closed.
            failed_rules.append(f"{silver_frequency}m:parquet_schema_and_contract")
        if any(rule.startswith(f"{silver_frequency}m:") for rule in failed_rules):
            failed_checks.append(_SILVER_CHECK_NAMES[index])

    if failed_rules:
        missing_rules = [
            f"{frequency}m:file_exists"
            for frequency, path in zip(INDEX_MINS_SILVER_FREQS, target_paths, strict=True)
            if not path.exists()
        ]
        return (
            _failure_status(
                trade_date=trade_date,
                check_names=failed_checks or _SILVER_CHECK_NAMES,
                failed_rules=(*failed_rules, *missing_rules),
                failed_row_count=len(failed_rules) + len(missing_rules),
                scanned_file_count=scanned_file_count,
                layer="silver",
            ),
            scanned_file_count,
        )
    if missing:
        missing_checks = tuple(
            _SILVER_CHECK_NAMES[index]
            for index, path in enumerate(target_paths)
            if not path.exists()
        )
        return (
            _missing_status(
                trade_date=trade_date,
                check_names=missing_checks,
                missing_paths=missing,
                layer="silver",
            ),
            scanned_file_count,
        )
    return (
        _ready_status(
            trade_date=trade_date,
            layer="silver",
            checked_row_count=checked_row_count,
            scanned_file_count=scanned_file_count,
        ),
        scanned_file_count,
    )


def batch_silver_index_mins_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
) -> ContinuityBatchReadiness:
    """Read seven Silver frequencies and their bounded source windows in one connection."""

    del registered_trade_days
    started_at = perf_counter()
    expected = _bounded_expected_dates(expected_trade_dates)
    statuses: dict[str, ContinuityDateReadiness] = {}
    scanned_file_count = 0
    for trade_date in expected:
        status, file_count = _silver_status_for_trade_date(
            connection=connection,
            lake_root=lake_root,
            trade_date=trade_date,
        )
        statuses[trade_date] = status
        scanned_file_count += file_count
    return ContinuityBatchReadiness(
        expected_trade_dates=expected,
        statuses_by_trade_date=statuses,
        elapsed_ms=round((perf_counter() - started_at) * 1000),
        scanned_file_count=scanned_file_count,
    )


__all__ = [
    "batch_raw_index_mins_lake_readiness",
    "batch_silver_index_mins_lake_readiness",
]
