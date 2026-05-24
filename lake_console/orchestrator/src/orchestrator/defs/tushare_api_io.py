import os
from pathlib import Path
import shutil
import time
from typing import Any, Mapping, Sequence

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string, read_parquet
from orchestrator.defs.resources import DuckDBResource, TushareResource


TUSHARE_API_SOURCE_METHOD = "tushare_api"
TUSHARE_API_PAGE_LIMIT = 6000
TUSHARE_INDEX_DAILY_PAGE_LIMIT = 8000
TUSHARE_INDEX_DAILY_MIN_REQUEST_INTERVAL_SECONDS = 0.14


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

    return {
        "path": str(target_path),
        "row_count": len(rows),
        "columns": list(field_names),
        "source_method": TUSHARE_API_SOURCE_METHOD,
        "api_name": api_name,
        "params": dict(api_params),
        "fields": list(field_names),
        "page_count": page_count,
        "limit": limit,
        "partition_key": partition_key,
    }


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

    return {
        "path": str(target_path),
        "row_count": len(rows),
        "columns": list(field_names),
        "source_method": TUSHARE_API_SOURCE_METHOD,
        "api_name": api_name,
        "params": dict(api_params),
        "fields": list(field_names),
        "page_count": page_count,
        "limit": limit,
    }


def fetch_tushare_index_daily_to_raw_partitions(
    *,
    tushare: TushareResource,
    duckdb: DuckDBResource,
    active_index_codes: Sequence[str],
    partition_keys: Sequence[str],
    fields: Sequence[str],
    column_types: Mapping[str, str],
    target_paths: Mapping[str, Path],
    staging_dir: Path,
    limit: int = TUSHARE_INDEX_DAILY_PAGE_LIMIT,
) -> dict[str, Any]:
    field_names = tuple(fields)
    _validate_contract(field_names, column_types)
    selected_partition_keys = tuple(sorted(set(partition_keys)))
    if not selected_partition_keys:
        raise ValueError("index_daily partition_keys must not be empty.")

    index_codes = tuple(dict.fromkeys(code.strip() for code in active_index_codes if code.strip()))
    if not index_codes:
        raise RuntimeError("silver_index_daily_active_pool has no ts_code values.")

    missing_target_paths = [
        partition_key
        for partition_key in selected_partition_keys
        if partition_key not in target_paths
    ]
    if missing_target_paths:
        raise ValueError(f"Missing target paths for partition keys: {missing_target_paths}")

    if staging_dir.exists():
        raise RuntimeError(f"Index daily staging directory already exists: {staging_dir}")

    staging_dir.mkdir(parents=True, exist_ok=False)
    source_date_values = {
        partition_key: partition_key.replace("-", "") for partition_key in selected_partition_keys
    }
    source_dates = set(source_date_values.values())
    use_trade_date = len(selected_partition_keys) == 1
    start_date = min(source_dates)
    end_date = max(source_dates)

    page_count = 0
    written_page_file_count = 0
    source_row_count = 0
    empty_index_code_count = 0
    last_request_started_at: float | None = None

    try:
        for index_code in index_codes:
            offset = 0
            code_had_rows = False
            while True:
                api_params: dict[str, Any] = {
                    "ts_code": index_code,
                    "limit": limit,
                    "offset": offset,
                }
                if use_trade_date:
                    api_params["trade_date"] = start_date
                else:
                    api_params["start_date"] = start_date
                    api_params["end_date"] = end_date

                last_request_started_at = _wait_for_next_request_slot(
                    last_request_started_at,
                    TUSHARE_INDEX_DAILY_MIN_REQUEST_INTERVAL_SECONDS,
                )
                result = tushare.call("index_daily", api_params, field_names)
                page_rows = [
                    row
                    for row in result.rows
                    if str(row.get("trade_date", "")).strip() in source_dates
                ]
                if result.columns != field_names and (result.columns or result.rows):
                    raise RuntimeError(
                        f"Tushare index_daily returned columns {list(result.columns)}, "
                        f"expected {list(field_names)}."
                    )

                page_count += 1
                if page_rows:
                    code_had_rows = True
                    page_path = staging_dir / f"{_safe_file_stem(index_code)}-{offset}.parquet"
                    _write_rows_to_parquet(
                        duckdb=duckdb,
                        rows=page_rows,
                        fields=field_names,
                        column_types=column_types,
                        target_path=page_path,
                    )
                    written_page_file_count += 1
                    source_row_count += len(page_rows)

                if len(result.rows) < limit:
                    break
                offset += limit

            if not code_had_rows:
                empty_index_code_count += 1

        if source_row_count == 0:
            raise RuntimeError(
                "Tushare index_daily returned 0 rows for the selected active index pool and "
                f"partition keys {list(selected_partition_keys)}."
            )

        partition_row_counts = _write_index_daily_partitions_from_pages(
            duckdb=duckdb,
            page_glob=staging_dir / "*.parquet",
            partition_source_dates=source_date_values,
            target_paths=target_paths,
            fields=field_names,
            column_types=column_types,
        )
    except Exception:
        raise
    else:
        shutil.rmtree(staging_dir)

    return {
        "source_method": TUSHARE_API_SOURCE_METHOD,
        "api_name": "index_daily",
        "params": {
            "code_scope": "silver_index_daily_active_pool",
            "start_date": start_date,
            "end_date": end_date,
            "use_trade_date": use_trade_date,
        },
        "fields": list(field_names),
        "limit": limit,
        "active_pool_count": len(index_codes),
        "estimated_request_count": len(index_codes),
        "page_count": page_count,
        "request_count": page_count,
        "min_request_interval_seconds": TUSHARE_INDEX_DAILY_MIN_REQUEST_INTERVAL_SECONDS,
        "row_count": source_row_count,
        "partition_keys": list(selected_partition_keys),
        "partition_row_counts": partition_row_counts,
        "written_page_file_count": written_page_file_count,
        "empty_index_code_count": empty_index_code_count,
        "staging_dir": str(staging_dir),
        "staging_retained": False,
        "target_paths": {
            partition_key: str(target_paths[partition_key])
            for partition_key in selected_partition_keys
        },
    }


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


def _write_index_daily_partitions_from_pages(
    *,
    duckdb: DuckDBResource,
    page_glob: Path,
    partition_source_dates: Mapping[str, str],
    target_paths: Mapping[str, Path],
    fields: tuple[str, ...],
    column_types: Mapping[str, str],
) -> dict[str, int]:
    partition_row_counts: dict[str, int] = {}
    with duckdb.connect() as connection:
        source_query = read_parquet(page_glob, hive_partitioning=False, union_by_name=True)
        source_dates_sql = ", ".join(duckdb_string(value) for value in partition_source_dates.values())
        row_count_rows = connection.execute(
            f"""
            SELECT trade_date, count(*) AS row_count
            FROM {source_query}
            WHERE trade_date IN ({source_dates_sql})
            GROUP BY trade_date
            """
        ).fetchall()
        row_counts_by_source_date = {str(row[0]): int(row[1]) for row in row_count_rows}
        missing_partition_keys = [
            partition_key
            for partition_key, source_date in partition_source_dates.items()
            if row_counts_by_source_date.get(source_date, 0) == 0
        ]
        if missing_partition_keys:
            raise RuntimeError(
                "Tushare index_daily returned no rows for partition keys: "
                f"{missing_partition_keys}"
            )

        select_sql = ", ".join(
            f"CAST({_quote_identifier(field)} AS {column_types[field]}) AS {_quote_identifier(field)}"
            for field in fields
        )
        pending_paths: list[tuple[str, Path, Path]] = []
        for partition_key, source_date in partition_source_dates.items():
            target_path = target_paths[partition_key]
            target_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = target_path.with_name(f"{target_path.name}.tmp")
            if temporary_path.exists():
                temporary_path.unlink()

            connection.execute(
                copy_query_to_parquet(
                    f"""
                    SELECT {select_sql}
                    FROM {source_query}
                    WHERE trade_date = {duckdb_string(source_date)}
                    ORDER BY ts_code
                    """,
                    temporary_path,
                )
            )
            pending_paths.append((partition_key, temporary_path, target_path))

        for partition_key, temporary_path, target_path in pending_paths:
            os.replace(temporary_path, target_path)
            partition_row_counts[partition_key] = row_counts_by_source_date[
                partition_source_dates[partition_key]
            ]

    return partition_row_counts


def _validate_contract(fields: tuple[str, ...], column_types: Mapping[str, str]) -> None:
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

    with duckdb.connect() as connection:
        column_defs = ", ".join(
            f"{_quote_identifier(field)} {column_types[field]}" for field in fields
        )
        connection.execute(f"CREATE TEMP TABLE api_rows ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _ in fields)
            values = [[_clean_value(row.get(field)) for field in fields] for row in rows]
            connection.executemany(f"INSERT INTO api_rows VALUES ({placeholders})", values)

        select_sql = ", ".join(
            f"CAST({_quote_identifier(field)} AS {column_types[field]}) AS {_quote_identifier(field)}"
            for field in fields
        )
        connection.execute(
            copy_query_to_parquet(f"SELECT {select_sql} FROM api_rows", temporary_path)
        )

    os.replace(temporary_path, target_path)


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


def _safe_file_stem(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def _wait_for_next_request_slot(
    last_request_started_at: float | None,
    min_interval_seconds: float,
) -> float:
    now = time.monotonic()
    if last_request_started_at is None:
        return now

    elapsed = now - last_request_started_at
    remaining = min_interval_seconds - elapsed
    if remaining > 0:
        time.sleep(remaining)
    return time.monotonic()
