from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator, Sequence

import duckdb

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import gold_stk_mins_qfq_as_of_basis_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_AS_OF_BASIS_SCHEMA,
)


GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS = tuple(
    column.name for column in GOLD_STK_MINS_QFQ_AS_OF_BASIS_SCHEMA
)
GOLD_STK_MINS_QFQ_AS_OF_BASIS_ORIGINS = frozenset(
    {"daily_qfq", "factor_repair", "history_reconstruction"}
)
GOLD_STK_MINS_QFQ_AS_OF_BASIS_FACTOR_TOLERANCE = 1e-12


@dataclass(frozen=True)
class GoldStkMinsQfqAsOfBasisWriteResult:
    year: str
    replacement_row_count: int
    row_count: int
    changed: bool
    path: Path


@dataclass(frozen=True)
class GoldStkMinsQfqAsOfBasisValidationCounts:
    basis_row_count: int
    invalid_basis_row_count: int
    duplicate_basis_key_count: int
    missing_source_factor_row_count: int
    duplicate_source_factor_key_count: int
    source_factor_mismatch_row_count: int

    @property
    def failed_row_count(self) -> int:
        return (
            self.invalid_basis_row_count
            + self.duplicate_basis_key_count
            + self.missing_source_factor_row_count
            + self.duplicate_source_factor_key_count
            + self.source_factor_mismatch_row_count
        )


def build_qfq_as_of_basis_rows_sql(
    *,
    silver_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
    as_of_trade_date: str | None,
    basis_origin: str,
    trade_dates: Sequence[str] | None = None,
    stock_codes: Sequence[str] | None = None,
) -> str:
    _validate_origin(basis_origin)
    as_of_date_sql = (
        f"DATE {duckdb_string(_normalize_trade_date(as_of_trade_date))}"
        if as_of_trade_date is not None
        else "CAST(NULL AS DATE)"
    )
    trade_date_filter = ""
    if trade_dates:
        normalized_dates = _normalize_trade_dates(trade_dates)
        values = ", ".join(f"DATE {duckdb_string(value)}" for value in normalized_dates)
        trade_date_filter = f" AND CAST(trade_date AS DATE) IN ({values})"
    code_filter = ""
    if stock_codes:
        normalized_codes = _normalize_stock_codes(stock_codes)
        values = ", ".join(duckdb_string(value) for value in normalized_codes)
        code_filter = f" AND CAST(ts_code AS VARCHAR) IN ({values})"
    return f"""
WITH silver_codes AS (
  SELECT DISTINCT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date
  FROM {_read_parquet_paths(silver_paths)}
  WHERE true{trade_date_filter}{code_filter}
),
as_of_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(adj_factor AS DOUBLE) AS as_of_adj_factor
  FROM {read_parquet(as_of_adj_factor_path, hive_partitioning=False)}
)
SELECT
  silver_codes.ts_code,
  silver_codes.trade_date,
  as_of_factor.as_of_adj_factor,
  {as_of_date_sql} AS as_of_trade_date,
  {duckdb_string(basis_origin)} AS basis_origin
FROM silver_codes
INNER JOIN as_of_factor
  ON silver_codes.ts_code = as_of_factor.ts_code
WHERE as_of_factor.as_of_adj_factor IS NOT NULL
ORDER BY silver_codes.ts_code, silver_codes.trade_date
"""


def write_gold_stk_mins_qfq_as_of_basis(
    *,
    lake_root: Path,
    replacement_rows_sql: str,
) -> tuple[GoldStkMinsQfqAsOfBasisWriteResult, ...]:
    with _basis_write_lock(lake_root):
        with connect_configured_duckdb() as connection:
            _create_basis_replacement_rows(connection, replacement_rows_sql)
            _validate_basis_replacement_rows(connection)
            groups = connection.execute(
                """
                SELECT strftime(trade_date, '%Y') AS year, count(*) AS row_count
                FROM qfq_as_of_basis_replacement_rows
                GROUP BY year
                ORDER BY year
                """
            ).fetchall()
            results: list[GoldStkMinsQfqAsOfBasisWriteResult] = []
            for year, replacement_row_count in groups:
                normalized_year = str(year)
                target_path = gold_stk_mins_qfq_as_of_basis_path(
                    lake_root,
                    normalized_year,
                )
                changed, row_count = _write_basis_year_file(
                    connection,
                    target_path=target_path,
                    year=normalized_year,
                )
                results.append(
                    GoldStkMinsQfqAsOfBasisWriteResult(
                        year=normalized_year,
                        replacement_row_count=int(replacement_row_count),
                        row_count=row_count,
                        changed=changed,
                        path=target_path,
                    )
                )
    return tuple(results)


def qfq_as_of_basis_path_for_trade_date(lake_root: Path, trade_date: str) -> Path:
    return gold_stk_mins_qfq_as_of_basis_path(
        lake_root,
        _normalize_trade_date(trade_date)[:4],
    )


def build_qfq_as_of_basis_by_code_sql(
    *,
    basis_paths: Sequence[Path],
) -> str:
    return f"""
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CAST(trade_date AS DATE) AS trade_date,
  CAST(as_of_adj_factor AS DOUBLE) AS as_of_adj_factor,
  CAST(as_of_trade_date AS DATE) AS as_of_trade_date,
  CAST(basis_origin AS VARCHAR) AS basis_origin
FROM {_read_parquet_paths(basis_paths)}
"""


def qfq_as_of_basis_source_trade_dates(
    connection: duckdb.DuckDBPyConnection,
    *,
    basis_paths: Sequence[Path],
    trade_dates: Sequence[str],
) -> tuple[str, ...]:
    """Return only proven source dates for the selected QFQ rows."""

    normalized_dates = _normalize_trade_dates(trade_dates)
    rows = connection.execute(
        f"""
        SELECT DISTINCT strftime(CAST(as_of_trade_date AS DATE), '%Y-%m-%d')
        FROM ({build_qfq_as_of_basis_by_code_sql(basis_paths=basis_paths)})
        WHERE CAST(trade_date AS DATE) IN ({_date_values_sql(normalized_dates)})
          AND basis_origin <> 'history_reconstruction'
          AND as_of_trade_date IS NOT NULL
        ORDER BY 1
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows if row[0] is not None)


def qfq_as_of_basis_validation_counts(
    connection: duckdb.DuckDBPyConnection,
    *,
    basis_paths: Sequence[Path],
    trade_dates: Sequence[str],
    source_factor_paths: Sequence[Path],
) -> GoldStkMinsQfqAsOfBasisValidationCounts:
    """Validate the compact as-of fact without consulting Dagster history."""

    counts_by_trade_date = qfq_as_of_basis_validation_counts_by_trade_date(
        connection,
        basis_paths=basis_paths,
        trade_dates=trade_dates,
        source_factor_paths=source_factor_paths,
    )
    return GoldStkMinsQfqAsOfBasisValidationCounts(
        basis_row_count=sum(
            counts.basis_row_count for counts in counts_by_trade_date.values()
        ),
        invalid_basis_row_count=sum(
            counts.invalid_basis_row_count for counts in counts_by_trade_date.values()
        ),
        duplicate_basis_key_count=sum(
            counts.duplicate_basis_key_count
            for counts in counts_by_trade_date.values()
        ),
        missing_source_factor_row_count=sum(
            counts.missing_source_factor_row_count
            for counts in counts_by_trade_date.values()
        ),
        duplicate_source_factor_key_count=sum(
            counts.duplicate_source_factor_key_count
            for counts in counts_by_trade_date.values()
        ),
        source_factor_mismatch_row_count=sum(
            counts.source_factor_mismatch_row_count
            for counts in counts_by_trade_date.values()
        ),
    )


def qfq_as_of_basis_validation_counts_by_trade_date(
    connection: duckdb.DuckDBPyConnection,
    *,
    basis_paths: Sequence[Path],
    trade_dates: Sequence[str],
    source_factor_paths: Sequence[Path],
) -> dict[str, GoldStkMinsQfqAsOfBasisValidationCounts]:
    """Batch-validate basis rows with one bounded DuckDB query."""

    normalized_dates = _normalize_trade_dates(trade_dates)
    source_factor_source = (
        _read_parquet_paths(source_factor_paths)
        if source_factor_paths
        else None
    )
    source_factor_cte = (
        f"""
        source_factor AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(adj_factor AS DOUBLE) AS adj_factor
          FROM {source_factor_source}
        )
        """
        if source_factor_source is not None
        else """
        source_factor AS (
          SELECT
            CAST(NULL AS VARCHAR) AS ts_code,
            CAST(NULL AS DATE) AS trade_date,
            CAST(NULL AS DOUBLE) AS adj_factor
          WHERE false
        )
        """
    )
    rows = connection.execute(
        f"""
        WITH selected(trade_date) AS (VALUES {_date_values_sql(normalized_dates)}),
        basis_rows AS (
          SELECT basis.*
          FROM ({build_qfq_as_of_basis_by_code_sql(basis_paths=basis_paths)}) AS basis
          INNER JOIN selected
            ON CAST(basis.trade_date AS DATE) = selected.trade_date
        ),
        {source_factor_cte},
        source_factor_summary AS (
          SELECT
            ts_code,
            trade_date,
            count(*) AS source_factor_count,
            min(adj_factor) AS source_adj_factor
          FROM source_factor
          GROUP BY ts_code, trade_date
        ),
        basis_rows_with_source AS (
          SELECT
            basis_rows.*,
            source_factor_summary.source_adj_factor,
            coalesce(source_factor_summary.source_factor_count, 0) AS source_factor_count
          FROM basis_rows
          LEFT JOIN source_factor_summary
            ON basis_rows.ts_code = source_factor_summary.ts_code
           AND basis_rows.as_of_trade_date = source_factor_summary.trade_date
        ),
        duplicate_basis_keys AS (
          SELECT ts_code, trade_date
          FROM basis_rows
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        ),
        basis_aggregates AS (
          SELECT
            trade_date,
            count(*) AS basis_row_count,
            count(*) FILTER (
            WHERE ts_code IS NULL
               OR trade_date IS NULL
               OR as_of_adj_factor IS NULL
               OR NOT isfinite(as_of_adj_factor)
               OR as_of_adj_factor = 0
               OR basis_origin NOT IN ('daily_qfq', 'factor_repair', 'history_reconstruction')
               OR (basis_origin <> 'history_reconstruction' AND as_of_trade_date IS NULL)
            ) AS invalid_basis_row_count,
            count(*) FILTER (
              WHERE basis_origin <> 'history_reconstruction'
                AND source_factor_count = 0
            ) AS missing_source_factor_row_count,
            count(*) FILTER (
              WHERE basis_origin <> 'history_reconstruction'
                AND source_factor_count > 1
            ) AS duplicate_source_factor_key_count,
            count(*) FILTER (
              WHERE basis_origin <> 'history_reconstruction'
                AND source_factor_count = 1
                AND abs(as_of_adj_factor - source_adj_factor)
                      > {GOLD_STK_MINS_QFQ_AS_OF_BASIS_FACTOR_TOLERANCE}
            ) AS source_factor_mismatch_row_count
          FROM basis_rows_with_source
          GROUP BY trade_date
        ),
        duplicate_basis_aggregates AS (
          SELECT
            trade_date,
            count(*) AS duplicate_basis_key_count
          FROM duplicate_basis_keys
          GROUP BY trade_date
        )
        SELECT
          strftime(selected.trade_date, '%Y-%m-%d') AS trade_date,
          coalesce(basis_aggregates.basis_row_count, 0) AS basis_row_count,
          coalesce(basis_aggregates.invalid_basis_row_count, 0)
            AS invalid_basis_row_count,
          coalesce(duplicate_basis_aggregates.duplicate_basis_key_count, 0)
            AS duplicate_basis_key_count,
          coalesce(basis_aggregates.missing_source_factor_row_count, 0)
            AS missing_source_factor_row_count,
          coalesce(basis_aggregates.duplicate_source_factor_key_count, 0)
            AS duplicate_source_factor_key_count,
          coalesce(basis_aggregates.source_factor_mismatch_row_count, 0)
            AS source_factor_mismatch_row_count
        FROM selected
        LEFT JOIN basis_aggregates
          ON selected.trade_date = basis_aggregates.trade_date
        LEFT JOIN duplicate_basis_aggregates
          ON selected.trade_date = duplicate_basis_aggregates.trade_date
        ORDER BY selected.trade_date
        """
    ).fetchall()
    return {
        str(trade_date): GoldStkMinsQfqAsOfBasisValidationCounts(
            *(int(value or 0) for value in values)
        )
        for trade_date, *values in rows
    }


def _create_basis_replacement_rows(
    connection: duckdb.DuckDBPyConnection,
    replacement_rows_sql: str,
) -> None:
    columns = ",\n    ".join(
        f"CAST({column.name} AS {column.type}) AS {column.name}"
        for column in GOLD_STK_MINS_QFQ_AS_OF_BASIS_SCHEMA
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE qfq_as_of_basis_replacement_rows AS
        SELECT
          {columns}
        FROM ({replacement_rows_sql})
        """
    )


def _validate_basis_replacement_rows(connection: duckdb.DuckDBPyConnection) -> None:
    row_count = int(
        connection.execute(
            "SELECT count(*) FROM qfq_as_of_basis_replacement_rows"
        ).fetchone()[0]
    )
    if row_count == 0:
        raise ValueError("qfq as-of basis replacement rows are empty.")
    null_or_invalid_count = int(
        connection.execute(
            """
            SELECT count(*)
            FROM qfq_as_of_basis_replacement_rows
            WHERE ts_code IS NULL
               OR trade_date IS NULL
               OR as_of_adj_factor IS NULL
               OR NOT isfinite(as_of_adj_factor)
               OR as_of_adj_factor = 0
               OR basis_origin NOT IN ('daily_qfq', 'factor_repair', 'history_reconstruction')
               OR (basis_origin <> 'history_reconstruction' AND as_of_trade_date IS NULL)
            """
        ).fetchone()[0]
    )
    if null_or_invalid_count:
        raise ValueError(
            "qfq as-of basis replacement rows contain invalid contract values: "
            f"{null_or_invalid_count}."
        )
    duplicate_count = int(
        connection.execute(
            """
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_date
              FROM qfq_as_of_basis_replacement_rows
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
    )
    if duplicate_count:
        raise ValueError(
            "qfq as-of basis replacement rows contain duplicate ts_code + trade_date keys: "
            f"{duplicate_count}."
        )


def _write_basis_year_file(
    connection: duckdb.DuckDBPyConnection,
    *,
    target_path: Path,
    year: str,
) -> tuple[bool, int]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        _validate_basis_year_file(connection, path=target_path, year=year)
        changed = bool(
            connection.execute(
                f"""
                WITH replacement_rows AS (
                  SELECT {', '.join(GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS)}
                  FROM qfq_as_of_basis_replacement_rows
                  WHERE strftime(trade_date, '%Y') = {duckdb_string(year)}
                ),
                existing_rows AS (
                  SELECT {', '.join(GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS)}
                  FROM {read_parquet(target_path, hive_partitioning=False)}
                  WHERE (ts_code, trade_date) IN (
                    SELECT ts_code, trade_date FROM replacement_rows
                  )
                )
                SELECT EXISTS (
                  SELECT 1
                  FROM replacement_rows
                  FULL OUTER JOIN existing_rows
                    USING (ts_code, trade_date)
                  WHERE replacement_rows.as_of_adj_factor IS DISTINCT FROM existing_rows.as_of_adj_factor
                     OR replacement_rows.as_of_trade_date IS DISTINCT FROM existing_rows.as_of_trade_date
                     OR replacement_rows.basis_origin IS DISTINCT FROM existing_rows.basis_origin
                )
                """
            ).fetchone()[0]
        )
        if not changed:
            row_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {read_parquet(target_path, hive_partitioning=False)}"
                ).fetchone()[0]
            )
            return False, row_count

    temporary_path = target_path.with_suffix(".tmp.parquet")
    if temporary_path.exists():
        temporary_path.unlink()
    existing_rows = (
        f"SELECT {', '.join(GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS)} "
        f"FROM {read_parquet(target_path, hive_partitioning=False)}"
        if target_path.exists()
        else _empty_basis_rows_select()
    )
    connection.execute(
        copy_query_to_parquet(
            f"""
            WITH replacement_rows AS (
              SELECT {', '.join(GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS)}
              FROM qfq_as_of_basis_replacement_rows
              WHERE strftime(trade_date, '%Y') = {duckdb_string(year)}
            ),
            merged_rows AS (
              SELECT {', '.join(GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS)}
              FROM ({existing_rows})
              WHERE (ts_code, trade_date) NOT IN (
                SELECT ts_code, trade_date FROM replacement_rows
              )
              UNION ALL
              SELECT {', '.join(GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS)}
              FROM replacement_rows
            )
            SELECT {', '.join(GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS)}
            FROM merged_rows
            ORDER BY trade_date, ts_code
            """,
            temporary_path,
        )
    )
    _validate_basis_year_file(connection, path=temporary_path, year=year)
    row_count = int(
        connection.execute(
            f"SELECT count(*) FROM {read_parquet(temporary_path, hive_partitioning=False)}"
        ).fetchone()[0]
    )
    os.replace(temporary_path, target_path)
    return True, row_count


def _validate_basis_year_file(
    connection: duckdb.DuckDBPyConnection,
    *,
    path: Path,
    year: str,
) -> None:
    columns = [row[0] for row in connection.execute(
        f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    ).fetchall()]
    if tuple(columns) != GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS:
        raise ValueError(f"qfq as-of basis schema mismatch: path={path}.")
    invalid_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE ts_code IS NULL
               OR trade_date IS NULL
               OR strftime(CAST(trade_date AS DATE), '%Y') <> {duckdb_string(year)}
               OR as_of_adj_factor IS NULL
               OR NOT isfinite(CAST(as_of_adj_factor AS DOUBLE))
               OR CAST(as_of_adj_factor AS DOUBLE) = 0
               OR basis_origin NOT IN ('daily_qfq', 'factor_repair', 'history_reconstruction')
               OR (basis_origin <> 'history_reconstruction' AND as_of_trade_date IS NULL)
            """
        ).fetchone()[0]
    )
    if invalid_count:
        raise ValueError(f"qfq as-of basis contract failed: path={path}, invalid={invalid_count}.")
    duplicate_count = int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_date
              FROM {read_parquet(path, hive_partitioning=False)}
              GROUP BY ts_code, trade_date
              HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
    )
    if duplicate_count:
        raise ValueError(f"qfq as-of basis duplicate keys: path={path}, count={duplicate_count}.")


def _empty_basis_rows_select() -> str:
    columns = ", ".join(
        f"CAST(NULL AS {column.type}) AS {column.name}"
        for column in GOLD_STK_MINS_QFQ_AS_OF_BASIS_SCHEMA
    )
    return f"SELECT {columns} WHERE false"


@contextmanager
def _basis_write_lock(lake_root: Path) -> Iterator[None]:
    lock_path = lake_root / "gold" / "quote" / "stk_mins_qfq_as_of_basis" / ".write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("qfq as-of basis source paths must not be empty.")
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    return "read_parquet([" + ", ".join(
        duckdb_string(path) for path in paths
    ) + "], hive_partitioning=false, union_by_name=true)"


def _normalize_trade_dates(trade_dates: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({_normalize_trade_date(value) for value in trade_dates}))
    if not normalized:
        raise ValueError("qfq as-of basis trade_dates must not be empty.")
    return normalized


def _normalize_trade_date(value: str) -> str:
    return date.fromisoformat(str(value).strip()).isoformat()


def _normalize_stock_codes(stock_codes: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({str(value).strip() for value in stock_codes if str(value).strip()}))
    if not normalized:
        raise ValueError("qfq as-of basis stock_codes must not be empty when supplied.")
    return normalized


def _validate_origin(basis_origin: str) -> None:
    if basis_origin not in GOLD_STK_MINS_QFQ_AS_OF_BASIS_ORIGINS:
        raise ValueError(f"Unsupported qfq as-of basis origin: {basis_origin!r}.")


def _date_values_sql(trade_dates: Sequence[str]) -> str:
    return ", ".join(
        f"(DATE {duckdb_string(trade_date)})" for trade_date in trade_dates
    )
