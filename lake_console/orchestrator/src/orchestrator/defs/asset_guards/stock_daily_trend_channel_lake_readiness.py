"""Bounded Lake readiness for stock daily trend-channel partitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import perf_counter

import duckdb

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_state_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA,
    GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA,
)
from orchestrator.defs.stock_daily_trend_channel import (
    FORMULA_VERSION,
    SEGMENT_TRADE_DAY_LIMIT,
    StockDailyTrendChannelCoverageRuleMetrics,
    StockDailyTrendChannelResultRuleMetrics,
    StockDailyTrendChannelStateRuleMetrics,
    evaluate_stock_daily_trend_channel_coverage_rules,
    evaluate_stock_daily_trend_channel_result_rules,
    evaluate_stock_daily_trend_channel_state_rules,
)

STOCK_DAILY_TREND_CHANNEL_READINESS_WINDOW_LIMIT = 10
STOCK_DAILY_TREND_CHANNEL_RESULT_CHECKS = (
    "gold_stock_daily_trend_channel_contract_check",
    "gold_stock_daily_trend_channel_input_coverage_check",
)
STOCK_DAILY_TREND_CHANNEL_STATE_CHECKS = (
    "gold_stock_daily_trend_channel_state_contract_check",
)
STOCK_DAILY_TREND_CHANNEL_ALL_CHECKS = (
    *STOCK_DAILY_TREND_CHANNEL_RESULT_CHECKS,
    *STOCK_DAILY_TREND_CHANNEL_STATE_CHECKS,
)


@dataclass(frozen=True)
class StockDailyTrendChannelBatchReadiness(ContinuityBatchReadiness):
    """Per-date readiness plus bounded-query performance evidence."""

    sql_count: int = 0
    slowest_query_ms: int = 0
    window_date_count: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.sql_count < 0:
            raise ValueError("sql_count must not be negative.")
        if self.slowest_query_ms < 0:
            raise ValueError("slowest_query_ms must not be negative.")
        if self.window_date_count != len(self.expected_trade_dates):
            raise ValueError(
                "window_date_count must match expected_trade_dates length."
            )

    def to_cursor_details(self, *, sample_limit: int = 20) -> dict[str, object]:
        details = super().to_cursor_details(sample_limit=sample_limit)
        details.update(
            {
                "sql_count": self.sql_count,
                "slowest_query_ms": self.slowest_query_ms,
                "window_date_count": self.window_date_count,
            }
        )
        return details


@dataclass(frozen=True)
class StockDailyTrendChannelHistorySegmentAudit:
    """Set-based audit evidence for one bounded history segment."""

    trade_dates: tuple[str, ...]
    statuses_by_trade_date: Mapping[str, ContinuityDateReadiness]
    elapsed_ms: int
    scanned_file_count: int
    sql_count: int
    slowest_query_ms: int

    @property
    def passed(self) -> bool:
        return bool(self.trade_dates) and all(
            self.statuses_by_trade_date[trade_date].ready
            for trade_date in self.trade_dates
        )

    @property
    def failed_trade_dates(self) -> tuple[str, ...]:
        return tuple(
            trade_date
            for trade_date in self.trade_dates
            if not self.statuses_by_trade_date[trade_date].ready
        )


def audit_stock_daily_trend_channel_history_segment(
    *,
    connection,
    trade_dates: Sequence[str],
    result_paths: Mapping[str, Path],
    state_paths: Mapping[str, Path],
    qfq_paths: Mapping[str, Path],
    lifecycle_path: Path,
    previous_state_path: Path | None,
) -> StockDailyTrendChannelHistorySegmentAudit:
    """Audit up to 250 history dates with two set-based DuckDB queries."""

    started_at = perf_counter()
    normalized_dates = _normalize_trade_dates(trade_dates)
    if not normalized_dates:
        raise ValueError("history segment trade dates must not be empty.")
    if len(normalized_dates) > SEGMENT_TRADE_DAY_LIMIT:
        raise ValueError(
            "history segment exceeds the trend-channel trade-day limit: "
            f"{len(normalized_dates)} > {SEGMENT_TRADE_DAY_LIMIT}."
        )
    expected_keys = set(normalized_dates)
    for label, paths in (
        ("result", result_paths),
        ("state", state_paths),
        ("qfq", qfq_paths),
    ):
        if set(paths) != expected_keys:
            raise ValueError(f"history {label} paths must match the exact date scope.")
    required_paths = tuple(
        dict.fromkeys(
            [lifecycle_path]
            + [result_paths[value] for value in normalized_dates]
            + [state_paths[value] for value in normalized_dates]
            + [qfq_paths[value] for value in normalized_dates]
            + ([previous_state_path] if previous_state_path is not None else [])
        )
    )
    missing_paths = tuple(path for path in required_paths if not path.is_file())
    if missing_paths:
        raise FileNotFoundError(
            "history segment audit inputs are missing: "
            + ", ".join(str(path) for path in missing_paths[:20])
        )

    output_paths = tuple(
        [result_paths[value] for value in normalized_dates]
        + [state_paths[value] for value in normalized_dates]
    )
    schema_started_at = perf_counter()
    schema_by_path = _load_parquet_schemas(connection, output_paths)
    schema_elapsed_ms = _elapsed_ms(schema_started_at)
    expected_result_schema = tuple(
        (column.name, column.type.upper())
        for column in GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA
    )
    expected_state_schema = tuple(
        (column.name, column.type.upper())
        for column in GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA
    )
    schema_failures = tuple(
        trade_date
        for trade_date in normalized_dates
        if schema_by_path.get(result_paths[trade_date]) != expected_result_schema
        or schema_by_path.get(state_paths[trade_date]) != expected_state_schema
    )
    if schema_failures:
        raise ValueError(
            "history segment schema contract failed: " + ", ".join(schema_failures[:20])
        )

    previous_paths: dict[str, Path | None] = {}
    previous = previous_state_path
    for trade_date in normalized_dates:
        previous_paths[trade_date] = previous
        previous = state_paths[trade_date]
    audit_started_at = perf_counter()
    audit_rows = _load_batch_audit_rows(
        connection,
        trade_dates=normalized_dates,
        result_paths=result_paths,
        state_paths=state_paths,
        qfq_paths=qfq_paths,
        lifecycle_path=lifecycle_path,
        previous_state_paths=previous_paths,
    )
    audit_elapsed_ms = _elapsed_ms(audit_started_at)
    statuses = {
        trade_date: _status_from_audit_row(
            trade_date=trade_date,
            row=audit_rows[trade_date],
        )
        for trade_date in normalized_dates
    }
    return StockDailyTrendChannelHistorySegmentAudit(
        trade_dates=normalized_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=_elapsed_ms(started_at),
        scanned_file_count=len(required_paths),
        sql_count=2,
        slowest_query_ms=max(schema_elapsed_ms, audit_elapsed_ms),
    )


@dataclass(frozen=True)
class _QueryMetrics:
    sql_count: int = 0
    slowest_query_ms: int = 0

    def add(self, elapsed_ms: int) -> _QueryMetrics:
        return _QueryMetrics(
            sql_count=self.sql_count + 1,
            slowest_query_ms=max(self.slowest_query_ms, elapsed_ms),
        )


def batch_gold_stock_daily_trend_channel_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    previous_trade_date: str | None,
) -> StockDailyTrendChannelBatchReadiness:
    """Audit at most ten paired target partitions with two set-based SQL calls."""

    started_at = perf_counter()
    trade_dates = _normalize_trade_dates(expected_trade_dates)
    if len(trade_dates) > STOCK_DAILY_TREND_CHANNEL_READINESS_WINDOW_LIMIT:
        raise ValueError(
            "stock daily trend-channel readiness accepts at most "
            f"{STOCK_DAILY_TREND_CHANNEL_READINESS_WINDOW_LIMIT} trade dates."
        )
    normalized_previous_trade_date = (
        _normalize_trade_date(previous_trade_date)
        if previous_trade_date is not None
        else None
    )
    if (
        trade_dates
        and normalized_previous_trade_date is not None
        and normalized_previous_trade_date >= trade_dates[0]
    ):
        raise ValueError(
            "previous_trade_date must precede the first expected trade date."
        )

    result_paths = {
        trade_date: gold_stock_daily_trend_channel_path(lake_root, trade_date)
        for trade_date in trade_dates
    }
    state_paths = {
        trade_date: gold_stock_daily_trend_channel_state_path(
            lake_root,
            trade_date,
        )
        for trade_date in trade_dates
    }
    qfq_paths = {
        trade_date: gold_stock_daily_qfq_path(lake_root, trade_date)
        for trade_date in trade_dates
    }
    lifecycle_path = silver_stock_lifecycle_path(lake_root)
    previous_by_trade_date = _previous_trade_dates_by_target(
        trade_dates=trade_dates,
        previous_trade_date=normalized_previous_trade_date,
    )
    previous_state_paths = {
        trade_date: (
            gold_stock_daily_trend_channel_state_path(lake_root, previous_date)
            if previous_date is not None
            else None
        )
        for trade_date, previous_date in previous_by_trade_date.items()
    }

    statuses: dict[str, ContinuityDateReadiness] = {}
    auditable_dates: list[str] = []
    output_paths: list[Path] = []
    for trade_date in trade_dates:
        result_path = result_paths[trade_date]
        state_path = state_paths[trade_date]
        result_exists = result_path.is_file()
        state_exists = state_path.is_file()
        if not result_exists and not state_exists:
            statuses[trade_date] = _missing_target_status(
                trade_date=trade_date,
                result_path=result_path,
                state_path=state_path,
            )
            continue
        if not result_exists or not state_exists:
            statuses[trade_date] = _partial_target_status(
                trade_date=trade_date,
                result_path=result_path,
                state_path=state_path,
            )
            continue

        path_failures = _partition_path_failures(
            trade_date=trade_date,
            result_path=result_path,
            state_path=state_path,
        )
        if path_failures:
            statuses[trade_date] = _failed_status(
                trade_date=trade_date,
                reason="target_partition_file_contract_failed",
                failed_check_names=STOCK_DAILY_TREND_CHANNEL_ALL_CHECKS,
                summary={"failure_rule_counts": path_failures},
            )
            continue

        missing_inputs = tuple(
            path
            for path in (
                qfq_paths[trade_date],
                lifecycle_path,
                previous_state_paths[trade_date],
            )
            if path is not None and not path.is_file()
        )
        if missing_inputs:
            statuses[trade_date] = _failed_status(
                trade_date=trade_date,
                reason="target_audit_input_missing",
                failed_check_names=STOCK_DAILY_TREND_CHANNEL_ALL_CHECKS,
                summary={
                    "failure_rule_counts": {"required_file_exists": len(missing_inputs)}
                },
            )
            continue
        auditable_dates.append(trade_date)
        output_paths.extend((result_path, state_path))

    metrics = _QueryMetrics()
    schema_by_path: dict[Path, tuple[tuple[str, str], ...]] = {}
    if output_paths:
        query_started_at = perf_counter()
        try:
            schema_by_path = _load_parquet_schemas(
                connection,
                tuple(dict.fromkeys(output_paths)),
            )
        except duckdb.Error as error:
            metrics = metrics.add(_elapsed_ms(query_started_at))
            for trade_date in auditable_dates:
                statuses[trade_date] = _failed_status(
                    trade_date=trade_date,
                    reason="target_schema_scan_failed",
                    failed_check_names=STOCK_DAILY_TREND_CHANNEL_ALL_CHECKS,
                    summary={"error_type": type(error).__name__},
                )
            auditable_dates = []
        else:
            metrics = metrics.add(_elapsed_ms(query_started_at))

    schema_valid_dates: list[str] = []
    result_schema = tuple(
        (column.name, column.type.upper())
        for column in GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA
    )
    state_schema = tuple(
        (column.name, column.type.upper())
        for column in GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA
    )
    for trade_date in auditable_dates:
        result_observed = schema_by_path.get(result_paths[trade_date], ())
        state_observed = schema_by_path.get(state_paths[trade_date], ())
        if result_observed != result_schema or state_observed != state_schema:
            statuses[trade_date] = _failed_status(
                trade_date=trade_date,
                reason="target_schema_contract_failed",
                failed_check_names=STOCK_DAILY_TREND_CHANNEL_ALL_CHECKS,
                summary={
                    "failure_rule_counts": {"schema_matches_contract": 1},
                    "result_schema_matches": result_observed == result_schema,
                    "state_schema_matches": state_observed == state_schema,
                },
            )
            continue
        schema_valid_dates.append(trade_date)

    if schema_valid_dates:
        query_started_at = perf_counter()
        try:
            audit_rows = _load_batch_audit_rows(
                connection,
                trade_dates=tuple(schema_valid_dates),
                result_paths=result_paths,
                state_paths=state_paths,
                qfq_paths=qfq_paths,
                lifecycle_path=lifecycle_path,
                previous_state_paths=previous_state_paths,
            )
        except duckdb.Error as error:
            metrics = metrics.add(_elapsed_ms(query_started_at))
            for trade_date in schema_valid_dates:
                statuses[trade_date] = _failed_status(
                    trade_date=trade_date,
                    reason="target_batch_audit_failed",
                    failed_check_names=STOCK_DAILY_TREND_CHANNEL_ALL_CHECKS,
                    summary={"error_type": type(error).__name__},
                )
        else:
            metrics = metrics.add(_elapsed_ms(query_started_at))
            for trade_date in schema_valid_dates:
                row = audit_rows.get(trade_date)
                if row is None:
                    statuses[trade_date] = _failed_status(
                        trade_date=trade_date,
                        reason="target_batch_audit_row_missing",
                        failed_check_names=STOCK_DAILY_TREND_CHANNEL_ALL_CHECKS,
                        summary={},
                    )
                    continue
                statuses[trade_date] = _status_from_audit_row(
                    trade_date=trade_date,
                    row=row,
                )

    boundary_state_path = (
        gold_stock_daily_trend_channel_state_path(
            lake_root,
            normalized_previous_trade_date,
        )
        if normalized_previous_trade_date is not None
        else None
    )
    scanned_file_count = sum(
        int(result_paths[trade_date].is_file()) + int(state_paths[trade_date].is_file())
        for trade_date in trade_dates
    ) + int(boundary_state_path is not None and boundary_state_path.is_file())
    return StockDailyTrendChannelBatchReadiness(
        expected_trade_dates=trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=_elapsed_ms(started_at),
        scanned_file_count=scanned_file_count,
        sql_count=metrics.sql_count,
        slowest_query_ms=metrics.slowest_query_ms,
        window_date_count=len(trade_dates),
    )


def _normalize_trade_date(value: str | None) -> str:
    normalized = str(value).strip()
    parsed = date.fromisoformat(normalized)
    if parsed.isoformat() != normalized:
        raise ValueError("trade date must use YYYY-MM-DD")
    return normalized


def _normalize_trade_dates(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(_normalize_trade_date(value) for value in values)
    if normalized != tuple(sorted(set(normalized))):
        raise ValueError("expected_trade_dates must be sorted and unique.")
    return normalized


def _previous_trade_dates_by_target(
    *,
    trade_dates: Sequence[str],
    previous_trade_date: str | None,
) -> dict[str, str | None]:
    previous_by_target: dict[str, str | None] = {}
    previous = previous_trade_date
    for trade_date in trade_dates:
        previous_by_target[trade_date] = previous
        previous = trade_date
    return previous_by_target


def _partition_path_failures(
    *,
    trade_date: str,
    result_path: Path,
    state_path: Path,
) -> dict[str, int]:
    paths = (result_path, state_path)
    path_match_count = sum(
        path.parent.name != f"trade_date={trade_date}" for path in paths
    )
    single_file_count = sum(
        tuple(sorted(path.parent.glob("*.parquet"))) != (path,) for path in paths
    )
    failures = {
        "partition_path_matches": int(path_match_count),
        "single_partition_file": int(single_file_count),
    }
    return {key: value for key, value in failures.items() if value}


def _load_parquet_schemas(
    connection,
    paths: Sequence[Path],
) -> dict[Path, tuple[tuple[str, str], ...]]:
    path_sql = _path_list_sql(paths)
    rows = connection.execute(
        f"""
        SELECT file_name, name, upper(duckdb_type) AS duckdb_type
        FROM parquet_schema({path_sql})
        WHERE name != 'duckdb_schema'
        ORDER BY file_name, column_id
        """
    ).fetchall()
    return {
        path: tuple(
            (str(row[1]), str(row[2])) for row in rows if str(row[0]) == str(path)
        )
        for path in paths
    }


def _load_batch_audit_rows(
    connection,
    *,
    trade_dates: Sequence[str],
    result_paths: Mapping[str, Path],
    state_paths: Mapping[str, Path],
    qfq_paths: Mapping[str, Path],
    lifecycle_path: Path,
    previous_state_paths: Mapping[str, Path | None],
) -> dict[str, tuple[int, ...]]:
    dates_sql = _date_values_sql(trade_dates)
    result_inputs_sql = _path_date_values_sql(result_paths, trade_dates)
    state_inputs_sql = _path_date_values_sql(state_paths, trade_dates)
    qfq_inputs_sql = _path_date_values_sql(qfq_paths, trade_dates)
    previous_inputs = {
        trade_date: path
        for trade_date, path in previous_state_paths.items()
        if trade_date in trade_dates and path is not None
    }
    previous_inputs_sql = _path_date_values_sql(
        previous_inputs,
        tuple(previous_inputs),
    )
    all_state_paths = tuple(
        dict.fromkeys(
            [state_paths[trade_date] for trade_date in trade_dates]
            + [path for path in previous_inputs.values()]
        )
    )
    rows = connection.execute(
        f"""
        WITH dates(target_trade_date) AS ({dates_sql}),
        result_inputs(file_path, target_trade_date) AS ({result_inputs_sql}),
        state_inputs(file_path, target_trade_date) AS ({state_inputs_sql}),
        qfq_inputs(file_path, target_trade_date) AS ({qfq_inputs_sql}),
        previous_inputs(file_path, target_trade_date) AS ({previous_inputs_sql}),
        result_rows AS (
          SELECT
            inputs.target_trade_date,
            CAST(rows.ts_code AS VARCHAR) AS ts_code,
            CAST(rows.trade_date AS DATE) AS trade_date,
            CAST(rows.open AS DOUBLE) AS open,
            CAST(rows.high AS DOUBLE) AS high,
            CAST(rows.low AS DOUBLE) AS low,
            CAST(rows.close AS DOUBLE) AS close,
            CAST(rows.short_upper AS DOUBLE) AS short_upper,
            CAST(rows.short_lower AS DOUBLE) AS short_lower,
            CAST(rows.short_position AS VARCHAR) AS short_position,
            CAST(rows.short_state AS VARCHAR) AS short_state,
            CAST(rows.long_upper AS DOUBLE) AS long_upper,
            CAST(rows.long_lower AS DOUBLE) AS long_lower,
            CAST(rows.long_position AS VARCHAR) AS long_position,
            CAST(rows.long_state AS VARCHAR) AS long_state,
            CAST(rows.combined_state AS VARCHAR) AS combined_state,
            CAST(rows.formula_version AS VARCHAR) AS formula_version
          FROM read_parquet(
            {_path_list_sql([result_paths[value] for value in trade_dates])},
            filename=true,
            hive_partitioning=false,
            union_by_name=true
          ) rows
          JOIN result_inputs inputs ON rows.filename = inputs.file_path
        ),
        state_rows AS (
          SELECT
            inputs.target_trade_date,
            CAST(rows.ts_code AS VARCHAR) AS ts_code,
            CAST(rows.trade_date AS DATE) AS trade_date,
            CAST(rows.state_source_trade_date AS DATE) AS state_source_trade_date,
            CAST(rows.observed_on_partition AS BOOLEAN) AS observed_on_partition,
            CAST(rows.short_upper_raw AS DOUBLE) AS short_upper_raw,
            CAST(rows.short_lower_raw AS DOUBLE) AS short_lower_raw,
            CAST(rows.short_state AS VARCHAR) AS short_state,
            CAST(rows.long_upper_raw AS DOUBLE) AS long_upper_raw,
            CAST(rows.long_lower_raw AS DOUBLE) AS long_lower_raw,
            CAST(rows.long_state AS VARCHAR) AS long_state,
            CAST(rows.combined_state AS VARCHAR) AS combined_state,
            CAST(rows.formula_version AS VARCHAR) AS formula_version
          FROM read_parquet(
            {_path_list_sql([state_paths[value] for value in trade_dates])},
            filename=true,
            hive_partitioning=false,
            union_by_name=true
          ) rows
          JOIN state_inputs inputs ON rows.filename = inputs.file_path
        ),
        all_state_rows AS (
          SELECT filename, CAST(ts_code AS VARCHAR) AS ts_code
          FROM read_parquet(
            {_path_list_sql(all_state_paths)},
            filename=true,
            hive_partitioning=false,
            union_by_name=true
          )
        ),
        previous_codes AS (
          SELECT inputs.target_trade_date, rows.ts_code
          FROM previous_inputs inputs
          JOIN all_state_rows rows ON rows.filename = inputs.file_path
        ),
        qfq_rows AS (
          SELECT
            inputs.target_trade_date,
            CAST(rows.ts_code AS VARCHAR) AS ts_code,
            CAST(rows.trade_date AS DATE) AS trade_date
          FROM read_parquet(
            {_path_list_sql([qfq_paths[value] for value in trade_dates])},
            filename=true,
            hive_partitioning=false,
            union_by_name=true
          ) rows
          JOIN qfq_inputs inputs ON rows.filename = inputs.file_path
        ),
        valid_lifecycle AS (
          SELECT dates.target_trade_date, CAST(lifecycle.ts_code AS VARCHAR) AS ts_code
          FROM dates
          JOIN read_parquet(
            {duckdb_string(lifecycle_path)},
            hive_partitioning=false
          ) lifecycle
            ON CAST(lifecycle.is_cny_stock AS BOOLEAN)
           AND CAST(lifecycle.list_date AS DATE) <= dates.target_trade_date
           AND (
             lifecycle.delist_date IS NULL
             OR CAST(lifecycle.delist_date AS DATE) > dates.target_trade_date
           )
          GROUP BY dates.target_trade_date, lifecycle.ts_code
        ),
        result_duplicate_counts AS (
          SELECT target_trade_date, coalesce(sum(row_count), 0) AS failed_count
          FROM (
            SELECT target_trade_date, ts_code, trade_date, count(*) AS row_count
            FROM result_rows
            GROUP BY target_trade_date, ts_code, trade_date
            HAVING count(*) > 1
          ) duplicate_rows
          GROUP BY target_trade_date
        ),
        state_duplicate_counts AS (
          SELECT target_trade_date, coalesce(sum(row_count), 0) AS failed_count
          FROM (
            SELECT target_trade_date, ts_code, trade_date, count(*) AS row_count
            FROM state_rows
            GROUP BY target_trade_date, ts_code, trade_date
            HAVING count(*) > 1
          ) duplicate_rows
          GROUP BY target_trade_date
        ),
        missing_qfq_result AS (
          SELECT target_trade_date, ts_code, trade_date FROM qfq_rows
          EXCEPT
          SELECT target_trade_date, ts_code, trade_date FROM result_rows
        ),
        unexpected_result AS (
          SELECT target_trade_date, ts_code, trade_date FROM result_rows
          EXCEPT
          SELECT target_trade_date, ts_code, trade_date FROM qfq_rows
        ),
        qfq_codes AS (
          SELECT DISTINCT target_trade_date, ts_code
          FROM qfq_rows
          WHERE trade_date = target_trade_date
        ),
        expected_carry AS (
          SELECT previous.target_trade_date, previous.ts_code
          FROM previous_codes previous
          JOIN valid_lifecycle lifecycle
            ON lifecycle.target_trade_date = previous.target_trade_date
           AND lifecycle.ts_code = previous.ts_code
          LEFT JOIN qfq_codes qfq
            ON qfq.target_trade_date = previous.target_trade_date
           AND qfq.ts_code = previous.ts_code
          WHERE qfq.ts_code IS NULL
        ),
        expected_state AS (
          SELECT target_trade_date, ts_code, true AS observed_on_partition
          FROM qfq_codes
          UNION ALL
          SELECT target_trade_date, ts_code, false AS observed_on_partition
          FROM expected_carry
        ),
        actual_state AS (
          SELECT target_trade_date, ts_code, observed_on_partition
          FROM state_rows
          WHERE trade_date = target_trade_date
        ),
        uninitialized AS (
          SELECT lifecycle.target_trade_date, lifecycle.ts_code
          FROM valid_lifecycle lifecycle
          LEFT JOIN expected_state expected
            ON expected.target_trade_date = lifecycle.target_trade_date
           AND expected.ts_code = lifecycle.ts_code
          WHERE expected.ts_code IS NULL
        ),
        missing_state AS (
          SELECT target_trade_date, ts_code, observed_on_partition FROM expected_state
          EXCEPT
          SELECT target_trade_date, ts_code, observed_on_partition FROM actual_state
        ),
        unexpected_state AS (
          SELECT target_trade_date, ts_code, observed_on_partition FROM actual_state
          EXCEPT
          SELECT target_trade_date, ts_code, observed_on_partition FROM expected_state
        )
        SELECT
          strftime(dates.target_trade_date, '%Y-%m-%d') AS trade_date,
          (SELECT count(*) FROM result_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM qfq_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM result_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.trade_date IS NULL OR rows.trade_date != dates.target_trade_date)),
          (SELECT count(*) FROM result_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.ts_code IS NULL OR trim(rows.ts_code) = '' OR rows.trade_date IS NULL)),
          coalesce((SELECT failed_count FROM result_duplicate_counts counts
                    WHERE counts.target_trade_date = dates.target_trade_date), 0),
          (SELECT count(*) FROM result_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.open IS NULL OR rows.high IS NULL OR rows.low IS NULL
               OR rows.close IS NULL OR NOT isfinite(rows.open)
               OR NOT isfinite(rows.high) OR NOT isfinite(rows.low)
               OR NOT isfinite(rows.close) OR rows.open <= 0 OR rows.high <= 0
               OR rows.low <= 0 OR rows.close <= 0
               OR rows.low > least(rows.open, rows.close)
               OR greatest(rows.open, rows.close) > rows.high)),
          (SELECT count(*) FROM result_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.short_upper IS NULL OR rows.short_lower IS NULL
               OR rows.long_upper IS NULL OR rows.long_lower IS NULL
               OR NOT isfinite(rows.short_upper) OR NOT isfinite(rows.short_lower)
               OR NOT isfinite(rows.long_upper) OR NOT isfinite(rows.long_lower)
               OR rows.short_upper <= 0 OR rows.short_lower <= 0
               OR rows.long_upper <= 0 OR rows.long_lower <= 0
               OR rows.short_upper < rows.short_lower
               OR rows.long_upper < rows.long_lower)),
          (SELECT count(*) FROM result_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.short_position IS NULL OR rows.long_position IS NULL
               OR rows.short_state IS NULL OR rows.long_state IS NULL
               OR rows.combined_state IS NULL
               OR rows.short_position NOT IN ('ABOVE', 'INSIDE', 'BELOW')
               OR rows.long_position NOT IN ('ABOVE', 'INSIDE', 'BELOW')
               OR rows.short_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
               OR rows.long_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
               OR rows.combined_state NOT IN (
                 'UNKNOWN', 'UP_UP', 'UP_DOWN', 'DOWN_UP', 'DOWN_DOWN'
               ))),
          (SELECT count(*) FROM result_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND rows.combined_state != CASE
               WHEN rows.short_state = 'UNKNOWN' OR rows.long_state = 'UNKNOWN'
                 THEN 'UNKNOWN'
               ELSE rows.short_state || '_' || rows.long_state END),
          (SELECT count(*) FROM result_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.formula_version IS NULL
               OR rows.formula_version != {duckdb_string(FORMULA_VERSION)})),
          (SELECT count(*) FROM missing_qfq_result rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM unexpected_result rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM state_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM valid_lifecycle rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM state_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.trade_date IS NULL OR rows.trade_date != dates.target_trade_date)),
          (SELECT count(*) FROM state_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.ts_code IS NULL OR trim(rows.ts_code) = ''
               OR rows.trade_date IS NULL OR rows.state_source_trade_date IS NULL
               OR rows.observed_on_partition IS NULL
               OR rows.short_upper_raw IS NULL OR rows.short_lower_raw IS NULL
               OR rows.short_state IS NULL OR rows.long_upper_raw IS NULL
               OR rows.long_lower_raw IS NULL OR rows.long_state IS NULL
               OR rows.combined_state IS NULL OR rows.formula_version IS NULL)),
          coalesce((SELECT failed_count FROM state_duplicate_counts counts
                    WHERE counts.target_trade_date = dates.target_trade_date), 0),
          (SELECT count(*) FROM state_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (NOT isfinite(rows.short_upper_raw)
               OR NOT isfinite(rows.short_lower_raw)
               OR NOT isfinite(rows.long_upper_raw)
               OR NOT isfinite(rows.long_lower_raw)
               OR rows.short_upper_raw <= 0 OR rows.short_lower_raw <= 0
               OR rows.long_upper_raw <= 0 OR rows.long_lower_raw <= 0
               OR rows.short_upper_raw < rows.short_lower_raw
               OR rows.long_upper_raw < rows.long_lower_raw)),
          (SELECT count(*) FROM state_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.short_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
               OR rows.long_state NOT IN ('UNKNOWN', 'UP', 'DOWN')
               OR rows.combined_state NOT IN (
                 'UNKNOWN', 'UP_UP', 'UP_DOWN', 'DOWN_UP', 'DOWN_DOWN'
               ))),
          (SELECT count(*) FROM state_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND rows.combined_state != CASE
               WHEN rows.short_state = 'UNKNOWN' OR rows.long_state = 'UNKNOWN'
                 THEN 'UNKNOWN'
               ELSE rows.short_state || '_' || rows.long_state END),
          (SELECT count(*) FROM state_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND (rows.state_source_trade_date > rows.trade_date
               OR (rows.observed_on_partition
                 AND rows.state_source_trade_date != rows.trade_date))),
          (SELECT count(*) FROM state_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND rows.formula_version != {duckdb_string(FORMULA_VERSION)}),
          (SELECT count(*) FROM state_rows rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND NOT EXISTS (
               SELECT 1 FROM valid_lifecycle lifecycle
               WHERE lifecycle.target_trade_date = dates.target_trade_date
                 AND lifecycle.ts_code = rows.ts_code)),
          (SELECT count(*) FROM qfq_codes rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM previous_codes rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM expected_carry rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM actual_state rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND rows.observed_on_partition),
          (SELECT count(*) FROM actual_state rows
           WHERE rows.target_trade_date = dates.target_trade_date
             AND NOT rows.observed_on_partition),
          (SELECT count(*) FROM uninitialized rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM missing_state rows
           WHERE rows.target_trade_date = dates.target_trade_date),
          (SELECT count(*) FROM unexpected_state rows
           WHERE rows.target_trade_date = dates.target_trade_date)
        FROM dates
        ORDER BY dates.target_trade_date
        """
    ).fetchall()
    return {str(row[0]): tuple(int(value) for value in row[1:]) for row in rows}


def _status_from_audit_row(
    *,
    trade_date: str,
    row: tuple[int, ...],
) -> ContinuityDateReadiness:
    (
        result_count,
        qfq_source_count,
        result_date_mismatch,
        result_null_key,
        result_duplicate,
        result_ohlc_invalid,
        result_channel_invalid,
        result_enum_invalid,
        result_combined_invalid,
        result_version_invalid,
        result_missing_qfq,
        result_unexpected,
        state_count,
        lifecycle_count,
        state_date_mismatch,
        state_required_null,
        state_duplicate,
        state_raw_invalid,
        state_enum_invalid,
        state_combined_invalid,
        state_source_date_invalid,
        state_version_invalid,
        state_lifecycle_invalid,
        qfq_observed_count,
        previous_initialized_count,
        expected_carry_count,
        actual_observed_count,
        actual_carry_count,
        uninitialized_count,
        missing_state_count,
        unexpected_state_count,
    ) = row
    result_failures = _nonzero_counts(
        evaluate_stock_daily_trend_channel_result_rules(
            StockDailyTrendChannelResultRuleMetrics(
                output_row_count=result_count,
                partition_date_mismatch_count=result_date_mismatch,
                null_key_count=result_null_key,
                duplicate_key_count=result_duplicate,
                invalid_ohlc_count=result_ohlc_invalid,
                invalid_channel_count=result_channel_invalid,
                invalid_enum_count=result_enum_invalid,
                inconsistent_combined_state_count=result_combined_invalid,
                invalid_formula_version_count=result_version_invalid,
                missing_qfq_result_count=result_missing_qfq,
                unexpected_result_count=result_unexpected,
            )
        )
    )
    state_failures = _nonzero_counts(
        evaluate_stock_daily_trend_channel_state_rules(
            StockDailyTrendChannelStateRuleMetrics(
                partition_date_mismatch_count=state_date_mismatch,
                required_null_count=state_required_null,
                duplicate_key_count=state_duplicate,
                invalid_raw_channel_count=state_raw_invalid,
                invalid_enum_count=state_enum_invalid,
                inconsistent_combined_state_count=state_combined_invalid,
                invalid_source_date_count=state_source_date_invalid,
                invalid_formula_version_count=state_version_invalid,
                invalid_lifecycle_membership_count=state_lifecycle_invalid,
            )
        )
    )
    coverage_failures = _nonzero_counts(
        evaluate_stock_daily_trend_channel_coverage_rules(
            StockDailyTrendChannelCoverageRuleMetrics(
                expected_lifecycle_count=lifecycle_count,
                qfq_observed_count=qfq_observed_count,
                expected_carry_count=expected_carry_count,
                actual_observed_state_count=actual_observed_count,
                actual_carry_state_count=actual_carry_count,
                uninitialized_count=uninitialized_count,
                missing_state_count=missing_state_count,
                unexpected_state_count=unexpected_state_count,
            )
        )
    )
    failed_checks = tuple(
        check_name
        for check_name, failures in (
            (STOCK_DAILY_TREND_CHANNEL_RESULT_CHECKS[0], result_failures),
            (STOCK_DAILY_TREND_CHANNEL_STATE_CHECKS[0], state_failures),
            (STOCK_DAILY_TREND_CHANNEL_RESULT_CHECKS[1], coverage_failures),
        )
        if failures
    )
    summary = {
        "result_failure_rule_counts": result_failures,
        "state_failure_rule_counts": state_failures,
        "coverage_failure_rule_counts": coverage_failures,
        "source_row_count": qfq_source_count,
        "result_row_count": result_count,
        "state_row_count": state_count,
        "expected_lifecycle_count": lifecycle_count,
        "qfq_observed_count": qfq_observed_count,
        "previous_initialized_count": previous_initialized_count,
        "expected_carry_count": expected_carry_count,
        "actual_observed_state_count": actual_observed_count,
        "actual_carry_state_count": actual_carry_count,
        "uninitialized_count": uninitialized_count,
    }
    if failed_checks:
        return _failed_status(
            trade_date=trade_date,
            reason="target_lake_checks_failed",
            failed_check_names=failed_checks,
            summary=summary,
        )
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason="ready",
        summary=summary,
    )


def _missing_target_status(
    *,
    trade_date: str,
    result_path: Path,
    state_path: Path,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason="target_not_materialized",
        missing_check_names=STOCK_DAILY_TREND_CHANNEL_ALL_CHECKS,
        missing_file_paths=(str(result_path), str(state_path)),
        summary={"missing_target_file_count": 2},
    )


def _partial_target_status(
    *,
    trade_date: str,
    result_path: Path,
    state_path: Path,
) -> ContinuityDateReadiness:
    missing_paths = tuple(
        str(path) for path in (result_path, state_path) if not path.is_file()
    )
    return _failed_status(
        trade_date=trade_date,
        reason="target_pair_partially_materialized",
        failed_check_names=STOCK_DAILY_TREND_CHANNEL_ALL_CHECKS,
        summary={"missing_target_file_count": len(missing_paths)},
        missing_file_paths=missing_paths,
    )


def _failed_status(
    *,
    trade_date: str,
    reason: str,
    failed_check_names: Sequence[str],
    summary: Mapping[str, object],
    missing_file_paths: Sequence[str] = (),
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason=reason,
        failed_check_names=tuple(failed_check_names),
        missing_file_paths=tuple(missing_file_paths),
        summary=dict(summary),
    )


def _nonzero_counts(values: Mapping[str, int]) -> dict[str, int]:
    return {key: int(value) for key, value in values.items() if int(value) != 0}


def _date_values_sql(trade_dates: Sequence[str]) -> str:
    return "VALUES " + ", ".join(
        f"(DATE {duckdb_string(trade_date)})" for trade_date in trade_dates
    )


def _path_date_values_sql(
    paths_by_trade_date: Mapping[str, Path],
    trade_dates: Sequence[str],
) -> str:
    if not trade_dates:
        return "SELECT CAST(NULL AS VARCHAR), CAST(NULL AS DATE) WHERE false"
    return "VALUES " + ", ".join(
        "("
        + duckdb_string(paths_by_trade_date[trade_date])
        + ", DATE "
        + duckdb_string(trade_date)
        + ")"
        for trade_date in trade_dates
    )


def _path_list_sql(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("at least one parquet path is required")
    return "[" + ", ".join(duckdb_string(path) for path in paths) + "]"


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))
