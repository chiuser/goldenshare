from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.stk_mins import (
    GOLD_STK_MINS_QFQ_ASSETS,
    GOLD_STK_MINS_QFQ_DERIVED_ASSETS,
    GOLD_STK_MINS_QFQ_NATIVE_ASSETS,
    RAW_STK_MINS_ASSETS,
    SILVER_STK_MINS_ASSETS,
    STK_MINS_RAW_COLUMN_TYPES,
    STK_MINS_SILVER_COLUMN_TYPES,
    gold_stk_mins_qfq_1m,
    gold_stk_mins_qfq_5m,
    gold_stk_mins_qfq_15m,
    gold_stk_mins_qfq_30m,
    gold_stk_mins_qfq_60m,
    gold_stk_mins_qfq_90m,
    gold_stk_mins_qfq_120m,
    raw_stk_mins_1m,
    raw_stk_mins_5m,
    raw_stk_mins_15m,
    raw_stk_mins_30m,
    raw_stk_mins_60m,
    silver_stk_mins_1m,
    silver_stk_mins_5m,
    silver_stk_mins_15m,
    silver_stk_mins_30m,
    silver_stk_mins_60m,
)
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    raw_stk_mins_path,
    silver_adj_factor_path,
    silver_namechange_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.stk_mins import (
    normalize_stk_mins_freq,
    normalize_stk_mins_qfq_freq,
    qfq_source_freq_for_derived_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_COLUMN_TYPES,
    build_gold_stk_mins_qfq_derived_diagnostics_sql,
    build_gold_stk_mins_qfq_derived_select_sql,
    build_daily_qfq_coverage_sql,
    build_daily_qfq_select_sql,
)


RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK = (
    "raw_stk_mins_file_exists_and_row_count_positive"
)
RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK = "raw_stk_mins_schema_matches_contract"
RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK = "raw_stk_mins_freq_matches_asset"
RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK = "raw_stk_mins_partition_date_matches"
RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK = (
    "raw_stk_mins_unique_ts_code_trade_time"
)
RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK = "raw_stk_mins_price_volume_sanity"
RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK = (
    "raw_stk_mins_stock_mins_partition_key_registered"
)

RAW_STK_MINS_CHECK_NAMES = (
    RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
    RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
    RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK,
    RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK,
    RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
    RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK,
    RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK,
)

SILVER_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK = (
    "silver_stk_mins_file_exists_and_row_count_positive"
)
SILVER_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK = (
    "silver_stk_mins_schema_matches_contract"
)
SILVER_STK_MINS_FREQ_AND_PARTITION_MATCH_CHECK = (
    "silver_stk_mins_freq_and_partition_match"
)
SILVER_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK = (
    "silver_stk_mins_unique_ts_code_trade_time"
)
SILVER_STK_MINS_PRICE_SANITY_CHECK = "silver_stk_mins_price_sanity"
SILVER_STK_MINS_VOLUME_AMOUNT_SANITY_CHECK = (
    "silver_stk_mins_volume_amount_sanity"
)
SILVER_STK_MINS_EXCHANGE_MATCHES_SUFFIX_CHECK = (
    "silver_stk_mins_exchange_matches_suffix"
)
SILVER_STK_MINS_CODES_EXIST_IN_STOCK_DAILY_CHECK = (
    "silver_stk_mins_codes_exist_in_stock_daily"
)
SILVER_STK_MINS_NO_FULL_DAY_SUSPEND_STRUCTURAL_ROWS_CHECK = (
    "silver_stk_mins_no_full_day_suspend_structural_rows"
)
SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK = (
    "silver_stk_mins_name_timeline_covered"
)

SILVER_STK_MINS_CHECK_NAMES = (
    SILVER_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
    SILVER_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
    SILVER_STK_MINS_FREQ_AND_PARTITION_MATCH_CHECK,
    SILVER_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
    SILVER_STK_MINS_PRICE_SANITY_CHECK,
    SILVER_STK_MINS_VOLUME_AMOUNT_SANITY_CHECK,
    SILVER_STK_MINS_EXCHANGE_MATCHES_SUFFIX_CHECK,
    SILVER_STK_MINS_CODES_EXIST_IN_STOCK_DAILY_CHECK,
    SILVER_STK_MINS_NO_FULL_DAY_SUSPEND_STRUCTURAL_ROWS_CHECK,
    SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
)

GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK = (
    "gold_stk_mins_qfq_file_exists_and_row_count_positive"
)
GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK = (
    "gold_stk_mins_qfq_schema_matches_contract"
)
GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK = (
    "gold_stk_mins_qfq_freq_date_path_match"
)
GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK = (
    "gold_stk_mins_qfq_unique_ts_code_trade_time"
)
GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK = "gold_stk_mins_qfq_price_sanity"
GOLD_STK_MINS_QFQ_ROW_COUNT_MATCHES_SILVER_CHECK = (
    "gold_stk_mins_qfq_row_count_matches_silver"
)
GOLD_STK_MINS_QFQ_FACTOR_COVERAGE_COMPLETE_CHECK = (
    "gold_stk_mins_qfq_factor_coverage_complete"
)
GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK = (
    "gold_stk_mins_qfq_formula_matches_silver_adj_factor"
)
GOLD_STK_MINS_QFQ_DERIVED_SOURCE_READY_CHECK = (
    "gold_stk_mins_qfq_derived_source_ready"
)
GOLD_STK_MINS_QFQ_DERIVED_ROW_COUNT_MATCHES_SOURCE_WINDOWS_CHECK = (
    "gold_stk_mins_qfq_derived_row_count_matches_source_windows"
)
GOLD_STK_MINS_QFQ_DERIVED_FORMULA_MATCHES_SOURCE_CHECK = (
    "gold_stk_mins_qfq_derived_formula_matches_source"
)

GOLD_STK_MINS_QFQ_BASE_CHECK_NAMES = (
    GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
    GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
    GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK,
    GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
    GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK,
)

GOLD_STK_MINS_QFQ_NATIVE_CHECK_NAMES = (
    *GOLD_STK_MINS_QFQ_BASE_CHECK_NAMES,
    GOLD_STK_MINS_QFQ_ROW_COUNT_MATCHES_SILVER_CHECK,
    GOLD_STK_MINS_QFQ_FACTOR_COVERAGE_COMPLETE_CHECK,
    GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK,
)

GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES = (
    *GOLD_STK_MINS_QFQ_BASE_CHECK_NAMES,
    GOLD_STK_MINS_QFQ_DERIVED_SOURCE_READY_CHECK,
    GOLD_STK_MINS_QFQ_DERIVED_ROW_COUNT_MATCHES_SOURCE_WINDOWS_CHECK,
    GOLD_STK_MINS_QFQ_DERIVED_FORMULA_MATCHES_SOURCE_CHECK,
)

GOLD_STK_MINS_QFQ_CHECK_NAMES = GOLD_STK_MINS_QFQ_NATIVE_CHECK_NAMES

GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE = 1e-6
GOLD_STK_MINS_QFQ_METADATA_SAMPLE_LIMIT = 20


@dataclass(frozen=True)
class GoldStkMinsQfqCheckCounts:
    silver_row_count: int
    expected_file_count: int
    existing_file_count: int
    missing_file_count: int
    gold_target_row_count: int
    missing_trade_adj_factor_row_count: int
    missing_as_of_adj_factor_row_count: int
    qfq_output_row_count: int
    schema_mismatch_file_count: int
    path_mismatch_row_count: int
    duplicate_key_count: int
    invalid_price_row_count: int
    formula_missing_gold_row_count: int
    formula_unexpected_gold_row_count: int
    formula_mismatch_row_count: int


@dataclass(frozen=True)
class GoldStkMinsQfqDerivedCheckCounts:
    source_freq: int
    source_file_count: int
    source_row_count: int
    source_stock_day_count: int
    expected_window_count: int
    generated_window_count: int
    incomplete_window_count: int
    exchange_mismatch_window_count: int
    expected_file_count: int
    existing_file_count: int
    missing_file_count: int
    gold_target_row_count: int
    schema_mismatch_file_count: int
    path_mismatch_row_count: int
    duplicate_key_count: int
    invalid_price_row_count: int
    formula_missing_gold_row_count: int
    formula_unexpected_gold_row_count: int
    formula_mismatch_row_count: int


def _missing_file_result(path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            missing_file_paths=[path],
            extra_metadata={"missing_file": True},
        ),
    )


def _missing_input_file_result(path: Path, missing_path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            missing_file_paths=[missing_path],
            extra_metadata={"missing_input_file": True},
        ),
    )


def _check_result(
    *,
    passed: bool,
    check_scope: CheckScope,
    asset_key: dg.AssetKey | None = None,
    check_name: str | None = None,
    file_path: Path | None = None,
    input_file_paths: Sequence[Path] | None = None,
    missing_file_paths: Sequence[Path] | None = None,
    checked_row_count: int | None = None,
    failed_row_count: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        asset_key=asset_key,
        check_name=check_name,
        metadata=build_check_metadata(
            check_scope=check_scope,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            file_path=file_path,
            input_file_paths=input_file_paths,
            missing_file_paths=missing_file_paths,
            extra_metadata=extra_metadata or {},
        ),
    )


def _describe_columns(connection, path: Path) -> dict[str, str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _row_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]
    )


def _sample_dicts(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _raw_path(lake_root: LakeRootResource, freq: int, partition_key: str) -> Path:
    return raw_stk_mins_path(lake_root.root(), freq, partition_key)


def _silver_path(lake_root: LakeRootResource, freq: int, partition_key: str) -> Path:
    return silver_stk_mins_path(lake_root.root(), freq, partition_key)


def _gold_qfq_expected_paths(
    connection,
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
    silver_path: Path,
) -> tuple[Path, ...]:
    relation = read_parquet(silver_path, hive_partitioning=False)
    rows = connection.execute(
        f"""
        SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
        FROM {relation}
        ORDER BY ts_code
        """
    ).fetchall()
    year = partition_key[:4]
    return tuple(
        gold_stk_mins_qfq_path(lake_root, freq, str(row[0]), year) for row in rows
    )


def _gold_qfq_year_paths(
    *,
    lake_root: Path,
    freq: int,
    year: str,
) -> tuple[Path, ...]:
    freq_root = gold_stk_mins_qfq_path(
        lake_root,
        freq,
        "{ts_code}",
        year,
    ).parents[2]
    return tuple(sorted(freq_root.glob(f"ts_code=*/year={year}/part-000.parquet")))


def _gold_qfq_derived_expected_paths(
    connection,
    *,
    lake_root: Path,
    target_freq: int,
    partition_key: str,
    expected_select_sql: str,
) -> tuple[Path, ...]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT
          CAST(ts_code AS VARCHAR) AS ts_code,
          strftime(CAST(trade_date AS DATE), '%Y') AS year
        FROM ({expected_select_sql})
        ORDER BY ts_code, year
        """
    ).fetchall()
    return tuple(
        gold_stk_mins_qfq_path(lake_root, target_freq, str(ts_code), str(year))
        for ts_code, year in rows
    )


def _read_parquet_paths(
    paths: Sequence[Path],
    *,
    filename: bool = False,
    union_by_name: bool = True,
) -> str:
    if not paths:
        raise ValueError("read_parquet paths must not be empty.")
    path_list = ", ".join(duckdb_string(path) for path in paths)
    filename_clause = ", filename=true" if filename else ""
    union_clause = ", union_by_name=true" if union_by_name else ""
    return (
        f"read_parquet([{path_list}], hive_partitioning=false"
        f"{union_clause}{filename_clause})"
    )


def _gold_qfq_asset_key(asset) -> dg.AssetKey:
    return asset.key


def _gold_qfq_input_failure_results(
    *,
    asset_key: dg.AssetKey,
    missing_path: Path,
    partition_key: str,
    freq: int,
    check_names: Sequence[str] = GOLD_STK_MINS_QFQ_CHECK_NAMES,
) -> tuple[dg.AssetCheckResult, ...]:
    return tuple(
        _check_result(
            passed=False,
            asset_key=asset_key,
            check_name=check_name,
            check_scope=_gold_qfq_check_scope(check_name),
            missing_file_paths=[missing_path],
            failed_row_count=1,
            extra_metadata={
                "partition_key": partition_key,
                "freq": freq,
                "missing_input_file": str(missing_path),
            },
        )
        for check_name in check_names
    )


def _gold_qfq_check_scope(check_name: str) -> CheckScope:
    if check_name == GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK:
        return CheckScope.FILE_EXISTS
    if check_name == GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK:
        return CheckScope.SCHEMA
    if check_name == GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK:
        return CheckScope.PARTITION_ALIGNMENT
    if check_name == GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK:
        return CheckScope.KEY_UNIQUENESS
    if check_name == GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK:
        return CheckScope.VALUE_SANITY
    return CheckScope.RECONCILIATION


def _gold_qfq_schema_mismatch_count(
    connection,
    paths: Sequence[Path],
) -> tuple[int, dict[str, str], str | None]:
    if not paths:
        return 1, {}, "No existing gold qfq files to describe."

    try:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM {_read_parquet_paths(paths, union_by_name=False)}"
        ).fetchall()
    except Exception as error:  # noqa: BLE001 - expose DuckDB schema reason in metadata.
        return 1, {}, str(error)

    observed_schema = {row[0]: row[1] for row in rows}
    missing_columns = [
        column for column in GOLD_STK_MINS_QFQ_COLUMN_TYPES if column not in observed_schema
    ]
    type_mismatches = [
        column
        for column, expected_type in GOLD_STK_MINS_QFQ_COLUMN_TYPES.items()
        if observed_schema.get(column) != expected_type
    ]
    return len(missing_columns) + len(type_mismatches), observed_schema, None


def _gold_qfq_counts_sql(
    *,
    gold_source: str,
    partition_key: str,
    freq: int,
) -> str:
    partition_date_sql = duckdb_string(partition_key)
    return f"""
    WITH gold_rows AS (
      SELECT
        CAST(ts_code AS VARCHAR) AS ts_code,
        CAST(freq AS INTEGER) AS freq,
        CAST(trade_date AS DATE) AS trade_date,
        CAST(trade_time AS TIMESTAMP) AS trade_time,
        CAST(open AS DOUBLE) AS open,
        CAST(high AS DOUBLE) AS high,
        CAST(low AS DOUBLE) AS low,
        CAST(close AS DOUBLE) AS close,
        CAST(vol AS DOUBLE) AS vol,
        CAST(amount AS DOUBLE) AS amount,
        CAST(exchange AS VARCHAR) AS exchange,
        CAST(filename AS VARCHAR) AS filename,
        regexp_extract(CAST(filename AS VARCHAR), 'ts_code=([^/]+)/year=', 1)
          AS path_ts_code,
        regexp_extract(CAST(filename AS VARCHAR), 'year=([0-9]{{4}})/', 1)
          AS path_year
      FROM {gold_source}
    ),
    target_rows AS (
      SELECT *
      FROM gold_rows
      WHERE trade_date = CAST({partition_date_sql} AS DATE)
    ),
    duplicate_groups AS (
      SELECT ts_code, trade_time, count(*) AS duplicate_count
      FROM target_rows
      GROUP BY ts_code, trade_time
      HAVING count(*) > 1
    )
    SELECT
      (SELECT count(*) FROM target_rows) AS gold_target_row_count,
      count(*) FILTER (
        WHERE freq != {freq}
           OR ts_code != path_ts_code
           OR strftime(trade_date, '%Y') != path_year
           OR (
             trade_date = CAST({partition_date_sql} AS DATE)
             AND CAST(trade_time AS DATE) != CAST({partition_date_sql} AS DATE)
           )
      ) AS path_mismatch_row_count,
      (SELECT count(*) FROM duplicate_groups) AS duplicate_key_count,
      (SELECT count(*)
       FROM target_rows
       WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
          OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
          OR high < low
          OR open < low OR open > high
          OR close < low OR close > high
      ) AS invalid_price_row_count
    FROM gold_rows
    """


def _gold_qfq_sample_queries(
    *,
    gold_source: str,
    partition_key: str,
    freq: int,
) -> dict[str, str]:
    partition_date_sql = duckdb_string(partition_key)
    base_cte = f"""
    WITH gold_rows AS (
      SELECT
        CAST(ts_code AS VARCHAR) AS ts_code,
        CAST(freq AS INTEGER) AS freq,
        CAST(trade_date AS DATE) AS trade_date,
        CAST(trade_time AS TIMESTAMP) AS trade_time,
        CAST(open AS DOUBLE) AS open,
        CAST(high AS DOUBLE) AS high,
        CAST(low AS DOUBLE) AS low,
        CAST(close AS DOUBLE) AS close,
        CAST(filename AS VARCHAR) AS filename,
        regexp_extract(CAST(filename AS VARCHAR), 'ts_code=([^/]+)/year=', 1)
          AS path_ts_code,
        regexp_extract(CAST(filename AS VARCHAR), 'year=([0-9]{{4}})/', 1)
          AS path_year
      FROM {gold_source}
    ),
    target_rows AS (
      SELECT *
      FROM gold_rows
      WHERE trade_date = CAST({partition_date_sql} AS DATE)
    )
    """
    return {
        "path_mismatch_samples": f"""
            {base_cte}
            SELECT ts_code, trade_date, trade_time, freq, path_ts_code, path_year
            FROM gold_rows
            WHERE freq != {freq}
               OR ts_code != path_ts_code
               OR strftime(trade_date, '%Y') != path_year
               OR (
                 trade_date = CAST({partition_date_sql} AS DATE)
                 AND CAST(trade_time AS DATE) != CAST({partition_date_sql} AS DATE)
               )
            ORDER BY filename, trade_date, trade_time
            LIMIT 5
        """,
        "duplicate_samples": f"""
            {base_cte}
            SELECT ts_code, trade_time, count(*) AS duplicate_count
            FROM target_rows
            GROUP BY ts_code, trade_time
            HAVING count(*) > 1
            ORDER BY ts_code, trade_time
            LIMIT 5
        """,
        "price_samples": f"""
            {base_cte}
            SELECT ts_code, trade_time, open, high, low, close
            FROM target_rows
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
               OR high < low
               OR open < low OR open > high
               OR close < low OR close > high
            ORDER BY ts_code, trade_time
            LIMIT 5
        """,
    }


def _gold_qfq_formula_counts_sql(
    *,
    gold_source: str,
    qfq_select_sql: str,
    partition_key: str,
) -> str:
    partition_date_sql = duckdb_string(partition_key)
    tolerance = GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE
    return f"""
    WITH gold_rows AS (
      SELECT
        CAST(ts_code AS VARCHAR) AS ts_code,
        CAST(trade_time AS TIMESTAMP) AS trade_time,
        CAST(open AS DOUBLE) AS open,
        CAST(high AS DOUBLE) AS high,
        CAST(low AS DOUBLE) AS low,
        CAST(close AS DOUBLE) AS close
      FROM {gold_source}
      WHERE CAST(trade_date AS DATE) = CAST({partition_date_sql} AS DATE)
    ),
    expected_rows AS (
      SELECT
        ts_code,
        trade_time,
        open,
        high,
        low,
        close
      FROM ({qfq_select_sql})
    ),
    compared_rows AS (
      SELECT
        coalesce(gold_rows.ts_code, expected_rows.ts_code) AS ts_code,
        coalesce(gold_rows.trade_time, expected_rows.trade_time) AS trade_time,
        gold_rows.open AS gold_open,
        expected_rows.open AS expected_open,
        gold_rows.high AS gold_high,
        expected_rows.high AS expected_high,
        gold_rows.low AS gold_low,
        expected_rows.low AS expected_low,
        gold_rows.close AS gold_close,
        expected_rows.close AS expected_close,
        gold_rows.ts_code IS NULL AS missing_gold_row,
        expected_rows.ts_code IS NULL AS unexpected_gold_row
      FROM gold_rows
      FULL OUTER JOIN expected_rows
        ON gold_rows.ts_code = expected_rows.ts_code
       AND gold_rows.trade_time = expected_rows.trade_time
    )
    SELECT
      count(*) FILTER (WHERE missing_gold_row) AS missing_gold_row_count,
      count(*) FILTER (WHERE unexpected_gold_row) AS unexpected_gold_row_count,
      count(*) FILTER (
        WHERE NOT missing_gold_row
          AND NOT unexpected_gold_row
          AND (
            abs(gold_open - expected_open) > {tolerance}
            OR abs(gold_high - expected_high) > {tolerance}
            OR abs(gold_low - expected_low) > {tolerance}
            OR abs(gold_close - expected_close) > {tolerance}
          )
      ) AS formula_mismatch_row_count
    FROM compared_rows
    """


def _gold_qfq_formula_sample_sql(
    *,
    gold_source: str,
    qfq_select_sql: str,
    partition_key: str,
) -> str:
    partition_date_sql = duckdb_string(partition_key)
    tolerance = GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE
    return f"""
    WITH gold_rows AS (
      SELECT
        CAST(ts_code AS VARCHAR) AS ts_code,
        CAST(trade_time AS TIMESTAMP) AS trade_time,
        CAST(open AS DOUBLE) AS open,
        CAST(high AS DOUBLE) AS high,
        CAST(low AS DOUBLE) AS low,
        CAST(close AS DOUBLE) AS close
      FROM {gold_source}
      WHERE CAST(trade_date AS DATE) = CAST({partition_date_sql} AS DATE)
    ),
    expected_rows AS (
      SELECT ts_code, trade_time, open, high, low, close
      FROM ({qfq_select_sql})
    ),
    compared_rows AS (
      SELECT
        coalesce(gold_rows.ts_code, expected_rows.ts_code) AS ts_code,
        coalesce(gold_rows.trade_time, expected_rows.trade_time) AS trade_time,
        gold_rows.open AS gold_open,
        expected_rows.open AS expected_open,
        gold_rows.high AS gold_high,
        expected_rows.high AS expected_high,
        gold_rows.low AS gold_low,
        expected_rows.low AS expected_low,
        gold_rows.close AS gold_close,
        expected_rows.close AS expected_close,
        gold_rows.ts_code IS NULL AS missing_gold_row,
        expected_rows.ts_code IS NULL AS unexpected_gold_row
      FROM gold_rows
      FULL OUTER JOIN expected_rows
        ON gold_rows.ts_code = expected_rows.ts_code
       AND gold_rows.trade_time = expected_rows.trade_time
    )
    SELECT
      ts_code,
      trade_time,
      gold_open,
      expected_open,
      gold_high,
      expected_high,
      gold_low,
      expected_low,
      gold_close,
      expected_close,
      missing_gold_row,
      unexpected_gold_row
    FROM compared_rows
    WHERE missing_gold_row
       OR unexpected_gold_row
       OR abs(gold_open - expected_open) > {tolerance}
       OR abs(gold_high - expected_high) > {tolerance}
       OR abs(gold_low - expected_low) > {tolerance}
       OR abs(gold_close - expected_close) > {tolerance}
    ORDER BY ts_code, trade_time
    LIMIT 5
    """


def _gold_qfq_check_results(
    *,
    asset_key: dg.AssetKey,
    partition_key: str,
    freq: int,
    counts: GoldStkMinsQfqCheckCounts,
    output_root_path: Path,
    input_file_paths: Sequence[Path],
    missing_gold_paths: Sequence[Path],
    observed_schema: dict[str, str],
    schema_error: str | None,
    samples: dict[str, list[dict[str, Any]]],
) -> tuple[dg.AssetCheckResult, ...]:
    common_metadata = {
        "partition_key": partition_key,
        "freq": freq,
        "expected_file_count": counts.expected_file_count,
        "existing_file_count": counts.existing_file_count,
        "missing_file_count": counts.missing_file_count,
        "gold_target_row_count": counts.gold_target_row_count,
        "silver_row_count": counts.silver_row_count,
        "missing_gold_file_samples": [
            str(path) for path in missing_gold_paths[:GOLD_STK_MINS_QFQ_METADATA_SAMPLE_LIMIT]
        ],
    }

    factor_coverage_failed_count = (
        counts.missing_trade_adj_factor_row_count
        + counts.missing_as_of_adj_factor_row_count
        + abs(counts.silver_row_count - counts.qfq_output_row_count)
    )
    formula_failed_count = (
        counts.formula_missing_gold_row_count
        + counts.formula_unexpected_gold_row_count
        + counts.formula_mismatch_row_count
    )

    return (
        _check_result(
            passed=counts.expected_file_count > 0
            and counts.missing_file_count == 0
            and counts.gold_target_row_count > 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
            check_scope=CheckScope.FILE_EXISTS,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            missing_file_paths=missing_gold_paths[:GOLD_STK_MINS_QFQ_METADATA_SAMPLE_LIMIT],
            checked_row_count=counts.expected_file_count,
            failed_row_count=counts.missing_file_count,
            extra_metadata=common_metadata,
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
            check_scope=CheckScope.SCHEMA,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.existing_file_count,
            failed_row_count=counts.schema_mismatch_file_count
            + counts.missing_file_count,
            extra_metadata={
                **common_metadata,
                "observed_schema": observed_schema,
                "expected_schema": GOLD_STK_MINS_QFQ_COLUMN_TYPES,
                "schema_error": schema_error,
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.path_mismatch_row_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK,
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.path_mismatch_row_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failure_samples": samples.get("path_mismatch_samples", []),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.duplicate_key_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
            check_scope=CheckScope.KEY_UNIQUENESS,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.duplicate_key_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failure_samples": samples.get("duplicate_samples", []),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.invalid_price_row_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK,
            check_scope=CheckScope.VALUE_SANITY,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.invalid_price_row_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failure_samples": samples.get("price_samples", []),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.gold_target_row_count == counts.silver_row_count,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_ROW_COUNT_MATCHES_SILVER_CHECK,
            check_scope=CheckScope.RECONCILIATION,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.silver_row_count,
            failed_row_count=abs(counts.gold_target_row_count - counts.silver_row_count)
            + counts.missing_file_count,
            extra_metadata=common_metadata,
        ),
        _check_result(
            passed=factor_coverage_failed_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_FACTOR_COVERAGE_COMPLETE_CHECK,
            check_scope=CheckScope.RECONCILIATION,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.silver_row_count,
            failed_row_count=factor_coverage_failed_count,
            extra_metadata={
                **common_metadata,
                "qfq_output_row_count": counts.qfq_output_row_count,
                "missing_trade_adj_factor_row_count": (
                    counts.missing_trade_adj_factor_row_count
                ),
                "missing_as_of_adj_factor_row_count": (
                    counts.missing_as_of_adj_factor_row_count
                ),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and formula_failed_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK,
            check_scope=CheckScope.RECONCILIATION,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=formula_failed_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "formula_tolerance": GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE,
                "formula_missing_gold_row_count": (
                    counts.formula_missing_gold_row_count
                ),
                "formula_unexpected_gold_row_count": (
                    counts.formula_unexpected_gold_row_count
                ),
                "formula_mismatch_row_count": counts.formula_mismatch_row_count,
                "failure_samples": samples.get("formula_samples", []),
            },
        ),
    )


def _gold_qfq_derived_check_results(
    *,
    asset_key: dg.AssetKey,
    partition_key: str,
    freq: int,
    counts: GoldStkMinsQfqDerivedCheckCounts,
    output_root_path: Path,
    input_file_paths: Sequence[Path],
    missing_gold_paths: Sequence[Path],
    observed_schema: dict[str, str],
    schema_error: str | None,
    samples: dict[str, list[dict[str, Any]]],
) -> tuple[dg.AssetCheckResult, ...]:
    common_metadata = {
        "partition_key": partition_key,
        "freq": freq,
        "source_freq": counts.source_freq,
        "source_file_count": counts.source_file_count,
        "source_row_count": counts.source_row_count,
        "source_stock_day_count": counts.source_stock_day_count,
        "expected_window_count": counts.expected_window_count,
        "generated_window_count": counts.generated_window_count,
        "incomplete_window_count": counts.incomplete_window_count,
        "exchange_mismatch_window_count": counts.exchange_mismatch_window_count,
        "expected_file_count": counts.expected_file_count,
        "existing_file_count": counts.existing_file_count,
        "missing_file_count": counts.missing_file_count,
        "gold_target_row_count": counts.gold_target_row_count,
        "missing_gold_file_samples": [
            str(path) for path in missing_gold_paths[:GOLD_STK_MINS_QFQ_METADATA_SAMPLE_LIMIT]
        ],
    }
    formula_failed_count = (
        counts.formula_missing_gold_row_count
        + counts.formula_unexpected_gold_row_count
        + counts.formula_mismatch_row_count
    )
    row_count_failed_count = abs(
        counts.gold_target_row_count - counts.generated_window_count
    ) + counts.missing_file_count

    return (
        _check_result(
            passed=counts.expected_file_count > 0
            and counts.missing_file_count == 0
            and counts.gold_target_row_count > 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
            check_scope=CheckScope.FILE_EXISTS,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            missing_file_paths=missing_gold_paths[:GOLD_STK_MINS_QFQ_METADATA_SAMPLE_LIMIT],
            checked_row_count=counts.expected_file_count,
            failed_row_count=counts.missing_file_count,
            extra_metadata=common_metadata,
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
            check_scope=CheckScope.SCHEMA,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.existing_file_count,
            failed_row_count=counts.schema_mismatch_file_count
            + counts.missing_file_count,
            extra_metadata={
                **common_metadata,
                "observed_schema": observed_schema,
                "expected_schema": GOLD_STK_MINS_QFQ_COLUMN_TYPES,
                "schema_error": schema_error,
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.path_mismatch_row_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK,
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.path_mismatch_row_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failure_samples": samples.get("path_mismatch_samples", []),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.duplicate_key_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
            check_scope=CheckScope.KEY_UNIQUENESS,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.duplicate_key_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failure_samples": samples.get("duplicate_samples", []),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.invalid_price_row_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK,
            check_scope=CheckScope.VALUE_SANITY,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.invalid_price_row_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failure_samples": samples.get("price_samples", []),
            },
        ),
        _check_result(
            passed=counts.source_file_count > 0
            and counts.source_row_count > 0
            and counts.source_stock_day_count > 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_DERIVED_SOURCE_READY_CHECK,
            check_scope=CheckScope.RECONCILIATION,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.source_row_count,
            failed_row_count=0 if counts.source_row_count > 0 else 1,
            extra_metadata=common_metadata,
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.exchange_mismatch_window_count == 0
            and counts.gold_target_row_count == counts.generated_window_count,
            asset_key=asset_key,
            check_name=(
                GOLD_STK_MINS_QFQ_DERIVED_ROW_COUNT_MATCHES_SOURCE_WINDOWS_CHECK
            ),
            check_scope=CheckScope.RECONCILIATION,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.generated_window_count,
            failed_row_count=row_count_failed_count
            + counts.schema_mismatch_file_count
            + counts.exchange_mismatch_window_count,
            extra_metadata=common_metadata,
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and formula_failed_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_DERIVED_FORMULA_MATCHES_SOURCE_CHECK,
            check_scope=CheckScope.RECONCILIATION,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=formula_failed_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "formula_tolerance": GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE,
                "formula_missing_gold_row_count": (
                    counts.formula_missing_gold_row_count
                ),
                "formula_unexpected_gold_row_count": (
                    counts.formula_unexpected_gold_row_count
                ),
                "formula_mismatch_row_count": counts.formula_mismatch_row_count,
                "failure_samples": samples.get("formula_samples", []),
            },
        ),
    )


def _gold_stk_mins_qfq_check_results(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
    asset_key: dg.AssetKey,
) -> tuple[dg.AssetCheckResult, ...]:
    partition_key = context.partition_key
    root = lake_root.root()
    normalized_freq = normalize_stk_mins_freq(freq)
    silver_path = _silver_path(lake_root, normalized_freq, partition_key)
    trade_adj_factor_path = silver_adj_factor_path(root, partition_key)
    output_root_path = gold_stk_mins_qfq_path(
        root,
        normalized_freq,
        "{ts_code}",
        partition_key[:4],
    ).parents[2]

    if not silver_path.exists():
        return _gold_qfq_input_failure_results(
            asset_key=asset_key,
            missing_path=silver_path,
            partition_key=partition_key,
            freq=normalized_freq,
        )

    input_file_paths = [silver_path, trade_adj_factor_path]

    with connect_configured_duckdb() as connection:
        expected_paths = _gold_qfq_expected_paths(
            connection,
            lake_root=root,
            freq=normalized_freq,
            partition_key=partition_key,
            silver_path=silver_path,
        )
        missing_gold_paths = tuple(path for path in expected_paths if not path.exists())
        existing_gold_paths = tuple(path for path in expected_paths if path.exists())
        silver_row_count = _row_count(connection, silver_path)

        schema_mismatch_count, observed_schema, schema_error = (
            _gold_qfq_schema_mismatch_count(connection, existing_gold_paths)
        )

        gold_target_row_count = 0
        path_mismatch_row_count = 0
        duplicate_key_count = 0
        invalid_price_row_count = 0
        formula_missing_gold_row_count = 0
        formula_unexpected_gold_row_count = 0
        formula_mismatch_row_count = 0
        samples: dict[str, list[dict[str, Any]]] = {}

        if existing_gold_paths and schema_mismatch_count == 0:
            gold_source = _read_parquet_paths(existing_gold_paths, filename=True)
            (
                gold_target_row_count,
                path_mismatch_row_count,
                duplicate_key_count,
                invalid_price_row_count,
            ) = (
                int(value or 0)
                for value in connection.execute(
                    _gold_qfq_counts_sql(
                        gold_source=gold_source,
                        partition_key=partition_key,
                        freq=normalized_freq,
                    )
                ).fetchone()
            )
            sample_queries: dict[str, str] = {}
            if (
                path_mismatch_row_count > 0
                or duplicate_key_count > 0
                or invalid_price_row_count > 0
            ):
                sample_queries = _gold_qfq_sample_queries(
                    gold_source=gold_source,
                    partition_key=partition_key,
                    freq=normalized_freq,
                )
            for sample_name, failed_count in (
                ("path_mismatch_samples", path_mismatch_row_count),
                ("duplicate_samples", duplicate_key_count),
                ("price_samples", invalid_price_row_count),
            ):
                if failed_count <= 0:
                    continue
                rows = connection.execute(sample_queries[sample_name]).fetchall()
                columns = [column[0] for column in connection.description]
                samples[sample_name] = _sample_dicts(columns, rows)

            if trade_adj_factor_path.exists():
                qfq_select_sql = build_daily_qfq_select_sql(
                    silver_paths=[silver_path],
                    trade_adj_factor_paths=[trade_adj_factor_path],
                    as_of_adj_factor_paths=[trade_adj_factor_path],
                )
                formula_counts = connection.execute(
                    _gold_qfq_formula_counts_sql(
                        gold_source=gold_source,
                        qfq_select_sql=qfq_select_sql,
                        partition_key=partition_key,
                    )
                ).fetchone()
                (
                    formula_missing_gold_row_count,
                    formula_unexpected_gold_row_count,
                    formula_mismatch_row_count,
                ) = (int(value or 0) for value in formula_counts)
                formula_failed_count = (
                    formula_missing_gold_row_count
                    + formula_unexpected_gold_row_count
                    + formula_mismatch_row_count
                )
                if formula_failed_count > 0:
                    rows = connection.execute(
                        _gold_qfq_formula_sample_sql(
                            gold_source=gold_source,
                            qfq_select_sql=qfq_select_sql,
                            partition_key=partition_key,
                        )
                    ).fetchall()
                    columns = [column[0] for column in connection.description]
                    samples["formula_samples"] = _sample_dicts(columns, rows)

        if trade_adj_factor_path.exists():
            coverage_counts = connection.execute(
                build_daily_qfq_coverage_sql(
                    silver_paths=[silver_path],
                    trade_adj_factor_paths=[trade_adj_factor_path],
                    as_of_adj_factor_paths=[trade_adj_factor_path],
                )
            ).fetchone()
            (
                _coverage_silver_row_count,
                qfq_output_row_count,
                missing_trade_adj_factor_row_count,
                missing_as_of_adj_factor_row_count,
            ) = (int(value or 0) for value in coverage_counts)
        else:
            qfq_output_row_count = 0
            missing_trade_adj_factor_row_count = silver_row_count
            missing_as_of_adj_factor_row_count = silver_row_count

    counts = GoldStkMinsQfqCheckCounts(
        silver_row_count=silver_row_count,
        expected_file_count=len(expected_paths),
        existing_file_count=len(existing_gold_paths),
        missing_file_count=len(missing_gold_paths),
        gold_target_row_count=gold_target_row_count,
        missing_trade_adj_factor_row_count=missing_trade_adj_factor_row_count,
        missing_as_of_adj_factor_row_count=missing_as_of_adj_factor_row_count,
        qfq_output_row_count=qfq_output_row_count,
        schema_mismatch_file_count=schema_mismatch_count,
        path_mismatch_row_count=path_mismatch_row_count,
        duplicate_key_count=duplicate_key_count,
        invalid_price_row_count=invalid_price_row_count,
        formula_missing_gold_row_count=formula_missing_gold_row_count,
        formula_unexpected_gold_row_count=formula_unexpected_gold_row_count,
        formula_mismatch_row_count=formula_mismatch_row_count,
    )
    return _gold_qfq_check_results(
        asset_key=asset_key,
        partition_key=partition_key,
        freq=normalized_freq,
        counts=counts,
        output_root_path=output_root_path,
        input_file_paths=input_file_paths,
        missing_gold_paths=missing_gold_paths,
        observed_schema=observed_schema,
        schema_error=schema_error,
        samples=samples,
    )


def _gold_stk_mins_qfq_derived_check_results(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
    asset_key: dg.AssetKey,
) -> tuple[dg.AssetCheckResult, ...]:
    partition_key = context.partition_key
    root = lake_root.root()
    normalized_freq = normalize_stk_mins_qfq_freq(freq)
    source_freq = qfq_source_freq_for_derived_freq(normalized_freq)
    year = partition_key[:4]
    source_paths = _gold_qfq_year_paths(
        lake_root=root,
        freq=source_freq,
        year=year,
    )
    source_root_path = gold_stk_mins_qfq_path(
        root,
        source_freq,
        "{ts_code}",
        year,
    ).parents[2]
    if not source_paths:
        return _gold_qfq_input_failure_results(
            asset_key=asset_key,
            missing_path=source_root_path,
            partition_key=partition_key,
            freq=normalized_freq,
            check_names=GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES,
        )

    output_root_path = gold_stk_mins_qfq_path(
        root,
        normalized_freq,
        "{ts_code}",
        year,
    ).parents[2]
    expected_select_sql = build_gold_stk_mins_qfq_derived_select_sql(
        source_qfq_paths=source_paths,
        target_freq=normalized_freq,
        partition_keys=[partition_key],
    )
    diagnostics_sql = build_gold_stk_mins_qfq_derived_diagnostics_sql(
        source_qfq_paths=source_paths,
        target_freq=normalized_freq,
        partition_keys=[partition_key],
    )
    with connect_configured_duckdb() as connection:
        (
            source_freq_from_sql,
            _target_freq,
            source_row_count,
            source_stock_day_count,
            expected_window_count,
            generated_window_count,
            incomplete_window_count,
            exchange_mismatch_window_count,
        ) = (int(value or 0) for value in connection.execute(diagnostics_sql).fetchone())
        expected_paths = _gold_qfq_derived_expected_paths(
            connection,
            lake_root=root,
            target_freq=normalized_freq,
            partition_key=partition_key,
            expected_select_sql=expected_select_sql,
        )
        missing_gold_paths = tuple(path for path in expected_paths if not path.exists())
        existing_gold_paths = tuple(path for path in expected_paths if path.exists())
        schema_mismatch_count, observed_schema, schema_error = (
            _gold_qfq_schema_mismatch_count(connection, existing_gold_paths)
        )

        gold_target_row_count = 0
        path_mismatch_row_count = 0
        duplicate_key_count = 0
        invalid_price_row_count = 0
        formula_missing_gold_row_count = 0
        formula_unexpected_gold_row_count = 0
        formula_mismatch_row_count = 0
        samples: dict[str, list[dict[str, Any]]] = {}

        if existing_gold_paths and schema_mismatch_count == 0:
            gold_source = _read_parquet_paths(existing_gold_paths, filename=True)
            (
                gold_target_row_count,
                path_mismatch_row_count,
                duplicate_key_count,
                invalid_price_row_count,
            ) = (
                int(value or 0)
                for value in connection.execute(
                    _gold_qfq_counts_sql(
                        gold_source=gold_source,
                        partition_key=partition_key,
                        freq=normalized_freq,
                    )
                ).fetchone()
            )
            sample_queries: dict[str, str] = {}
            if (
                path_mismatch_row_count > 0
                or duplicate_key_count > 0
                or invalid_price_row_count > 0
            ):
                sample_queries = _gold_qfq_sample_queries(
                    gold_source=gold_source,
                    partition_key=partition_key,
                    freq=normalized_freq,
                )
            for sample_name, failed_count in (
                ("path_mismatch_samples", path_mismatch_row_count),
                ("duplicate_samples", duplicate_key_count),
                ("price_samples", invalid_price_row_count),
            ):
                if failed_count <= 0:
                    continue
                rows = connection.execute(sample_queries[sample_name]).fetchall()
                columns = [column[0] for column in connection.description]
                samples[sample_name] = _sample_dicts(columns, rows)

            formula_counts = connection.execute(
                _gold_qfq_formula_counts_sql(
                    gold_source=gold_source,
                    qfq_select_sql=expected_select_sql,
                    partition_key=partition_key,
                )
            ).fetchone()
            (
                formula_missing_gold_row_count,
                formula_unexpected_gold_row_count,
                formula_mismatch_row_count,
            ) = (int(value or 0) for value in formula_counts)
            formula_failed_count = (
                formula_missing_gold_row_count
                + formula_unexpected_gold_row_count
                + formula_mismatch_row_count
            )
            if formula_failed_count > 0:
                rows = connection.execute(
                    _gold_qfq_formula_sample_sql(
                        gold_source=gold_source,
                        qfq_select_sql=expected_select_sql,
                        partition_key=partition_key,
                    )
                ).fetchall()
                columns = [column[0] for column in connection.description]
                samples["formula_samples"] = _sample_dicts(columns, rows)

    counts = GoldStkMinsQfqDerivedCheckCounts(
        source_freq=source_freq_from_sql,
        source_file_count=len(source_paths),
        source_row_count=source_row_count,
        source_stock_day_count=source_stock_day_count,
        expected_window_count=expected_window_count,
        generated_window_count=generated_window_count,
        incomplete_window_count=incomplete_window_count,
        exchange_mismatch_window_count=exchange_mismatch_window_count,
        expected_file_count=len(expected_paths),
        existing_file_count=len(existing_gold_paths),
        missing_file_count=len(missing_gold_paths),
        gold_target_row_count=gold_target_row_count,
        schema_mismatch_file_count=schema_mismatch_count,
        path_mismatch_row_count=path_mismatch_row_count,
        duplicate_key_count=duplicate_key_count,
        invalid_price_row_count=invalid_price_row_count,
        formula_missing_gold_row_count=formula_missing_gold_row_count,
        formula_unexpected_gold_row_count=formula_unexpected_gold_row_count,
        formula_mismatch_row_count=formula_mismatch_row_count,
    )
    return _gold_qfq_derived_check_results(
        asset_key=asset_key,
        partition_key=partition_key,
        freq=normalized_freq,
        counts=counts,
        output_root_path=output_root_path,
        input_file_paths=source_paths,
        missing_gold_paths=missing_gold_paths,
        observed_schema=observed_schema,
        schema_error=schema_error,
        samples=samples,
    )


def _file_exists_and_row_count_positive(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _raw_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = _row_count(connection, path)

    return _check_result(
        passed=row_count > 0,
        check_scope=CheckScope.ROW_COUNT,
        file_path=path,
        checked_row_count=row_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
        },
    )


def _schema_matches_contract(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _raw_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        observed_schema = _describe_columns(connection, path)
        row_count = _row_count(connection, path)

    missing_columns = [
        column for column in STK_MINS_RAW_COLUMN_TYPES if column not in observed_schema
    ]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": observed_schema.get(column),
        }
        for column, expected_type in STK_MINS_RAW_COLUMN_TYPES.items()
        if observed_schema.get(column) != expected_type
    }
    return _check_result(
        passed=not missing_columns and not type_mismatches,
        check_scope=CheckScope.SCHEMA,
        file_path=path,
        checked_row_count=row_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "observed_schema": observed_schema,
            "expected_schema": STK_MINS_RAW_COLUMN_TYPES,
            "missing_columns": missing_columns,
            "type_mismatches": type_mismatches,
        },
    )


def _freq_matches_asset(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _raw_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        row = connection.execute(
            f"""
            SELECT count(*) AS checked_count,
                   sum(CASE WHEN CAST(freq AS INTEGER) != {freq} THEN 1 ELSE 0 END)
                     AS failed_count
            FROM {relation}
            """
        ).fetchone()

    checked_count = int(row[0])
    failed_count = int(row[1] or 0)
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.PARTITION_ALIGNMENT,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "expected_freq": freq,
        },
    )


def _partition_date_matches(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _raw_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        row = connection.execute(
            f"""
            SELECT count(*) AS checked_count,
                   sum(
                     CASE
                       WHEN CAST(trade_time AS DATE)
                         != CAST({duckdb_string(partition_key)} AS DATE)
                       THEN 1 ELSE 0
                     END
                   ) AS failed_count
            FROM {relation}
            """
        ).fetchone()

    checked_count = int(row[0])
    failed_count = int(row[1] or 0)
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.PARTITION_ALIGNMENT,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
        },
    )


def _unique_ts_code_trade_time(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _raw_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        row = connection.execute(
            f"""
            WITH duplicate_groups AS (
              SELECT ts_code, trade_time, count(*) AS duplicate_count
              FROM {relation}
              GROUP BY ts_code, trade_time
              HAVING count(*) > 1
            )
            SELECT
              (SELECT count(*) FROM {relation}) AS checked_count,
              (SELECT count(*) FROM duplicate_groups) AS failed_count
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            SELECT ts_code, trade_time, duplicate_count
            FROM (
              SELECT ts_code, trade_time, count(*) AS duplicate_count
              FROM {relation}
              GROUP BY ts_code, trade_time
              HAVING count(*) > 1
            )
            ORDER BY ts_code, trade_time
            LIMIT 5
            """
        ).fetchall()

    checked_count = int(row[0])
    failed_count = int(row[1])
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.KEY_UNIQUENESS,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "failure_samples": _sample_dicts(
                ("ts_code", "trade_time", "duplicate_count"),
                sample_rows,
            ),
        },
    )


def _price_volume_sanity(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _raw_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        row = connection.execute(
            f"""
            SELECT
              count(*) AS checked_count,
              sum(
                CASE
                  WHEN ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
                    OR open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
                    OR vol IS NULL OR amount IS NULL OR vwap IS NULL
                    OR open < 0 OR close < 0 OR high < 0 OR low < 0
                    OR vol < 0 OR amount < 0 OR vwap < 0
                  THEN 1 ELSE 0
                END
              ) AS failed_count
            FROM {relation}
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            SELECT ts_code, trade_time, open, close, high, low, vol, amount, vwap
            FROM {relation}
            WHERE ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
               OR vol IS NULL OR amount IS NULL OR vwap IS NULL
               OR open < 0 OR close < 0 OR high < 0 OR low < 0
               OR vol < 0 OR amount < 0 OR vwap < 0
            ORDER BY ts_code, trade_time
            LIMIT 5
            """
        ).fetchall()

    checked_count = int(row[0])
    failed_count = int(row[1] or 0)
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.VALUE_SANITY,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "raw_sanity_policy": (
                "Raw stk_mins keeps backup clean_next source facts. This check only "
                "blocks null values, negative numeric values, and empty stock codes."
            ),
            "failure_samples": _sample_dicts(
                (
                    "ts_code",
                    "trade_time",
                    "open",
                    "close",
                    "high",
                    "low",
                    "vol",
                    "amount",
                    "vwap",
                ),
                sample_rows,
            ),
        },
    )


def _partition_key_registered(
    *,
    context: dg.AssetCheckExecutionContext,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    registered_keys = set(
        context.instance.get_dynamic_partitions(cn_a_stock_mins_trade_days.name)
    )
    is_registered = partition_key in registered_keys
    return _check_result(
        passed=is_registered,
        check_scope=CheckScope.PARTITION_ALIGNMENT,
        checked_row_count=1,
        failed_row_count=0 if is_registered else 1,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "partition_set": cn_a_stock_mins_trade_days.name,
            "is_registered": is_registered,
        },
    )


def _silver_file_exists_and_row_count_positive(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = _row_count(connection, path)

    return _check_result(
        passed=row_count > 0,
        check_scope=CheckScope.ROW_COUNT,
        file_path=path,
        checked_row_count=row_count,
        extra_metadata={"partition_key": partition_key, "freq": freq},
    )


def _silver_schema_matches_contract(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        observed_schema = _describe_columns(connection, path)
        row_count = _row_count(connection, path)

    missing_columns = [
        column for column in STK_MINS_SILVER_COLUMN_TYPES if column not in observed_schema
    ]
    type_mismatches = {
        column: {"expected": expected_type, "actual": observed_schema.get(column)}
        for column, expected_type in STK_MINS_SILVER_COLUMN_TYPES.items()
        if observed_schema.get(column) != expected_type
    }
    return _check_result(
        passed=not missing_columns and not type_mismatches,
        check_scope=CheckScope.SCHEMA,
        file_path=path,
        checked_row_count=row_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "observed_schema": observed_schema,
            "expected_schema": STK_MINS_SILVER_COLUMN_TYPES,
            "missing_columns": missing_columns,
            "type_mismatches": type_mismatches,
        },
    )


def _silver_freq_and_partition_match(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        row = connection.execute(
            f"""
            SELECT
              count(*) AS checked_count,
              sum(
                CASE
                  WHEN CAST(freq AS INTEGER) != {freq}
                    OR trade_date != CAST({duckdb_string(partition_key)} AS DATE)
                    OR CAST(trade_time AS DATE) != CAST({duckdb_string(partition_key)} AS DATE)
                  THEN 1 ELSE 0
                END
              ) AS failed_count
            FROM {relation}
            """
        ).fetchone()

    checked_count = int(row[0])
    failed_count = int(row[1] or 0)
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.PARTITION_ALIGNMENT,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={"partition_key": partition_key, "freq": freq},
    )


def _silver_unique_ts_code_trade_time(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        row = connection.execute(
            f"""
            WITH duplicate_groups AS (
              SELECT ts_code, trade_time, count(*) AS duplicate_count
              FROM {relation}
              GROUP BY ts_code, trade_time
              HAVING count(*) > 1
            )
            SELECT
              (SELECT count(*) FROM {relation}) AS checked_count,
              (SELECT count(*) FROM duplicate_groups) AS failed_count
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            SELECT ts_code, trade_time, duplicate_count
            FROM (
              SELECT ts_code, trade_time, count(*) AS duplicate_count
              FROM {relation}
              GROUP BY ts_code, trade_time
              HAVING count(*) > 1
            )
            ORDER BY ts_code, trade_time
            LIMIT 5
            """
        ).fetchall()

    checked_count = int(row[0])
    failed_count = int(row[1])
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.KEY_UNIQUENESS,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "failure_samples": _sample_dicts(
                ("ts_code", "trade_time", "duplicate_count"),
                sample_rows,
            ),
        },
    )


def _silver_price_sanity(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    predicate = """
      open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
      OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
      OR high < low
      OR open < low OR open > high
      OR close < low OR close > high
    """
    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        row = connection.execute(
            f"""
            SELECT
              count(*) AS checked_count,
              sum(CASE WHEN {predicate} THEN 1 ELSE 0 END) AS failed_count
            FROM {relation}
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            SELECT ts_code, trade_time, open, high, low, close
            FROM {relation}
            WHERE {predicate}
            ORDER BY ts_code, trade_time
            LIMIT 5
            """
        ).fetchall()

    checked_count = int(row[0])
    failed_count = int(row[1] or 0)
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.VALUE_SANITY,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "failure_samples": _sample_dicts(
                ("ts_code", "trade_time", "open", "high", "low", "close"),
                sample_rows,
            ),
        },
    )


def _silver_volume_amount_sanity(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    predicate = """
      vol IS NULL OR amount IS NULL
      OR vol < 0 OR amount < 0
      OR (vol = 0 AND amount != 0)
      OR (vol > 0 AND vol < 100)
      OR (vol >= 100 AND amount <= 0)
    """
    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        row = connection.execute(
            f"""
            SELECT
              count(*) AS checked_count,
              sum(CASE WHEN {predicate} THEN 1 ELSE 0 END) AS failed_count
            FROM {relation}
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            SELECT ts_code, trade_time, vol, amount
            FROM {relation}
            WHERE {predicate}
            ORDER BY ts_code, trade_time
            LIMIT 5
            """
        ).fetchall()

    checked_count = int(row[0])
    failed_count = int(row[1] or 0)
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.VALUE_SANITY,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "failure_samples": _sample_dicts(
                ("ts_code", "trade_time", "vol", "amount"),
                sample_rows,
            ),
        },
    )


def _silver_exchange_matches_suffix(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    if not path.exists():
        return _missing_file_result(path)

    expected_exchange = """
      CASE
        WHEN upper(ts_code) LIKE '%.SH' THEN 'SSE'
        WHEN upper(ts_code) LIKE '%.SZ' THEN 'SZSE'
        WHEN upper(ts_code) LIKE '%.BJ' THEN 'BSE'
        ELSE NULL
      END
    """
    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        row = connection.execute(
            f"""
            SELECT
              count(*) AS checked_count,
              sum(
                CASE
                  WHEN exchange IS NULL OR exchange != {expected_exchange}
                  THEN 1 ELSE 0
                END
              ) AS failed_count
            FROM {relation}
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            SELECT ts_code, exchange, {expected_exchange} AS expected_exchange
            FROM {relation}
            WHERE exchange IS NULL OR exchange != {expected_exchange}
            ORDER BY ts_code
            LIMIT 5
            """
        ).fetchall()

    checked_count = int(row[0])
    failed_count = int(row[1] or 0)
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.VALUE_SANITY,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "failure_samples": _sample_dicts(
                ("ts_code", "exchange", "expected_exchange"),
                sample_rows,
            ),
        },
    )


def _silver_codes_exist_in_stock_daily(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    daily_path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)
    if not daily_path.exists():
        return _missing_input_file_result(path, daily_path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        daily_relation = read_parquet(daily_path, hive_partitioning=False)
        row = connection.execute(
            f"""
            WITH silver_codes AS (
              SELECT DISTINCT ts_code FROM {relation}
            ),
            missing_codes AS (
              SELECT silver_codes.ts_code
              FROM silver_codes
              LEFT JOIN {daily_relation} AS daily_rows
                ON silver_codes.ts_code = daily_rows.ts_code
               AND daily_rows.trade_date = CAST({duckdb_string(partition_key)} AS DATE)
              WHERE daily_rows.ts_code IS NULL
            )
            SELECT
              (SELECT count(*) FROM silver_codes) AS checked_count,
              (SELECT count(*) FROM missing_codes) AS failed_count
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            WITH silver_codes AS (
              SELECT DISTINCT ts_code FROM {relation}
            )
            SELECT silver_codes.ts_code
            FROM silver_codes
            LEFT JOIN {daily_relation} AS daily_rows
              ON silver_codes.ts_code = daily_rows.ts_code
             AND daily_rows.trade_date = CAST({duckdb_string(partition_key)} AS DATE)
            WHERE daily_rows.ts_code IS NULL
            ORDER BY silver_codes.ts_code
            LIMIT 10
            """
        ).fetchall()

    checked_count = int(row[0])
    failed_count = int(row[1])
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.REFERENTIAL_INTEGRITY,
        file_path=path,
        input_file_paths=[daily_path],
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "failure_samples": _sample_dicts(("ts_code",), sample_rows),
        },
    )


def _silver_no_full_day_suspend_structural_rows(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    suspend_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)
    if not suspend_path.exists():
        return _missing_input_file_result(path, suspend_path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        suspend_relation = read_parquet(suspend_path, hive_partitioning=False)
        row = connection.execute(
            f"""
            SELECT
              (SELECT count(*) FROM {relation}) AS checked_count,
              count(*) AS failed_count
            FROM {relation} AS silver_rows
            INNER JOIN {suspend_relation} AS suspend_rows
              ON silver_rows.ts_code = suspend_rows.ts_code
             AND silver_rows.trade_date = suspend_rows.trade_date
            WHERE suspend_rows.suspend_type = 'S'
              AND suspend_rows.suspend_timing IS NULL
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            SELECT silver_rows.ts_code, silver_rows.trade_time
            FROM {relation} AS silver_rows
            INNER JOIN {suspend_relation} AS suspend_rows
              ON silver_rows.ts_code = suspend_rows.ts_code
             AND silver_rows.trade_date = suspend_rows.trade_date
            WHERE suspend_rows.suspend_type = 'S'
              AND suspend_rows.suspend_timing IS NULL
            ORDER BY silver_rows.ts_code, silver_rows.trade_time
            LIMIT 10
            """
        ).fetchall()

    checked_count = int(row[0])
    failed_count = int(row[1])
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.RECONCILIATION,
        file_path=path,
        input_file_paths=[suspend_path],
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "failure_samples": _sample_dicts(("ts_code", "trade_time"), sample_rows),
        },
    )


def _silver_name_timeline_covered(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    namechange_path = silver_namechange_path(lake_root.root())
    stock_basic_path = silver_stock_basic_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    if not namechange_path.exists():
        return _missing_input_file_result(path, namechange_path)
    if not stock_basic_path.exists():
        return _missing_input_file_result(path, stock_basic_path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        namechange_relation = read_parquet(namechange_path, hive_partitioning=False)
        stock_basic_relation = read_parquet(stock_basic_path, hive_partitioning=False)
        row = connection.execute(
            f"""
            WITH silver_codes AS (
              SELECT DISTINCT ts_code, trade_date FROM {relation}
            ),
            missing_names AS (
              SELECT silver_codes.ts_code, silver_codes.trade_date
              FROM silver_codes
              WHERE NOT EXISTS (
                SELECT 1
                FROM {namechange_relation} AS names
                WHERE names.ts_code = silver_codes.ts_code
                  AND silver_codes.trade_date >= names.start_date
                  AND (
                    names.end_date IS NULL
                    OR silver_codes.trade_date <= names.end_date
                  )
              )
                AND NOT EXISTS (
                  SELECT 1
                  FROM {stock_basic_relation} AS basic
                  WHERE basic.ts_code = silver_codes.ts_code
                )
            )
            SELECT
              (SELECT count(*) FROM silver_codes) AS checked_count,
              (SELECT count(*) FROM missing_names) AS failed_count
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            WITH silver_codes AS (
              SELECT DISTINCT ts_code, trade_date FROM {relation}
            )
            SELECT silver_codes.ts_code, silver_codes.trade_date
            FROM silver_codes
            WHERE NOT EXISTS (
              SELECT 1
              FROM {namechange_relation} AS names
              WHERE names.ts_code = silver_codes.ts_code
                AND silver_codes.trade_date >= names.start_date
                AND (
                  names.end_date IS NULL
                  OR silver_codes.trade_date <= names.end_date
                )
            )
              AND NOT EXISTS (
                SELECT 1
                FROM {stock_basic_relation} AS basic
                WHERE basic.ts_code = silver_codes.ts_code
              )
            ORDER BY silver_codes.ts_code
            LIMIT 10
            """
        ).fetchall()

    checked_count = int(row[0])
    failed_count = int(row[1])
    return _check_result(
        passed=failed_count == 0,
        check_scope=CheckScope.REFERENTIAL_INTEGRITY,
        file_path=path,
        input_file_paths=[namechange_path, stock_basic_path],
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "failure_samples": _sample_dicts(("ts_code", "trade_date"), sample_rows),
        },
    )


def _build_file_exists_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _file_exists_and_row_count_positive(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_schema_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _schema_matches_contract(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_freq_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _freq_matches_asset(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_partition_date_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _partition_date_matches(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_unique_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _unique_ts_code_trade_time(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_price_volume_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _price_volume_sanity(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_partition_registered_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK,
        blocking=True,
    )
    def _check(context: dg.AssetCheckExecutionContext) -> dg.AssetCheckResult:
        return _partition_key_registered(context=context, freq=freq)

    return _check


def _build_raw_stk_mins_checks(asset, freq: int):
    normalized_freq = normalize_stk_mins_freq(freq)
    return (
        _build_file_exists_check(asset, normalized_freq),
        _build_schema_check(asset, normalized_freq),
        _build_freq_check(asset, normalized_freq),
        _build_partition_date_check(asset, normalized_freq),
        _build_unique_check(asset, normalized_freq),
        _build_price_volume_check(asset, normalized_freq),
        _build_partition_registered_check(asset, normalized_freq),
    )


(
    raw_stk_mins_1m_file_exists_and_row_count_positive,
    raw_stk_mins_1m_schema_matches_contract,
    raw_stk_mins_1m_freq_matches_asset,
    raw_stk_mins_1m_partition_date_matches,
    raw_stk_mins_1m_unique_ts_code_trade_time,
    raw_stk_mins_1m_price_volume_sanity,
    raw_stk_mins_1m_stock_mins_partition_key_registered,
) = _build_raw_stk_mins_checks(raw_stk_mins_1m, 1)

(
    raw_stk_mins_5m_file_exists_and_row_count_positive,
    raw_stk_mins_5m_schema_matches_contract,
    raw_stk_mins_5m_freq_matches_asset,
    raw_stk_mins_5m_partition_date_matches,
    raw_stk_mins_5m_unique_ts_code_trade_time,
    raw_stk_mins_5m_price_volume_sanity,
    raw_stk_mins_5m_stock_mins_partition_key_registered,
) = _build_raw_stk_mins_checks(raw_stk_mins_5m, 5)

(
    raw_stk_mins_15m_file_exists_and_row_count_positive,
    raw_stk_mins_15m_schema_matches_contract,
    raw_stk_mins_15m_freq_matches_asset,
    raw_stk_mins_15m_partition_date_matches,
    raw_stk_mins_15m_unique_ts_code_trade_time,
    raw_stk_mins_15m_price_volume_sanity,
    raw_stk_mins_15m_stock_mins_partition_key_registered,
) = _build_raw_stk_mins_checks(raw_stk_mins_15m, 15)

(
    raw_stk_mins_30m_file_exists_and_row_count_positive,
    raw_stk_mins_30m_schema_matches_contract,
    raw_stk_mins_30m_freq_matches_asset,
    raw_stk_mins_30m_partition_date_matches,
    raw_stk_mins_30m_unique_ts_code_trade_time,
    raw_stk_mins_30m_price_volume_sanity,
    raw_stk_mins_30m_stock_mins_partition_key_registered,
) = _build_raw_stk_mins_checks(raw_stk_mins_30m, 30)

(
    raw_stk_mins_60m_file_exists_and_row_count_positive,
    raw_stk_mins_60m_schema_matches_contract,
    raw_stk_mins_60m_freq_matches_asset,
    raw_stk_mins_60m_partition_date_matches,
    raw_stk_mins_60m_unique_ts_code_trade_time,
    raw_stk_mins_60m_price_volume_sanity,
    raw_stk_mins_60m_stock_mins_partition_key_registered,
) = _build_raw_stk_mins_checks(raw_stk_mins_60m, 60)

RAW_STK_MINS_CHECK_DEFINITIONS = (
    raw_stk_mins_1m_file_exists_and_row_count_positive,
    raw_stk_mins_1m_schema_matches_contract,
    raw_stk_mins_1m_freq_matches_asset,
    raw_stk_mins_1m_partition_date_matches,
    raw_stk_mins_1m_unique_ts_code_trade_time,
    raw_stk_mins_1m_price_volume_sanity,
    raw_stk_mins_1m_stock_mins_partition_key_registered,
    raw_stk_mins_5m_file_exists_and_row_count_positive,
    raw_stk_mins_5m_schema_matches_contract,
    raw_stk_mins_5m_freq_matches_asset,
    raw_stk_mins_5m_partition_date_matches,
    raw_stk_mins_5m_unique_ts_code_trade_time,
    raw_stk_mins_5m_price_volume_sanity,
    raw_stk_mins_5m_stock_mins_partition_key_registered,
    raw_stk_mins_15m_file_exists_and_row_count_positive,
    raw_stk_mins_15m_schema_matches_contract,
    raw_stk_mins_15m_freq_matches_asset,
    raw_stk_mins_15m_partition_date_matches,
    raw_stk_mins_15m_unique_ts_code_trade_time,
    raw_stk_mins_15m_price_volume_sanity,
    raw_stk_mins_15m_stock_mins_partition_key_registered,
    raw_stk_mins_30m_file_exists_and_row_count_positive,
    raw_stk_mins_30m_schema_matches_contract,
    raw_stk_mins_30m_freq_matches_asset,
    raw_stk_mins_30m_partition_date_matches,
    raw_stk_mins_30m_unique_ts_code_trade_time,
    raw_stk_mins_30m_price_volume_sanity,
    raw_stk_mins_30m_stock_mins_partition_key_registered,
    raw_stk_mins_60m_file_exists_and_row_count_positive,
    raw_stk_mins_60m_schema_matches_contract,
    raw_stk_mins_60m_freq_matches_asset,
    raw_stk_mins_60m_partition_date_matches,
    raw_stk_mins_60m_unique_ts_code_trade_time,
    raw_stk_mins_60m_price_volume_sanity,
    raw_stk_mins_60m_stock_mins_partition_key_registered,
)

assert len(RAW_STK_MINS_CHECK_DEFINITIONS) == len(RAW_STK_MINS_ASSETS) * len(
    RAW_STK_MINS_CHECK_NAMES
)


def _build_silver_check(asset, freq: int, name: str, evaluator):
    @dg.asset_check(
        asset=asset,
        name=name,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return evaluator(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_silver_stk_mins_checks(asset, freq: int):
    normalized_freq = normalize_stk_mins_freq(freq)
    return (
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
            _silver_file_exists_and_row_count_positive,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
            _silver_schema_matches_contract,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_FREQ_AND_PARTITION_MATCH_CHECK,
            _silver_freq_and_partition_match,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
            _silver_unique_ts_code_trade_time,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_PRICE_SANITY_CHECK,
            _silver_price_sanity,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_VOLUME_AMOUNT_SANITY_CHECK,
            _silver_volume_amount_sanity,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_EXCHANGE_MATCHES_SUFFIX_CHECK,
            _silver_exchange_matches_suffix,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_CODES_EXIST_IN_STOCK_DAILY_CHECK,
            _silver_codes_exist_in_stock_daily,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_NO_FULL_DAY_SUSPEND_STRUCTURAL_ROWS_CHECK,
            _silver_no_full_day_suspend_structural_rows,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
            _silver_name_timeline_covered,
        ),
    )


(
    silver_stk_mins_1m_file_exists_and_row_count_positive,
    silver_stk_mins_1m_schema_matches_contract,
    silver_stk_mins_1m_freq_and_partition_match,
    silver_stk_mins_1m_unique_ts_code_trade_time,
    silver_stk_mins_1m_price_sanity,
    silver_stk_mins_1m_volume_amount_sanity,
    silver_stk_mins_1m_exchange_matches_suffix,
    silver_stk_mins_1m_codes_exist_in_stock_daily,
    silver_stk_mins_1m_no_full_day_suspend_structural_rows,
    silver_stk_mins_1m_name_timeline_covered,
) = _build_silver_stk_mins_checks(silver_stk_mins_1m, 1)

(
    silver_stk_mins_5m_file_exists_and_row_count_positive,
    silver_stk_mins_5m_schema_matches_contract,
    silver_stk_mins_5m_freq_and_partition_match,
    silver_stk_mins_5m_unique_ts_code_trade_time,
    silver_stk_mins_5m_price_sanity,
    silver_stk_mins_5m_volume_amount_sanity,
    silver_stk_mins_5m_exchange_matches_suffix,
    silver_stk_mins_5m_codes_exist_in_stock_daily,
    silver_stk_mins_5m_no_full_day_suspend_structural_rows,
    silver_stk_mins_5m_name_timeline_covered,
) = _build_silver_stk_mins_checks(silver_stk_mins_5m, 5)

(
    silver_stk_mins_15m_file_exists_and_row_count_positive,
    silver_stk_mins_15m_schema_matches_contract,
    silver_stk_mins_15m_freq_and_partition_match,
    silver_stk_mins_15m_unique_ts_code_trade_time,
    silver_stk_mins_15m_price_sanity,
    silver_stk_mins_15m_volume_amount_sanity,
    silver_stk_mins_15m_exchange_matches_suffix,
    silver_stk_mins_15m_codes_exist_in_stock_daily,
    silver_stk_mins_15m_no_full_day_suspend_structural_rows,
    silver_stk_mins_15m_name_timeline_covered,
) = _build_silver_stk_mins_checks(silver_stk_mins_15m, 15)

(
    silver_stk_mins_30m_file_exists_and_row_count_positive,
    silver_stk_mins_30m_schema_matches_contract,
    silver_stk_mins_30m_freq_and_partition_match,
    silver_stk_mins_30m_unique_ts_code_trade_time,
    silver_stk_mins_30m_price_sanity,
    silver_stk_mins_30m_volume_amount_sanity,
    silver_stk_mins_30m_exchange_matches_suffix,
    silver_stk_mins_30m_codes_exist_in_stock_daily,
    silver_stk_mins_30m_no_full_day_suspend_structural_rows,
    silver_stk_mins_30m_name_timeline_covered,
) = _build_silver_stk_mins_checks(silver_stk_mins_30m, 30)

(
    silver_stk_mins_60m_file_exists_and_row_count_positive,
    silver_stk_mins_60m_schema_matches_contract,
    silver_stk_mins_60m_freq_and_partition_match,
    silver_stk_mins_60m_unique_ts_code_trade_time,
    silver_stk_mins_60m_price_sanity,
    silver_stk_mins_60m_volume_amount_sanity,
    silver_stk_mins_60m_exchange_matches_suffix,
    silver_stk_mins_60m_codes_exist_in_stock_daily,
    silver_stk_mins_60m_no_full_day_suspend_structural_rows,
    silver_stk_mins_60m_name_timeline_covered,
) = _build_silver_stk_mins_checks(silver_stk_mins_60m, 60)

SILVER_STK_MINS_CHECK_DEFINITIONS = (
    silver_stk_mins_1m_file_exists_and_row_count_positive,
    silver_stk_mins_1m_schema_matches_contract,
    silver_stk_mins_1m_freq_and_partition_match,
    silver_stk_mins_1m_unique_ts_code_trade_time,
    silver_stk_mins_1m_price_sanity,
    silver_stk_mins_1m_volume_amount_sanity,
    silver_stk_mins_1m_exchange_matches_suffix,
    silver_stk_mins_1m_codes_exist_in_stock_daily,
    silver_stk_mins_1m_no_full_day_suspend_structural_rows,
    silver_stk_mins_1m_name_timeline_covered,
    silver_stk_mins_5m_file_exists_and_row_count_positive,
    silver_stk_mins_5m_schema_matches_contract,
    silver_stk_mins_5m_freq_and_partition_match,
    silver_stk_mins_5m_unique_ts_code_trade_time,
    silver_stk_mins_5m_price_sanity,
    silver_stk_mins_5m_volume_amount_sanity,
    silver_stk_mins_5m_exchange_matches_suffix,
    silver_stk_mins_5m_codes_exist_in_stock_daily,
    silver_stk_mins_5m_no_full_day_suspend_structural_rows,
    silver_stk_mins_5m_name_timeline_covered,
    silver_stk_mins_15m_file_exists_and_row_count_positive,
    silver_stk_mins_15m_schema_matches_contract,
    silver_stk_mins_15m_freq_and_partition_match,
    silver_stk_mins_15m_unique_ts_code_trade_time,
    silver_stk_mins_15m_price_sanity,
    silver_stk_mins_15m_volume_amount_sanity,
    silver_stk_mins_15m_exchange_matches_suffix,
    silver_stk_mins_15m_codes_exist_in_stock_daily,
    silver_stk_mins_15m_no_full_day_suspend_structural_rows,
    silver_stk_mins_15m_name_timeline_covered,
    silver_stk_mins_30m_file_exists_and_row_count_positive,
    silver_stk_mins_30m_schema_matches_contract,
    silver_stk_mins_30m_freq_and_partition_match,
    silver_stk_mins_30m_unique_ts_code_trade_time,
    silver_stk_mins_30m_price_sanity,
    silver_stk_mins_30m_volume_amount_sanity,
    silver_stk_mins_30m_exchange_matches_suffix,
    silver_stk_mins_30m_codes_exist_in_stock_daily,
    silver_stk_mins_30m_no_full_day_suspend_structural_rows,
    silver_stk_mins_30m_name_timeline_covered,
    silver_stk_mins_60m_file_exists_and_row_count_positive,
    silver_stk_mins_60m_schema_matches_contract,
    silver_stk_mins_60m_freq_and_partition_match,
    silver_stk_mins_60m_unique_ts_code_trade_time,
    silver_stk_mins_60m_price_sanity,
    silver_stk_mins_60m_volume_amount_sanity,
    silver_stk_mins_60m_exchange_matches_suffix,
    silver_stk_mins_60m_codes_exist_in_stock_daily,
    silver_stk_mins_60m_no_full_day_suspend_structural_rows,
    silver_stk_mins_60m_name_timeline_covered,
)

assert len(SILVER_STK_MINS_CHECK_DEFINITIONS) == len(SILVER_STK_MINS_ASSETS) * len(
    SILVER_STK_MINS_CHECK_NAMES
)


def _build_gold_qfq_native_multi_check(asset, freq: int):
    normalized_freq = normalize_stk_mins_freq(freq)
    asset_key = _gold_qfq_asset_key(asset)
    specs = tuple(
        dg.AssetCheckSpec(name=check_name, asset=asset, blocking=True)
        for check_name in GOLD_STK_MINS_QFQ_NATIVE_CHECK_NAMES
    )

    @dg.multi_asset_check(
        name=f"{asset_key.path[-1]}_blocking_checks",
        specs=specs,
        can_subset=False,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> Iterator[dg.AssetCheckResult]:
        yield from _gold_stk_mins_qfq_check_results(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=normalized_freq,
            asset_key=asset_key,
        )

    return _check


def _build_gold_qfq_derived_multi_check(asset, freq: int):
    normalized_freq = normalize_stk_mins_qfq_freq(freq)
    asset_key = _gold_qfq_asset_key(asset)
    specs = tuple(
        dg.AssetCheckSpec(name=check_name, asset=asset, blocking=True)
        for check_name in GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES
    )

    @dg.multi_asset_check(
        name=f"{asset_key.path[-1]}_blocking_checks",
        specs=specs,
        can_subset=False,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> Iterator[dg.AssetCheckResult]:
        yield from _gold_stk_mins_qfq_derived_check_results(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=normalized_freq,
            asset_key=asset_key,
        )

    return _check


gold_stk_mins_qfq_1m_blocking_checks = _build_gold_qfq_native_multi_check(
    gold_stk_mins_qfq_1m,
    1,
)
gold_stk_mins_qfq_5m_blocking_checks = _build_gold_qfq_native_multi_check(
    gold_stk_mins_qfq_5m,
    5,
)
gold_stk_mins_qfq_15m_blocking_checks = _build_gold_qfq_native_multi_check(
    gold_stk_mins_qfq_15m,
    15,
)
gold_stk_mins_qfq_30m_blocking_checks = _build_gold_qfq_native_multi_check(
    gold_stk_mins_qfq_30m,
    30,
)
gold_stk_mins_qfq_60m_blocking_checks = _build_gold_qfq_native_multi_check(
    gold_stk_mins_qfq_60m,
    60,
)
gold_stk_mins_qfq_90m_blocking_checks = _build_gold_qfq_derived_multi_check(
    gold_stk_mins_qfq_90m,
    90,
)
gold_stk_mins_qfq_120m_blocking_checks = _build_gold_qfq_derived_multi_check(
    gold_stk_mins_qfq_120m,
    120,
)

GOLD_STK_MINS_QFQ_CHECK_DEFINITIONS = (
    gold_stk_mins_qfq_1m_blocking_checks,
    gold_stk_mins_qfq_5m_blocking_checks,
    gold_stk_mins_qfq_15m_blocking_checks,
    gold_stk_mins_qfq_30m_blocking_checks,
    gold_stk_mins_qfq_60m_blocking_checks,
    gold_stk_mins_qfq_90m_blocking_checks,
    gold_stk_mins_qfq_120m_blocking_checks,
)

assert sum(
    len(check_definition.check_keys)
    for check_definition in GOLD_STK_MINS_QFQ_CHECK_DEFINITIONS
) == (
    len(GOLD_STK_MINS_QFQ_NATIVE_ASSETS) * len(GOLD_STK_MINS_QFQ_NATIVE_CHECK_NAMES)
    + len(GOLD_STK_MINS_QFQ_DERIVED_ASSETS) * len(GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES)
)
assert len(GOLD_STK_MINS_QFQ_ASSETS) == (
    len(GOLD_STK_MINS_QFQ_NATIVE_ASSETS) + len(GOLD_STK_MINS_QFQ_DERIVED_ASSETS)
)
