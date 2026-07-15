from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle
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
    silver_cny_stock_lifecycle_select,
)
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    raw_stk_mins_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
    silver_stock_lifecycle_path,
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
    build_daily_qfq_coverage_identities_sql,
    build_daily_qfq_coverage_sql,
    build_gold_stk_mins_qfq_derived_diagnostics_sql,
    build_gold_stk_mins_qfq_derived_coverage_sql,
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
RAW_STK_MINS_CONTRACT_CHECK = "raw_stk_mins_contract_check"
RAW_STK_MINS_KEY_INTEGRITY_CHECK = "raw_stk_mins_key_integrity_check"
RAW_STK_MINS_VALUE_DOMAIN_CHECK = "raw_stk_mins_value_domain_check"

RAW_STK_MINS_CHECK_NAMES = (
    RAW_STK_MINS_CONTRACT_CHECK,
    RAW_STK_MINS_KEY_INTEGRITY_CHECK,
    RAW_STK_MINS_VALUE_DOMAIN_CHECK,
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
SILVER_STK_MINS_CONTRACT_CHECK = "silver_stk_mins_contract_check"
SILVER_STK_MINS_KEY_INTEGRITY_CHECK = "silver_stk_mins_key_integrity_check"
SILVER_STK_MINS_VALUE_DOMAIN_CHECK = "silver_stk_mins_value_domain_check"
SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK = (
    "silver_stk_mins_reference_coverage_check"
)

SILVER_STK_MINS_CHECK_NAMES = (
    SILVER_STK_MINS_CONTRACT_CHECK,
    SILVER_STK_MINS_KEY_INTEGRITY_CHECK,
    SILVER_STK_MINS_VALUE_DOMAIN_CHECK,
    SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK,
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
GOLD_STK_MINS_QFQ_DERIVED_SOURCE_READY_CHECK = (
    "gold_stk_mins_qfq_derived_source_ready"
)
GOLD_STK_MINS_QFQ_DERIVED_ROW_COUNT_MATCHES_SOURCE_WINDOWS_CHECK = (
    "gold_stk_mins_qfq_derived_row_count_matches_source_windows"
)
GOLD_STK_MINS_QFQ_CONTRACT_CHECK = "gold_stk_mins_qfq_contract_check"
GOLD_STK_MINS_QFQ_KEY_INTEGRITY_CHECK = "gold_stk_mins_qfq_key_integrity_check"
GOLD_STK_MINS_QFQ_VALUE_DOMAIN_CHECK = "gold_stk_mins_qfq_value_domain_check"
GOLD_STK_MINS_QFQ_SOURCE_COVERAGE_CHECK = "gold_stk_mins_qfq_source_coverage_check"
GOLD_STK_MINS_QFQ_DERIVED_SOURCE_COVERAGE_CHECK = (
    "gold_stk_mins_qfq_derived_source_coverage_check"
)

GOLD_STK_MINS_QFQ_BASE_CHECK_NAMES = (
    GOLD_STK_MINS_QFQ_CONTRACT_CHECK,
    GOLD_STK_MINS_QFQ_KEY_INTEGRITY_CHECK,
    GOLD_STK_MINS_QFQ_VALUE_DOMAIN_CHECK,
)

GOLD_STK_MINS_QFQ_NATIVE_CHECK_NAMES = (
    *GOLD_STK_MINS_QFQ_BASE_CHECK_NAMES,
    GOLD_STK_MINS_QFQ_SOURCE_COVERAGE_CHECK,
)

GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES = (
    *GOLD_STK_MINS_QFQ_BASE_CHECK_NAMES,
    GOLD_STK_MINS_QFQ_DERIVED_SOURCE_COVERAGE_CHECK,
)

GOLD_STK_MINS_QFQ_CHECK_NAMES = GOLD_STK_MINS_QFQ_NATIVE_CHECK_NAMES

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
    invalid_trade_adj_factor_row_count: int
    invalid_as_of_adj_factor_row_count: int
    qfq_output_row_count: int
    schema_mismatch_file_count: int
    path_mismatch_row_count: int
    duplicate_key_count: int
    invalid_price_row_count: int
    missing_gold_identity_row_count: int
    unexpected_gold_identity_row_count: int
    exchange_mismatch_row_count: int


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
    missing_gold_identity_row_count: int
    unexpected_gold_identity_row_count: int
    exchange_mismatch_row_count: int


def _missing_file_result(path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            missing_file_paths=[path],
            extra_metadata={
                "summary": "失败：分钟线检查所需的目标文件不存在。",
                "next_action": "先生成或恢复缺失的分钟线文件，再重新运行该 asset/check。",
                "missing_file": True,
            },
        ),
    )


def _missing_input_file_result(path: Path, missing_path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            missing_file_paths=[missing_path],
            extra_metadata={
                "summary": "失败：分钟线检查所需的上游输入文件不存在。",
                "next_action": "先补齐缺失的上游输入，再重新运行当前分钟线 asset/check。",
                "missing_input_file": True,
            },
        ),
    )


def _rule_summary(
    rule_names: Sequence[str],
    failed_rule_names: Sequence[str],
) -> list[dict[str, object]]:
    failed_rule_set = set(failed_rule_names)
    return [
        {"rule_name": rule_name, "passed": rule_name not in failed_rule_set}
        for rule_name in rule_names
    ]


def _readable_check_metadata(
    *,
    dataset_label: str,
    rule_names: Sequence[str],
    failed_rule_names: Sequence[str],
    success_next_action: str,
    failure_next_action: str,
) -> dict[str, object]:
    failed_count = len(failed_rule_names)
    summary = (
        f"通过：{dataset_label} 的 {len(rule_names)} 条质量规则全部通过。"
        if failed_count == 0
        else (
            f"失败：{dataset_label} 有 {failed_count} / {len(rule_names)} "
            "条质量规则未通过。"
        )
    )
    return {
        "summary": summary,
        "next_action": success_next_action if failed_count == 0 else failure_next_action,
        "rule_summary": _rule_summary(rule_names, failed_rule_names),
    }


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
    expected_identity_sql: str,
) -> tuple[Path, ...]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT
          CAST(ts_code AS VARCHAR) AS ts_code,
          strftime(CAST(trade_date AS DATE), '%Y') AS year
        FROM ({expected_identity_sql})
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
    if check_name == GOLD_STK_MINS_QFQ_CONTRACT_CHECK:
        return CheckScope.SCHEMA
    if check_name == GOLD_STK_MINS_QFQ_KEY_INTEGRITY_CHECK:
        return CheckScope.KEY_UNIQUENESS
    if check_name == GOLD_STK_MINS_QFQ_VALUE_DOMAIN_CHECK:
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


def _gold_qfq_identity_coverage_counts_sql(
    *,
    gold_source: str,
    expected_identity_sql: str,
    partition_key: str,
) -> str:
    partition_date_sql = duckdb_string(partition_key)
    return f"""
    WITH gold_rows AS (
      SELECT
        CAST(ts_code AS VARCHAR) AS ts_code,
        CAST(trade_time AS TIMESTAMP) AS trade_time,
        CAST(exchange AS VARCHAR) AS exchange
      FROM {gold_source}
      WHERE CAST(trade_date AS DATE) = CAST({partition_date_sql} AS DATE)
    ),
    expected_rows AS (
      SELECT
        ts_code,
        trade_time,
        exchange
      FROM ({expected_identity_sql})
    ),
    compared_rows AS (
      SELECT
        coalesce(gold_rows.ts_code, expected_rows.ts_code) AS ts_code,
        coalesce(gold_rows.trade_time, expected_rows.trade_time) AS trade_time,
        gold_rows.exchange AS gold_exchange,
        expected_rows.exchange AS expected_exchange,
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
          AND gold_exchange IS DISTINCT FROM expected_exchange
      ) AS exchange_mismatch_row_count
    FROM compared_rows
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
        + counts.invalid_trade_adj_factor_row_count
        + counts.invalid_as_of_adj_factor_row_count
        + abs(counts.silver_row_count - counts.qfq_output_row_count)
    )

    contract_failed_rule_names = []
    if not (
        counts.expected_file_count > 0
        and counts.missing_file_count == 0
        and counts.gold_target_row_count > 0
    ):
        contract_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
        )
    if counts.missing_file_count or counts.schema_mismatch_file_count:
        contract_failed_rule_names.append(GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK)
    if (
        counts.missing_file_count
        or counts.schema_mismatch_file_count
        or counts.path_mismatch_row_count
    ):
        contract_failed_rule_names.append(GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK)

    source_failed_rule_names = []
    if (
        counts.missing_file_count
        or counts.gold_target_row_count != counts.silver_row_count
        or counts.missing_gold_identity_row_count
        or counts.unexpected_gold_identity_row_count
        or counts.exchange_mismatch_row_count
    ):
        source_failed_rule_names.append(GOLD_STK_MINS_QFQ_ROW_COUNT_MATCHES_SILVER_CHECK)
    if factor_coverage_failed_count:
        source_failed_rule_names.append(GOLD_STK_MINS_QFQ_FACTOR_COVERAGE_COMPLETE_CHECK)

    contract_rule_names = (
        GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
        GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
        GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK,
    )
    key_failed_rule_names = (
        []
        if counts.duplicate_key_count == 0
        else [GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK]
    )
    key_readable_failed_rule_names = list(key_failed_rule_names)
    if counts.missing_file_count:
        key_readable_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
        )
    if counts.schema_mismatch_file_count:
        key_readable_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK
        )
    value_failed_rule_names = (
        []
        if counts.invalid_price_row_count == 0
        else [GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK]
    )
    value_readable_failed_rule_names = list(value_failed_rule_names)
    if counts.missing_file_count:
        value_readable_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
        )
    if counts.schema_mismatch_file_count:
        value_readable_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK
        )
    return (
        _check_result(
            passed=not contract_failed_rule_names,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_CONTRACT_CHECK,
            check_scope=CheckScope.SCHEMA,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            missing_file_paths=missing_gold_paths[:GOLD_STK_MINS_QFQ_METADATA_SAMPLE_LIMIT],
            checked_row_count=counts.expected_file_count,
            failed_row_count=len(contract_failed_rule_names),
            extra_metadata={
                **common_metadata,
                "observed_schema": observed_schema,
                "expected_schema": GOLD_STK_MINS_QFQ_COLUMN_TYPES,
                "schema_error": schema_error,
                "path_mismatch_row_count": counts.path_mismatch_row_count,
                "failed_rule_names": contract_failed_rule_names,
                **_readable_check_metadata(
                    dataset_label=f"股票 {freq} 分钟 gold qfq 文件契约",
                    rule_names=contract_rule_names,
                    failed_rule_names=contract_failed_rule_names,
                    success_next_action="无需处理；等待 factor repair 或指标链路消费。",
                    failure_next_action=(
                        "先查看缺失文件、schema 或路径日期/频度不一致，再重新运行 qfq。"
                    ),
                ),
                "failure_samples": samples.get("path_mismatch_samples", []),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.duplicate_key_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_KEY_INTEGRITY_CHECK,
            check_scope=CheckScope.KEY_UNIQUENESS,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.duplicate_key_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failed_rule_names": key_failed_rule_names,
                **_readable_check_metadata(
                    dataset_label=f"股票 {freq} 分钟 gold qfq 主键",
                    rule_names=(
                        GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
                        GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
                        GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
                    ),
                    failed_rule_names=key_readable_failed_rule_names,
                    success_next_action="无需处理；等待 factor repair 或指标链路消费。",
                    failure_next_action=(
                        "先查看 duplicate_samples；若是缺文件或 schema 问题，"
                        "先修复文件契约。"
                    ),
                ),
                "failure_samples": samples.get("duplicate_samples", []),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.invalid_price_row_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_VALUE_DOMAIN_CHECK,
            check_scope=CheckScope.VALUE_SANITY,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.invalid_price_row_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failed_rule_names": value_failed_rule_names,
                **_readable_check_metadata(
                    dataset_label=f"股票 {freq} 分钟 gold qfq 取值",
                    rule_names=(
                        GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK,
                        GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
                        GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
                    ),
                    failed_rule_names=value_readable_failed_rule_names,
                    success_next_action="无需处理；等待 factor repair 或指标链路消费。",
                    failure_next_action=(
                        "先查看 price_samples；若是缺文件或 schema 问题，"
                        "先修复文件契约。"
                    ),
                ),
                "failure_samples": samples.get("price_samples", []),
            },
        ),
        _check_result(
            passed=not source_failed_rule_names,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_SOURCE_COVERAGE_CHECK,
            check_scope=CheckScope.RECONCILIATION,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.silver_row_count,
            failed_row_count=factor_coverage_failed_count
            + abs(counts.gold_target_row_count - counts.silver_row_count)
            + counts.missing_gold_identity_row_count
            + counts.unexpected_gold_identity_row_count
            + counts.exchange_mismatch_row_count
            + counts.missing_file_count,
            extra_metadata={
                **common_metadata,
                "qfq_output_row_count": counts.qfq_output_row_count,
                "missing_trade_adj_factor_row_count": (
                    counts.missing_trade_adj_factor_row_count
                ),
                "missing_as_of_adj_factor_row_count": (
                    counts.missing_as_of_adj_factor_row_count
                ),
                "invalid_trade_adj_factor_row_count": (
                    counts.invalid_trade_adj_factor_row_count
                ),
                "invalid_as_of_adj_factor_row_count": (
                    counts.invalid_as_of_adj_factor_row_count
                ),
                "missing_gold_identity_row_count": (
                    counts.missing_gold_identity_row_count
                ),
                "unexpected_gold_identity_row_count": (
                    counts.unexpected_gold_identity_row_count
                ),
                "exchange_mismatch_row_count": counts.exchange_mismatch_row_count,
                "failed_rule_names": source_failed_rule_names,
                **_readable_check_metadata(
                    dataset_label=f"股票 {freq} 分钟 gold qfq 输入覆盖",
                    rule_names=(
                        GOLD_STK_MINS_QFQ_ROW_COUNT_MATCHES_SILVER_CHECK,
                        GOLD_STK_MINS_QFQ_FACTOR_COVERAGE_COMPLETE_CHECK,
                    ),
                    failed_rule_names=source_failed_rule_names,
                    success_next_action="无需处理；等待 factor repair 或指标链路消费。",
                    failure_next_action=(
                        "先确认 silver 行、当日复权因子和目标 qfq 身份覆盖完整。"
                    ),
                ),
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
    row_count_failed_count = abs(
        counts.gold_target_row_count - counts.generated_window_count
    ) + counts.missing_file_count + counts.incomplete_window_count

    contract_failed_rule_names = []
    if not (
        counts.expected_file_count > 0
        and counts.missing_file_count == 0
        and counts.gold_target_row_count > 0
    ):
        contract_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
        )
    if counts.missing_file_count or counts.schema_mismatch_file_count:
        contract_failed_rule_names.append(GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK)
    if (
        counts.missing_file_count
        or counts.schema_mismatch_file_count
        or counts.path_mismatch_row_count
    ):
        contract_failed_rule_names.append(GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK)

    source_failed_rule_names = []
    if not (
        counts.source_file_count > 0
        and counts.source_row_count > 0
        and counts.source_stock_day_count > 0
    ):
        source_failed_rule_names.append(GOLD_STK_MINS_QFQ_DERIVED_SOURCE_READY_CHECK)
    if (
        counts.missing_file_count
        or counts.schema_mismatch_file_count
        or counts.incomplete_window_count
        or counts.exchange_mismatch_window_count
        or counts.gold_target_row_count != counts.generated_window_count
        or counts.missing_gold_identity_row_count
        or counts.unexpected_gold_identity_row_count
        or counts.exchange_mismatch_row_count
    ):
        source_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_DERIVED_ROW_COUNT_MATCHES_SOURCE_WINDOWS_CHECK
        )

    contract_rule_names = (
        GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
        GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
        GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK,
    )
    key_failed_rule_names = (
        []
        if counts.duplicate_key_count == 0
        else [GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK]
    )
    key_readable_failed_rule_names = list(key_failed_rule_names)
    if counts.missing_file_count:
        key_readable_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
        )
    if counts.schema_mismatch_file_count:
        key_readable_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK
        )
    value_failed_rule_names = (
        []
        if counts.invalid_price_row_count == 0
        else [GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK]
    )
    value_readable_failed_rule_names = list(value_failed_rule_names)
    if counts.missing_file_count:
        value_readable_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
        )
    if counts.schema_mismatch_file_count:
        value_readable_failed_rule_names.append(
            GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK
        )
    return (
        _check_result(
            passed=not contract_failed_rule_names,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_CONTRACT_CHECK,
            check_scope=CheckScope.SCHEMA,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            missing_file_paths=missing_gold_paths[:GOLD_STK_MINS_QFQ_METADATA_SAMPLE_LIMIT],
            checked_row_count=counts.expected_file_count,
            failed_row_count=len(contract_failed_rule_names),
            extra_metadata={
                **common_metadata,
                "observed_schema": observed_schema,
                "expected_schema": GOLD_STK_MINS_QFQ_COLUMN_TYPES,
                "schema_error": schema_error,
                "path_mismatch_row_count": counts.path_mismatch_row_count,
                "failed_rule_names": contract_failed_rule_names,
                **_readable_check_metadata(
                    dataset_label=f"股票 {freq} 分钟 gold qfq 派生文件契约",
                    rule_names=contract_rule_names,
                    failed_rule_names=contract_failed_rule_names,
                    success_next_action="无需处理；等待指标链路消费。",
                    failure_next_action=(
                        "先查看缺失文件、schema 或路径日期/频度不一致，再重新运行派生 qfq。"
                    ),
                ),
                "failure_samples": samples.get("path_mismatch_samples", []),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.duplicate_key_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_KEY_INTEGRITY_CHECK,
            check_scope=CheckScope.KEY_UNIQUENESS,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.duplicate_key_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failed_rule_names": key_failed_rule_names,
                **_readable_check_metadata(
                    dataset_label=f"股票 {freq} 分钟 gold qfq 派生主键",
                    rule_names=(
                        GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
                        GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
                        GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
                    ),
                    failed_rule_names=key_readable_failed_rule_names,
                    success_next_action="无需处理；等待指标链路消费。",
                    failure_next_action=(
                        "先查看 duplicate_samples；若是缺文件或 schema 问题，"
                        "先修复文件契约。"
                    ),
                ),
                "failure_samples": samples.get("duplicate_samples", []),
            },
        ),
        _check_result(
            passed=counts.missing_file_count == 0
            and counts.schema_mismatch_file_count == 0
            and counts.invalid_price_row_count == 0,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_VALUE_DOMAIN_CHECK,
            check_scope=CheckScope.VALUE_SANITY,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.gold_target_row_count,
            failed_row_count=counts.invalid_price_row_count
            + counts.missing_file_count
            + counts.schema_mismatch_file_count,
            extra_metadata={
                **common_metadata,
                "failed_rule_names": value_failed_rule_names,
                **_readable_check_metadata(
                    dataset_label=f"股票 {freq} 分钟 gold qfq 派生取值",
                    rule_names=(
                        GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK,
                        GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
                        GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK,
                    ),
                    failed_rule_names=value_readable_failed_rule_names,
                    success_next_action="无需处理；等待指标链路消费。",
                    failure_next_action=(
                        "先查看 price_samples；若是缺文件或 schema 问题，"
                        "先修复文件契约。"
                    ),
                ),
                "failure_samples": samples.get("price_samples", []),
            },
        ),
        _check_result(
            passed=not source_failed_rule_names,
            asset_key=asset_key,
            check_name=GOLD_STK_MINS_QFQ_DERIVED_SOURCE_COVERAGE_CHECK,
            check_scope=CheckScope.RECONCILIATION,
            file_path=output_root_path,
            input_file_paths=input_file_paths,
            checked_row_count=counts.source_row_count,
            failed_row_count=row_count_failed_count
            + counts.schema_mismatch_file_count
            + counts.exchange_mismatch_window_count
            + counts.missing_gold_identity_row_count
            + counts.unexpected_gold_identity_row_count
            + counts.exchange_mismatch_row_count,
            extra_metadata={
                **common_metadata,
                "failed_rule_names": source_failed_rule_names,
                **_readable_check_metadata(
                    dataset_label=f"股票 {freq} 分钟 gold qfq 派生输入覆盖",
                    rule_names=(
                        GOLD_STK_MINS_QFQ_DERIVED_SOURCE_READY_CHECK,
                        GOLD_STK_MINS_QFQ_DERIVED_ROW_COUNT_MATCHES_SOURCE_WINDOWS_CHECK,
                    ),
                    failed_rule_names=source_failed_rule_names,
                    success_next_action="无需处理；等待指标链路消费。",
                    failure_next_action=(
                        "先确认 source_freq 输入文件、窗口生成数量和 exchange 唯一性。"
                    ),
                ),
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
        missing_gold_identity_row_count = 0
        unexpected_gold_identity_row_count = 0
        exchange_mismatch_row_count = 0
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
                expected_identity_sql = build_daily_qfq_coverage_identities_sql(
                    silver_paths=[silver_path],
                    trade_adj_factor_paths=[trade_adj_factor_path],
                    as_of_adj_factor_paths=[trade_adj_factor_path],
                )
                identity_counts = connection.execute(
                    _gold_qfq_identity_coverage_counts_sql(
                        gold_source=gold_source,
                        expected_identity_sql=expected_identity_sql,
                        partition_key=partition_key,
                    )
                ).fetchone()
                (
                    missing_gold_identity_row_count,
                    unexpected_gold_identity_row_count,
                    exchange_mismatch_row_count,
                ) = (int(value or 0) for value in identity_counts)

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
                invalid_trade_adj_factor_row_count,
                invalid_as_of_adj_factor_row_count,
            ) = (int(value or 0) for value in coverage_counts)
        else:
            qfq_output_row_count = 0
            missing_trade_adj_factor_row_count = silver_row_count
            missing_as_of_adj_factor_row_count = silver_row_count
            invalid_trade_adj_factor_row_count = 0
            invalid_as_of_adj_factor_row_count = 0

    counts = GoldStkMinsQfqCheckCounts(
        silver_row_count=silver_row_count,
        expected_file_count=len(expected_paths),
        existing_file_count=len(existing_gold_paths),
        missing_file_count=len(missing_gold_paths),
        gold_target_row_count=gold_target_row_count,
        missing_trade_adj_factor_row_count=missing_trade_adj_factor_row_count,
        missing_as_of_adj_factor_row_count=missing_as_of_adj_factor_row_count,
        invalid_trade_adj_factor_row_count=invalid_trade_adj_factor_row_count,
        invalid_as_of_adj_factor_row_count=invalid_as_of_adj_factor_row_count,
        qfq_output_row_count=qfq_output_row_count,
        schema_mismatch_file_count=schema_mismatch_count,
        path_mismatch_row_count=path_mismatch_row_count,
        duplicate_key_count=duplicate_key_count,
        invalid_price_row_count=invalid_price_row_count,
        missing_gold_identity_row_count=missing_gold_identity_row_count,
        unexpected_gold_identity_row_count=unexpected_gold_identity_row_count,
        exchange_mismatch_row_count=exchange_mismatch_row_count,
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
    expected_identity_sql = build_gold_stk_mins_qfq_derived_coverage_sql(
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
            expected_identity_sql=expected_identity_sql,
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
        missing_gold_identity_row_count = 0
        unexpected_gold_identity_row_count = 0
        exchange_mismatch_row_count = 0
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

            identity_counts = connection.execute(
                _gold_qfq_identity_coverage_counts_sql(
                    gold_source=gold_source,
                    expected_identity_sql=expected_identity_sql,
                    partition_key=partition_key,
                )
            ).fetchone()
            (
                missing_gold_identity_row_count,
                unexpected_gold_identity_row_count,
                exchange_mismatch_row_count,
            ) = (int(value or 0) for value in identity_counts)

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
        missing_gold_identity_row_count=missing_gold_identity_row_count,
        unexpected_gold_identity_row_count=unexpected_gold_identity_row_count,
        exchange_mismatch_row_count=exchange_mismatch_row_count,
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
    failed_rule_names = (
        [RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK] if failed_count else []
    )
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
            "failed_rule_names": failed_rule_names,
            **_readable_check_metadata(
                dataset_label=f"股票 {freq} 分钟 raw 取值",
                rule_names=(RAW_STK_MINS_PRICE_VOLUME_SANITY_CHECK,),
                failed_rule_names=failed_rule_names,
                success_next_action="无需处理；等待 raw 下游或 silver 标准化消费。",
                failure_next_action=(
                    "先查看 failure_samples，修复空 ts_code、空值或负数行情字段。"
                ),
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


def _raw_contract_check(
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

    failed_rule_names: list[str] = []
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
        if missing_columns or type_mismatches:
            failed_rule_names.append(RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK)

        freq_failed_count = 0
        if "freq" in observed_schema:
            relation = read_parquet(path, hive_partitioning=False)
            freq_failed_count = int(
                connection.execute(
                    f"""
                    SELECT sum(CASE WHEN CAST(freq AS INTEGER) != {freq} THEN 1 ELSE 0 END)
                    FROM {relation}
                    """
                ).fetchone()[0]
                or 0
            )
            if freq_failed_count:
                failed_rule_names.append(RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK)

        date_failed_count = 0
        if "trade_time" in observed_schema:
            relation = read_parquet(path, hive_partitioning=False)
            date_failed_count = int(
                connection.execute(
                    f"""
                    SELECT sum(
                      CASE
                        WHEN CAST(trade_time AS DATE)
                          != CAST({duckdb_string(partition_key)} AS DATE)
                        THEN 1 ELSE 0
                      END
                    )
                    FROM {relation}
                    """
                ).fetchone()[0]
                or 0
            )
            if date_failed_count:
                failed_rule_names.append(RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK)

    if row_count <= 0:
        failed_rule_names.append(RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK)

    failed_rule_names = sorted(set(failed_rule_names))
    rule_names = (
        RAW_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
        RAW_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
        RAW_STK_MINS_FREQ_MATCHES_ASSET_CHECK,
        RAW_STK_MINS_PARTITION_DATE_MATCHES_CHECK,
    )
    return _check_result(
        passed=not failed_rule_names,
        check_scope=CheckScope.SCHEMA,
        file_path=path,
        checked_row_count=row_count,
        failed_row_count=len(failed_rule_names),
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "observed_schema": observed_schema,
            "expected_schema": STK_MINS_RAW_COLUMN_TYPES,
            "missing_columns": missing_columns,
            "type_mismatches": type_mismatches,
            "freq_failed_row_count": freq_failed_count,
            "partition_date_failed_row_count": date_failed_count,
            "failed_rule_names": failed_rule_names,
            **_readable_check_metadata(
                dataset_label=f"股票 {freq} 分钟 raw 契约",
                rule_names=rule_names,
                failed_rule_names=failed_rule_names,
                success_next_action="无需处理；等待 raw 下游或 silver 标准化消费。",
                failure_next_action=(
                    "先查看 failed_rule_names，优先修复缺文件、schema、"
                    "频度或分区日期不一致问题。"
                ),
            ),
        },
    )


def _raw_key_integrity_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _raw_path(lake_root, freq, partition_key)
    registered_keys = set(
        context.instance.get_dynamic_partitions(cn_a_stock_mins_trade_days.name)
    )
    is_registered = partition_key in registered_keys
    if not path.exists():
        failed_rule_names = [RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK]
        if not is_registered:
            failed_rule_names.append(RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK)
        return _check_result(
            passed=False,
            check_scope=CheckScope.KEY_UNIQUENESS,
            file_path=path,
            missing_file_paths=[path],
            checked_row_count=0,
            failed_row_count=1,
            extra_metadata={
                "partition_key": partition_key,
                "freq": freq,
                "partition_set": cn_a_stock_mins_trade_days.name,
                "is_registered": is_registered,
                "failed_rule_names": failed_rule_names,
                **_readable_check_metadata(
                    dataset_label=f"股票 {freq} 分钟 raw 主键",
                    rule_names=(
                        RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
                        RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK,
                    ),
                    failed_rule_names=failed_rule_names,
                    success_next_action="无需处理；等待 raw 下游或 silver 标准化消费。",
                    failure_next_action="先生成缺失 raw 文件，再重新运行主键完整性检查。",
                ),
            },
        )

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
              (SELECT count(*) FROM duplicate_groups) AS duplicate_group_count
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
    duplicate_group_count = int(row[1])
    failed_rule_names = []
    if duplicate_group_count:
        failed_rule_names.append(RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK)
    if not is_registered:
        failed_rule_names.append(RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK)
    rule_names = (
        RAW_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
        RAW_STK_MINS_PARTITION_KEY_REGISTERED_CHECK,
    )

    return _check_result(
        passed=not failed_rule_names,
        check_scope=CheckScope.KEY_UNIQUENESS,
        file_path=path,
        checked_row_count=checked_count,
        failed_row_count=duplicate_group_count + (0 if is_registered else 1),
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "partition_set": cn_a_stock_mins_trade_days.name,
            "is_registered": is_registered,
            "duplicate_group_count": duplicate_group_count,
            "failed_rule_names": failed_rule_names,
            **_readable_check_metadata(
                dataset_label=f"股票 {freq} 分钟 raw 主键",
                rule_names=rule_names,
                failed_rule_names=failed_rule_names,
                success_next_action="无需处理；等待 raw 下游或 silver 标准化消费。",
                failure_next_action=(
                    "先查看 duplicate_group_count、分区注册状态和 failure_samples，"
                    "修复重复 key 或动态分区缺口。"
                ),
            ),
            "failure_samples": _sample_dicts(
                ("ts_code", "trade_time", "duplicate_count"),
                sample_rows,
            ),
        },
    )


def _raw_value_domain_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    return _price_volume_sanity(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        freq=freq,
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
    stock_lifecycle_path = silver_stock_lifecycle_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    if not stock_lifecycle_path.exists():
        return _missing_input_file_result(path, stock_lifecycle_path)

    with connect_configured_duckdb() as connection:
        relation = read_parquet(path, hive_partitioning=False)
        lifecycle_relation = silver_cny_stock_lifecycle_select(stock_lifecycle_path)
        row = connection.execute(
            f"""
            WITH silver_codes AS (
              SELECT DISTINCT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(trade_date AS DATE) AS trade_date
              FROM {relation}
            ),
            stock_lifecycle AS (
              {lifecycle_relation}
            ),
            lifecycle_failures AS (
              SELECT silver_codes.ts_code, silver_codes.trade_date
              FROM silver_codes
              LEFT JOIN stock_lifecycle
                ON stock_lifecycle.ts_code = silver_codes.ts_code
               AND silver_codes.trade_date >= stock_lifecycle.list_date
               AND (
                 stock_lifecycle.delist_date IS NULL
                 OR silver_codes.trade_date < stock_lifecycle.delist_date
               )
              WHERE stock_lifecycle.ts_code IS NULL
            )
            SELECT
              (SELECT count(*) FROM silver_codes) AS checked_count,
              (SELECT count(*) FROM lifecycle_failures) AS failed_count
            """
        ).fetchone()
        sample_rows = connection.execute(
            f"""
            WITH silver_codes AS (
              SELECT DISTINCT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(trade_date AS DATE) AS trade_date
              FROM {relation}
            ),
            stock_lifecycle AS (
              {lifecycle_relation}
            )
            SELECT silver_codes.ts_code, silver_codes.trade_date
            FROM silver_codes
            LEFT JOIN stock_lifecycle
              ON stock_lifecycle.ts_code = silver_codes.ts_code
             AND silver_codes.trade_date >= stock_lifecycle.list_date
             AND (
               stock_lifecycle.delist_date IS NULL
               OR silver_codes.trade_date < stock_lifecycle.delist_date
             )
            WHERE stock_lifecycle.ts_code IS NULL
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
        input_file_paths=[stock_lifecycle_path],
        checked_row_count=checked_count,
        failed_row_count=failed_count,
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "lifecycle_fact_source": "silver_stock_lifecycle",
            "silver_stock_lifecycle_file_path": str(stock_lifecycle_path),
            "checked_code_date_count": checked_count,
            "failed_code_date_count": failed_count,
            "failure_samples": _sample_dicts(("ts_code", "trade_date"), sample_rows),
        },
    )


def _collapsed_silver_check_result(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
    rule_evaluators: Sequence[tuple[str, Any]],
    check_scope: CheckScope,
    check_label: str,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = _silver_path(lake_root, freq, partition_key)
    failed_rule_names: list[str] = []
    for rule_name, evaluator in rule_evaluators:
        result = evaluator(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )
        if not result.passed:
            failed_rule_names.append(rule_name)

    failed_rule_names = sorted(set(failed_rule_names))
    return _check_result(
        passed=not failed_rule_names,
        check_scope=check_scope,
        file_path=path,
        failed_row_count=len(failed_rule_names),
        extra_metadata={
            "partition_key": partition_key,
            "freq": freq,
            "failed_rule_names": failed_rule_names,
            **_readable_check_metadata(
                dataset_label=f"股票 {freq} 分钟 silver {check_label}",
                rule_names=tuple(rule_name for rule_name, _ in rule_evaluators),
                failed_rule_names=failed_rule_names,
                success_next_action="无需处理；等待 qfq、财富成交额等下游消费。",
                failure_next_action=(
                    "先查看 failed_rule_names 中的子规则，再看对应子规则 "
                    "metadata 定位文件、字段或覆盖缺口。"
                ),
            ),
        },
    )


def _silver_contract_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    return _collapsed_silver_check_result(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        freq=freq,
        rule_evaluators=(
            (
                SILVER_STK_MINS_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK,
                _silver_file_exists_and_row_count_positive,
            ),
            (
                SILVER_STK_MINS_SCHEMA_MATCHES_CONTRACT_CHECK,
                _silver_schema_matches_contract,
            ),
            (
                SILVER_STK_MINS_FREQ_AND_PARTITION_MATCH_CHECK,
                _silver_freq_and_partition_match,
            ),
        ),
        check_scope=CheckScope.SCHEMA,
        check_label="文件契约",
    )


def _silver_key_integrity_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    return _collapsed_silver_check_result(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        freq=freq,
        rule_evaluators=(
            (
                SILVER_STK_MINS_UNIQUE_TS_CODE_TRADE_TIME_CHECK,
                _silver_unique_ts_code_trade_time,
            ),
        ),
        check_scope=CheckScope.KEY_UNIQUENESS,
        check_label="主键",
    )


def _silver_value_domain_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    return _collapsed_silver_check_result(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        freq=freq,
        rule_evaluators=(
            (SILVER_STK_MINS_PRICE_SANITY_CHECK, _silver_price_sanity),
            (SILVER_STK_MINS_VOLUME_AMOUNT_SANITY_CHECK, _silver_volume_amount_sanity),
            (
                SILVER_STK_MINS_EXCHANGE_MATCHES_SUFFIX_CHECK,
                _silver_exchange_matches_suffix,
            ),
        ),
        check_scope=CheckScope.VALUE_SANITY,
        check_label="取值",
    )


def _silver_reference_coverage_check(
    *,
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    freq: int,
) -> dg.AssetCheckResult:
    return _collapsed_silver_check_result(
        context=context,
        lake_root=lake_root,
        duckdb=duckdb,
        freq=freq,
        rule_evaluators=(
            (
                SILVER_STK_MINS_CODES_EXIST_IN_STOCK_DAILY_CHECK,
                _silver_codes_exist_in_stock_daily,
            ),
            (
                SILVER_STK_MINS_NO_FULL_DAY_SUSPEND_STRUCTURAL_ROWS_CHECK,
                _silver_no_full_day_suspend_structural_rows,
            ),
            (
                SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
                _silver_name_timeline_covered,
            ),
        ),
        check_scope=CheckScope.REFERENTIAL_INTEGRITY,
        check_label="引用覆盖",
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


def _build_raw_contract_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_CONTRACT_CHECK,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _raw_contract_check(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_raw_key_integrity_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_KEY_INTEGRITY_CHECK,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _raw_key_integrity_check(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_raw_value_domain_check(asset, freq: int):
    @dg.asset_check(
        asset=asset,
        name=RAW_STK_MINS_VALUE_DOMAIN_CHECK,
        blocking=True,
    )
    def _check(
        context: dg.AssetCheckExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.AssetCheckResult:
        return _raw_value_domain_check(
            context=context,
            lake_root=lake_root,
            duckdb=duckdb,
            freq=freq,
        )

    return _check


def _build_raw_stk_mins_checks(asset, freq: int):
    normalized_freq = normalize_stk_mins_freq(freq)
    return (
        _build_raw_contract_check(asset, normalized_freq),
        _build_raw_key_integrity_check(asset, normalized_freq),
        _build_raw_value_domain_check(asset, normalized_freq),
    )


(
    raw_stk_mins_1m_contract_check,
    raw_stk_mins_1m_key_integrity_check,
    raw_stk_mins_1m_value_domain_check,
) = _build_raw_stk_mins_checks(raw_stk_mins_1m, 1)

(
    raw_stk_mins_5m_contract_check,
    raw_stk_mins_5m_key_integrity_check,
    raw_stk_mins_5m_value_domain_check,
) = _build_raw_stk_mins_checks(raw_stk_mins_5m, 5)

(
    raw_stk_mins_15m_contract_check,
    raw_stk_mins_15m_key_integrity_check,
    raw_stk_mins_15m_value_domain_check,
) = _build_raw_stk_mins_checks(raw_stk_mins_15m, 15)

(
    raw_stk_mins_30m_contract_check,
    raw_stk_mins_30m_key_integrity_check,
    raw_stk_mins_30m_value_domain_check,
) = _build_raw_stk_mins_checks(raw_stk_mins_30m, 30)

(
    raw_stk_mins_60m_contract_check,
    raw_stk_mins_60m_key_integrity_check,
    raw_stk_mins_60m_value_domain_check,
) = _build_raw_stk_mins_checks(raw_stk_mins_60m, 60)

RAW_STK_MINS_CHECK_DEFINITIONS = (
    raw_stk_mins_1m_contract_check,
    raw_stk_mins_1m_key_integrity_check,
    raw_stk_mins_1m_value_domain_check,
    raw_stk_mins_5m_contract_check,
    raw_stk_mins_5m_key_integrity_check,
    raw_stk_mins_5m_value_domain_check,
    raw_stk_mins_15m_contract_check,
    raw_stk_mins_15m_key_integrity_check,
    raw_stk_mins_15m_value_domain_check,
    raw_stk_mins_30m_contract_check,
    raw_stk_mins_30m_key_integrity_check,
    raw_stk_mins_30m_value_domain_check,
    raw_stk_mins_60m_contract_check,
    raw_stk_mins_60m_key_integrity_check,
    raw_stk_mins_60m_value_domain_check,
)

assert len(RAW_STK_MINS_CHECK_DEFINITIONS) == len(RAW_STK_MINS_ASSETS) * len(
    RAW_STK_MINS_CHECK_NAMES
)


def _build_silver_check(
    asset,
    freq: int,
    name: str,
    evaluator,
    *,
    additional_deps: Sequence[object] = (),
):
    @dg.asset_check(
        asset=asset,
        name=name,
        blocking=True,
        additional_deps=additional_deps,
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
            SILVER_STK_MINS_CONTRACT_CHECK,
            _silver_contract_check,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_KEY_INTEGRITY_CHECK,
            _silver_key_integrity_check,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_VALUE_DOMAIN_CHECK,
            _silver_value_domain_check,
        ),
        _build_silver_check(
            asset,
            normalized_freq,
            SILVER_STK_MINS_REFERENCE_COVERAGE_CHECK,
            _silver_reference_coverage_check,
            additional_deps=(silver_stock_lifecycle,),
        ),
    )


(
    silver_stk_mins_1m_contract_check,
    silver_stk_mins_1m_key_integrity_check,
    silver_stk_mins_1m_value_domain_check,
    silver_stk_mins_1m_reference_coverage_check,
) = _build_silver_stk_mins_checks(silver_stk_mins_1m, 1)

(
    silver_stk_mins_5m_contract_check,
    silver_stk_mins_5m_key_integrity_check,
    silver_stk_mins_5m_value_domain_check,
    silver_stk_mins_5m_reference_coverage_check,
) = _build_silver_stk_mins_checks(silver_stk_mins_5m, 5)

(
    silver_stk_mins_15m_contract_check,
    silver_stk_mins_15m_key_integrity_check,
    silver_stk_mins_15m_value_domain_check,
    silver_stk_mins_15m_reference_coverage_check,
) = _build_silver_stk_mins_checks(silver_stk_mins_15m, 15)

(
    silver_stk_mins_30m_contract_check,
    silver_stk_mins_30m_key_integrity_check,
    silver_stk_mins_30m_value_domain_check,
    silver_stk_mins_30m_reference_coverage_check,
) = _build_silver_stk_mins_checks(silver_stk_mins_30m, 30)

(
    silver_stk_mins_60m_contract_check,
    silver_stk_mins_60m_key_integrity_check,
    silver_stk_mins_60m_value_domain_check,
    silver_stk_mins_60m_reference_coverage_check,
) = _build_silver_stk_mins_checks(silver_stk_mins_60m, 60)

SILVER_STK_MINS_CHECK_DEFINITIONS = (
    silver_stk_mins_1m_contract_check,
    silver_stk_mins_1m_key_integrity_check,
    silver_stk_mins_1m_value_domain_check,
    silver_stk_mins_1m_reference_coverage_check,
    silver_stk_mins_5m_contract_check,
    silver_stk_mins_5m_key_integrity_check,
    silver_stk_mins_5m_value_domain_check,
    silver_stk_mins_5m_reference_coverage_check,
    silver_stk_mins_15m_contract_check,
    silver_stk_mins_15m_key_integrity_check,
    silver_stk_mins_15m_value_domain_check,
    silver_stk_mins_15m_reference_coverage_check,
    silver_stk_mins_30m_contract_check,
    silver_stk_mins_30m_key_integrity_check,
    silver_stk_mins_30m_value_domain_check,
    silver_stk_mins_30m_reference_coverage_check,
    silver_stk_mins_60m_contract_check,
    silver_stk_mins_60m_key_integrity_check,
    silver_stk_mins_60m_value_domain_check,
    silver_stk_mins_60m_reference_coverage_check,
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
