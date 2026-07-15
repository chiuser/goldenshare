"""Manual, non-Dagster Bootstrap helpers for board Raw partitions."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from orchestrator.defs.assets.dc_board import (
    DcBoardRawWriteResult,
    write_dc_daily_partition,
    write_dc_index_partition,
    write_dc_member_rows_streaming,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource, TushareResource
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_HISTORY_START_DATE,
    DC_INDEX_HISTORY_START_DATE,
    DC_MEMBER_HISTORY_START_DATE,
)


DC_MEMBER_BOOTSTRAP_SELECT_SQL = """
SELECT
    trade_date,
    ts_code,
    con_code,
    name
FROM raw_tushare.dc_member
WHERE trade_date = %s
ORDER BY ts_code, con_code
"""

DC_MEMBER_BOOTSTRAP_AUDIT_SQL = """
WITH scoped AS (
    SELECT trade_date, ts_code, con_code, name
    FROM raw_tushare.dc_member
    WHERE trade_date IS NULL
       OR (trade_date >= %s AND trade_date <= %s)
), duplicate_keys AS (
    SELECT trade_date, count(*) AS duplicate_key_count
    FROM (
        SELECT trade_date, ts_code, con_code
        FROM scoped
        GROUP BY trade_date, ts_code, con_code
        HAVING count(*) > 1
    ) duplicated
    GROUP BY trade_date
)
SELECT
    scoped.trade_date,
    count(*) AS source_row_count,
    coalesce(duplicate_keys.duplicate_key_count, 0) AS duplicate_key_count,
    sum(CASE WHEN ts_code IS NULL
                  OR ts_code !~ '^BK[0-9]{4}\\.DC$'
                  OR con_code IS NULL
                  OR con_code !~ '^[0-9]{6}\\.(SZ|SH|BJ)$'
             THEN 1 ELSE 0 END) AS invalid_code_count,
    sum(CASE WHEN trade_date IS NULL THEN 1 ELSE 0 END) AS out_of_partition_count,
    sum(CASE WHEN name IS NULL OR btrim(name) = '' THEN 1 ELSE 0 END) AS blank_name_count
FROM scoped
LEFT JOIN duplicate_keys USING (trade_date)
GROUP BY scoped.trade_date, duplicate_keys.duplicate_key_count
ORDER BY scoped.trade_date
"""


def _row_mapping(row: Any) -> dict[str, object]:
    if isinstance(row, dict):
        return {
            "trade_date": row.get("trade_date"),
            "ts_code": row.get("ts_code"),
            "con_code": row.get("con_code"),
            "name": row.get("name"),
        }
    if len(row) != 4:
        raise ValueError(f"dc_member bootstrap row must have four columns, got {len(row)}")
    return dict(zip(("trade_date", "ts_code", "con_code", "name"), row, strict=True))


def _cursor_chunks(cursor: Any, *, chunk_size: int) -> Iterator[tuple[dict[str, object], ...]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    while True:
        rows = cursor.fetchmany(chunk_size)
        if not rows:
            return
        yield tuple(_row_mapping(row) for row in rows)


def export_dc_member_partition_from_prod_db(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    partition_key: str,
    chunk_size: int = 5_000,
    cursor_itersize: int = 5_000,
) -> DcBoardRawWriteResult:
    """Stream one prod member partition into a validated temporary Parquet file."""

    try:
        partition_date = date.fromisoformat(partition_key)
    except ValueError as exc:
        raise ValueError(f"partition_key must be ISO date YYYY-MM-DD: {partition_key}") from exc
    if chunk_size <= 0 or cursor_itersize <= 0:
        raise ValueError("chunk_size and cursor_itersize must be positive.")

    with prod_postgres.connect_readonly_transaction() as connection:
        cursor = connection.cursor(name=f"dc_member_bootstrap_{uuid4().hex}")
        cursor.itersize = cursor_itersize
        try:
            cursor.execute(DC_MEMBER_BOOTSTRAP_SELECT_SQL, (partition_date,))
            result = write_dc_member_rows_streaming(
                lake_root_path=lake_root_path,
                duckdb_resource=duckdb_resource,
                partition_key=partition_key,
                chunks=_cursor_chunks(cursor, chunk_size=chunk_size),
                source_method="prod_db_readonly_export",
            )
        finally:
            cursor.close()
        return result


def bootstrap_dc_index_partition_from_tushare(**kwargs: Any) -> DcBoardRawWriteResult:
    """Manual Bootstrap wrapper; it intentionally remains outside Dagster."""

    return write_dc_index_partition(**kwargs)


def bootstrap_dc_daily_partition_from_tushare(**kwargs: Any) -> DcBoardRawWriteResult:
    """Manual Bootstrap wrapper; it intentionally remains outside Dagster."""

    return write_dc_daily_partition(**kwargs)


__all__ = [
    "DC_DAILY_HISTORY_START_DATE",
    "DC_INDEX_HISTORY_START_DATE",
    "DC_MEMBER_BOOTSTRAP_SELECT_SQL",
    "DC_MEMBER_BOOTSTRAP_AUDIT_SQL",
    "DC_MEMBER_HISTORY_START_DATE",
    "bootstrap_dc_daily_partition_from_tushare",
    "bootstrap_dc_index_partition_from_tushare",
    "export_dc_member_partition_from_prod_db",
]
