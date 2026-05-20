from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.assets.stock_daily import raw_tushare_stock_daily, silver_stock_daily
from orchestrator.defs.assets.suspend_d import silver_stock_suspend_daily
from orchestrator.defs.duckdb_sql import (
    STOCK_DAILY_RAW_REQUIRED_COLUMNS,
    STOCK_DAILY_SILVER_REQUIRED_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
    stock_daily_normalized_select,
)
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


STOCK_DAILY_COLUMNS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change_amount",
    "pct_chg",
    "vol",
    "amount",
]


def _column_names(connection, path: Path, *, hive_partitioning: bool = False) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _sample_dicts(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
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
        metadata={
            "path": str(path),
            "missing_file": True,
        },
    )


def _warn_result(passed: bool, metadata: dict[str, Any]) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=metadata,
        severity=dg.AssetCheckSeverity.WARN,
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


@dg.asset_check(
    asset=raw_tushare_stock_daily,
    blocking=True,
)
def raw_stock_daily_file_exists(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    path = raw_stock_daily_path(lake_root.root(), partition_key)
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "exists": path.exists(),
        },
    )


@dg.asset_check(
    asset=raw_tushare_stock_daily,
    blocking=True,
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

    with duckdb.connect() as connection:
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "row_count": int(row_count),
        },
    )


@dg.asset_check(
    asset=raw_tushare_stock_daily,
    blocking=True,
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

    with duckdb.connect() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)

    missing_columns = [column for column in STOCK_DAILY_RAW_REQUIRED_COLUMNS if column not in columns]
    return dg.AssetCheckResult(
        passed=not missing_columns,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "columns": columns,
            "required_columns": list(STOCK_DAILY_RAW_REQUIRED_COLUMNS),
            "missing_columns": missing_columns,
        },
    )


@dg.asset_check(
    asset=raw_tushare_stock_daily,
    blocking=True,
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

    with duckdb.connect() as connection:
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
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "mismatch_count": int(mismatch_count),
            "mismatch_sample_rows": _sample_dicts(["ts_code", "trade_date"], rows),
        },
    )


@dg.asset_check(
    asset=silver_stock_daily,
    blocking=True,
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

    with duckdb.connect() as connection:
        row_count = connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]

    return dg.AssetCheckResult(
        passed=row_count > 0,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "row_count": int(row_count),
        },
    )


@dg.asset_check(
    asset=silver_stock_daily,
    blocking=True,
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
    with duckdb.connect() as connection:
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
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "duplicate_key_count": int(duplicate_key_count),
            "duplicate_sample_keys": _sample_dicts(
                ["ts_code", "trade_date", "row_count"], rows
            ),
        },
    )


@dg.asset_check(
    asset=silver_stock_daily,
    blocking=True,
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

    with duckdb.connect() as connection:
        conflict_key_count = _conflict_key_count(connection, raw_path)
        conflict_sample_keys = _conflict_sample_keys(connection, raw_path)
        conflict_sample_rows = _conflict_sample_rows(connection, raw_path)

    return dg.AssetCheckResult(
        passed=conflict_key_count == 0,
        metadata={
            "raw_path": str(raw_path),
            "partition_key": partition_key,
            "conflict_key_count": conflict_key_count,
            "conflict_sample_keys": conflict_sample_keys,
            "conflict_sample_rows": conflict_sample_rows,
        },
    )


@dg.asset_check(
    asset=silver_stock_daily,
    blocking=True,
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

    with duckdb.connect() as connection:
        columns = _column_names(connection, path, hive_partitioning=False)
        missing_columns = [
            column for column in STOCK_DAILY_SILVER_REQUIRED_COLUMNS if column not in columns
        ]
        if missing_columns:
            return dg.AssetCheckResult(
                passed=False,
                metadata={
                    "path": str(path),
                    "partition_key": partition_key,
                    "columns": columns,
                    "required_columns": list(STOCK_DAILY_SILVER_REQUIRED_COLUMNS),
                    "missing_columns": missing_columns,
                },
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
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "required_non_null_columns": ["ts_code", "trade_date", "pct_chg"],
            "null_row_count": int(null_count),
            "null_sample_rows": _sample_dicts(["ts_code", "trade_date", "pct_chg"], rows),
        },
    )


@dg.asset_check(
    asset=silver_stock_daily,
    blocking=True,
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

    with duckdb.connect() as connection:
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
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "mismatch_count": int(mismatch_count),
            "mismatch_sample_rows": _sample_dicts(["ts_code", "trade_date"], rows),
        },
    )


@dg.asset_check(
    asset=silver_stock_daily,
    blocking=False,
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

    with duckdb.connect() as connection:
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
            LIMIT 10
            """
        ).fetchall()

    return _warn_result(
        passed=anomaly_count == 0,
        metadata={
            "path": str(path),
            "partition_key": partition_key,
            "anomaly_count": int(anomaly_count),
            "anomaly_sample_rows": _sample_dicts(
                ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close"],
                rows,
            ),
        },
    )


@dg.asset_check(
    asset=silver_stock_daily,
    blocking=False,
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

    with duckdb.connect() as connection:
        raw_count = connection.execute(
            count_parquet_query(raw_path, hive_partitioning=False)
        ).fetchone()[0]
        silver_count = connection.execute(
            count_parquet_query(silver_path, hive_partitioning=False)
        ).fetchone()[0]

    return _warn_result(
        passed=silver_count <= raw_count,
        metadata={
            "raw_path": str(raw_path),
            "silver_path": str(silver_path),
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
    basic_path: Path,
    suspend_path: Path,
) -> dict[str, Any]:
    universe_cte = f"""
    WITH listed AS (
      SELECT DISTINCT ts_code
      FROM {read_parquet(basic_path, hive_partitioning=False)}
      WHERE list_date <= DATE '{partition_key}'
        AND (delist_date IS NULL OR delist_date > DATE '{partition_key}')
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
      SELECT DISTINCT ts_code
      FROM {read_parquet(daily_path, hive_partitioning=False)}
      WHERE trade_date = DATE '{partition_key}'
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
    return {
        "daily_path": str(daily_path),
        "stock_basic_path": str(basic_path),
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


@dg.asset_check(
    asset=silver_stock_daily,
    additional_deps=[silver_stock_basic, silver_stock_suspend_daily],
    blocking=False,
)
def silver_stock_daily_row_count_matches_expected_tradable_count(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    daily_path = silver_stock_daily_path(lake_root.root(), partition_key)
    basic_path = silver_stock_basic_path(lake_root.root())
    suspend_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    for path in (daily_path, basic_path, suspend_path):
        if not path.exists():
            return _missing_file_result(path)

    with duckdb.connect() as connection:
        metadata = _expected_tradable_universe_metadata(
            connection,
            partition_key=partition_key,
            daily_path=daily_path,
            basic_path=basic_path,
            suspend_path=suspend_path,
        )

    return _warn_result(
        passed=metadata["daily_count"] == metadata["expected_count"],
        metadata=metadata,
    )


@dg.asset_check(
    asset=silver_stock_daily,
    additional_deps=[silver_stock_basic, silver_stock_suspend_daily],
    blocking=False,
)
def silver_stock_daily_covers_expected_tradable_universe(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    daily_path = silver_stock_daily_path(lake_root.root(), partition_key)
    basic_path = silver_stock_basic_path(lake_root.root())
    suspend_path = silver_stock_suspend_daily_path(lake_root.root(), partition_key)
    for path in (daily_path, basic_path, suspend_path):
        if not path.exists():
            return _missing_file_result(path)

    with duckdb.connect() as connection:
        metadata = _expected_tradable_universe_metadata(
            connection,
            partition_key=partition_key,
            daily_path=daily_path,
            basic_path=basic_path,
            suspend_path=suspend_path,
        )

    return _warn_result(
        passed=(
            metadata["unexplained_missing_count"] == 0
            and metadata["unexplained_extra_count"] == 0
        ),
        metadata=metadata,
    )
