from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
)
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMN_TYPES,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMN_TYPES,
    discover_gold_stk_mins_qfq_source_year_paths,
)


GOLD_STK_MINS_QFQ_MACD_KDJ_FILE_EXISTS_AND_SCHEMA_CHECK = (
    "gold_stk_mins_qfq_macd_kdj_file_exists_and_schema_check"
)
GOLD_STK_MINS_QFQ_MACD_KDJ_SOURCE_READY_CHECK = (
    "gold_stk_mins_qfq_macd_kdj_source_ready_check"
)
GOLD_STK_MINS_QFQ_MACD_KDJ_ROW_COUNT_MATCHES_QFQ_CHECK = (
    "gold_stk_mins_qfq_macd_kdj_row_count_matches_qfq_check"
)
GOLD_STK_MINS_QFQ_MACD_KDJ_FORMULA_SAMPLE_CHECK = (
    "gold_stk_mins_qfq_macd_kdj_formula_sample_check"
)
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_FILE_EXISTS_AND_SCHEMA_CHECK = (
    "gold_stk_mins_qfq_macd_kdj_state_file_exists_and_schema_check"
)
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_LATEST_COVERAGE_CHECK = (
    "gold_stk_mins_qfq_macd_kdj_state_latest_coverage_check"
)

GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES = (
    GOLD_STK_MINS_QFQ_MACD_KDJ_FILE_EXISTS_AND_SCHEMA_CHECK,
    GOLD_STK_MINS_QFQ_MACD_KDJ_SOURCE_READY_CHECK,
    GOLD_STK_MINS_QFQ_MACD_KDJ_ROW_COUNT_MATCHES_QFQ_CHECK,
    GOLD_STK_MINS_QFQ_MACD_KDJ_FORMULA_SAMPLE_CHECK,
)
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES = (
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_FILE_EXISTS_AND_SCHEMA_CHECK,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_LATEST_COVERAGE_CHECK,
)
GOLD_STK_MINS_QFQ_MACD_KDJ_FORMULA_TOLERANCE = 1e-8
GOLD_STK_MINS_QFQ_MACD_KDJ_SAMPLE_LIMIT = 20


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("At least one parquet path is required.")
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False, union_by_name=True)
    quoted_paths = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{quoted_paths}], hive_partitioning=false, union_by_name=true)"


def _sample_dicts(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _missing_paths_result(
    *,
    check_scope: CheckScope,
    missing_paths: Sequence[Path],
    extra_metadata: dict[str, Any] | None = None,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=check_scope,
            missing_file_paths=missing_paths[:GOLD_STK_MINS_QFQ_MACD_KDJ_SAMPLE_LIMIT],
            extra_metadata={
                "missing_file_count": len(missing_paths),
                **(extra_metadata or {}),
            },
        ),
    )


def _indicator_expected_paths(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
    source_paths: Sequence[Path],
) -> tuple[Path, ...]:
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT
              CAST(ts_code AS VARCHAR) AS ts_code,
              strftime(CAST(trade_date AS DATE), '%Y') AS year
            FROM {_read_parquet_paths(source_paths)}
            WHERE CAST(freq AS INTEGER) = {freq}
              AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
            ORDER BY ts_code, year
            """
        ).fetchall()
    return tuple(
        gold_stk_mins_qfq_macd_kdj_path(lake_root, freq, str(ts_code), str(year))
        for ts_code, year in rows
    )


def _observed_schema(path: Path) -> dict[str, str]:
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchall()
    return {str(row[0]): str(row[1]).upper() for row in rows}


def _schema_matches(path: Path, expected_types: dict[str, str]) -> tuple[bool, dict[str, str]]:
    observed = _observed_schema(path)
    expected = {column: column_type.upper() for column, column_type in expected_types.items()}
    return observed == expected, observed


def _indicator_file_exists_and_schema_result(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
) -> dg.AssetCheckResult:
    source_paths = discover_gold_stk_mins_qfq_source_year_paths(
        lake_root,
        freq=freq,
        trade_dates=[partition_key],
    )
    if not source_paths:
        return _missing_paths_result(
            check_scope=CheckScope.FILE_EXISTS,
            missing_paths=(),
            extra_metadata={"source_file_count": 0},
        )
    expected_paths = _indicator_expected_paths(
        lake_root=lake_root,
        freq=freq,
        partition_key=partition_key,
        source_paths=source_paths,
    )
    missing_paths = tuple(path for path in expected_paths if not path.exists())
    if missing_paths:
        return _missing_paths_result(
            check_scope=CheckScope.FILE_EXISTS,
            missing_paths=missing_paths,
            extra_metadata={
                "expected_file_count": len(expected_paths),
                "source_file_count": len(source_paths),
            },
        )
    schema_mismatches = []
    for path in expected_paths[:GOLD_STK_MINS_QFQ_MACD_KDJ_SAMPLE_LIMIT]:
        matches, observed = _schema_matches(path, GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMN_TYPES)
        if not matches:
            schema_mismatches.append({"path": str(path), "observed_schema": observed})

    return dg.AssetCheckResult(
        passed=not schema_mismatches,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=len(expected_paths),
            failed_row_count=len(schema_mismatches),
            input_file_paths=expected_paths[:GOLD_STK_MINS_QFQ_MACD_KDJ_SAMPLE_LIMIT],
            extra_metadata={
                "expected_file_count": len(expected_paths),
                "source_file_count": len(source_paths),
                "schema_mismatch_samples": schema_mismatches,
            },
        ),
    )


def _indicator_source_ready_result(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
) -> dg.AssetCheckResult:
    source_paths = discover_gold_stk_mins_qfq_source_year_paths(
        lake_root,
        freq=freq,
        trade_dates=[partition_key],
    )
    if not source_paths:
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.FILE_EXISTS,
                failed_row_count=1,
                extra_metadata={"source_file_count": 0},
            ),
        )
    with connect_configured_duckdb() as connection:
        row_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {_read_parquet_paths(source_paths)}
                WHERE CAST(freq AS INTEGER) = {freq}
                  AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
                """
            ).fetchone()[0]
        )
    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            checked_row_count=row_count,
            failed_row_count=0 if row_count > 0 else 1,
            input_file_paths=source_paths[:GOLD_STK_MINS_QFQ_MACD_KDJ_SAMPLE_LIMIT],
            extra_metadata={"source_file_count": len(source_paths)},
        ),
    )


def _indicator_row_count_matches_qfq_result(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
) -> dg.AssetCheckResult:
    source_paths = discover_gold_stk_mins_qfq_source_year_paths(
        lake_root,
        freq=freq,
        trade_dates=[partition_key],
    )
    if not source_paths:
        return _indicator_source_ready_result(
            lake_root=lake_root,
            freq=freq,
            partition_key=partition_key,
        )
    expected_paths = tuple(
        path
        for path in _indicator_expected_paths(
            lake_root=lake_root,
            freq=freq,
            partition_key=partition_key,
            source_paths=source_paths,
        )
        if path.exists()
    )
    if not expected_paths:
        return _missing_paths_result(
            check_scope=CheckScope.FILE_EXISTS,
            missing_paths=(),
            extra_metadata={"existing_indicator_file_count": 0},
        )
    with connect_configured_duckdb() as connection:
        source_row_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {_read_parquet_paths(source_paths)}
                WHERE CAST(freq AS INTEGER) = {freq}
                  AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
                """
            ).fetchone()[0]
        )
        indicator_row_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {_read_parquet_paths(expected_paths)}
                WHERE CAST(freq AS INTEGER) = {freq}
                  AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
                """
            ).fetchone()[0]
        )
    return dg.AssetCheckResult(
        passed=source_row_count == indicator_row_count,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=source_row_count,
            failed_row_count=abs(source_row_count - indicator_row_count),
            input_file_paths=expected_paths[:GOLD_STK_MINS_QFQ_MACD_KDJ_SAMPLE_LIMIT],
            extra_metadata={
                "source_row_count": source_row_count,
                "indicator_row_count": indicator_row_count,
            },
        ),
    )


def _indicator_formula_result(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
) -> dg.AssetCheckResult:
    source_paths = discover_gold_stk_mins_qfq_source_year_paths(
        lake_root,
        freq=freq,
        trade_dates=[partition_key],
    )
    if not source_paths:
        return _indicator_source_ready_result(
            lake_root=lake_root,
            freq=freq,
            partition_key=partition_key,
        )
    indicator_paths = tuple(
        path
        for path in _indicator_expected_paths(
            lake_root=lake_root,
            freq=freq,
            partition_key=partition_key,
            source_paths=source_paths,
        )
        if path.exists()
    )
    if not indicator_paths:
        return _missing_paths_result(
            check_scope=CheckScope.FILE_EXISTS,
            missing_paths=(),
            extra_metadata={"existing_indicator_file_count": 0},
        )
    tolerance = GOLD_STK_MINS_QFQ_MACD_KDJ_FORMULA_TOLERANCE
    with connect_configured_duckdb() as connection:
        mismatch_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {_read_parquet_paths(indicator_paths)}
                WHERE CAST(freq AS INTEGER) = {freq}
                  AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
                  AND (
                    abs(macd_qfq - 2.0 * (macd_dif_qfq - macd_dea_qfq)) > {tolerance}
                    OR abs(kdj_qfq - (3.0 * kdj_k_qfq - 2.0 * kdj_d_qfq)) > {tolerance}
                  )
                """
            ).fetchone()[0]
        )
        sample_rows = []
        if mismatch_count:
            sample_rows = connection.execute(
                f"""
                SELECT
                  ts_code,
                  trade_time,
                  macd_dif_qfq,
                  macd_dea_qfq,
                  macd_qfq,
                  kdj_k_qfq,
                  kdj_d_qfq,
                  kdj_qfq
                FROM {_read_parquet_paths(indicator_paths)}
                WHERE CAST(freq AS INTEGER) = {freq}
                  AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
                  AND (
                    abs(macd_qfq - 2.0 * (macd_dif_qfq - macd_dea_qfq)) > {tolerance}
                    OR abs(kdj_qfq - (3.0 * kdj_k_qfq - 2.0 * kdj_d_qfq)) > {tolerance}
                  )
                LIMIT {GOLD_STK_MINS_QFQ_MACD_KDJ_SAMPLE_LIMIT}
                """
            ).fetchall()
    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=mismatch_count,
            input_file_paths=indicator_paths[:GOLD_STK_MINS_QFQ_MACD_KDJ_SAMPLE_LIMIT],
            extra_metadata={
                "formula_tolerance": tolerance,
                "failure_samples": _sample_dicts(
                    (
                        "ts_code",
                        "trade_time",
                        "macd_dif_qfq",
                        "macd_dea_qfq",
                        "macd_qfq",
                        "kdj_k_qfq",
                        "kdj_d_qfq",
                        "kdj_qfq",
                    ),
                    sample_rows,
                ),
            },
        ),
    )


def _state_file_exists_and_schema_result(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
) -> dg.AssetCheckResult:
    path = gold_stk_mins_qfq_macd_kdj_state_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_paths_result(
            check_scope=CheckScope.FILE_EXISTS,
            missing_paths=(path,),
        )
    matches, observed = _schema_matches(path, GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMN_TYPES)
    return dg.AssetCheckResult(
        passed=matches,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            file_path=path,
            failed_row_count=0 if matches else 1,
            extra_metadata={"observed_schema": observed},
        ),
    )


def _state_latest_coverage_result(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
) -> dg.AssetCheckResult:
    state_path = gold_stk_mins_qfq_macd_kdj_state_path(lake_root, freq, partition_key)
    if not state_path.exists():
        return _missing_paths_result(
            check_scope=CheckScope.FILE_EXISTS,
            missing_paths=(state_path,),
        )
    source_paths = discover_gold_stk_mins_qfq_source_year_paths(
        lake_root,
        freq=freq,
        trade_dates=[partition_key],
    )
    indicator_paths = tuple(
        path
        for path in _indicator_expected_paths(
            lake_root=lake_root,
            freq=freq,
            partition_key=partition_key,
            source_paths=source_paths,
        )
        if path.exists()
    ) if source_paths else ()
    if not indicator_paths:
        return _missing_paths_result(
            check_scope=CheckScope.FILE_EXISTS,
            missing_paths=(),
            extra_metadata={"existing_indicator_file_count": 0},
        )
    with connect_configured_duckdb() as connection:
        row = connection.execute(
            f"""
            WITH indicator_latest AS (
              SELECT
                ts_code,
                max(trade_time) AS last_trade_time
              FROM {_read_parquet_paths(indicator_paths)}
              WHERE CAST(freq AS INTEGER) = {freq}
                AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
              GROUP BY ts_code
            ),
            state_rows AS (
              SELECT
                ts_code,
                last_trade_time
              FROM {read_parquet(state_path, hive_partitioning=False)}
              WHERE CAST(freq AS INTEGER) = {freq}
                AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
            ),
            joined AS (
              SELECT
                coalesce(indicator_latest.ts_code, state_rows.ts_code) AS ts_code,
                indicator_latest.last_trade_time AS indicator_last_trade_time,
                state_rows.last_trade_time AS state_last_trade_time
              FROM indicator_latest
              FULL OUTER JOIN state_rows USING (ts_code)
            )
            SELECT
              (SELECT count(*) FROM indicator_latest) AS indicator_stock_count,
              (SELECT count(*) FROM state_rows) AS state_row_count,
              count(*) FILTER (
                WHERE indicator_last_trade_time IS NOT NULL
                  AND (
                    state_last_trade_time IS NULL
                   OR indicator_last_trade_time != state_last_trade_time
                  )
              ) AS current_indicator_mismatch_count,
              count(*) FILTER (
                WHERE state_last_trade_time IS NOT NULL
                  AND CAST(state_last_trade_time AS DATE) > DATE {duckdb_string(partition_key)}
              ) AS mismatch_count
            FROM joined
            """
        ).fetchone()
    (
        indicator_stock_count,
        state_row_count,
        current_indicator_mismatch_count,
        future_state_mismatch_count,
    ) = (int(value or 0) for value in row)
    failed_count = current_indicator_mismatch_count + future_state_mismatch_count
    return dg.AssetCheckResult(
        passed=failed_count == 0 and state_row_count >= indicator_stock_count,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=indicator_stock_count,
            failed_row_count=failed_count,
            file_path=state_path,
            input_file_paths=indicator_paths[:GOLD_STK_MINS_QFQ_MACD_KDJ_SAMPLE_LIMIT],
            extra_metadata={
                "indicator_stock_count": indicator_stock_count,
                "state_row_count": state_row_count,
                "current_indicator_mismatch_count": current_indicator_mismatch_count,
                "future_state_mismatch_count": future_state_mismatch_count,
                "carry_forward_state_row_count": max(
                    0,
                    state_row_count - indicator_stock_count,
                ),
            },
        ),
    )


def _build_indicator_check(asset_name: str, check_name: str, freq: int):
    @dg.asset_check(asset=asset_name, name=check_name, blocking=True)
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
    ) -> dg.AssetCheckResult:
        partition_key = context.partition_key
        if check_name == GOLD_STK_MINS_QFQ_MACD_KDJ_FILE_EXISTS_AND_SCHEMA_CHECK:
            return _indicator_file_exists_and_schema_result(
                lake_root=lake_root.root(),
                freq=freq,
                partition_key=partition_key,
            )
        if check_name == GOLD_STK_MINS_QFQ_MACD_KDJ_SOURCE_READY_CHECK:
            return _indicator_source_ready_result(
                lake_root=lake_root.root(),
                freq=freq,
                partition_key=partition_key,
            )
        if check_name == GOLD_STK_MINS_QFQ_MACD_KDJ_ROW_COUNT_MATCHES_QFQ_CHECK:
            return _indicator_row_count_matches_qfq_result(
                lake_root=lake_root.root(),
                freq=freq,
                partition_key=partition_key,
            )
        if check_name == GOLD_STK_MINS_QFQ_MACD_KDJ_FORMULA_SAMPLE_CHECK:
            return _indicator_formula_result(
                lake_root=lake_root.root(),
                freq=freq,
                partition_key=partition_key,
            )
        raise AssertionError(f"Unsupported MACD/KDJ indicator check: {check_name}")

    return _check


def _build_state_check(asset_name: str, check_name: str, freq: int):
    @dg.asset_check(asset=asset_name, name=check_name, blocking=True)
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
    ) -> dg.AssetCheckResult:
        partition_key = context.partition_key
        if check_name == GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_FILE_EXISTS_AND_SCHEMA_CHECK:
            return _state_file_exists_and_schema_result(
                lake_root=lake_root.root(),
                freq=freq,
                partition_key=partition_key,
            )
        if check_name == GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_LATEST_COVERAGE_CHECK:
            return _state_latest_coverage_result(
                lake_root=lake_root.root(),
                freq=freq,
                partition_key=partition_key,
            )
        raise AssertionError(f"Unsupported MACD/KDJ state check: {check_name}")

    return _check


for _freq in (1, 5, 15, 30, 60, 90, 120):
    for _check_name in GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES:
        globals()[f"gold_stk_mins_qfq_macd_kdj_{_freq}m_{_check_name}"] = (
            _build_indicator_check(f"gold_stk_mins_qfq_macd_kdj_{_freq}m", _check_name, _freq)
        )
    for _check_name in GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES:
        globals()[f"gold_stk_mins_qfq_macd_kdj_state_{_freq}m_{_check_name}"] = (
            _build_state_check(f"gold_stk_mins_qfq_macd_kdj_state_{_freq}m", _check_name, _freq)
        )
