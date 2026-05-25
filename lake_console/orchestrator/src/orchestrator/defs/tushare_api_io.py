import os
from pathlib import Path
import shutil
import time
from typing import Any, Iterable, Mapping, Sequence

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource
from orchestrator.utils.dg_log_helper import DgStdoutLogger


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
    active_index_entries: Sequence[Mapping[str, Any]],
    partition_keys: Sequence[str],
    fields: Sequence[str],
    column_types: Mapping[str, str],
    target_paths: Mapping[str, Path],
    staging_dir: Path,
    limit: int = TUSHARE_INDEX_DAILY_PAGE_LIMIT,
    log: DgStdoutLogger | None = None,
) -> dict[str, Any]:
    field_names = tuple(fields)
    _validate_contract(field_names, column_types)
    selected_partition_keys = tuple(sorted(set(partition_keys)))
    if not selected_partition_keys:
        raise ValueError("index_daily partition_keys must not be empty.")

    index_entries = _normalize_active_index_entries(active_index_entries)
    if not index_entries:
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
    request_date_label = start_date if use_trade_date else f"{start_date}..{end_date}"

    if log:
        log.stdout(
            "fetch_start",
            partitions=len(selected_partition_keys),
            date=request_date_label,
            active_pool=len(index_entries),
            limit=limit,
            staging_dir=staging_dir,
        )

    page_count = 0
    written_page_file_count = 0
    source_row_count = 0
    empty_index_code_count = 0
    last_request_started_at: float | None = None

    try:
        for index_position, index_entry in enumerate(index_entries, start=1):
            index_code = index_entry["ts_code"]
            index_name = index_entry["name"]
            offset = 0
            code_had_rows = False
            code_page_count = 0
            code_row_count = 0
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
                code_page_count += 1
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
                    code_row_count += len(page_rows)

                if len(result.rows) < limit:
                    break
                offset += limit

            if log:
                log.stdout(
                    "fetch_progress",
                    progress=f"{index_position}/{len(index_entries)}",
                    date=request_date_label,
                    code=index_code,
                    name=index_name,
                    rows=code_row_count,
                    pages=code_page_count,
                    total_rows=source_row_count,
                )
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
            log=log,
        )
    except Exception:
        if log:
            log.stdout("staging_retained", staging_dir=staging_dir, reason="exception")
        raise
    else:
        try:
            shutil.rmtree(staging_dir)
        except Exception:
            if log:
                log.stdout("staging_retained", staging_dir=staging_dir, reason="cleanup_failed")
            raise
        if log:
            log.stdout("staging_cleaned", staging_dir=staging_dir)

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
        "active_pool_count": len(index_entries),
        "estimated_request_count": len(index_entries),
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


def fetch_tushare_index_daily_by_code_to_raw(
    *,
    tushare: TushareResource,
    duckdb: DuckDBResource,
    ts_code: str,
    start_date: str,
    end_date: str,
    fields: Sequence[str],
    column_types: Mapping[str, str],
    target_path: Path,
    staging_dir: Path,
    write_mode: str,
    limit: int = TUSHARE_INDEX_DAILY_PAGE_LIMIT,
) -> dict[str, Any]:
    if write_mode != "replace":
        raise ValueError("index_daily raw-by-code only supports write_mode='replace'.")

    field_names = tuple(fields)
    _validate_contract(field_names, column_types)
    api_params = {
        "ts_code": ts_code,
        "start_date": start_date,
        "end_date": end_date,
    }
    rows, page_count = _fetch_all_pages(
        tushare=tushare,
        api_name="index_daily",
        api_params=api_params,
        field_names=field_names,
        limit=limit,
    )
    window_rows = [
        row
        for row in rows
        if start_date <= str(row.get("trade_date", "")).strip() <= end_date
    ]
    if not window_rows:
        raise RuntimeError(
            "Tushare index_daily returned 0 rows for "
            f"ts_code={ts_code}, start_date={start_date}, end_date={end_date}."
        )

    if staging_dir.exists():
        raise RuntimeError(f"Index daily by-code staging directory already exists: {staging_dir}")
    staging_dir.mkdir(parents=True, exist_ok=False)
    staging_path = staging_dir / "fetched.parquet"

    try:
        _write_rows_to_parquet(
            duckdb=duckdb,
            rows=window_rows,
            fields=field_names,
            column_types=column_types,
            target_path=staging_path,
        )
        output_row_count = _replace_index_daily_by_code_window(
            duckdb=duckdb,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields=field_names,
            column_types=column_types,
            target_path=target_path,
            staging_path=staging_path,
        )
    except Exception:
        raise
    else:
        shutil.rmtree(staging_dir)

    return {
        "source_method": TUSHARE_API_SOURCE_METHOD,
        "api_name": "index_daily",
        "params": api_params,
        "fields": list(field_names),
        "limit": limit,
        "ts_code": ts_code,
        "start_date": start_date,
        "end_date": end_date,
        "write_mode": write_mode,
        "page_count": page_count,
        "fetched_row_count": len(window_rows),
        "row_count": output_row_count,
        "path": str(target_path),
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


def _replace_index_daily_by_code_window(
    *,
    duckdb: DuckDBResource,
    ts_code: str,
    start_date: str,
    end_date: str,
    fields: tuple[str, ...],
    column_types: Mapping[str, str],
    target_path: Path,
    staging_path: Path,
) -> int:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    select_sql = ", ".join(
        f"CAST({_quote_identifier(field)} AS {column_types[field]}) AS {_quote_identifier(field)}"
        for field in fields
    )
    staging_query = read_parquet(staging_path, hive_partitioning=False)
    with duckdb.connect() as connection:
        mismatch_count = int(
            connection.execute(
                f"""
                SELECT count(*) AS mismatch_count
                FROM {staging_query}
                WHERE CAST(ts_code AS VARCHAR) != {duckdb_string(ts_code)}
                   OR CAST(trade_date AS VARCHAR) < {duckdb_string(start_date)}
                   OR CAST(trade_date AS VARCHAR) > {duckdb_string(end_date)}
                """
            ).fetchone()[0]
        )
        if mismatch_count:
            raise RuntimeError(
                "Tushare index_daily returned rows outside the requested code/date window: "
                f"ts_code={ts_code}, start_date={start_date}, end_date={end_date}, "
                f"mismatch_count={mismatch_count}."
            )

        fetched_rows_sql = f"""
        SELECT {select_sql}
        FROM {staging_query}
        """
        if target_path.exists():
            existing_query = read_parquet(target_path, hive_partitioning=False, union_by_name=True)
            output_sql = f"""
            WITH existing_rows AS (
              SELECT {select_sql}
              FROM {existing_query}
              WHERE NOT (
                CAST(ts_code AS VARCHAR) = {duckdb_string(ts_code)}
                AND CAST(trade_date AS VARCHAR) >= {duckdb_string(start_date)}
                AND CAST(trade_date AS VARCHAR) <= {duckdb_string(end_date)}
              )
            ),
            fetched_rows AS (
              {fetched_rows_sql}
            ),
            combined_rows AS (
              SELECT * FROM existing_rows
              UNION ALL
              SELECT * FROM fetched_rows
            )
            SELECT DISTINCT *
            FROM combined_rows
            ORDER BY trade_date
            """
        else:
            output_sql = f"""
            SELECT DISTINCT *
            FROM ({fetched_rows_sql}) fetched_rows
            ORDER BY trade_date
            """

        connection.execute(copy_query_to_parquet(output_sql, temporary_path))
        output_row_count = int(
            connection.execute(count_parquet_query(temporary_path, hive_partitioning=False)).fetchone()[
                0
            ]
        )

    os.replace(temporary_path, target_path)
    return output_row_count


def _write_index_daily_partitions_from_pages(
    *,
    duckdb: DuckDBResource,
    page_glob: Path,
    partition_source_dates: Mapping[str, str],
    target_paths: Mapping[str, Path],
    fields: tuple[str, ...],
    column_types: Mapping[str, str],
    log: DgStdoutLogger | None = None,
) -> dict[str, int]:
    partition_row_counts: dict[str, int] = {}
    if log:
        log.stdout(
            "staging_split_start",
            partitions=len(partition_source_dates),
            trade_date=_source_date_range_label(partition_source_dates.values()),
        )

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
            if log:
                log.stdout(
                    "raw_partition_written",
                    partition_key=partition_key,
                    trade_date=partition_source_dates[partition_key],
                    rows=partition_row_counts[partition_key],
                    path=target_path,
                )

    if log:
        log.stdout(
            "raw_partitions_completed",
            partitions=len(partition_row_counts),
            total_rows=sum(partition_row_counts.values()),
        )

    return partition_row_counts


def _normalize_active_index_entries(
    active_index_entries: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], ...]:
    normalized_entries: list[dict[str, str]] = []
    seen_codes: set[str] = set()
    for active_index_entry in active_index_entries:
        raw_ts_code = active_index_entry.get("ts_code")
        if raw_ts_code is None:
            continue
        ts_code = str(raw_ts_code).strip()
        if not ts_code or ts_code in seen_codes:
            continue
        seen_codes.add(ts_code)
        raw_name = active_index_entry.get("name")
        name = str(raw_name).strip() if raw_name is not None else "-"
        name = name or "-"
        normalized_entries.append({"ts_code": ts_code, "name": name})
    return tuple(normalized_entries)


def _source_date_range_label(source_dates: Iterable[str]) -> str:
    sorted_source_dates = sorted(set(source_dates))
    if not sorted_source_dates:
        return "-"
    if len(sorted_source_dates) == 1:
        return sorted_source_dates[0]
    return f"{sorted_source_dates[0]}..{sorted_source_dates[-1]}"


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
