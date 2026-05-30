from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.stk_mins import (
    RAW_STK_MINS_ASSETS,
    STK_MINS_RAW_COLUMN_TYPES,
    raw_stk_mins_1m,
    raw_stk_mins_5m,
    raw_stk_mins_15m,
    raw_stk_mins_30m,
    raw_stk_mins_60m,
)
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import raw_stk_mins_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.stk_mins import normalize_stk_mins_freq


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


def _check_result(
    *,
    passed: bool,
    check_scope: CheckScope,
    file_path: Path | None = None,
    checked_row_count: int | None = None,
    failed_row_count: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=check_scope,
            checked_row_count=checked_row_count,
            failed_row_count=failed_row_count,
            file_path=file_path,
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

    with duckdb.connect() as connection:
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

    with duckdb.connect() as connection:
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

    with duckdb.connect() as connection:
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

    with duckdb.connect() as connection:
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

    with duckdb.connect() as connection:
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

    with duckdb.connect() as connection:
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
