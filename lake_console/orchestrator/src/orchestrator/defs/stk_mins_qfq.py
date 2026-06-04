from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import duckdb

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string, read_parquet
from orchestrator.defs.paths import gold_stk_mins_qfq_path
from orchestrator.defs.run_contracts.asset_column_schemas import GOLD_STK_MINS_QFQ_SCHEMA
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.stk_mins import normalize_stk_mins_freq


GOLD_STK_MINS_QFQ_COLUMNS = tuple(column.name for column in GOLD_STK_MINS_QFQ_SCHEMA)
GOLD_STK_MINS_QFQ_COLUMN_TYPES = {
    column.name: column.type for column in GOLD_STK_MINS_QFQ_SCHEMA
}
GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME = (
    "gold_stk_mins_qfq_factor_repair_plan_evaluated"
)
GOLD_STK_MINS_QFQ_WRITER_POOL = "gold_stk_mins_qfq_writer"
QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED = "no_factor_changed"
QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED = "factor_changed"
QFQ_FACTOR_REPAIR_REASON_NEW_CURRENT_CODE = "new_current_code"
QFQ_FACTOR_REPAIR_REASON_MISSING_PREVIOUS_FACTOR = "missing_previous_factor"
QFQ_FACTOR_REPAIR_REASONS = (
    QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED,
    QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED,
    QFQ_FACTOR_REPAIR_REASON_NEW_CURRENT_CODE,
    QFQ_FACTOR_REPAIR_REASON_MISSING_PREVIOUS_FACTOR,
)
QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT = 20


@dataclass(frozen=True)
class GoldStkMinsQfqWriteResult:
    path: Path
    ts_code: str
    year: str
    row_count: int
    replacement_row_count: int


@dataclass(frozen=True)
class GoldStkMinsQfqFactorRepairPlan:
    trade_date: str
    previous_trade_date: str
    reason: str
    can_execute_repair: bool
    repair_required: bool
    detected_change_code_count: int
    repair_required_code_count: int
    factor_changed_code_count: int
    new_current_code_count: int
    missing_previous_factor_code_count: int
    repair_required_codes: tuple[str, ...]
    factor_changed_code_samples: tuple[str, ...]
    new_current_code_samples: tuple[str, ...]
    missing_previous_factor_code_samples: tuple[str, ...]


def build_latest_adj_factor_by_code_sql(adj_factor_paths: Sequence[Path]) -> str:
    adj_factor_source = _read_parquet_paths(adj_factor_paths)
    return f"""
WITH adj_factor_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(adj_factor AS DOUBLE) AS adj_factor
  FROM {adj_factor_source}
),
ranked_adj_factor AS (
  SELECT
    ts_code,
    trade_date,
    adj_factor,
    row_number() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS row_number
  FROM adj_factor_rows
)
SELECT
  ts_code,
  trade_date AS latest_trade_date,
  adj_factor AS latest_adj_factor
FROM ranked_adj_factor
WHERE row_number = 1
"""


def build_daily_qfq_select_sql(
    *,
    silver_paths: Sequence[Path],
    trade_adj_factor_paths: Sequence[Path],
    latest_adj_factor_paths: Sequence[Path],
) -> str:
    silver_source = _read_parquet_paths(silver_paths)
    trade_adj_source = _read_parquet_paths(trade_adj_factor_paths)
    latest_adj_sql = build_latest_adj_factor_by_code_sql(latest_adj_factor_paths)
    return f"""
WITH silver_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(freq AS INTEGER) AS freq,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(trade_time AS TIMESTAMP) AS trade_time,
    CAST(open AS DOUBLE) AS open,
    CAST(high AS DOUBLE) AS high,
    CAST(low AS DOUBLE) AS low,
    CAST(close AS DOUBLE) AS close,
    CAST(vol AS DOUBLE) AS vol,
    CAST(amount AS DOUBLE) AS amount,
    CAST(exchange AS VARCHAR) AS exchange
  FROM {silver_source}
),
trade_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(adj_factor AS DOUBLE) AS trade_adj_factor
  FROM {trade_adj_source}
),
latest_adj_factor AS (
  {latest_adj_sql}
)
SELECT
  silver_rows.ts_code,
  silver_rows.freq,
  silver_rows.trade_date,
  silver_rows.trade_time,
  CAST(silver_rows.open * trade_adj_factor.trade_adj_factor / latest_adj_factor.latest_adj_factor AS DOUBLE) AS open,
  CAST(silver_rows.high * trade_adj_factor.trade_adj_factor / latest_adj_factor.latest_adj_factor AS DOUBLE) AS high,
  CAST(silver_rows.low * trade_adj_factor.trade_adj_factor / latest_adj_factor.latest_adj_factor AS DOUBLE) AS low,
  CAST(silver_rows.close * trade_adj_factor.trade_adj_factor / latest_adj_factor.latest_adj_factor AS DOUBLE) AS close,
  silver_rows.vol,
  silver_rows.amount,
  silver_rows.exchange
FROM silver_rows
INNER JOIN trade_adj_factor
  ON silver_rows.ts_code = trade_adj_factor.ts_code
 AND silver_rows.trade_date = trade_adj_factor.trade_date
INNER JOIN latest_adj_factor
  ON silver_rows.ts_code = latest_adj_factor.ts_code
WHERE trade_adj_factor.trade_adj_factor IS NOT NULL
  AND latest_adj_factor.latest_adj_factor IS NOT NULL
ORDER BY silver_rows.ts_code, silver_rows.trade_time
"""


def build_daily_qfq_coverage_sql(
    *,
    silver_paths: Sequence[Path],
    trade_adj_factor_paths: Sequence[Path],
    latest_adj_factor_paths: Sequence[Path],
) -> str:
    silver_source = _read_parquet_paths(silver_paths)
    trade_adj_source = _read_parquet_paths(trade_adj_factor_paths)
    latest_adj_sql = build_latest_adj_factor_by_code_sql(latest_adj_factor_paths)
    return f"""
WITH silver_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date
  FROM {silver_source}
),
trade_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(adj_factor AS DOUBLE) AS trade_adj_factor
  FROM {trade_adj_source}
),
latest_adj_factor AS (
  {latest_adj_sql}
),
joined_rows AS (
  SELECT
    silver_rows.ts_code,
    silver_rows.trade_date,
    trade_adj_factor.trade_adj_factor,
    latest_adj_factor.latest_adj_factor
  FROM silver_rows
  LEFT JOIN trade_adj_factor
    ON silver_rows.ts_code = trade_adj_factor.ts_code
   AND silver_rows.trade_date = trade_adj_factor.trade_date
  LEFT JOIN latest_adj_factor
    ON silver_rows.ts_code = latest_adj_factor.ts_code
)
SELECT
  count(*) AS silver_row_count,
  count(*) FILTER (
    WHERE trade_adj_factor IS NOT NULL AND latest_adj_factor IS NOT NULL
  ) AS qfq_output_row_count,
  count(*) FILTER (WHERE trade_adj_factor IS NULL) AS missing_trade_adj_factor_row_count,
  count(*) FILTER (WHERE latest_adj_factor IS NULL) AS missing_latest_adj_factor_row_count
FROM joined_rows
"""


def build_adj_factor_changed_codes_sql(
    *,
    current_adj_factor_path: Path,
    previous_adj_factor_path: Path,
    silver_stock_basic_path: Path | None = None,
    trade_date: str | None = None,
    previous_trade_date: str | None = None,
) -> str:
    _validate_repair_detection_args(
        silver_stock_basic_path=silver_stock_basic_path,
        trade_date=trade_date,
        previous_trade_date=previous_trade_date,
    )
    current_source = read_parquet(current_adj_factor_path, hive_partitioning=False)
    previous_source = read_parquet(previous_adj_factor_path, hive_partitioning=False)
    stock_basic_cte = ""
    stock_basic_join = ""
    change_reason_sql = """
    CASE
      WHEN previous_factor.ts_code IS NULL THEN 'new_current_code'
      ELSE 'factor_changed'
    END
    """
    if silver_stock_basic_path is not None:
        stock_basic_source = read_parquet(silver_stock_basic_path, hive_partitioning=False)
        stock_basic_cte = f""",
stock_basic AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(list_date AS DATE) AS list_date
  FROM {stock_basic_source}
)"""
        stock_basic_join = """
LEFT JOIN stock_basic
  ON current_factor.ts_code = stock_basic.ts_code
"""
        change_reason_sql = f"""
    CASE
      WHEN previous_factor.ts_code IS NULL
       AND stock_basic.list_date > DATE {duckdb_string(previous_trade_date)}
       AND stock_basic.list_date <= DATE {duckdb_string(trade_date)}
        THEN 'new_current_code'
      WHEN previous_factor.ts_code IS NULL THEN 'missing_previous_factor'
      ELSE 'factor_changed'
    END
        """
    return f"""
WITH current_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(adj_factor AS DOUBLE) AS current_adj_factor
  FROM {current_source}
),
previous_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(adj_factor AS DOUBLE) AS previous_adj_factor
  FROM {previous_source}
){stock_basic_cte}
SELECT
  current_factor.ts_code,
  current_factor.current_adj_factor,
  previous_factor.previous_adj_factor,
  {change_reason_sql} AS change_reason
FROM current_factor
LEFT JOIN previous_factor
  ON current_factor.ts_code = previous_factor.ts_code
{stock_basic_join}
WHERE previous_factor.ts_code IS NULL
   OR current_factor.current_adj_factor IS DISTINCT FROM previous_factor.previous_adj_factor
ORDER BY current_factor.ts_code
"""


def build_gold_stk_mins_qfq_factor_repair_plan(
    *,
    current_adj_factor_path: Path,
    previous_adj_factor_path: Path,
    silver_stock_basic_path: Path,
    trade_date: str,
    previous_trade_date: str,
    sample_limit: int = QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT,
) -> GoldStkMinsQfqFactorRepairPlan:
    if sample_limit <= 0:
        raise ValueError("sample_limit must be positive.")
    date.fromisoformat(trade_date)
    date.fromisoformat(previous_trade_date)
    sql = build_adj_factor_changed_codes_sql(
        current_adj_factor_path=current_adj_factor_path,
        previous_adj_factor_path=previous_adj_factor_path,
        silver_stock_basic_path=silver_stock_basic_path,
        trade_date=trade_date,
        previous_trade_date=previous_trade_date,
    )
    with connect_configured_duckdb() as connection:
        rows = connection.execute(sql).fetchall()

    factor_changed_codes = tuple(
        str(ts_code)
        for ts_code, _current_factor, _previous_factor, change_reason in rows
        if change_reason == QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED
    )
    new_current_codes = tuple(
        str(ts_code)
        for ts_code, _current_factor, _previous_factor, change_reason in rows
        if change_reason == QFQ_FACTOR_REPAIR_REASON_NEW_CURRENT_CODE
    )
    missing_previous_codes = tuple(
        str(ts_code)
        for ts_code, _current_factor, _previous_factor, change_reason in rows
        if change_reason == QFQ_FACTOR_REPAIR_REASON_MISSING_PREVIOUS_FACTOR
    )

    if missing_previous_codes:
        reason = QFQ_FACTOR_REPAIR_REASON_MISSING_PREVIOUS_FACTOR
    elif factor_changed_codes:
        reason = QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED
    elif new_current_codes:
        reason = QFQ_FACTOR_REPAIR_REASON_NEW_CURRENT_CODE
    else:
        reason = QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED

    return GoldStkMinsQfqFactorRepairPlan(
        trade_date=trade_date,
        previous_trade_date=previous_trade_date,
        reason=reason,
        can_execute_repair=not missing_previous_codes,
        repair_required=bool(factor_changed_codes),
        detected_change_code_count=len(rows),
        repair_required_code_count=len(factor_changed_codes),
        factor_changed_code_count=len(factor_changed_codes),
        new_current_code_count=len(new_current_codes),
        missing_previous_factor_code_count=len(missing_previous_codes),
        repair_required_codes=factor_changed_codes,
        factor_changed_code_samples=factor_changed_codes[:sample_limit],
        new_current_code_samples=new_current_codes[:sample_limit],
        missing_previous_factor_code_samples=missing_previous_codes[:sample_limit],
    )


def build_gold_stk_mins_qfq_factor_repair_check_metadata(
    plan: GoldStkMinsQfqFactorRepairPlan,
    *,
    repaired_code_count: int = 0,
    skipped_code_count: int = 0,
    failed_code_count: int = 0,
    rewritten_file_count: int = 0,
    rewritten_row_count: int = 0,
    repaired_file_samples: Sequence[str] = (),
    execution_model: str = "freq_year_batch",
    planned_batch_count: int = 0,
    executed_batch_count: int = 0,
    non_empty_batch_count: int = 0,
) -> dict[str, Any]:
    for name, value in (
        ("repaired_code_count", repaired_code_count),
        ("skipped_code_count", skipped_code_count),
        ("failed_code_count", failed_code_count),
        ("rewritten_file_count", rewritten_file_count),
        ("rewritten_row_count", rewritten_row_count),
        ("planned_batch_count", planned_batch_count),
        ("executed_batch_count", executed_batch_count),
        ("non_empty_batch_count", non_empty_batch_count),
    ):
        if value < 0:
            raise ValueError(f"{name} must be non-negative.")
    return build_check_metadata(
        check_scope=CheckScope.RECONCILIATION,
        checked_row_count=plan.detected_change_code_count,
        failed_row_count=plan.missing_previous_factor_code_count + failed_code_count,
        extra_metadata={
            "reason": plan.reason,
            "trade_date": plan.trade_date,
            "previous_trade_date": plan.previous_trade_date,
            "can_execute_repair": plan.can_execute_repair,
            "repair_required": plan.repair_required,
            "repaired_code_count": repaired_code_count,
            "skipped_code_count": skipped_code_count,
            "failed_code_count": failed_code_count,
            "rewritten_file_count": rewritten_file_count,
            "rewritten_row_count": rewritten_row_count,
            "execution_model": execution_model,
            "planned_batch_count": planned_batch_count,
            "executed_batch_count": executed_batch_count,
            "non_empty_batch_count": non_empty_batch_count,
            "repaired_file_samples": list(
                repaired_file_samples[:QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT]
            ),
            "detected_change_code_count": plan.detected_change_code_count,
            "repair_required_code_count": plan.repair_required_code_count,
            "factor_changed_code_count": plan.factor_changed_code_count,
            "new_current_code_count": plan.new_current_code_count,
            "missing_previous_factor_code_count": (
                plan.missing_previous_factor_code_count
            ),
            "factor_changed_code_samples": list(plan.factor_changed_code_samples),
            "new_current_code_samples": list(plan.new_current_code_samples),
            "missing_previous_factor_code_samples": (
                list(plan.missing_previous_factor_code_samples)
            ),
        },
    )


def write_gold_stk_mins_qfq_rows_to_year_files(
    *,
    lake_root: Path,
    freq: int | str,
    qfq_select_sql: str,
    replace_trade_dates: Sequence[str],
    fail_if_target_exists: bool = False,
    allow_empty_replacement: bool = False,
) -> tuple[GoldStkMinsQfqWriteResult, ...]:
    normalized_freq = normalize_stk_mins_freq(freq)
    allowed_trade_dates = _normalize_trade_dates(replace_trade_dates)
    allowed_dates_sql = _date_values_sql(allowed_trade_dates)

    with connect_configured_duckdb() as connection:
        _create_replacement_rows_table(connection, qfq_select_sql)
        replacement_row_count = int(
            connection.execute("SELECT count(*) FROM qfq_replacement_rows").fetchone()[0]
        )
        if replacement_row_count == 0 and allow_empty_replacement:
            return ()
        _validate_replacement_rows(
            connection,
            normalized_freq=normalized_freq,
            allowed_dates_sql=allowed_dates_sql,
            replacement_row_count=replacement_row_count,
        )
        groups = connection.execute(
            """
            SELECT
              ts_code,
              strftime(trade_date, '%Y') AS year,
              count(*) AS replacement_row_count
            FROM qfq_replacement_rows
            GROUP BY ts_code, year
            ORDER BY ts_code, year
            """
        ).fetchall()

        results: list[GoldStkMinsQfqWriteResult] = []
        for ts_code, year, replacement_row_count in groups:
            target_path = gold_stk_mins_qfq_path(
                lake_root,
                normalized_freq,
                str(ts_code),
                str(year),
            )
            row_count = _write_gold_qfq_group_to_year_file(
                connection,
                target_path=target_path,
                normalized_freq=normalized_freq,
                ts_code=str(ts_code),
                year=str(year),
                fail_if_target_exists=fail_if_target_exists,
            )
            results.append(
                GoldStkMinsQfqWriteResult(
                    path=target_path,
                    ts_code=str(ts_code),
                    year=str(year),
                    row_count=row_count,
                    replacement_row_count=int(replacement_row_count),
                )
            )

    return tuple(results)


def rewrite_qfq_year_file_for_stock_code(
    *,
    lake_root: Path,
    freq: int | str,
    stock_code: str,
    year: int | str,
    replacement_select_sql: str,
    replace_trade_dates: Sequence[str],
) -> GoldStkMinsQfqWriteResult:
    normalized_year = _normalize_year(year)
    _validate_replacement_select_scope(
        replacement_select_sql,
        stock_code=stock_code,
        year=normalized_year,
    )
    results = write_gold_stk_mins_qfq_rows_to_year_files(
        lake_root=lake_root,
        freq=freq,
        qfq_select_sql=replacement_select_sql,
        replace_trade_dates=replace_trade_dates,
    )
    if len(results) != 1 or results[0].ts_code != stock_code or results[0].year != normalized_year:
        raise ValueError(
            "qfq repair replacement must target exactly one stock code and year: "
            f"stock_code={stock_code!r}, year={normalized_year!r}."
        )
    return results[0]


def _create_replacement_rows_table(
    connection: duckdb.DuckDBPyConnection,
    qfq_select_sql: str,
) -> None:
    select_columns = ",\n    ".join(
        f"CAST({column.name} AS {column.type}) AS {column.name}"
        for column in GOLD_STK_MINS_QFQ_SCHEMA
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE qfq_replacement_rows AS
        SELECT
          {select_columns}
        FROM ({qfq_select_sql})
        """
    )


def _validate_replacement_rows(
    connection: duckdb.DuckDBPyConnection,
    *,
    normalized_freq: int,
    allowed_dates_sql: str,
    replacement_row_count: int | None = None,
) -> None:
    row_count = (
        replacement_row_count
        if replacement_row_count is not None
        else connection.execute("SELECT count(*) FROM qfq_replacement_rows").fetchone()[0]
    )
    if row_count == 0:
        raise ValueError("qfq replacement rows are empty; refusing to write gold qfq files.")

    null_key_count = connection.execute(
        """
        SELECT count(*)
        FROM qfq_replacement_rows
        WHERE ts_code IS NULL OR trade_date IS NULL OR trade_time IS NULL
        """
    ).fetchone()[0]
    if null_key_count:
        raise ValueError(f"qfq replacement rows contain null business keys: {null_key_count}.")

    freq_mismatch_count = connection.execute(
        f"""
        SELECT count(*)
        FROM qfq_replacement_rows
        WHERE freq <> {normalized_freq}
        """
    ).fetchone()[0]
    if freq_mismatch_count:
        raise ValueError(
            "qfq replacement rows contain freq values that do not match the target freq: "
            f"{freq_mismatch_count}."
        )

    outside_date_count = connection.execute(
        f"""
        SELECT count(*)
        FROM qfq_replacement_rows
        WHERE trade_date NOT IN ({allowed_dates_sql})
        """
    ).fetchone()[0]
    if outside_date_count:
        raise ValueError(
            "qfq replacement rows contain trade_date values outside replace_trade_dates: "
            f"{outside_date_count}."
        )

    duplicate_count = connection.execute(
        """
        SELECT count(*)
        FROM (
          SELECT ts_code, trade_time, count(*) AS row_count
          FROM qfq_replacement_rows
          GROUP BY ts_code, trade_time
          HAVING count(*) > 1
        )
        """
    ).fetchone()[0]
    if duplicate_count:
        raise ValueError(
            "qfq replacement rows contain duplicate ts_code + trade_time keys: "
            f"{duplicate_count}."
        )


def _write_gold_qfq_group_to_year_file(
    connection: duckdb.DuckDBPyConnection,
    *,
    target_path: Path,
    normalized_freq: int,
    ts_code: str,
    year: str,
    fail_if_target_exists: bool,
) -> int:
    if target_path.exists():
        if fail_if_target_exists:
            raise FileExistsError(f"Gold qfq target already exists: {target_path}")
        _validate_existing_year_file(
            connection,
            target_path=target_path,
            normalized_freq=normalized_freq,
            ts_code=ts_code,
            year=year,
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_path_for(target_path)
    if temp_path.exists():
        temp_path.unlink()

    connection.execute(
        copy_query_to_parquet(
            f"""
            WITH replacement_group AS (
              SELECT {', '.join(GOLD_STK_MINS_QFQ_COLUMNS)}
              FROM qfq_replacement_rows
              WHERE ts_code = {duckdb_string(ts_code)}
                AND strftime(trade_date, '%Y') = {duckdb_string(year)}
            ),
            existing_rows AS (
              {_existing_rows_select(target_path)}
            ),
            merged_rows AS (
              SELECT {', '.join(GOLD_STK_MINS_QFQ_COLUMNS)}
              FROM existing_rows
              WHERE trade_date NOT IN (
                SELECT DISTINCT trade_date FROM replacement_group
              )
              UNION ALL
              SELECT {', '.join(GOLD_STK_MINS_QFQ_COLUMNS)}
              FROM replacement_group
            )
            SELECT {', '.join(GOLD_STK_MINS_QFQ_COLUMNS)}
            FROM merged_rows
            ORDER BY trade_date, trade_time
            """,
            temp_path,
        )
    )
    _validate_written_year_file(
        connection,
        temp_path=temp_path,
        normalized_freq=normalized_freq,
        ts_code=ts_code,
        year=year,
    )
    row_count = connection.execute(
        f"SELECT count(*) FROM {read_parquet(temp_path, hive_partitioning=False)}"
    ).fetchone()[0]
    os.replace(temp_path, target_path)
    return int(row_count)


def _existing_rows_select(target_path: Path) -> str:
    if not target_path.exists():
        return _empty_gold_qfq_select()
    select_columns = ", ".join(
        f"CAST({column.name} AS {column.type}) AS {column.name}"
        for column in GOLD_STK_MINS_QFQ_SCHEMA
    )
    return f"""
    SELECT {select_columns}
    FROM {read_parquet(target_path, hive_partitioning=False)}
    """


def _empty_gold_qfq_select() -> str:
    select_columns = ", ".join(
        f"CAST(NULL AS {column.type}) AS {column.name}"
        for column in GOLD_STK_MINS_QFQ_SCHEMA
    )
    return f"SELECT {select_columns} WHERE false"


def _validate_existing_year_file(
    connection: duckdb.DuckDBPyConnection,
    *,
    target_path: Path,
    normalized_freq: int,
    ts_code: str,
    year: str,
) -> None:
    invalid_count = connection.execute(
        f"""
        SELECT count(*)
        FROM {read_parquet(target_path, hive_partitioning=False)}
        WHERE CAST(freq AS INTEGER) <> {normalized_freq}
           OR CAST(ts_code AS VARCHAR) <> {duckdb_string(ts_code)}
           OR strftime(CAST(trade_date AS DATE), '%Y') <> {duckdb_string(year)}
        """
    ).fetchone()[0]
    if invalid_count:
        raise ValueError(
            "Existing gold qfq year file contains rows that do not match its "
            f"freq/ts_code/year path: {target_path}."
        )


def _validate_written_year_file(
    connection: duckdb.DuckDBPyConnection,
    *,
    temp_path: Path,
    normalized_freq: int,
    ts_code: str,
    year: str,
) -> None:
    invalid_count = connection.execute(
        f"""
        SELECT count(*)
        FROM {read_parquet(temp_path, hive_partitioning=False)}
        WHERE freq <> {normalized_freq}
           OR ts_code <> {duckdb_string(ts_code)}
           OR strftime(trade_date, '%Y') <> {duckdb_string(year)}
        """
    ).fetchone()[0]
    if invalid_count:
        temp_path.unlink(missing_ok=True)
        raise ValueError(
            "Written gold qfq year file contains rows that do not match its "
            f"freq/ts_code/year path: {temp_path}."
        )

    duplicate_count = connection.execute(
        f"""
        SELECT count(*)
        FROM (
          SELECT ts_code, trade_time, count(*) AS row_count
          FROM {read_parquet(temp_path, hive_partitioning=False)}
          GROUP BY ts_code, trade_time
          HAVING count(*) > 1
        )
        """
    ).fetchone()[0]
    if duplicate_count:
        temp_path.unlink(missing_ok=True)
        raise ValueError(
            "Written gold qfq year file contains duplicate ts_code + trade_time keys: "
            f"{duplicate_count}."
        )


def _validate_replacement_select_scope(
    replacement_select_sql: str,
    *,
    stock_code: str,
    year: str,
) -> None:
    with connect_configured_duckdb() as connection:
        _create_replacement_rows_table(connection, replacement_select_sql)
        row_count, out_of_scope_count = connection.execute(
            f"""
            SELECT
              count(*) AS row_count,
              count(*) FILTER (
                WHERE ts_code <> {duckdb_string(stock_code)}
                   OR strftime(trade_date, '%Y') <> {duckdb_string(year)}
              ) AS out_of_scope_count
            FROM qfq_replacement_rows
            """
        ).fetchone()
    if row_count == 0:
        raise ValueError("qfq repair replacement rows are empty.")
    if out_of_scope_count:
        raise ValueError(
            "qfq repair replacement must target exactly one stock code and year: "
            f"stock_code={stock_code!r}, year={year!r}."
        )


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("At least one parquet path is required.")
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    path_list = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{path_list}], hive_partitioning=false, union_by_name=true)"


def _validate_repair_detection_args(
    *,
    silver_stock_basic_path: Path | None,
    trade_date: str | None,
    previous_trade_date: str | None,
) -> None:
    args = (silver_stock_basic_path, trade_date, previous_trade_date)
    if any(item is not None for item in args) and not all(
        item is not None for item in args
    ):
        raise ValueError(
            "silver_stock_basic_path, trade_date, and previous_trade_date must "
            "be provided together."
        )
    if trade_date is not None:
        date.fromisoformat(trade_date)
    if previous_trade_date is not None:
        date.fromisoformat(previous_trade_date)


def _normalize_trade_dates(trade_dates: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({date.fromisoformat(str(item).strip()).isoformat() for item in trade_dates}))
    if not normalized:
        raise ValueError("replace_trade_dates must not be empty.")
    return normalized


def _normalize_year(year: int | str) -> str:
    year_value = str(year)
    if len(year_value) != 4 or not year_value.isdigit():
        raise ValueError("qfq repair year must be a four-digit year.")
    return year_value


def _date_values_sql(trade_dates: Sequence[str]) -> str:
    return ", ".join(f"DATE {duckdb_string(item)}" for item in trade_dates)


def _temp_path_for(target_path: Path) -> Path:
    return target_path.with_suffix(target_path.suffix + ".tmp")
