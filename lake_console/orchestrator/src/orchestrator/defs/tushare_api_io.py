import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.resources import DuckDBResource, TushareResource


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
