import os
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from orchestrator.utils.dg_log_helper import DgStdoutLogger


TUSHARE_API_SOURCE_METHOD = "tushare_api"
TUSHARE_API_PAGE_LIMIT = 6000
TUSHARE_INDEX_DAILY_PAGE_LIMIT = 8000


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
        columns=field_names,
        extra_metadata={
            "source_method": TUSHARE_API_SOURCE_METHOD,
            "params": dict(api_params),
            "fields": list(field_names),
            "page_count": page_count,
            "limit": limit,
            "partition_key": partition_key,
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
        columns=field_names,
        extra_metadata={
            "source_method": TUSHARE_API_SOURCE_METHOD,
            "params": dict(api_params),
            "fields": list(field_names),
            "page_count": page_count,
            "limit": limit,
        },
    )


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
    log: DgStdoutLogger | None = None,
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
    if log:
        log.stdout(
            "fetch_start",
            code=ts_code,
            start_date=start_date,
            end_date=end_date,
            write_mode=write_mode,
            limit=limit,
            staging_dir=staging_dir,
        )
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
    if log:
        log.stdout(
            "fetch_progress",
            code=ts_code,
            start_date=start_date,
            end_date=end_date,
            rows=len(window_rows),
            pages=page_count,
        )

    if staging_dir.exists():
        raise RuntimeError(
            f"Index daily by-code staging directory already exists: {staging_dir}"
        )
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
        if log:
            log.stdout("staging_written", rows=len(window_rows), path=staging_path)
            log.stdout(
                "raw_by_code_replace_start",
                code=ts_code,
                start_date=start_date,
                end_date=end_date,
                path=target_path,
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
        if log:
            log.stdout("staging_retained", staging_dir=staging_dir, reason="exception")
        raise
    else:
        try:
            shutil.rmtree(staging_dir)
            _remove_empty_staging_parent_dirs(staging_dir)
        except Exception:
            if log:
                log.stdout(
                    "staging_retained", staging_dir=staging_dir, reason="cleanup_failed"
                )
            raise
        if log:
            log.stdout(
                "raw_by_code_written",
                code=ts_code,
                start_date=start_date,
                end_date=end_date,
                rows=output_row_count,
                path=target_path,
            )
            log.stdout("staging_cleaned", staging_dir=staging_dir)

    return build_materialization_metadata(
        uri=target_path,
        row_count=output_row_count,
        columns=field_names,
        extra_metadata={
            "source_method": TUSHARE_API_SOURCE_METHOD,
            "params": api_params,
            "fields": list(field_names),
            "limit": limit,
            "ts_code": ts_code,
            "start_date": start_date,
            "end_date": end_date,
            "write_mode": write_mode,
            "page_count": page_count,
            "fetched_row_count": len(window_rows),
        },
    )


def _remove_empty_staging_parent_dirs(staging_dir: Path) -> None:
    """Remove empty run-level staging parents left after a successful write."""
    for directory in (staging_dir.parent, staging_dir.parent.parent):
        try:
            directory.rmdir()
        except OSError:
            break


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
            existing_query = read_parquet(
                target_path, hive_partitioning=False, union_by_name=True
            )
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
            connection.execute(
                count_parquet_query(temporary_path, hive_partitioning=False)
            ).fetchone()[0]
        )

    os.replace(temporary_path, target_path)
    return output_row_count


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

    with duckdb.connect() as connection:
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
