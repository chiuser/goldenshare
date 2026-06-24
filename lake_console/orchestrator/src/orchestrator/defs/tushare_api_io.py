import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource
from orchestrator.defs.run_contracts.configs import (
    MAX_STOCK_DAILY_MISSING_CODE_REPAIR_COUNT,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata


TUSHARE_API_SOURCE_METHOD = "tushare_api"
TUSHARE_API_PAGE_LIMIT = 6000


def fetch_tushare_partition_to_raw(
    *,
    tushare: TushareResource,
    duckdb: DuckDBResource,
    api_name: str,
    api_params: Mapping[str, Any],
    fields: Sequence[str],
    column_types: Mapping[str, str],
    target_path: Path,
    partition_key: str,
    allow_empty: bool,
    limit: int = TUSHARE_API_PAGE_LIMIT,
) -> dict[str, Any]:
    field_names = tuple(fields)
    _validate_contract(field_names, column_types)

    rows, page_count = _fetch_all_pages(
        tushare=tushare,
        api_name=api_name,
        api_params=api_params,
        field_names=field_names,
        limit=limit,
    )

    if not allow_empty and not rows:
        raise RuntimeError(
            f"Tushare {api_name} returned 0 rows for partition {partition_key}; "
            "raw source mirror will not write an empty file for this asset."
        )

    _write_rows_to_parquet(
        duckdb=duckdb,
        rows=rows,
        fields=field_names,
        column_types=column_types,
        target_path=target_path,
    )

    return build_materialization_metadata(
        uri=target_path,
        row_count=len(rows),
        observed_columns=field_names,
        extra_metadata={
            "source_method": TUSHARE_API_SOURCE_METHOD,
            "params": dict(api_params),
            "fields": list(field_names),
            "page_count": page_count,
            "limit": limit,
            "partition_key": partition_key,
        },
    )


def fetch_tushare_stock_daily_missing_codes_to_raw(
    *,
    tushare: TushareResource,
    duckdb: DuckDBResource,
    ts_codes: Sequence[str],
    fields: Sequence[str],
    column_types: Mapping[str, str],
    target_path: Path,
    partition_key: str,
    missing_codes_hash: str,
    repair_attempt: int,
    limit: int = TUSHARE_API_PAGE_LIMIT,
) -> dict[str, Any]:
    field_names = tuple(fields)
    _validate_contract(field_names, column_types)
    requested_codes = tuple(str(code).strip().upper() for code in ts_codes)
    if not requested_codes:
        raise ValueError("stock_daily missing-code repair requires at least one ts_code.")
    if any(not code for code in requested_codes):
        raise ValueError("stock_daily missing-code repair ts_codes must be non-empty.")
    duplicate_codes = sorted(
        {
            ts_code
            for ts_code in requested_codes
            if requested_codes.count(ts_code) > 1
        }
    )
    if duplicate_codes:
        raise ValueError(
            "stock_daily missing-code repair ts_codes must not contain duplicates: "
            f"{duplicate_codes}."
        )
    if len(requested_codes) > MAX_STOCK_DAILY_MISSING_CODE_REPAIR_COUNT:
        raise ValueError(
            "stock_daily missing-code repair ts_codes must not contain more than "
            f"{MAX_STOCK_DAILY_MISSING_CODE_REPAIR_COUNT} codes."
        )
    if not target_path.exists():
        raise FileNotFoundError(
            f"Missing raw stock daily file for repair: {target_path}"
        )

    compact_trade_date = partition_key.replace("-", "")
    api_params = {
        "trade_date": compact_trade_date,
        "ts_code": ",".join(requested_codes),
        "limit": limit,
        "offset": 0,
    }
    result = tushare.call("daily", api_params, field_names)
    rows = result.rows
    if result.columns != field_names and (result.columns or rows):
        raise RuntimeError(
            f"Tushare daily returned columns {list(result.columns)}, "
            f"expected {list(field_names)}."
        )
    if not rows:
        raise RuntimeError(
            "Tushare daily returned 0 rows for stock_daily missing-code repair: "
            f"partition_key={partition_key}, requested_code_count={len(requested_codes)}."
        )

    staging_path = target_path.with_name(
        f"{target_path.name}.repair-{missing_codes_hash[:16]}-{repair_attempt}.parquet"
    )
    if staging_path.exists():
        raise RuntimeError(f"Stock daily repair staging file already exists: {staging_path}")

    try:
        _write_rows_to_parquet(
            duckdb=duckdb,
            rows=rows,
            fields=field_names,
            column_types=column_types,
            target_path=staging_path,
        )
        fetched_row_count, fetched_code_count = _validate_stock_daily_repair_staging(
            staging_path=staging_path,
            requested_codes=requested_codes,
            compact_trade_date=compact_trade_date,
        )
        output_row_count = _merge_stock_daily_repair_staging(
            target_path=target_path,
            staging_path=staging_path,
            requested_codes=requested_codes,
            compact_trade_date=compact_trade_date,
            fields=field_names,
            column_types=column_types,
        )
    except Exception:
        raise
    else:
        try:
            staging_path.unlink()
        except FileNotFoundError:
            pass

    return build_materialization_metadata(
        uri=target_path,
        row_count=output_row_count,
        observed_columns=field_names,
        extra_metadata={
            "source_method": TUSHARE_API_SOURCE_METHOD,
            "params": api_params,
            "fields": list(field_names),
            "limit": limit,
            "partition_key": partition_key,
            "write_mode": "missing_code_repair",
            "missing_codes_hash": missing_codes_hash,
            "repair_attempt": repair_attempt,
            "requested_code_count": len(requested_codes),
            "fetched_row_count": fetched_row_count,
            "fetched_code_count": fetched_code_count,
            "merged_row_count": output_row_count,
        },
    )


def fetch_tushare_full_file_to_raw(
    *,
    tushare: TushareResource,
    duckdb: DuckDBResource,
    api_name: str,
    api_params: Mapping[str, Any],
    fields: Sequence[str],
    column_types: Mapping[str, str],
    target_path: Path,
    allow_empty: bool,
    limit: int = TUSHARE_API_PAGE_LIMIT,
) -> dict[str, Any]:
    field_names = tuple(fields)
    _validate_contract(field_names, column_types)

    rows, page_count = _fetch_all_pages(
        tushare=tushare,
        api_name=api_name,
        api_params=api_params,
        field_names=field_names,
        limit=limit,
    )

    if not allow_empty and not rows:
        raise RuntimeError(
            f"Tushare {api_name} returned 0 rows; raw source mirror will not write "
            "an empty full-file asset."
        )

    _write_rows_to_parquet(
        duckdb=duckdb,
        rows=rows,
        fields=field_names,
        column_types=column_types,
        target_path=target_path,
    )

    return build_materialization_metadata(
        uri=target_path,
        row_count=len(rows),
        observed_columns=field_names,
        extra_metadata={
            "source_method": TUSHARE_API_SOURCE_METHOD,
            "params": dict(api_params),
            "fields": list(field_names),
            "page_count": page_count,
            "limit": limit,
        },
    )


def fetch_tushare_full_file_distinct_to_raw(
    *,
    tushare: TushareResource,
    duckdb: DuckDBResource,
    api_name: str,
    api_params: Mapping[str, Any],
    fields: Sequence[str],
    column_types: Mapping[str, str],
    target_path: Path,
    allow_empty: bool,
    limit: int = TUSHARE_API_PAGE_LIMIT,
) -> dict[str, Any]:
    field_names = tuple(fields)
    _validate_contract(field_names, column_types)

    rows, page_count = _fetch_all_pages(
        tushare=tushare,
        api_name=api_name,
        api_params=api_params,
        field_names=field_names,
        limit=limit,
    )

    if not allow_empty and not rows:
        raise RuntimeError(
            f"Tushare {api_name} returned 0 rows; raw source mirror will not write "
            "an empty full-file asset."
        )

    row_count = _write_distinct_rows_to_parquet(
        duckdb=duckdb,
        rows=rows,
        fields=field_names,
        column_types=column_types,
        target_path=target_path,
    )
    if not allow_empty and row_count == 0:
        raise RuntimeError(
            f"Tushare {api_name} returned 0 distinct rows; raw source mirror will not "
            "write an empty full-file asset."
        )

    return build_materialization_metadata(
        uri=target_path,
        row_count=row_count,
        observed_columns=field_names,
        extra_metadata={
            "source_method": TUSHARE_API_SOURCE_METHOD,
            "params": dict(api_params),
            "fields": list(field_names),
            "page_count": page_count,
            "limit": limit,
            "source_row_count": len(rows),
            "duplicate_removed_count": len(rows) - row_count,
        },
    )


def _validate_stock_daily_repair_staging(
    *,
    staging_path: Path,
    requested_codes: tuple[str, ...],
    compact_trade_date: str,
) -> tuple[int, int]:
    requested_values = ", ".join(duckdb_string(code) for code in requested_codes)
    staging_query = read_parquet(staging_path, hive_partitioning=False)
    with connect_configured_duckdb() as connection:
        mismatch_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS mismatch_count
                FROM {staging_query}
                WHERE CAST(ts_code AS VARCHAR) NOT IN ({requested_values})
                   OR CAST(trade_date AS VARCHAR) != {duckdb_string(compact_trade_date)}
                """
            ).fetchone()[0]
        )
        if mismatch_count:
            raise RuntimeError(
                "Tushare daily returned rows outside the requested stock_daily repair "
                f"window: trade_date={compact_trade_date}, mismatch_count={mismatch_count}."
            )
        fetched_row_count = int(
            connection.execute(
                count_parquet_query(staging_path, hive_partitioning=False)
            ).fetchone()[0]
        )
        fetched_code_count = int(
            connection.execute(
                f"""
                SELECT count(DISTINCT CAST(ts_code AS VARCHAR)) AS fetched_code_count
                FROM {staging_query}
                """
            ).fetchone()[0]
        )
    return fetched_row_count, fetched_code_count


def _merge_stock_daily_repair_staging(
    *,
    target_path: Path,
    staging_path: Path,
    requested_codes: tuple[str, ...],
    compact_trade_date: str,
    fields: tuple[str, ...],
    column_types: Mapping[str, str],
) -> int:
    requested_values = ", ".join(duckdb_string(code) for code in requested_codes)
    select_sql = ", ".join(
        f"CAST({_quote_identifier(field)} AS {column_types[field]}) AS {_quote_identifier(field)}"
        for field in fields
    )
    target_query = read_parquet(target_path, hive_partitioning=False, union_by_name=True)
    staging_query = read_parquet(staging_path, hive_partitioning=False)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    output_sql = f"""
    WITH existing_rows AS (
      SELECT {select_sql}
      FROM {target_query}
      WHERE NOT (
        CAST(ts_code AS VARCHAR) IN ({requested_values})
        AND CAST(trade_date AS VARCHAR) = {duckdb_string(compact_trade_date)}
      )
    ),
    fetched_rows AS (
      SELECT {select_sql}
      FROM {staging_query}
    ),
    combined_rows AS (
      SELECT * FROM existing_rows
      UNION ALL
      SELECT * FROM fetched_rows
    )
    SELECT DISTINCT *
    FROM combined_rows
    ORDER BY ts_code, trade_date
    """
    with connect_configured_duckdb() as connection:
        connection.execute(copy_query_to_parquet(output_sql, temporary_path))
        output_row_count = int(
            connection.execute(
                count_parquet_query(temporary_path, hive_partitioning=False)
            ).fetchone()[0]
        )

    os.replace(temporary_path, target_path)
    return output_row_count


def _fetch_all_pages(
    *,
    tushare: TushareResource,
    api_name: str,
    api_params: Mapping[str, Any],
    field_names: tuple[str, ...],
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    page_count = 0
    offset = 0
    while True:
        page_params = {**dict(api_params), "limit": limit, "offset": offset}
        result = tushare.call(api_name, page_params, field_names)
        page_rows = result.rows
        if result.columns != field_names and (result.columns or page_rows):
            raise RuntimeError(
                f"Tushare {api_name} returned columns {list(result.columns)}, "
                f"expected {list(field_names)}."
            )

        rows.extend(page_rows)
        page_count += 1
        if len(page_rows) < limit:
            break
        offset += limit

    return rows, page_count


def _validate_contract(
    fields: tuple[str, ...], column_types: Mapping[str, str]
) -> None:
    if not fields:
        raise ValueError("Tushare raw fields must be explicit.")
    missing_types = [field for field in fields if field not in column_types]
    if missing_types:
        raise ValueError(f"Missing DuckDB column types for fields: {missing_types}")
    extra_types = [field for field in column_types if field not in fields]
    if extra_types:
        raise ValueError(f"Unexpected DuckDB column types for fields: {extra_types}")


def _write_rows_to_parquet(
    *,
    duckdb: DuckDBResource,
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
    column_types: Mapping[str, str],
    target_path: Path,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    with connect_configured_duckdb() as connection:
        column_defs = ", ".join(
            f"{_quote_identifier(field)} {column_types[field]}" for field in fields
        )
        connection.execute(f"CREATE TEMP TABLE api_rows ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _ in fields)
            values = [
                [_clean_value(row.get(field)) for field in fields] for row in rows
            ]
            connection.executemany(
                f"INSERT INTO api_rows VALUES ({placeholders})", values
            )

        select_sql = ", ".join(
            f"CAST({_quote_identifier(field)} AS {column_types[field]}) AS {_quote_identifier(field)}"
            for field in fields
        )
        connection.execute(
            copy_query_to_parquet(f"SELECT {select_sql} FROM api_rows", temporary_path)
        )

    os.replace(temporary_path, target_path)


def _write_distinct_rows_to_parquet(
    *,
    duckdb: DuckDBResource,
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
    column_types: Mapping[str, str],
    target_path: Path,
) -> int:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    with connect_configured_duckdb() as connection:
        column_defs = ", ".join(
            f"{_quote_identifier(field)} {column_types[field]}" for field in fields
        )
        connection.execute(f"CREATE TEMP TABLE api_rows ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _ in fields)
            values = [
                [_clean_value(row.get(field)) for field in fields] for row in rows
            ]
            connection.executemany(
                f"INSERT INTO api_rows VALUES ({placeholders})", values
            )

        select_sql = ", ".join(
            f"CAST({_quote_identifier(field)} AS {column_types[field]}) AS {_quote_identifier(field)}"
            for field in fields
        )
        output_sql = f"""
        SELECT DISTINCT {select_sql}
        FROM api_rows
        """
        connection.execute(copy_query_to_parquet(output_sql, temporary_path))
        row_count = int(
            connection.execute(
                count_parquet_query(temporary_path, hive_partitioning=False)
            ).fetchone()[0]
        )

    os.replace(temporary_path, target_path)
    return row_count


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) + chr(34))}"'


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except TypeError:
        return value
    return value
