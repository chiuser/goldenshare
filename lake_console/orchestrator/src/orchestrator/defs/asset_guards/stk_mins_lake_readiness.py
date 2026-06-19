"""Lake-file readiness helpers for stock minute hot-path sensors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.assets.stk_mins import STK_MINS_RAW_COLUMN_TYPES
from orchestrator.defs.checks.stk_mins_checks import (
    RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
    RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK,
    RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK,
    RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK,
    RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK,
    RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
    RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
)
from orchestrator.defs.duckdb_sql import describe_parquet_query, duckdb_string
from orchestrator.defs.paths import raw_stk_mins_path
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    normalize_stk_mins_freq,
)


@dataclass(frozen=True)
class StkMinsDateReadiness:
    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    reason: str
    failed_check_names: tuple[str, ...]
    missing_file_paths: tuple[str, ...]
    expected_file_count: int
    existing_file_count: int
    checked_row_count: int = 0
    failed_row_count: int = 0
    sample_rows: tuple[dict[str, object], ...] = ()

    def to_cursor_details(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "ready": self.ready,
            "materialized": self.materialized,
            "checks_passed": self.checks_passed,
            "reason": self.reason,
            "failed_check_names": list(self.failed_check_names),
            "missing_file_paths": list(self.missing_file_paths),
            "expected_file_count": self.expected_file_count,
            "existing_file_count": self.existing_file_count,
            "checked_row_count": self.checked_row_count,
            "failed_row_count": self.failed_row_count,
            "sample_rows": list(self.sample_rows),
        }


@dataclass(frozen=True)
class StkMinsBatchReadiness:
    dataset: str
    expected_start_date: str | None
    expected_end_date: str | None
    expected_count: int
    freq_count: int
    elapsed_ms: float
    statuses_by_trade_date: Mapping[str, StkMinsDateReadiness]

    def status_for_trade_date(self, trade_date: str) -> StkMinsDateReadiness:
        status = self.statuses_by_trade_date.get(trade_date)
        if status is not None:
            return status
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"raw stk mins lake readiness status is missing for {trade_date}",
            failed_check_names=("raw_stk_mins_lake_readiness_status_missing",),
            missing_file_paths=(),
            expected_file_count=self.freq_count,
            existing_file_count=0,
        )


@dataclass(frozen=True)
class _RawPathPlan:
    trade_date: str
    freq: int
    path: Path


@dataclass(frozen=True)
class _RawPathMetrics:
    row_count: int = 0
    freq_failed_count: int = 0
    date_failed_count: int = 0
    duplicate_failed_count: int = 0
    sanity_failed_count: int = 0

    @property
    def failed_row_count(self) -> int:
        return (
            self.freq_failed_count
            + self.date_failed_count
            + self.duplicate_failed_count
            + self.sanity_failed_count
        )


def _normalize_trade_dates(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _normalize_freqs(freqs: Sequence[int]) -> tuple[int, ...]:
    return tuple(normalize_stk_mins_freq(freq) for freq in freqs)


def _expected_bounds(
    expected_trade_dates: Sequence[str],
) -> tuple[str | None, str | None]:
    if not expected_trade_dates:
        return None, None
    return expected_trade_dates[0], expected_trade_dates[-1]


def _raw_path_plans(
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    freqs: Sequence[int],
) -> tuple[_RawPathPlan, ...]:
    return tuple(
        _RawPathPlan(
            trade_date=trade_date,
            freq=freq,
            path=raw_stk_mins_path(lake_root, freq, trade_date),
        )
        for trade_date in expected_trade_dates
        for freq in freqs
    )


def _describe_columns(connection, path: Path) -> dict[str, str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _schema_matches_raw_contract(connection, path: Path) -> bool:
    observed_schema = _describe_columns(connection, path)
    missing_columns = [
        column for column in STK_MINS_RAW_COLUMN_TYPES if column not in observed_schema
    ]
    type_mismatches = [
        column
        for column, expected_type in STK_MINS_RAW_COLUMN_TYPES.items()
        if observed_schema.get(column) != expected_type
    ]
    return not missing_columns and not type_mismatches


def _path_list_sql(paths: Sequence[Path]) -> str:
    return "[" + ", ".join(duckdb_string(path) for path in paths) + "]"


def _path_plan_values_sql(path_plans: Sequence[_RawPathPlan]) -> str:
    return ",\n".join(
        f"({duckdb_string(path_plan.path)}, "
        f"{duckdb_string(path_plan.trade_date)}, {int(path_plan.freq)})"
        for path_plan in path_plans
    )


def _raw_path_metrics(
    connection,
    path_plans: Sequence[_RawPathPlan],
) -> dict[Path, _RawPathMetrics]:
    if not path_plans:
        return {}

    path_list_sql = _path_list_sql(tuple(path_plan.path for path_plan in path_plans))
    path_values_sql = _path_plan_values_sql(path_plans)
    rows = connection.execute(
        f"""
        WITH path_plan(file_path, expected_trade_date, expected_freq) AS (
          VALUES {path_values_sql}
        ),
        raw_rows AS (
          SELECT
            filename AS file_path,
            path_plan.expected_trade_date,
            path_plan.expected_freq,
            ts_code,
            trade_time,
            freq,
            open,
            close,
            high,
            low,
            vol,
            amount,
            vwap
          FROM read_parquet(
            {path_list_sql},
            hive_partitioning=false,
            filename=true,
            union_by_name=true
          ) AS raw_file
          INNER JOIN path_plan
            ON raw_file.filename = path_plan.file_path
        ),
        row_checks AS (
          SELECT
            file_path,
            count(*) AS row_count,
            sum(
              CASE WHEN CAST(freq AS INTEGER) != expected_freq THEN 1 ELSE 0 END
            ) AS freq_failed_count,
            sum(
              CASE
                WHEN CAST(trade_time AS DATE)
                  != CAST(expected_trade_date AS DATE)
                THEN 1 ELSE 0
              END
            ) AS date_failed_count,
            sum(
              CASE
                WHEN ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
                  OR open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
                  OR vol IS NULL OR amount IS NULL OR vwap IS NULL
                  OR open < 0 OR close < 0 OR high < 0 OR low < 0
                  OR vol < 0 OR amount < 0 OR vwap < 0
                THEN 1 ELSE 0
              END
            ) AS sanity_failed_count
          FROM raw_rows
          GROUP BY file_path
        ),
        duplicate_checks AS (
          SELECT file_path, count(*) AS duplicate_failed_count
          FROM (
            SELECT file_path, ts_code, trade_time, count(*) AS duplicate_count
            FROM raw_rows
            GROUP BY file_path, ts_code, trade_time
            HAVING count(*) > 1
          )
          GROUP BY file_path
        )
        SELECT
          path_plan.file_path,
          coalesce(row_checks.row_count, 0) AS row_count,
          coalesce(row_checks.freq_failed_count, 0) AS freq_failed_count,
          coalesce(row_checks.date_failed_count, 0) AS date_failed_count,
          coalesce(duplicate_checks.duplicate_failed_count, 0)
            AS duplicate_failed_count,
          coalesce(row_checks.sanity_failed_count, 0) AS sanity_failed_count
        FROM path_plan
        LEFT JOIN row_checks
          ON path_plan.file_path = row_checks.file_path
        LEFT JOIN duplicate_checks
          ON path_plan.file_path = duplicate_checks.file_path
        ORDER BY path_plan.expected_trade_date, path_plan.expected_freq
        """
    ).fetchall()
    return {
        Path(str(row[0])): _RawPathMetrics(
            row_count=int(row[1] or 0),
            freq_failed_count=int(row[2] or 0),
            date_failed_count=int(row[3] or 0),
            duplicate_failed_count=int(row[4] or 0),
            sanity_failed_count=int(row[5] or 0),
        )
        for row in rows
    }


def _raw_path_row_counts(
    connection,
    path_plans: Sequence[_RawPathPlan],
) -> dict[Path, int]:
    if not path_plans:
        return {}
    path_list_sql = _path_list_sql(tuple(path_plan.path for path_plan in path_plans))
    rows = connection.execute(
        f"""
        SELECT filename AS file_path, count(*) AS row_count
        FROM read_parquet(
          {path_list_sql},
          hive_partitioning=false,
          filename=true,
          union_by_name=true
        )
        GROUP BY filename
        """
    ).fetchall()
    return {Path(str(row[0])): int(row[1] or 0) for row in rows}


def _raw_status_for_trade_date(
    *,
    trade_date: str,
    path_plans: Sequence[_RawPathPlan],
    registered_trade_day_set: set[str],
    schema_valid_paths: set[Path],
    metrics_by_path: Mapping[Path, _RawPathMetrics],
    full_semantics: bool,
) -> StkMinsDateReadiness:
    missing_paths = tuple(
        str(path_plan.path) for path_plan in path_plans if not path_plan.path.exists()
    )
    if trade_date not in registered_trade_day_set:
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"raw stk mins partition is not registered for {trade_date}",
            failed_check_names=(RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK,),
            missing_file_paths=missing_paths,
            expected_file_count=len(path_plans),
            existing_file_count=len(path_plans) - len(missing_paths),
        )
    if missing_paths:
        return StkMinsDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=False,
            checks_passed=False,
            reason=f"raw stk mins files are missing for {trade_date}",
            failed_check_names=(
                RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
            ),
            missing_file_paths=missing_paths,
            expected_file_count=len(path_plans),
            existing_file_count=len(path_plans) - len(missing_paths),
        )

    failed_check_names: list[str] = []
    checked_row_count = 0
    failed_row_count = 0
    for path_plan in path_plans:
        metrics = metrics_by_path.get(path_plan.path, _RawPathMetrics())
        checked_row_count += metrics.row_count
        failed_row_count += metrics.failed_row_count
        if metrics.row_count <= 0:
            failed_check_names.append(
                RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
            )
        if full_semantics and path_plan.path not in schema_valid_paths:
            failed_check_names.append(RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK)
        if full_semantics and metrics.freq_failed_count:
            failed_check_names.append(RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK)
        if full_semantics and metrics.date_failed_count:
            failed_check_names.append(RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK)
        if full_semantics and metrics.duplicate_failed_count:
            failed_check_names.append(RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK)
        if full_semantics and metrics.sanity_failed_count:
            failed_check_names.append(RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK)

    failed_check_names = sorted(set(failed_check_names))
    checks_passed = not failed_check_names
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=checks_passed,
        materialized=True,
        checks_passed=checks_passed,
        reason=(
            "ready"
            if checks_passed
            else "raw stk mins blocking checks failed for "
            f"{trade_date}: {', '.join(failed_check_names)}"
        ),
        failed_check_names=tuple(failed_check_names),
        missing_file_paths=(),
        expected_file_count=len(path_plans),
        existing_file_count=len(path_plans),
        checked_row_count=checked_row_count,
        failed_row_count=failed_row_count,
    )


def batch_raw_stk_mins_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    freqs: Sequence[int] = STK_MINS_FREQS,
    full_semantics: bool = True,
) -> StkMinsBatchReadiness:
    started_at = perf_counter()
    expected_trade_dates = _normalize_trade_dates(expected_trade_dates)
    registered_trade_day_set = set(_normalize_trade_dates(registered_trade_days))
    freqs = _normalize_freqs(freqs)
    expected_start_date, expected_end_date = _expected_bounds(expected_trade_dates)
    path_plans = _raw_path_plans(
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        freqs=freqs,
    )
    existing_path_plans = tuple(path_plan for path_plan in path_plans if path_plan.path.exists())

    schema_valid_paths: set[Path] = set()
    if full_semantics:
        for path_plan in existing_path_plans:
            if _schema_matches_raw_contract(connection, path_plan.path):
                schema_valid_paths.add(path_plan.path)
    else:
        schema_valid_paths = {path_plan.path for path_plan in existing_path_plans}

    data_check_path_plans = tuple(
        path_plan
        for path_plan in existing_path_plans
        if path_plan.path in schema_valid_paths
    )
    row_counts_by_path = _raw_path_row_counts(connection, existing_path_plans)
    metrics_by_path = {
        path: _RawPathMetrics(row_count=row_count)
        for path, row_count in row_counts_by_path.items()
    }
    metrics_by_path.update(_raw_path_metrics(connection, data_check_path_plans))
    path_plans_by_trade_date = {
        trade_date: tuple(
            path_plan for path_plan in path_plans if path_plan.trade_date == trade_date
        )
        for trade_date in expected_trade_dates
    }
    statuses_by_trade_date = {
        trade_date: _raw_status_for_trade_date(
            trade_date=trade_date,
            path_plans=path_plans_by_trade_date[trade_date],
            registered_trade_day_set=registered_trade_day_set,
            schema_valid_paths=schema_valid_paths,
            metrics_by_path=metrics_by_path,
            full_semantics=full_semantics,
        )
        for trade_date in expected_trade_dates
    }

    elapsed_ms = (perf_counter() - started_at) * 1000
    return StkMinsBatchReadiness(
        dataset="raw_stk_mins",
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
        expected_count=len(expected_trade_dates),
        freq_count=len(freqs),
        elapsed_ms=elapsed_ms,
        statuses_by_trade_date=statuses_by_trade_date,
    )
