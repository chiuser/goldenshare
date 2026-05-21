import os
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.duckdb_sql import (
    BJ_MARKET_OPEN_DATE,
    STOCK_DAILY_RAW_REQUIRED_COLUMNS,
    STOCK_DAILY_MIN_TRADE_DATE,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
    silver_stock_daily_select,
    stock_daily_normalized_select,
)
from orchestrator.defs.partitions import cn_a_trade_days
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResource
from orchestrator.defs.tushare_api_io import fetch_tushare_partition_to_raw


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

STOCK_DAILY_RAW_COLUMN_TYPES = {
    "ts_code": "VARCHAR",
    "trade_date": "VARCHAR",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "pre_close": "DOUBLE",
    "change": "DOUBLE",
    "pct_chg": "DOUBLE",
    "vol": "DOUBLE",
    "amount": "DOUBLE",
}


def _column_names(connection, path: Path, *, hive_partitioning: bool = False) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(count_parquet_query(path, hive_partitioning=hive_partitioning)).fetchone()[
            0
        ]
    )


def _sample_dicts(columns: list[str], rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


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


def _duplicate_removed_count(connection, raw_path: Path) -> int:
    normalized_sql = stock_daily_normalized_select(raw_path)
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        deduped AS (
          SELECT DISTINCT *
          FROM normalized
        )
        SELECT
          (SELECT count(*) FROM normalized) - (SELECT count(*) FROM deduped)
            AS duplicate_removed_count
        """
    ).fetchone()
    return int(row[0])


def _duplicate_key_count(connection, raw_path: Path) -> int:
    normalized_sql = stock_daily_normalized_select(raw_path)
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        raw_key_counts AS (
          SELECT ts_code, trade_date, count(*) AS raw_row_count
          FROM normalized
          GROUP BY ts_code, trade_date
        ),
        deduped_key_counts AS (
          SELECT ts_code, trade_date, count(*) AS deduped_row_count
          FROM (
            SELECT DISTINCT *
            FROM normalized
          ) deduped
          GROUP BY ts_code, trade_date
        )
        SELECT count(*) AS duplicate_key_count
        FROM raw_key_counts
        INNER JOIN deduped_key_counts
          ON raw_key_counts.ts_code = deduped_key_counts.ts_code
         AND raw_key_counts.trade_date = deduped_key_counts.trade_date
        WHERE raw_key_counts.raw_row_count > deduped_key_counts.deduped_row_count
        """
    ).fetchone()
    return int(row[0])


def _duplicate_sample_rows(connection, raw_path: Path) -> list[dict[str, Any]]:
    normalized_sql = stock_daily_normalized_select(raw_path)
    rows = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        )
        SELECT
          ts_code,
          trade_date,
          open,
          high,
          low,
          close,
          pre_close,
          change_amount,
          pct_chg,
          vol,
          amount,
          count(*) AS duplicate_row_count
        FROM normalized
        GROUP BY
          ts_code,
          trade_date,
          open,
          high,
          low,
          close,
          pre_close,
          change_amount,
          pct_chg,
          vol,
          amount
        HAVING count(*) > 1
        ORDER BY ts_code, trade_date
        LIMIT 10
        """
    ).fetchall()
    return _sample_dicts([*STOCK_DAILY_COLUMNS, "duplicate_row_count"], rows)


def _silver_filter_counts(
    connection,
    raw_path: Path,
    basic_path: Path,
) -> dict[str, int]:
    normalized_sql = stock_daily_normalized_select(raw_path)
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        deduped AS (
          SELECT DISTINCT *
          FROM normalized
        ),
        current_listed AS (
          SELECT DISTINCT ts_code, list_date
          FROM {read_parquet(basic_path, hive_partitioning=False)}
          WHERE list_status = 'L'
        ),
        after_current_listed AS (
          SELECT deduped.*, current_listed.list_date
          FROM deduped
          INNER JOIN current_listed USING (ts_code)
        ),
        after_min_trade_date AS (
          SELECT *
          FROM after_current_listed
          WHERE trade_date >= DATE '{STOCK_DAILY_MIN_TRADE_DATE}'
        ),
        after_list_date AS (
          SELECT *
          FROM after_min_trade_date
          WHERE trade_date >= list_date
        ),
        after_bj_market_open_date AS (
          SELECT *
          FROM after_list_date
          WHERE NOT ends_with(ts_code, '.BJ')
             OR trade_date >= DATE '{BJ_MARKET_OPEN_DATE}'
        )
        SELECT
          (SELECT count(*) FROM normalized) AS raw_normalized_row_count,
          (SELECT count(*) FROM deduped) AS deduped_row_count,
          (SELECT count(*) FROM after_current_listed) AS after_current_listed_count,
          (SELECT count(*) FROM after_min_trade_date) AS after_min_trade_date_count,
          (SELECT count(*) FROM after_list_date) AS after_list_date_count,
          (SELECT count(*) FROM after_bj_market_open_date) AS final_silver_row_count
        """
    ).fetchone()
    (
        raw_normalized_row_count,
        deduped_row_count,
        after_current_listed_count,
        after_min_trade_date_count,
        after_list_date_count,
        final_silver_row_count,
    ) = row
    return {
        "raw_normalized_row_count": int(raw_normalized_row_count),
        "deduped_row_count": int(deduped_row_count),
        "filtered_out_not_current_listed_count": int(
            deduped_row_count - after_current_listed_count
        ),
        "filtered_out_before_2014_count": int(
            after_current_listed_count - after_min_trade_date_count
        ),
        "filtered_out_before_list_date_count": int(
            after_min_trade_date_count - after_list_date_count
        ),
        "filtered_out_bj_before_market_open_count": int(
            after_list_date_count - final_silver_row_count
        ),
        "final_silver_row_count": int(final_silver_row_count),
    }


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


@dg.asset(
    name="raw_tushare_stock_daily",
    partitions_def=cn_a_trade_days,
    group_name="quote",
    description="Tushare stock daily raw partition registered under the new raw lake path.",
)
def raw_tushare_stock_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    metadata = fetch_tushare_partition_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        api_name="daily",
        api_params={"trade_date": partition_key.replace("-", "")},
        fields=STOCK_DAILY_RAW_REQUIRED_COLUMNS,
        column_types=STOCK_DAILY_RAW_COLUMN_TYPES,
        target_path=raw_stock_daily_path(lake_root.root(), partition_key),
        partition_key=partition_key,
        allow_empty=False,
    )

    return dg.MaterializeResult(
        metadata={
            **metadata,
            "partition_key": partition_key,
            "layer": "raw",
            "source_api": "daily",
            "data_contract": "source_mirror",
            "raw_contract": "Tushare daily source mirror: trade_date YYYYMMDD string, field name change.",
            "required_columns": list(STOCK_DAILY_RAW_REQUIRED_COLUMNS),
            "write_summary": "Tushare API rows written to raw parquet with explicit source contract fields.",
        }
    )


@dg.asset(
    name="silver_stock_daily",
    deps=[raw_tushare_stock_daily, silver_stock_basic],
    partitions_def=cn_a_trade_days,
    group_name="quote",
    description="Standardized stock daily quote data derived from Tushare daily raw data.",
)
def silver_stock_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    raw_path = raw_stock_daily_path(lake_root.root(), partition_key)
    basic_path = silver_stock_basic_path(lake_root.root())
    target_path = silver_stock_daily_path(lake_root.root(), partition_key)
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw stock daily file: {raw_path}")
    if not basic_path.exists():
        raise FileNotFoundError(f"Missing silver stock basic file: {basic_path}")

    with duckdb.connect() as connection:
        conflict_key_count = _conflict_key_count(connection, raw_path)
        if conflict_key_count > 0:
            raise dg.Failure(
                description=(
                    "Conflicting stock daily facts found for the same ts_code + trade_date."
                ),
                metadata={
                    "path": str(raw_path),
                    "partition_key": partition_key,
                    "conflict_key_count": conflict_key_count,
                    "conflict_sample_keys": _conflict_sample_keys(connection, raw_path),
                    "conflict_sample_rows": _conflict_sample_rows(connection, raw_path),
                },
            )

        duplicate_removed_count = _duplicate_removed_count(connection, raw_path)
        duplicate_key_count = _duplicate_key_count(connection, raw_path)
        duplicate_sample_rows = _duplicate_sample_rows(connection, raw_path)
        filter_counts = _silver_filter_counts(connection, raw_path, basic_path)

        _replace_parquet_from_query(
            connection,
            silver_stock_daily_select(raw_path, basic_path),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)

    return dg.MaterializeResult(
        metadata={
            "path": str(target_path),
            "raw_path": str(raw_path),
            "stock_basic_path": str(basic_path),
            "row_count": row_count,
            "columns": columns,
            "partition_key": partition_key,
            "layer": "silver",
            "data_contract": "standardized_stock_daily_quote",
            "filter_policy": (
                "Keep current listed stocks only; keep rows on/after list_date; "
                "keep BJ stocks only on/after 2021-11-15; raw remains source mirror."
            ),
            **filter_counts,
            "duplicate_removed_count": duplicate_removed_count,
            "duplicate_key_count": duplicate_key_count,
            "duplicate_sample_rows": duplicate_sample_rows,
            "conflict_key_count": conflict_key_count,
        }
    )
