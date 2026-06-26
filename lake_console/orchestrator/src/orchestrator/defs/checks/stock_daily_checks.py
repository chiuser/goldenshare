from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.assets.stock_daily import (
    raw_tushare_stock_daily,
    silver_stock_daily,
)
from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle
from orchestrator.defs.assets.suspend_d import silver_stock_suspend_daily
from orchestrator.defs.duckdb_sql import (
    BJ_MARKET_OPEN_DATE,
    STOCK_DAILY_RAW_REQUIRED_COLUMNS,
    STOCK_DAILY_SILVER_REQUIRED_COLUMNS,
    STOCK_DAILY_MIN_TRADE_DATE,
    count_parquet_query,
    current_cny_stock_basic_select,
    describe_parquet_query,
    read_parquet,
    silver_cny_stock_lifecycle_select,
    stock_daily_normalized_select,
)
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


STOCK_DAILY_COLUMNS = tuple(STOCK_DAILY_SILVER_REQUIRED_COLUMNS)


def _current_cny_stock_lifecycle_select(silver_stock_basic_path: Path) -> str:
    return f"""
SELECT
  ts_code,
  list_date,
  CAST(NULL AS DATE) AS delist_date
FROM ({current_cny_stock_basic_select(silver_stock_basic_path)}) stock_basic
"""


def _column_names(
    connection, path: Path, *, hive_partitioning: bool = False
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _sample_dicts(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _missing_file_result(path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            extra_metadata={
                "summary": "失败：检查所需的输入文件不存在。",
                "next_action": "先生成或恢复缺失文件，再重新运行该 asset/check。",
                "file_path": str(path),
                "missing_file": True,
            },
        ),
    )


def _warn_result(passed: bool, metadata: dict[str, Any]) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            extra_metadata=metadata,
        ),
        severity=dg.AssetCheckSeverity.WARN,
    )


def _combined_check_result(
    *,
    rule_results: Sequence[tuple[str, dg.AssetCheckResult]],
    check_scope: CheckScope,
) -> dg.AssetCheckResult:
    rule_summary = [
        {"rule_name": rule_name, "passed": bool(result.passed)}
        for rule_name, result in rule_results
    ]
    failed_rule_names = [
        rule_name for rule_name, result in rule_results if not bool(result.passed)
    ]
    summary = (
        f"通过：{len(rule_results)} 条股票日线质量规则全部通过。"
        if not failed_rule_names
        else (
            "失败："
            f"{len(failed_rule_names)} / {len(rule_results)} 条股票日线质量规则未通过。"
        )
    )
    next_action = (
        "无需处理；等待下游消费或下一次更新。"
        if not failed_rule_names
        else "先查看 failed_rule_names 中列出的规则，再看对应子规则 metadata 定位文件、字段或覆盖缺口。"
    )
    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=check_scope,
            extra_metadata={
                "summary": summary,
                "next_action": next_action,
                "rule_summary": rule_summary,
                "rule_passed": {
                    rule_name: bool(result.passed)
                    for rule_name, result in rule_results
                },
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


def _conflict_key_count(connection, raw_path: Path) -> int:
    normalized_sql = stock_daily_normalized_select(raw_path)
    return int(
        connection.execute(
            f"""
            WITH distinct_rows AS (
              SELECT DISTINCT *
              FROM ({normalized_sql}) normalized
            )
            SELECT count(*) AS conflict_key_count
            FROM (
              SELECT ts_code, trade_date
              FROM distinct_rows
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            ) conflict_keys
            """
        ).fetchone()[0]
    )


def _conflict_sample_keys(connection, raw_path: Path) -> list[dict[str, Any]]:
    normalized_sql = stock_daily_normalized_select(raw_path)
    rows = connection.execute(
        f"""
        WITH distinct_rows AS (
          SELECT DISTINCT *
          FROM ({normalized_sql}) normalized
        )
        SELECT ts_code, trade_date, count(*) AS version_count
        FROM distinct_rows
        GROUP BY ts_code, trade_date
        HAVING count(*) > 1
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    return _sample_dicts(["ts_code", "trade_date", "version_count"], rows)


def _conflict_sample_rows(connection, raw_path: Path) -> list[dict[str, Any]]:
    normalized_sql = stock_daily_normalized_select(raw_path)
    rows = connection.execute(
        f"""
        WITH distinct_rows AS (
          SELECT DISTINCT *
          FROM ({normalized_sql}) normalized
        ),
        conflict_keys AS (
          SELECT ts_code, trade_date
          FROM distinct_rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        )
        SELECT
          distinct_rows.ts_code,
          distinct_rows.trade_date,
          distinct_rows.open,
          distinct_rows.high,
          distinct_rows.low,
          distinct_rows.close,
          distinct_rows.pre_close,
          distinct_rows.change_amount,
          distinct_rows.pct_chg,
          distinct_rows.vol,
          distinct_rows.amount
        FROM distinct_rows
        INNER JOIN conflict_keys
          ON distinct_rows.ts_code = conflict_keys.ts_code
         AND distinct_rows.trade_date = conflict_keys.trade_date
        ORDER BY distinct_rows.ts_code, distinct_rows.trade_date
        LIMIT 20
        """
    ).fetchall()
    return _sample_dicts(STOCK_DAILY_COLUMNS, rows)


def raw_stock_daily_file_exists(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_stock_daily_path(lake_root.root(), partition_key)
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "exists": path.exists(),
            },
        ),
    )


def raw_stock_daily_row_count_positive(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "checked_row_count": int(row_count),
            },
        ),
    )


def raw_stock_daily_required_columns(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)

    missing_columns = [
        column for column in STOCK_DAILY_RAW_REQUIRED_COLUMNS if column not in columns
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "observed_columns": columns,
                "required_columns": list(STOCK_DAILY_RAW_REQUIRED_COLUMNS),
                "missing_columns": missing_columns,
            },
        ),
    )


def raw_stock_daily_partition_date_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        mismatch_count = connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE CAST(strptime(trade_date, '%Y%m%d') AS DATE) != DATE '{partition_key}'
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE CAST(strptime(trade_date, '%Y%m%d') AS DATE) != DATE '{partition_key}'
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "mismatch_count": int(mismatch_count),
                "mismatch_sample_rows": _sample_dicts(["ts_code", "trade_date"], rows),
            },
        ),
    )


def _raw_duplicate_key_metadata(
    connection,
    *,
    raw_path: Path,
) -> dict[str, Any]:
    duplicate_sql = f"""
    SELECT ts_code, trade_date, count(*) AS duplicate_row_count
    FROM {read_parquet(raw_path, hive_partitioning=False)}
    GROUP BY ts_code, trade_date
    HAVING count(*) > 1
    """
    duplicate_key_count = int(
        connection.execute(
            f"SELECT count(*) FROM ({duplicate_sql}) duplicate_keys"
        ).fetchone()[0]
    )
    duplicate_extra_row_count = int(
        connection.execute(
            f"""
            SELECT COALESCE(sum(duplicate_row_count - 1), 0)
            FROM ({duplicate_sql}) duplicate_keys
            """
        ).fetchone()[0]
    )
    rows = connection.execute(
        f"""
        {duplicate_sql}
        ORDER BY ts_code, trade_date
        LIMIT 20
        """
    ).fetchall()
    return {
        "duplicate_key_count": duplicate_key_count,
        "duplicate_extra_row_count": duplicate_extra_row_count,
        "duplicate_sample_rows": _sample_dicts(
            ["ts_code", "trade_date", "duplicate_row_count"], rows
        ),
    }


def raw_stock_daily_unique_ts_code_trade_date(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        metadata = _raw_duplicate_key_metadata(connection, raw_path=path)

    return dg.AssetCheckResult(
        passed=metadata["duplicate_key_count"] == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                **metadata,
            },
        ),
    )


def silver_stock_daily_row_count_positive(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "checked_row_count": int(row_count),
            },
        ),
    )


def silver_stock_daily_unique_ts_code_trade_date(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    duplicate_keys_sql = f"""
    SELECT ts_code, trade_date, count(*) AS row_count
    FROM {read_parquet(path, hive_partitioning=False)}
    GROUP BY ts_code, trade_date
    HAVING count(*) > 1
    """
    with connect_configured_duckdb() as connection:
        duplicate_key_count = connection.execute(
            f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            {duplicate_keys_sql}
            ORDER BY ts_code, trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=duplicate_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "duplicate_key_count": int(duplicate_key_count),
                "duplicate_sample_keys": _sample_dicts(
                    ["ts_code", "trade_date", "row_count"], rows
                ),
            },
        ),
    )


def silver_stock_daily_conflicting_duplicate_absent(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    raw_path = raw_stock_daily_path(lake_root.root(), partition_key)
    if not raw_path.exists():
        return _missing_file_result(raw_path)

    with connect_configured_duckdb() as connection:
        conflict_key_count = _conflict_key_count(connection, raw_path)
        conflict_sample_keys = _conflict_sample_keys(connection, raw_path)
        conflict_sample_rows = _conflict_sample_rows(connection, raw_path)

    return dg.AssetCheckResult(
        passed=conflict_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "raw_file_path": str(raw_path),
                "partition_key": partition_key,
                "conflict_key_count": conflict_key_count,
                "conflict_sample_keys": conflict_sample_keys,
                "conflict_sample_rows": conflict_sample_rows,
            },
        ),
    )


def silver_stock_daily_required_columns_non_null(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)
        missing_columns = [
            column
            for column in STOCK_DAILY_SILVER_REQUIRED_COLUMNS
            if column not in columns
        ]
        if missing_columns:
            return dg.AssetCheckResult(
                passed=False,
                metadata=build_check_metadata(
                    check_scope=CheckScope.SCHEMA,
                    extra_metadata={
                        "file_path": str(path),
                        "partition_key": partition_key,
                        "observed_columns": columns,
                        "required_columns": list(STOCK_DAILY_SILVER_REQUIRED_COLUMNS),
                        "missing_columns": missing_columns,
                    },
                ),
            )

        null_count = connection.execute(
            f"""
            SELECT count(*) AS null_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR trim(ts_code) = ''
               OR trade_date IS NULL
               OR pct_chg IS NULL
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, pct_chg
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR trim(ts_code) = ''
               OR trade_date IS NULL
               OR pct_chg IS NULL
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=null_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "required_non_null_columns": ["ts_code", "trade_date", "pct_chg"],
                "null_row_count": int(null_count),
                "null_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date", "pct_chg"], rows
                ),
            },
        ),
    )


def silver_stock_daily_partition_date_matches(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        mismatch_count = connection.execute(
            f"""
            SELECT count(*) AS mismatch_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE trade_date != DATE '{partition_key}'
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE trade_date != DATE '{partition_key}'
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=mismatch_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "mismatch_count": int(mismatch_count),
                "mismatch_sample_rows": _sample_dicts(["ts_code", "trade_date"], rows),
            },
        ),
    )


def silver_stock_daily_stock_lifecycle_covered(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    daily_path = silver_stock_daily_path(lake_root.root(), partition_key)
    lifecycle_path = silver_stock_lifecycle_path(lake_root.root())
    for path in (daily_path, lifecycle_path):
        if not path.exists():
            return _missing_file_result(path)

    stock_lifecycle_sql = silver_cny_stock_lifecycle_select(lifecycle_path)
    with connect_configured_duckdb() as connection:
        lifecycle_uncovered_count = connection.execute(
            f"""
            SELECT count(*) AS lifecycle_uncovered_count
            FROM {read_parquet(daily_path, hive_partitioning=False)} daily
            LEFT JOIN ({stock_lifecycle_sql}) basic
              ON daily.ts_code = basic.ts_code
             AND daily.trade_date >= basic.list_date
             AND (basic.delist_date IS NULL OR daily.trade_date <= basic.delist_date)
            WHERE basic.ts_code IS NULL
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT daily.ts_code, daily.trade_date, basic.list_date, basic.delist_date
            FROM {read_parquet(daily_path, hive_partitioning=False)} daily
            LEFT JOIN ({stock_lifecycle_sql}) basic
              ON daily.ts_code = basic.ts_code
             AND daily.trade_date >= basic.list_date
             AND (basic.delist_date IS NULL OR daily.trade_date <= basic.delist_date)
            WHERE basic.ts_code IS NULL
            ORDER BY daily.ts_code
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=lifecycle_uncovered_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(daily_path),
                "silver_stock_lifecycle_file_path": str(lifecycle_path),
                "partition_key": partition_key,
                "lifecycle_uncovered_count": int(lifecycle_uncovered_count),
                "lifecycle_uncovered_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date", "list_date", "delist_date"], rows
                ),
            },
        ),
    )


def silver_stock_daily_after_list_date_only(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    daily_path = silver_stock_daily_path(lake_root.root(), partition_key)
    lifecycle_path = silver_stock_lifecycle_path(lake_root.root())
    for path in (daily_path, lifecycle_path):
        if not path.exists():
            return _missing_file_result(path)

    stock_lifecycle_sql = silver_cny_stock_lifecycle_select(lifecycle_path)
    with connect_configured_duckdb() as connection:
        before_list_date_count = connection.execute(
            f"""
            SELECT count(*) AS before_list_date_count
            FROM {read_parquet(daily_path, hive_partitioning=False)} daily
            INNER JOIN ({stock_lifecycle_sql}) basic
              ON daily.ts_code = basic.ts_code
            WHERE daily.trade_date < basic.list_date
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT daily.ts_code, daily.trade_date, basic.list_date
            FROM {read_parquet(daily_path, hive_partitioning=False)} daily
            INNER JOIN ({stock_lifecycle_sql}) basic
              ON daily.ts_code = basic.ts_code
            WHERE daily.trade_date < basic.list_date
            ORDER BY daily.ts_code, daily.trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=before_list_date_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(daily_path),
                "silver_stock_lifecycle_file_path": str(lifecycle_path),
                "partition_key": partition_key,
                "before_list_date_count": int(before_list_date_count),
                "before_list_date_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date", "list_date"], rows
                ),
            },
        ),
    )


def silver_stock_daily_bj_after_market_open_only(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        bj_before_open_count = connection.execute(
            f"""
            SELECT count(*) AS bj_before_open_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ends_with(ts_code, '.BJ')
              AND trade_date < DATE '{BJ_MARKET_OPEN_DATE}'
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ends_with(ts_code, '.BJ')
              AND trade_date < DATE '{BJ_MARKET_OPEN_DATE}'
            ORDER BY ts_code, trade_date
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=bj_before_open_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "bj_market_open_date": BJ_MARKET_OPEN_DATE,
                "bj_before_market_open_count": int(bj_before_open_count),
                "bj_before_market_open_sample_rows": _sample_dicts(
                    ["ts_code", "trade_date"], rows
                ),
            },
        ),
    )


def silver_stock_daily_price_sanity(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not path.exists():
        return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        anomaly_count = connection.execute(
            f"""
            SELECT count(*) AS anomaly_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE high < low
               OR open < 0
               OR high < 0
               OR low < 0
               OR close < 0
               OR pre_close < 0
               OR open > high
               OR open < low
               OR close > high
               OR close < low
            """
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT ts_code, trade_date, open, high, low, close, pre_close
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE high < low
               OR open < 0
               OR high < 0
               OR low < 0
               OR close < 0
               OR pre_close < 0
               OR open > high
               OR open < low
               OR close > high
               OR close < low
            LIMIT 10
            """
        ).fetchall()

    return dg.AssetCheckResult(
        passed=anomaly_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "file_path": str(path),
                "partition_key": partition_key,
                "blocking_rules": [
                    "price fields must be non-negative",
                    "high >= low",
                    "high >= open >= low",
                    "high >= close >= low",
                ],
                "anomaly_count": int(anomaly_count),
                "anomaly_sample_rows": _sample_dicts(
                    [
                        "ts_code",
                        "trade_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "pre_close",
                    ],
                    rows,
                ),
            },
        ),
    )


def silver_stock_daily_row_count_not_greater_than_raw(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    raw_path = raw_stock_daily_path(lake_root.root(), partition_key)
    silver_path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not raw_path.exists():
        return _missing_file_result(raw_path)
    if not silver_path.exists():
        return _missing_file_result(silver_path)

    with connect_configured_duckdb() as connection:
        raw_count = connection.execute(
            count_parquet_query(raw_path, hive_partitioning=False)
        ).fetchone()[0]
        silver_count = connection.execute(
            count_parquet_query(silver_path, hive_partitioning=False)
        ).fetchone()[0]

    return _warn_result(
        passed=silver_count <= raw_count,
        metadata={
            "raw_file_path": str(raw_path),
            "silver_file_path": str(silver_path),
            "partition_key": partition_key,
            "raw_count": int(raw_count),
            "silver_count": int(silver_count),
            "diff_count": int(silver_count - raw_count),
        },
    )


def _expected_tradable_universe_metadata(
    connection,
    *,
    partition_key: str,
    daily_path: Path,
    stock_lifecycle_path: Path,
    stock_lifecycle_sql: str,
    suspend_path: Path,
    daily_code_set_sql: str,
) -> dict[str, Any]:
    universe_cte = f"""
    WITH listed AS (
      SELECT DISTINCT ts_code
      FROM ({stock_lifecycle_sql}) stock_lifecycle
      WHERE DATE '{partition_key}' >= DATE '{STOCK_DAILY_MIN_TRADE_DATE}'
        AND list_date <= DATE '{partition_key}'
        AND (
          delist_date IS NULL
          OR DATE '{partition_key}' <= delist_date
        )
        AND (
          NOT ends_with(ts_code, '.BJ')
          OR DATE '{partition_key}' >= DATE '{BJ_MARKET_OPEN_DATE}'
        )
    ),
    full_day_suspended AS (
      SELECT DISTINCT suspend.ts_code
      FROM {read_parquet(suspend_path, hive_partitioning=False)} suspend
      INNER JOIN listed USING (ts_code)
      WHERE suspend.trade_date = DATE '{partition_key}'
        AND suspend.suspend_type = 'S'
        AND suspend.suspend_timing IS NULL
    ),
    intraday_suspended AS (
      SELECT DISTINCT
        suspend.ts_code,
        suspend.suspend_type,
        suspend.suspend_timing
      FROM {read_parquet(suspend_path, hive_partitioning=False)} suspend
      INNER JOIN listed USING (ts_code)
      WHERE suspend.trade_date = DATE '{partition_key}'
        AND suspend.suspend_type = 'S'
        AND suspend.suspend_timing IS NOT NULL
    ),
    expected AS (
      SELECT ts_code
      FROM listed
      EXCEPT
      SELECT ts_code
      FROM full_day_suspended
    ),
    daily AS (
      {daily_code_set_sql}
    ),
    missing AS (
      SELECT expected.ts_code
      FROM expected
      LEFT JOIN daily USING (ts_code)
      WHERE daily.ts_code IS NULL
    ),
    extra AS (
      SELECT daily.ts_code
      FROM daily
      LEFT JOIN expected USING (ts_code)
      WHERE expected.ts_code IS NULL
    )
    """
    counts = connection.execute(
        f"""
        {universe_cte}
        SELECT
          (SELECT count(*) FROM listed) AS listed_count,
          (SELECT count(*) FROM full_day_suspended) AS full_day_suspend_count,
          (SELECT count(*) FROM intraday_suspended) AS intraday_suspend_count,
          (SELECT count(*) FROM expected) AS expected_count,
          (SELECT count(*) FROM daily) AS daily_count,
          (SELECT count(*) FROM missing) AS unexplained_missing_count,
          (SELECT count(*) FROM extra) AS unexplained_extra_count
        """
    ).fetchone()
    missing_rows = connection.execute(
        f"""
        {universe_cte}
        SELECT ts_code
        FROM missing
        ORDER BY ts_code
        LIMIT 20
        """
    ).fetchall()
    extra_rows = connection.execute(
        f"""
        {universe_cte}
        SELECT ts_code
        FROM extra
        ORDER BY ts_code
        LIMIT 20
        """
    ).fetchall()
    full_day_suspend_rows = connection.execute(
        f"""
        {universe_cte}
        SELECT ts_code
        FROM full_day_suspended
        ORDER BY ts_code
        LIMIT 20
        """
    ).fetchall()
    intraday_suspend_rows = connection.execute(
        f"""
        {universe_cte}
        SELECT ts_code, suspend_type, suspend_timing
        FROM intraday_suspended
        ORDER BY ts_code, suspend_timing
        LIMIT 20
        """
    ).fetchall()

    (
        listed_count,
        full_day_suspend_count,
        intraday_suspend_count,
        expected_count,
        daily_count,
        unexplained_missing_count,
        unexplained_extra_count,
    ) = counts
    summary = (
        "通过：股票日线代码覆盖与应交易股票集合一致。"
        if unexplained_missing_count == 0 and unexplained_extra_count == 0
        else (
            "失败：股票日线代码覆盖与应交易股票集合不一致，"
            f"缺失 {int(unexplained_missing_count)} 个，额外 {int(unexplained_extra_count)} 个。"
        )
    )
    next_action = (
        "无需处理；全日停牌已作为合理缺席解释。"
        if unexplained_missing_count == 0 and unexplained_extra_count == 0
        else "先查看 missing/extra 样本；缺失通常需要补 raw 源数据，额外通常需要核对生命周期或停复牌事实。"
    )
    return {
        "summary": summary,
        "next_action": next_action,
        "tradable_universe_summary": {
            "expected_count": int(expected_count),
            "actual_count": int(daily_count),
            "unexplained_missing_count": int(unexplained_missing_count),
            "unexplained_extra_count": int(unexplained_extra_count),
            "explained_by_full_day_suspend_count": int(full_day_suspend_count),
        },
        "daily_path": str(daily_path),
        "stock_lifecycle_file_path": str(stock_lifecycle_path),
        "stock_suspend_daily_path": str(suspend_path),
        "trade_date": partition_key,
        "listed_count": int(listed_count),
        "full_day_suspend_count": int(full_day_suspend_count),
        "explained_by_full_day_suspend_count": int(full_day_suspend_count),
        "intraday_suspend_count": int(intraday_suspend_count),
        "expected_count": int(expected_count),
        "daily_count": int(daily_count),
        "diff_count": int(daily_count - expected_count),
        "unexplained_missing_count": int(unexplained_missing_count),
        "unexplained_extra_count": int(unexplained_extra_count),
        "missing_sample_ts_codes": [row[0] for row in missing_rows],
        "extra_sample_ts_codes": [row[0] for row in extra_rows],
        "full_day_suspend_sample_ts_codes": [row[0] for row in full_day_suspend_rows],
        "intraday_suspend_sample_rows": _sample_dicts(
            ["ts_code", "suspend_type", "suspend_timing"], intraday_suspend_rows
        ),
    }


def _raw_daily_code_set_sql(raw_path: Path, partition_key: str) -> str:
    return f"""
      SELECT DISTINCT ts_code
      FROM {read_parquet(raw_path, hive_partitioning=False)}
      WHERE CAST(strptime(trade_date, '%Y%m%d') AS DATE) = DATE '{partition_key}'
    """


def _silver_daily_code_set_sql(daily_path: Path, partition_key: str) -> str:
    return f"""
      SELECT DISTINCT ts_code
      FROM {read_parquet(daily_path, hive_partitioning=False)}
      WHERE trade_date = DATE '{partition_key}'
    """


def raw_stock_daily_row_count_matches_expected_tradable_count(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    daily_path = raw_stock_daily_path(lake_root.root(), partition_key)
    basic_path = silver_stock_basic_path(lake_root.root())
    suspend_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    for path in (daily_path, basic_path, suspend_path):
        if not path.exists():
            return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        metadata = _expected_tradable_universe_metadata(
            connection,
            partition_key=partition_key,
            daily_path=daily_path,
            stock_lifecycle_path=basic_path,
            stock_lifecycle_sql=_current_cny_stock_lifecycle_select(basic_path),
            suspend_path=suspend_path,
            daily_code_set_sql=_raw_daily_code_set_sql(daily_path, partition_key),
        )

    return dg.AssetCheckResult(
        passed=metadata["daily_count"] == metadata["expected_count"],
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            extra_metadata=metadata,
        ),
    )


def raw_stock_daily_covers_expected_tradable_universe(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    daily_path = raw_stock_daily_path(lake_root.root(), partition_key)
    basic_path = silver_stock_basic_path(lake_root.root())
    suspend_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    for path in (daily_path, basic_path, suspend_path):
        if not path.exists():
            return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        metadata = _expected_tradable_universe_metadata(
            connection,
            partition_key=partition_key,
            daily_path=daily_path,
            stock_lifecycle_path=basic_path,
            stock_lifecycle_sql=_current_cny_stock_lifecycle_select(basic_path),
            suspend_path=suspend_path,
            daily_code_set_sql=_raw_daily_code_set_sql(daily_path, partition_key),
        )

    return dg.AssetCheckResult(
        passed=(
            metadata["unexplained_missing_count"] == 0
            and metadata["unexplained_extra_count"] == 0
        ),
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            extra_metadata=metadata,
        ),
    )


def silver_stock_daily_row_count_matches_expected_tradable_count(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    daily_path = silver_stock_daily_path(lake_root.root(), partition_key)
    lifecycle_path = silver_stock_lifecycle_path(lake_root.root())
    suspend_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    for path in (daily_path, lifecycle_path, suspend_path):
        if not path.exists():
            return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        metadata = _expected_tradable_universe_metadata(
            connection,
            partition_key=partition_key,
            daily_path=daily_path,
            stock_lifecycle_path=lifecycle_path,
            stock_lifecycle_sql=silver_cny_stock_lifecycle_select(lifecycle_path),
            suspend_path=suspend_path,
            daily_code_set_sql=_silver_daily_code_set_sql(daily_path, partition_key),
        )

    return _warn_result(
        passed=metadata["daily_count"] == metadata["expected_count"],
        metadata=metadata,
    )


def silver_stock_daily_covers_expected_tradable_universe(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    daily_path = silver_stock_daily_path(lake_root.root(), partition_key)
    lifecycle_path = silver_stock_lifecycle_path(lake_root.root())
    suspend_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    for path in (daily_path, lifecycle_path, suspend_path):
        if not path.exists():
            return _missing_file_result(path)

    with connect_configured_duckdb() as connection:
        metadata = _expected_tradable_universe_metadata(
            connection,
            partition_key=partition_key,
            daily_path=daily_path,
            stock_lifecycle_path=lifecycle_path,
            stock_lifecycle_sql=silver_cny_stock_lifecycle_select(lifecycle_path),
            suspend_path=suspend_path,
            daily_code_set_sql=_silver_daily_code_set_sql(daily_path, partition_key),
        )

    return dg.AssetCheckResult(
        passed=(
            metadata["unexplained_missing_count"] == 0
            and metadata["unexplained_extra_count"] == 0
        ),
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            extra_metadata=metadata,
        ),
    )


@dg.asset_check(asset=raw_tushare_stock_daily, blocking=True)
def raw_stock_daily_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.SCHEMA,
        rule_results=(
            ("raw_stock_daily_file_exists", raw_stock_daily_file_exists(context, lake_root)),
            (
                "raw_stock_daily_row_count_positive",
                raw_stock_daily_row_count_positive(context, lake_root, duckdb),
            ),
            (
                "raw_stock_daily_required_columns",
                raw_stock_daily_required_columns(context, lake_root, duckdb),
            ),
            (
                "raw_stock_daily_partition_date_matches",
                raw_stock_daily_partition_date_matches(context, lake_root, duckdb),
            ),
        ),
    )


@dg.asset_check(asset=raw_tushare_stock_daily, blocking=True)
def raw_stock_daily_key_integrity_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return raw_stock_daily_unique_ts_code_trade_date(context, lake_root, duckdb)


@dg.asset_check(
    asset=raw_tushare_stock_daily,
    additional_deps=[silver_stock_basic, silver_stock_suspend_daily],
    blocking=True,
)
def raw_stock_daily_tradable_universe_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.VALUE_SANITY,
        rule_results=(
            (
                "raw_stock_daily_row_count_matches_expected_tradable_count",
                raw_stock_daily_row_count_matches_expected_tradable_count(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
            (
                "raw_stock_daily_covers_expected_tradable_universe",
                raw_stock_daily_covers_expected_tradable_universe(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
        ),
    )


@dg.asset_check(asset=silver_stock_daily, blocking=True)
def silver_stock_daily_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.SCHEMA,
        rule_results=(
            (
                "silver_stock_daily_row_count_positive",
                silver_stock_daily_row_count_positive(context, lake_root, duckdb),
            ),
            (
                "silver_stock_daily_required_columns_non_null",
                silver_stock_daily_required_columns_non_null(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
            (
                "silver_stock_daily_partition_date_matches",
                silver_stock_daily_partition_date_matches(context, lake_root, duckdb),
            ),
        ),
    )


@dg.asset_check(asset=silver_stock_daily, blocking=True)
def silver_stock_daily_key_integrity_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.KEY_UNIQUENESS,
        rule_results=(
            (
                "silver_stock_daily_unique_ts_code_trade_date",
                silver_stock_daily_unique_ts_code_trade_date(context, lake_root, duckdb),
            ),
            (
                "silver_stock_daily_conflicting_duplicate_absent",
                silver_stock_daily_conflicting_duplicate_absent(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
        ),
    )


@dg.asset_check(asset=silver_stock_daily, blocking=True)
def silver_stock_daily_value_domain_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.VALUE_SANITY,
        rule_results=(
            (
                "silver_stock_daily_bj_after_market_open_only",
                silver_stock_daily_bj_after_market_open_only(
                    context,
                    lake_root,
                    duckdb,
                ),
            ),
            (
                "silver_stock_daily_price_sanity",
                silver_stock_daily_price_sanity(context, lake_root, duckdb),
            ),
        ),
    )


@dg.asset_check(
    asset=silver_stock_daily,
    additional_deps=[silver_stock_lifecycle],
    blocking=True,
)
def silver_stock_daily_lifecycle_coverage_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.REFERENTIAL_INTEGRITY,
        rule_results=(
            (
                "silver_stock_daily_stock_lifecycle_covered",
                silver_stock_daily_stock_lifecycle_covered(context, lake_root, duckdb),
            ),
            (
                "silver_stock_daily_after_list_date_only",
                silver_stock_daily_after_list_date_only(context, lake_root, duckdb),
            ),
        ),
    )


@dg.asset_check(
    asset=silver_stock_daily,
    additional_deps=[silver_stock_lifecycle, silver_stock_suspend_daily],
    blocking=True,
)
def silver_stock_daily_tradable_universe_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return silver_stock_daily_covers_expected_tradable_universe(
        context,
        lake_root,
        duckdb,
    )
