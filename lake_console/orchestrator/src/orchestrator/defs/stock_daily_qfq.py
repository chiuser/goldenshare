from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import duckdb

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_stock_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_QFQ_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


GOLD_STOCK_DAILY_QFQ_COLUMNS = tuple(
    column.name for column in GOLD_STOCK_DAILY_QFQ_SCHEMA
)
GOLD_STOCK_DAILY_QFQ_COLUMN_TYPES = {
    column.name: column.type for column in GOLD_STOCK_DAILY_QFQ_SCHEMA
}
STOCK_DAILY_QFQ_PREVIOUS_LOOKUP_LIMIT = 20
GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME = (
    "gold_stock_daily_qfq_factor_repair_plan_evaluated"
)
GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT = 500
GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED = "no_factor_changed"
GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED = "factor_changed"
GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT = 20


@dataclass(frozen=True)
class GoldStockDailyQfqPartitionWriteResult:
    path: Path
    stock_daily_file_path: Path
    trade_adj_factor_file_path: Path
    as_of_adj_factor_file_path: Path
    previous_lookup_trade_date_count: int
    previous_stock_daily_file_count: int
    previous_adj_factor_file_count: int
    source_row_count: int
    output_row_count: int
    missing_previous_row_count: int
    observed_columns: tuple[str, ...]


@dataclass(frozen=True)
class GoldStockDailyQfqFactorRepairPlan:
    qfq_factor_trade_date: str
    previous_trade_date: str | None
    reason: str
    can_execute_repair: bool
    repair_required: bool
    repair_required_codes: tuple[str, ...]
    repair_required_codes_hash: str

    @property
    def repair_required_code_count(self) -> int:
        return len(self.repair_required_codes)


@dataclass(frozen=True)
class GoldStockDailyQfqFactorRepairResult:
    plan: GoldStockDailyQfqFactorRepairPlan
    repair_start_trade_date: str | None
    repair_end_trade_date: str
    selected_partition_count: int
    rewritten_partition_count: int
    rewritten_row_count: int
    repaired_code_count: int
    repaired_file_samples: tuple[str, ...]
    upstream_batch_id: str


@dataclass(frozen=True)
class GoldStockDailyQfqRepairPartitionWriteResult:
    path: Path
    replacement_row_count: int
    output_row_count: int


def gold_stock_daily_qfq_factor_repair_codes_hash(
    stock_codes: Sequence[str],
) -> str:
    normalized_codes = tuple(
        sorted(
            {
                str(stock_code).strip().upper()
                for stock_code in stock_codes
                if str(stock_code).strip()
            }
        )
    )
    return hashlib.sha256("\n".join(normalized_codes).encode("utf-8")).hexdigest()


def load_stock_daily_qfq_previous_lookup_trade_dates(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    limit: int = STOCK_DAILY_QFQ_PREVIOUS_LOOKUP_LIMIT,
) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("previous lookup limit must be positive.")

    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing silver trade calendar file: {calendar_path}")

    rows = connection.execute(
        f"""
        SELECT strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS trade_date
        FROM {read_parquet(calendar_path, hive_partitioning=False)}
        WHERE CAST(exchange AS VARCHAR) = 'SSE'
          AND CAST(is_open AS BOOLEAN)
          AND CAST(trade_date AS DATE) < DATE {duckdb_string(trade_date)}
        ORDER BY CAST(trade_date AS DATE) DESC
        LIMIT {int(limit)}
        """
    ).fetchall()
    return tuple(reversed([str(row[0]) for row in rows]))


def build_stock_daily_qfq_factor_changed_codes_sql(
    *,
    current_adj_factor_path: Path,
    previous_adj_factor_path: Path,
) -> str:
    return f"""
WITH current_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(adj_factor AS DOUBLE) AS current_adj_factor
  FROM {read_parquet(current_adj_factor_path, hive_partitioning=False)}
),
previous_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(adj_factor AS DOUBLE) AS previous_adj_factor
  FROM {read_parquet(previous_adj_factor_path, hive_partitioning=False)}
)
SELECT current_adj_factor.ts_code
FROM current_adj_factor
INNER JOIN previous_adj_factor
  ON current_adj_factor.ts_code = previous_adj_factor.ts_code
WHERE current_adj_factor.current_adj_factor IS NOT NULL
  AND previous_adj_factor.previous_adj_factor IS NOT NULL
  AND abs(current_adj_factor.current_adj_factor - previous_adj_factor.previous_adj_factor) > 1e-12
ORDER BY current_adj_factor.ts_code
"""


def build_gold_stock_daily_qfq_factor_repair_plan(
    *,
    connection: duckdb.DuckDBPyConnection,
    current_adj_factor_path: Path,
    previous_adj_factor_path: Path | None,
    qfq_factor_trade_date: str,
    previous_trade_date: str | None,
) -> GoldStockDailyQfqFactorRepairPlan:
    normalized_trade_date = date.fromisoformat(qfq_factor_trade_date).isoformat()
    if previous_trade_date is None or previous_adj_factor_path is None:
        return GoldStockDailyQfqFactorRepairPlan(
            qfq_factor_trade_date=normalized_trade_date,
            previous_trade_date=None,
            reason=GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED,
            can_execute_repair=True,
            repair_required=False,
            repair_required_codes=(),
            repair_required_codes_hash=gold_stock_daily_qfq_factor_repair_codes_hash(()),
        )
    for input_path, label in (
        (current_adj_factor_path, "current adj factor"),
        (previous_adj_factor_path, "previous adj factor"),
    ):
        if not input_path.exists():
            raise FileNotFoundError(f"Missing {label} file: {input_path}")

    rows = connection.execute(
        build_stock_daily_qfq_factor_changed_codes_sql(
            current_adj_factor_path=current_adj_factor_path,
            previous_adj_factor_path=previous_adj_factor_path,
        )
    ).fetchall()
    repair_required_codes = tuple(str(row[0]).strip().upper() for row in rows)
    repair_required = bool(repair_required_codes)
    return GoldStockDailyQfqFactorRepairPlan(
        qfq_factor_trade_date=normalized_trade_date,
        previous_trade_date=date.fromisoformat(previous_trade_date).isoformat(),
        reason=(
            GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED
            if repair_required
            else GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED
        ),
        can_execute_repair=True,
        repair_required=repair_required,
        repair_required_codes=repair_required_codes,
        repair_required_codes_hash=gold_stock_daily_qfq_factor_repair_codes_hash(
            repair_required_codes
        ),
    )


def build_stock_daily_qfq_select_sql(
    *,
    stock_daily_path: Path,
    trade_adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
    trade_date: str,
    as_of_trade_date: str,
) -> str:
    return f"""
{_stock_daily_qfq_base_ctes_sql(
    stock_daily_path=stock_daily_path,
    trade_adj_factor_path=trade_adj_factor_path,
    previous_stock_daily_paths=previous_stock_daily_paths,
    previous_adj_factor_paths=previous_adj_factor_paths,
    as_of_adj_factor_path=as_of_adj_factor_path,
    trade_date=trade_date,
    as_of_trade_date=as_of_trade_date,
)}
, priced_rows AS (
  SELECT
    ts_code,
    trade_date,
    open_qfq AS open,
    high_qfq AS high,
    low_qfq AS low,
    close_qfq AS close,
    CASE
      WHEN previous_trade_date IS NULL THEN CAST(0 AS DOUBLE)
      ELSE previous_close * previous_adj_factor / as_of_adj_factor
    END AS pre_close,
    vol,
    amount
  FROM joined_rows
  WHERE trade_adj_factor IS NOT NULL
    AND as_of_adj_factor IS NOT NULL
    AND (previous_trade_date IS NULL OR previous_adj_factor IS NOT NULL)
)
SELECT
  ts_code,
  trade_date,
  CAST(open AS DOUBLE) AS open,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(close AS DOUBLE) AS close,
  CAST(pre_close AS DOUBLE) AS pre_close,
  CAST(
    CASE
      WHEN pre_close = 0 THEN 0
      ELSE close - pre_close
    END AS DOUBLE
  ) AS change_amount,
  CAST(
    CASE
      WHEN pre_close = 0 THEN 0
      ELSE (close - pre_close) / pre_close * 100
    END AS DOUBLE
  ) AS pct_chg,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount
FROM priced_rows
ORDER BY ts_code, trade_date
"""


def build_stock_daily_qfq_coverage_sql(
    *,
    stock_daily_path: Path,
    trade_adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
    trade_date: str,
    as_of_trade_date: str,
) -> str:
    return f"""
{_stock_daily_qfq_base_ctes_sql(
    stock_daily_path=stock_daily_path,
    trade_adj_factor_path=trade_adj_factor_path,
    previous_stock_daily_paths=previous_stock_daily_paths,
    previous_adj_factor_paths=previous_adj_factor_paths,
    as_of_adj_factor_path=as_of_adj_factor_path,
    trade_date=trade_date,
    as_of_trade_date=as_of_trade_date,
)}
SELECT
  count(*) AS source_row_count,
  count(*) FILTER (
    WHERE trade_adj_factor IS NOT NULL
      AND as_of_adj_factor IS NOT NULL
      AND (previous_trade_date IS NULL OR previous_adj_factor IS NOT NULL)
  ) AS qfq_output_row_count,
  count(*) FILTER (WHERE trade_adj_factor IS NULL)
    AS missing_trade_adj_factor_row_count,
  count(*) FILTER (WHERE as_of_adj_factor IS NULL)
    AS missing_as_of_adj_factor_row_count,
  count(*) FILTER (WHERE previous_trade_date IS NULL)
    AS missing_previous_row_count,
  count(*) FILTER (
    WHERE previous_trade_date IS NOT NULL AND previous_adj_factor IS NULL
  ) AS missing_previous_adj_factor_row_count
FROM joined_rows
"""


def write_gold_stock_daily_qfq_partition(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    previous_lookup_trade_dates: Sequence[str],
    as_of_trade_date: str | None = None,
    as_of_adj_factor_path: Path | None = None,
) -> GoldStockDailyQfqPartitionWriteResult:
    resolved_as_of_trade_date = as_of_trade_date or trade_date
    stock_daily_path = silver_stock_daily_path(lake_root, trade_date)
    trade_adj_factor_path = silver_adj_factor_path(lake_root, trade_date)
    resolved_as_of_adj_factor_path = as_of_adj_factor_path or silver_adj_factor_path(
        lake_root,
        resolved_as_of_trade_date,
    )
    target_path = gold_stock_daily_qfq_path(lake_root, trade_date)

    for input_path, label in (
        (stock_daily_path, "silver stock daily"),
        (trade_adj_factor_path, "silver trade-date adj factor"),
        (resolved_as_of_adj_factor_path, "silver as-of adj factor"),
    ):
        if not input_path.exists():
            raise FileNotFoundError(f"Missing {label} file: {input_path}")

    previous_stock_daily_paths = tuple(
        path
        for path in (
            silver_stock_daily_path(lake_root, previous_trade_date)
            for previous_trade_date in previous_lookup_trade_dates
        )
        if path.exists()
    )
    previous_adj_factor_paths = tuple(
        path
        for path in (
            silver_adj_factor_path(lake_root, previous_trade_date)
            for previous_trade_date in previous_lookup_trade_dates
        )
        if path.exists()
    )
    coverage_row = connection.execute(
        build_stock_daily_qfq_coverage_sql(
            stock_daily_path=stock_daily_path,
            trade_adj_factor_path=trade_adj_factor_path,
            previous_stock_daily_paths=previous_stock_daily_paths,
            previous_adj_factor_paths=previous_adj_factor_paths,
            as_of_adj_factor_path=resolved_as_of_adj_factor_path,
            trade_date=trade_date,
            as_of_trade_date=resolved_as_of_trade_date,
        )
    ).fetchone()
    source_row_count = int(coverage_row[0])
    output_row_count = int(coverage_row[1])
    missing_trade_adj_factor_row_count = int(coverage_row[2])
    missing_as_of_adj_factor_row_count = int(coverage_row[3])
    missing_previous_row_count = int(coverage_row[4])
    missing_previous_adj_factor_row_count = int(coverage_row[5])

    if source_row_count <= 0:
        raise ValueError(f"Silver stock daily has no rows for {trade_date}.")
    if missing_trade_adj_factor_row_count:
        raise ValueError(
            "Missing trade-date adj factor rows for stock daily qfq: "
            f"trade_date={trade_date}, "
            f"missing_row_count={missing_trade_adj_factor_row_count}."
        )
    if missing_as_of_adj_factor_row_count:
        raise ValueError(
            "Missing as-of adj factor rows for stock daily qfq: "
            f"as_of_trade_date={resolved_as_of_trade_date}, "
            f"missing_row_count={missing_as_of_adj_factor_row_count}."
        )
    if missing_previous_adj_factor_row_count:
        raise ValueError(
            "Previous stock daily rows exist but previous adj factor rows are missing: "
            f"trade_date={trade_date}, "
            f"missing_row_count={missing_previous_adj_factor_row_count}."
        )
    if output_row_count != source_row_count:
        raise ValueError(
            "Stock daily qfq output row count must match source row count: "
            f"source_row_count={source_row_count}, output_row_count={output_row_count}."
        )

    _replace_parquet_from_query(
        connection,
        build_stock_daily_qfq_select_sql(
            stock_daily_path=stock_daily_path,
            trade_adj_factor_path=trade_adj_factor_path,
            previous_stock_daily_paths=previous_stock_daily_paths,
            previous_adj_factor_paths=previous_adj_factor_paths,
            as_of_adj_factor_path=resolved_as_of_adj_factor_path,
            trade_date=trade_date,
            as_of_trade_date=resolved_as_of_trade_date,
        ),
        target_path,
    )
    observed_columns = tuple(
        _column_names(connection, target_path, hive_partitioning=False)
    )
    written_row_count = _row_count(connection, target_path, hive_partitioning=False)
    if written_row_count != output_row_count:
        raise ValueError(
            "Written stock daily qfq row count changed after parquet write: "
            f"expected={output_row_count}, actual={written_row_count}."
        )

    return GoldStockDailyQfqPartitionWriteResult(
        path=target_path,
        stock_daily_file_path=stock_daily_path,
        trade_adj_factor_file_path=trade_adj_factor_path,
        as_of_adj_factor_file_path=resolved_as_of_adj_factor_path,
        previous_lookup_trade_date_count=len(tuple(previous_lookup_trade_dates)),
        previous_stock_daily_file_count=len(previous_stock_daily_paths),
        previous_adj_factor_file_count=len(previous_adj_factor_paths),
        source_row_count=source_row_count,
        output_row_count=output_row_count,
        missing_previous_row_count=missing_previous_row_count,
        observed_columns=observed_columns,
    )


def execute_gold_stock_daily_qfq_factor_repair(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    qfq_factor_trade_date: str,
    expected_trade_dates: Sequence[str],
    repair_required_codes_hash: str,
    upstream_batch_id: str,
) -> GoldStockDailyQfqFactorRepairResult:
    normalized_trade_date = date.fromisoformat(qfq_factor_trade_date).isoformat()
    normalized_expected_dates = _normalize_expected_trade_dates(expected_trade_dates)
    if normalized_trade_date not in normalized_expected_dates:
        raise ValueError(
            "qfq_factor_trade_date must be in expected trade dates: "
            f"{normalized_trade_date}."
        )
    previous_trade_date = _previous_expected_trade_date(
        normalized_expected_dates,
        normalized_trade_date,
    )
    plan = build_gold_stock_daily_qfq_factor_repair_plan(
        connection=connection,
        current_adj_factor_path=silver_adj_factor_path(lake_root, normalized_trade_date),
        previous_adj_factor_path=(
            silver_adj_factor_path(lake_root, previous_trade_date)
            if previous_trade_date is not None
            else None
        ),
        qfq_factor_trade_date=normalized_trade_date,
        previous_trade_date=previous_trade_date,
    )
    if repair_required_codes_hash != plan.repair_required_codes_hash:
        raise ValueError(
            "gold stock daily qfq repair_required_codes_hash does not match "
            "the affected code set computed from silver_adj_factor."
        )
    if not plan.repair_required:
        return GoldStockDailyQfqFactorRepairResult(
            plan=plan,
            repair_start_trade_date=None,
            repair_end_trade_date=normalized_trade_date,
            selected_partition_count=0,
            rewritten_partition_count=0,
            rewritten_row_count=0,
            repaired_code_count=0,
            repaired_file_samples=(),
            upstream_batch_id=upstream_batch_id,
        )

    repair_start_trade_date = _effective_repair_start_trade_date(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=normalized_expected_dates,
        end_trade_date=normalized_trade_date,
        repair_required_codes=plan.repair_required_codes,
    )
    selected_trade_dates = _expected_trade_dates_between(
        normalized_expected_dates,
        start_trade_date=repair_start_trade_date,
        end_trade_date=normalized_trade_date,
    )
    _require_repair_input_files(
        lake_root=lake_root,
        selected_trade_dates=selected_trade_dates,
        as_of_trade_date=normalized_trade_date,
    )

    write_results = []
    for target_trade_date in selected_trade_dates:
        previous_lookup_trade_dates = load_stock_daily_qfq_previous_lookup_trade_dates(
            connection=connection,
            lake_root=lake_root,
            trade_date=target_trade_date,
        )
        write_results.append(
            write_gold_stock_daily_qfq_factor_repair_partition(
                connection=connection,
                lake_root=lake_root,
                trade_date=target_trade_date,
                as_of_trade_date=normalized_trade_date,
                previous_lookup_trade_dates=previous_lookup_trade_dates,
                repair_required_codes=plan.repair_required_codes,
            )
        )

    return GoldStockDailyQfqFactorRepairResult(
        plan=plan,
        repair_start_trade_date=repair_start_trade_date,
        repair_end_trade_date=normalized_trade_date,
        selected_partition_count=len(selected_trade_dates),
        rewritten_partition_count=len(write_results),
        rewritten_row_count=sum(result.replacement_row_count for result in write_results),
        repaired_code_count=plan.repair_required_code_count,
        repaired_file_samples=tuple(str(result.path) for result in write_results[:20]),
        upstream_batch_id=upstream_batch_id,
    )


def write_gold_stock_daily_qfq_factor_repair_partition(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    as_of_trade_date: str,
    previous_lookup_trade_dates: Sequence[str],
    repair_required_codes: Sequence[str],
) -> GoldStockDailyQfqRepairPartitionWriteResult:
    target_path = gold_stock_daily_qfq_path(lake_root, trade_date)
    if not target_path.exists():
        raise FileNotFoundError(f"Missing existing gold stock daily qfq file: {target_path}")
    stock_daily_path = silver_stock_daily_path(lake_root, trade_date)
    trade_adj_factor_path = silver_adj_factor_path(lake_root, trade_date)
    as_of_adj_factor_path = silver_adj_factor_path(lake_root, as_of_trade_date)
    for input_path, label in (
        (stock_daily_path, "silver stock daily"),
        (trade_adj_factor_path, "silver trade-date adj factor"),
        (as_of_adj_factor_path, "silver as-of adj factor"),
    ):
        if not input_path.exists():
            raise FileNotFoundError(f"Missing {label} file: {input_path}")

    normalized_codes = _normalize_repair_required_codes(repair_required_codes)
    previous_stock_daily_paths = tuple(
        path
        for path in (
            silver_stock_daily_path(lake_root, previous_trade_date)
            for previous_trade_date in previous_lookup_trade_dates
        )
        if path.exists()
    )
    previous_adj_factor_paths = tuple(
        path
        for path in (
            silver_adj_factor_path(lake_root, previous_trade_date)
            for previous_trade_date in previous_lookup_trade_dates
        )
        if path.exists()
    )
    replacement_sql = build_stock_daily_qfq_select_sql(
        stock_daily_path=stock_daily_path,
        trade_adj_factor_path=trade_adj_factor_path,
        previous_stock_daily_paths=previous_stock_daily_paths,
        previous_adj_factor_paths=previous_adj_factor_paths,
        as_of_adj_factor_path=as_of_adj_factor_path,
        trade_date=trade_date,
        as_of_trade_date=as_of_trade_date,
    )
    source_count = _repair_required_source_row_count(
        connection,
        stock_daily_path=stock_daily_path,
        trade_date=trade_date,
        repair_required_codes=normalized_codes,
    )
    replacement_count = _repair_required_replacement_row_count(
        connection,
        replacement_sql=replacement_sql,
        repair_required_codes=normalized_codes,
    )
    if replacement_count != source_count:
        raise ValueError(
            "Gold stock daily qfq repair replacement row count must match "
            "affected source row count: "
            f"trade_date={trade_date}, source_row_count={source_count}, "
            f"replacement_row_count={replacement_count}."
        )

    output_sql = _build_repair_partition_output_sql(
        target_path=target_path,
        replacement_sql=replacement_sql,
        repair_required_codes=normalized_codes,
    )
    _replace_parquet_from_query(connection, output_sql, target_path)
    output_row_count = _row_count(connection, target_path, hive_partitioning=False)
    return GoldStockDailyQfqRepairPartitionWriteResult(
        path=target_path,
        replacement_row_count=replacement_count,
        output_row_count=output_row_count,
    )


def build_gold_stock_daily_qfq_factor_repair_check_metadata(
    result: GoldStockDailyQfqFactorRepairResult,
    *,
    producer_run_id: str,
) -> dict[str, object]:
    repair_required_codes = result.plan.repair_required_codes
    repair_required_codes_truncated = (
        len(repair_required_codes) > GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT
    )
    repair_required_code_samples = repair_required_codes[
        :GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT
    ]
    return build_check_metadata(
        check_scope=CheckScope.RECONCILIATION,
        checked_row_count=result.rewritten_row_count,
        failed_row_count=0,
        extra_metadata={
            "summary": (
                "Stock daily qfq factor repair completed."
                if result.plan.repair_required
                else "Stock daily qfq factor repair found no changed factors."
            ),
            "next_action": "No action needed.",
            "qfq_factor_trade_date": result.plan.qfq_factor_trade_date,
            "repair_start_trade_date": result.repair_start_trade_date or "",
            "repair_end_trade_date": result.repair_end_trade_date,
            "selected_partition_count": result.selected_partition_count,
            "repair_required": result.plan.repair_required,
            "repair_required_code_count": result.plan.repair_required_code_count,
            "repair_required_codes": list(repair_required_code_samples),
            "repair_required_codes_hash": result.plan.repair_required_codes_hash,
            "repair_required_codes_truncated": repair_required_codes_truncated,
            "rewritten_partition_count": result.rewritten_partition_count,
            "rewritten_row_count": result.rewritten_row_count,
            "repaired_code_count": result.repaired_code_count,
            "repaired_file_samples": list(result.repaired_file_samples),
            "upstream_batch_id": result.upstream_batch_id,
            "producer_run_id": producer_run_id,
            "reason": result.plan.reason,
        },
    )


def _normalize_expected_trade_dates(expected_trade_dates: Sequence[str]) -> tuple[str, ...]:
    normalized_dates = tuple(
        date.fromisoformat(str(trade_date).strip()).isoformat()
        for trade_date in expected_trade_dates
    )
    if not normalized_dates:
        raise ValueError("expected_trade_dates must not be empty.")
    if tuple(sorted(set(normalized_dates))) != normalized_dates:
        raise ValueError("expected_trade_dates must be sorted and unique.")
    return normalized_dates


def _previous_expected_trade_date(
    expected_trade_dates: Sequence[str],
    trade_date: str,
) -> str | None:
    normalized_trade_date = date.fromisoformat(trade_date).isoformat()
    previous = None
    for expected_trade_date in expected_trade_dates:
        if expected_trade_date == normalized_trade_date:
            return previous
        previous = expected_trade_date
    return None


def _expected_trade_dates_between(
    expected_trade_dates: Sequence[str],
    *,
    start_trade_date: str,
    end_trade_date: str,
) -> tuple[str, ...]:
    normalized_start = date.fromisoformat(start_trade_date).isoformat()
    normalized_end = date.fromisoformat(end_trade_date).isoformat()
    selected = tuple(
        trade_date
        for trade_date in expected_trade_dates
        if normalized_start <= trade_date <= normalized_end
    )
    if not selected or selected[0] != normalized_start or selected[-1] != normalized_end:
        raise ValueError(
            "repair range boundaries must exist in expected_trade_dates: "
            f"start={normalized_start}, end={normalized_end}."
        )
    return selected


def _effective_repair_start_trade_date(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    end_trade_date: str,
    repair_required_codes: Sequence[str],
) -> str:
    normalized_codes = _normalize_repair_required_codes(repair_required_codes)
    candidate_paths = tuple(
        gold_stock_daily_qfq_path(lake_root, trade_date)
        for trade_date in expected_trade_dates
        if trade_date <= end_trade_date
        and gold_stock_daily_qfq_path(lake_root, trade_date).exists()
    )
    if not candidate_paths:
        raise ValueError(
            "Cannot compute stock daily qfq repair start because no existing "
            "gold_stock_daily_qfq files were found."
        )
    row = connection.execute(
        f"""
        WITH repair_codes AS (
          {_repair_codes_values_sql(normalized_codes)}
        ),
        qfq_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS trade_date
          FROM {_read_parquet_paths(candidate_paths)}
        )
        SELECT min(qfq_rows.trade_date)
        FROM qfq_rows
        INNER JOIN repair_codes
          ON qfq_rows.ts_code = repair_codes.ts_code
        """
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError(
            "Cannot compute stock daily qfq repair start because affected codes "
            "have no existing gold_stock_daily_qfq rows."
        )
    return str(row[0])


def _require_repair_input_files(
    *,
    lake_root: Path,
    selected_trade_dates: Sequence[str],
    as_of_trade_date: str,
) -> None:
    missing_paths = []
    as_of_adj_factor_path = silver_adj_factor_path(lake_root, as_of_trade_date)
    if not as_of_adj_factor_path.exists():
        missing_paths.append(as_of_adj_factor_path)
    for trade_date in selected_trade_dates:
        for path in (
            gold_stock_daily_qfq_path(lake_root, trade_date),
            silver_stock_daily_path(lake_root, trade_date),
            silver_adj_factor_path(lake_root, trade_date),
        ):
            if not path.exists():
                missing_paths.append(path)
    if missing_paths:
        sample = ", ".join(str(path) for path in missing_paths[:10])
        raise FileNotFoundError(
            "Missing stock daily qfq repair input files: "
            f"missing_count={len(missing_paths)}, sample={sample}."
        )


def _normalize_repair_required_codes(stock_codes: Sequence[str]) -> tuple[str, ...]:
    normalized_codes = tuple(
        sorted(
            {
                str(stock_code).strip().upper()
                for stock_code in stock_codes
                if str(stock_code).strip()
            }
        )
    )
    if not normalized_codes:
        raise ValueError("repair_required_codes must not be empty.")
    return normalized_codes


def _repair_codes_values_sql(stock_codes: Sequence[str]) -> str:
    normalized_codes = _normalize_repair_required_codes(stock_codes)
    values_sql = ", ".join(
        f"({duckdb_string(stock_code)})" for stock_code in normalized_codes
    )
    return (
        "SELECT CAST(ts_code AS VARCHAR) AS ts_code "
        f"FROM (VALUES {values_sql}) AS repair_code_values(ts_code)"
    )


def _repair_required_source_row_count(
    connection: duckdb.DuckDBPyConnection,
    *,
    stock_daily_path: Path,
    trade_date: str,
    repair_required_codes: Sequence[str],
) -> int:
    row = connection.execute(
        f"""
        WITH repair_codes AS (
          {_repair_codes_values_sql(repair_required_codes)}
        ),
        source_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_date AS DATE) AS trade_date
          FROM {read_parquet(stock_daily_path, hive_partitioning=False)}
          WHERE CAST(trade_date AS DATE) = DATE {duckdb_string(trade_date)}
        )
        SELECT count(*)
        FROM source_rows
        INNER JOIN repair_codes
          ON source_rows.ts_code = repair_codes.ts_code
        """
    ).fetchone()
    return int(row[0])


def _repair_required_replacement_row_count(
    connection: duckdb.DuckDBPyConnection,
    *,
    replacement_sql: str,
    repair_required_codes: Sequence[str],
) -> int:
    row = connection.execute(
        f"""
        WITH repair_codes AS (
          {_repair_codes_values_sql(repair_required_codes)}
        ),
        replacement_rows AS (
          {replacement_sql}
        )
        SELECT count(*)
        FROM replacement_rows
        INNER JOIN repair_codes
          ON replacement_rows.ts_code = repair_codes.ts_code
        """
    ).fetchone()
    return int(row[0])


def _build_repair_partition_output_sql(
    *,
    target_path: Path,
    replacement_sql: str,
    repair_required_codes: Sequence[str],
) -> str:
    columns = ", ".join(GOLD_STOCK_DAILY_QFQ_COLUMNS)
    return f"""
WITH repair_codes AS (
  {_repair_codes_values_sql(repair_required_codes)}
),
existing_rows AS (
  SELECT {columns}
  FROM {read_parquet(target_path, hive_partitioning=False)}
  WHERE CAST(ts_code AS VARCHAR) NOT IN (SELECT ts_code FROM repair_codes)
),
replacement_rows AS (
  SELECT {columns}
  FROM ({replacement_sql})
  WHERE CAST(ts_code AS VARCHAR) IN (SELECT ts_code FROM repair_codes)
),
combined_rows AS (
  SELECT {columns} FROM existing_rows
  UNION ALL
  SELECT {columns} FROM replacement_rows
)
SELECT {columns}
FROM combined_rows
ORDER BY ts_code, trade_date
"""


def _stock_daily_qfq_base_ctes_sql(
    *,
    stock_daily_path: Path,
    trade_adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
    trade_date: str,
    as_of_trade_date: str,
) -> str:
    source_daily = read_parquet(stock_daily_path, hive_partitioning=False)
    trade_factor = read_parquet(trade_adj_factor_path, hive_partitioning=False)
    as_of_factor = read_parquet(as_of_adj_factor_path, hive_partitioning=False)
    previous_daily = _previous_stock_daily_source(previous_stock_daily_paths)
    previous_factor = _previous_adj_factor_source(previous_adj_factor_paths)
    trade_date_sql = f"DATE {duckdb_string(trade_date)}"
    as_of_trade_date_sql = f"DATE {duckdb_string(as_of_trade_date)}"
    return f"""
WITH source_daily AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(open AS DOUBLE) AS open,
    CAST(high AS DOUBLE) AS high,
    CAST(low AS DOUBLE) AS low,
    CAST(close AS DOUBLE) AS close,
    CAST(vol AS DOUBLE) AS vol,
    CAST(amount AS DOUBLE) AS amount
  FROM {source_daily}
  WHERE CAST(trade_date AS DATE) = {trade_date_sql}
),
trade_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(adj_factor AS DOUBLE) AS trade_adj_factor
  FROM {trade_factor}
  WHERE CAST(trade_date AS DATE) = {trade_date_sql}
),
as_of_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS as_of_trade_date,
    CAST(adj_factor AS DOUBLE) AS as_of_adj_factor
  FROM {as_of_factor}
  WHERE CAST(trade_date AS DATE) = {as_of_trade_date_sql}
),
previous_daily_candidates AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(close AS DOUBLE) AS close
  FROM {previous_daily}
  WHERE CAST(trade_date AS DATE) < {trade_date_sql}
),
previous_daily AS (
  SELECT ts_code, trade_date AS previous_trade_date, close AS previous_close
  FROM (
    SELECT
      ts_code,
      trade_date,
      close,
      row_number() OVER (
        PARTITION BY ts_code
        ORDER BY trade_date DESC
      ) AS row_number
    FROM previous_daily_candidates
  )
  WHERE row_number = 1
),
previous_adj_factor AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS previous_trade_date,
    CAST(adj_factor AS DOUBLE) AS previous_adj_factor
  FROM {previous_factor}
),
joined_rows AS (
  SELECT
    source_daily.ts_code,
    source_daily.trade_date,
    CAST(
      source_daily.open
      * trade_adj_factor.trade_adj_factor
      / as_of_adj_factor.as_of_adj_factor
      AS DOUBLE
    ) AS open_qfq,
    CAST(
      source_daily.high
      * trade_adj_factor.trade_adj_factor
      / as_of_adj_factor.as_of_adj_factor
      AS DOUBLE
    ) AS high_qfq,
    CAST(
      source_daily.low
      * trade_adj_factor.trade_adj_factor
      / as_of_adj_factor.as_of_adj_factor
      AS DOUBLE
    ) AS low_qfq,
    CAST(
      source_daily.close
      * trade_adj_factor.trade_adj_factor
      / as_of_adj_factor.as_of_adj_factor
      AS DOUBLE
    ) AS close_qfq,
    source_daily.vol,
    source_daily.amount,
    trade_adj_factor.trade_adj_factor,
    as_of_adj_factor.as_of_adj_factor,
    previous_daily.previous_trade_date,
    previous_daily.previous_close,
    previous_adj_factor.previous_adj_factor
  FROM source_daily
  LEFT JOIN trade_adj_factor
    ON source_daily.ts_code = trade_adj_factor.ts_code
   AND source_daily.trade_date = trade_adj_factor.trade_date
  LEFT JOIN as_of_adj_factor
    ON source_daily.ts_code = as_of_adj_factor.ts_code
  LEFT JOIN previous_daily
    ON source_daily.ts_code = previous_daily.ts_code
  LEFT JOIN previous_adj_factor
    ON previous_daily.ts_code = previous_adj_factor.ts_code
   AND previous_daily.previous_trade_date = previous_adj_factor.previous_trade_date
)
"""


def _previous_stock_daily_source(paths: Sequence[Path]) -> str:
    if paths:
        return _read_parquet_paths(paths)
    return """
    (
      SELECT
        CAST(NULL AS VARCHAR) AS ts_code,
        CAST(NULL AS DATE) AS trade_date,
        CAST(NULL AS DOUBLE) AS close
      WHERE false
    )
    """


def _previous_adj_factor_source(paths: Sequence[Path]) -> str:
    if paths:
        return _read_parquet_paths(paths)
    return """
    (
      SELECT
        CAST(NULL AS VARCHAR) AS ts_code,
        CAST(NULL AS DATE) AS trade_date,
        CAST(NULL AS DOUBLE) AS adj_factor
      WHERE false
    )
    """


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("At least one parquet path is required.")
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    path_list = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{path_list}], hive_partitioning=false, union_by_name=true)"


def _replace_parquet_from_query(
    connection: duckdb.DuckDBPyConnection,
    select_sql: str,
    target_path: Path,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()
    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


def _column_names(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    *,
    hive_partitioning: bool = False,
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [str(row[0]) for row in rows]


def _row_count(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    *,
    hive_partitioning: bool = False,
) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=hive_partitioning)
        ).fetchone()[0]
    )
