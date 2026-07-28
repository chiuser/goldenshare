"""Bounded lake gates shared by the index_global Silver sensor and checks."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.defs.duckdb_sql import describe_parquet_query, read_parquet
from orchestrator.defs.run_contracts.asset_column_schemas import SILVER_INDEX_GLOBAL_SCHEMA
from orchestrator.defs.run_contracts.index_global import INDEX_GLOBAL_EXPECTED_CODES


@dataclass(frozen=True, slots=True)
class IndexGlobalLakeFileStatus:
    path: Path
    partition_key: str
    ready: bool
    reason_code: str
    row_count: int


def _schema_matches(connection: Any, path: Path) -> bool:
    observed = tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(describe_parquet_query(path)).fetchall()
    )
    expected = tuple(
        (str(column.name), str(column.type).upper())
        for column in SILVER_INDEX_GLOBAL_SCHEMA
    )
    return observed == expected


def silver_index_global_file_status(
    connection: Any,
    path: Path,
    *,
    partition_key: str,
) -> IndexGlobalLakeFileStatus:
    """Check one existing Silver file with one set-based DuckDB query.

    Empty natural days are valid for this dataset. The gate therefore checks
    schema, date scope, identity, uniqueness, and finite values, but does not
    require a positive row count.
    """

    if not path.exists():
        return IndexGlobalLakeFileStatus(
            path=path,
            partition_key=partition_key,
            ready=False,
            reason_code="file_missing",
            row_count=0,
        )
    if not _schema_matches(connection, path):
        return IndexGlobalLakeFileStatus(
            path=path,
            partition_key=partition_key,
            ready=False,
            reason_code="schema_mismatch",
            row_count=0,
        )

    numeric_predicate = " OR ".join(
        f'("{column.name}" IS NOT NULL AND NOT isfinite("{column.name}"))'
        for column in SILVER_INDEX_GLOBAL_SCHEMA[2:]
    )
    expected_codes = ", ".join(f"'{code}'" for code in INDEX_GLOBAL_EXPECTED_CODES)
    row_count, invalid_scope, invalid_identity, duplicate_count, non_finite = connection.execute(
        f"""
        SELECT
          count(*),
          count(*) FILTER (
            WHERE trade_date IS NULL
              OR trade_date <> CAST(? AS DATE)
          ),
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
              OR trim(CAST(ts_code AS VARCHAR)) NOT IN ({expected_codes})
          ),
          count(*) - count(DISTINCT (ts_code, trade_date)),
          count(*) FILTER (WHERE {numeric_predicate})
        FROM {read_parquet(path, hive_partitioning=False)}
        """,
        [partition_key],
    ).fetchone()
    row_count = int(row_count or 0)
    if (
        int(invalid_scope or 0)
        or int(invalid_identity or 0)
        or int(duplicate_count or 0)
        or int(non_finite or 0)
    ):
        return IndexGlobalLakeFileStatus(
            path=path,
            partition_key=partition_key,
            ready=False,
            reason_code="core_contract_failed",
            row_count=row_count,
        )
    return IndexGlobalLakeFileStatus(
        path=path,
        partition_key=partition_key,
        ready=True,
        reason_code="ready",
        row_count=row_count,
    )


__all__ = ["IndexGlobalLakeFileStatus", "silver_index_global_file_status"]
