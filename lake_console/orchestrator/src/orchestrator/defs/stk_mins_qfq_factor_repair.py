from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    silver_adj_factor_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    normalize_stk_mins_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    GoldStkMinsQfqFactorRepairPlan,
    GoldStkMinsQfqWriteResult,
    build_daily_qfq_select_sql,
    build_gold_stk_mins_qfq_factor_repair_plan,
    build_latest_adj_factor_by_code_sql,
    write_gold_stk_mins_qfq_rows_to_year_files,
)


@dataclass(frozen=True)
class GoldStkMinsQfqFactorRepairCodeResult:
    ts_code: str
    rewritten_file_count: int
    rewritten_row_count: int
    write_results: tuple[GoldStkMinsQfqWriteResult, ...]


@dataclass(frozen=True)
class GoldStkMinsQfqFactorRepairResult:
    plan: GoldStkMinsQfqFactorRepairPlan
    repaired_code_count: int
    skipped_code_count: int
    rewritten_file_count: int
    rewritten_row_count: int
    repaired_file_samples: tuple[str, ...]
    code_results: tuple[GoldStkMinsQfqFactorRepairCodeResult, ...]
    execution_model: str
    planned_batch_count: int
    executed_batch_count: int
    non_empty_batch_count: int


@dataclass(frozen=True)
class GoldStkMinsQfqFactorRepairBatch:
    freq: int
    year: str
    partition_keys: tuple[str, ...]


def execute_gold_stk_mins_qfq_factor_repair(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    trade_date: str,
    registered_partition_keys: Sequence[str],
    freqs: Sequence[int | str] = STK_MINS_FREQS,
) -> GoldStkMinsQfqFactorRepairResult:
    normalized_trade_date = date.fromisoformat(trade_date).isoformat()
    selected_partition_keys = _select_repair_partition_keys(
        registered_partition_keys,
        trade_date=normalized_trade_date,
    )
    previous_trade_date = _previous_trade_date(
        selected_partition_keys,
        trade_date=normalized_trade_date,
    )
    plan = build_gold_stk_mins_qfq_factor_repair_plan(
        current_adj_factor_path=silver_adj_factor_path(lake_root, normalized_trade_date),
        previous_adj_factor_path=silver_adj_factor_path(lake_root, previous_trade_date),
        silver_stock_basic_path=silver_stock_basic_path(lake_root),
        trade_date=normalized_trade_date,
        previous_trade_date=previous_trade_date,
    )
    if not plan.can_execute_repair or not plan.repair_required:
        return GoldStkMinsQfqFactorRepairResult(
            plan=plan,
            repaired_code_count=0,
            skipped_code_count=0,
            rewritten_file_count=0,
            rewritten_row_count=0,
            repaired_file_samples=(),
            code_results=(),
            execution_model="freq_year_batch",
            planned_batch_count=0,
            executed_batch_count=0,
            non_empty_batch_count=0,
        )

    normalized_freqs = tuple(normalize_stk_mins_freq(freq) for freq in freqs)
    latest_adj_factor_paths = _discover_silver_adj_factor_paths(lake_root)
    if not latest_adj_factor_paths:
        raise FileNotFoundError("No silver_adj_factor files available for qfq repair.")

    batches = _build_repair_batches(
        freqs=normalized_freqs,
        selected_partition_keys=selected_partition_keys,
    )
    write_results: list[GoldStkMinsQfqWriteResult] = []
    with TemporaryDirectory(prefix="gold_stk_mins_qfq_factor_repair_") as temp_dir:
        latest_adj_factor_snapshot_path = Path(temp_dir) / "latest_adj_factor.parquet"
        _write_latest_adj_factor_snapshot(
            duckdb_resource,
            latest_adj_factor_paths=latest_adj_factor_paths,
            target_path=latest_adj_factor_snapshot_path,
        )
        for batch in batches:
            batch_select_sql = _build_stock_year_batch_repair_select_sql(
                lake_root=lake_root,
                freq=batch.freq,
                stock_codes=plan.repair_required_codes,
                partition_keys=batch.partition_keys,
                latest_adj_factor_paths=(latest_adj_factor_snapshot_path,),
            )
            batch_write_results = write_gold_stk_mins_qfq_rows_to_year_files(
                lake_root=lake_root,
                freq=batch.freq,
                qfq_select_sql=batch_select_sql,
                replace_trade_dates=batch.partition_keys,
                allow_empty_replacement=True,
            )
            write_results.extend(batch_write_results)

    code_results = _build_repair_code_results(
        repair_required_codes=plan.repair_required_codes,
        write_results=write_results,
    )
    repaired_file_samples = tuple(str(result.path) for result in write_results[:20])

    return GoldStkMinsQfqFactorRepairResult(
        plan=plan,
        repaired_code_count=len(code_results),
        skipped_code_count=0,
        rewritten_file_count=len(write_results),
        rewritten_row_count=sum(result.replacement_row_count for result in write_results),
        repaired_file_samples=repaired_file_samples,
        code_results=code_results,
        execution_model="freq_year_batch",
        planned_batch_count=len(batches),
        executed_batch_count=len(batches),
        non_empty_batch_count=len(_non_empty_batch_keys(write_results)),
    )


def _build_repair_batches(
    *,
    freqs: Sequence[int],
    selected_partition_keys: Sequence[str],
) -> tuple[GoldStkMinsQfqFactorRepairBatch, ...]:
    batches: list[GoldStkMinsQfqFactorRepairBatch] = []
    for freq in freqs:
        for year, year_partition_keys in _partition_keys_by_year(
            selected_partition_keys
        ).items():
            batches.append(
                GoldStkMinsQfqFactorRepairBatch(
                    freq=freq,
                    year=year,
                    partition_keys=year_partition_keys,
                )
            )
    return tuple(batches)


def _build_stock_year_batch_repair_select_sql(
    *,
    lake_root: Path,
    freq: int,
    stock_codes: Sequence[str],
    partition_keys: Sequence[str],
    latest_adj_factor_paths: Sequence[Path],
) -> str:
    silver_paths = tuple(
        silver_stk_mins_path(lake_root, freq, partition_key)
        for partition_key in partition_keys
    )
    trade_adj_factor_paths = tuple(
        silver_adj_factor_path(lake_root, partition_key)
        for partition_key in partition_keys
    )
    _require_existing_paths("silver_stk_mins", silver_paths)
    _require_existing_paths("silver_adj_factor", trade_adj_factor_paths)
    qfq_select_sql = build_daily_qfq_select_sql(
        silver_paths=silver_paths,
        trade_adj_factor_paths=trade_adj_factor_paths,
        latest_adj_factor_paths=latest_adj_factor_paths,
    )
    stock_codes_sql = _string_values_sql(stock_codes)
    return f"""
SELECT *
FROM ({qfq_select_sql})
WHERE ts_code IN ({stock_codes_sql})
"""


def _require_existing_paths(label: str, paths: Sequence[Path]) -> None:
    missing_paths = tuple(path for path in paths if not path.exists())
    if missing_paths:
        samples = ", ".join(str(path) for path in missing_paths[:5])
        raise FileNotFoundError(f"Missing qfq repair {label} input files: {samples}")


def _write_latest_adj_factor_snapshot(
    duckdb_resource: DuckDBResource,
    *,
    latest_adj_factor_paths: Sequence[Path],
    target_path: Path,
) -> None:
    latest_factor_sql = build_latest_adj_factor_by_code_sql(latest_adj_factor_paths)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb_resource.connect() as connection:
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT
                  CAST(ts_code AS VARCHAR) AS ts_code,
                  CAST(latest_trade_date AS DATE) AS trade_date,
                  CAST(latest_adj_factor AS DOUBLE) AS adj_factor
                FROM ({latest_factor_sql})
                ORDER BY ts_code
                """,
                target_path,
            )
        )
        row_count = connection.execute(
            f"SELECT count(*) FROM {read_parquet(target_path, hive_partitioning=False)}"
        ).fetchone()[0]
    if int(row_count) == 0:
        raise ValueError("Latest adj factor snapshot is empty.")


def _build_repair_code_results(
    *,
    repair_required_codes: Sequence[str],
    write_results: Sequence[GoldStkMinsQfqWriteResult],
) -> tuple[GoldStkMinsQfqFactorRepairCodeResult, ...]:
    by_code: dict[str, list[GoldStkMinsQfqWriteResult]] = {
        code: [] for code in repair_required_codes
    }
    for write_result in write_results:
        by_code.setdefault(write_result.ts_code, []).append(write_result)

    code_results: list[GoldStkMinsQfqFactorRepairCodeResult] = []
    for stock_code in repair_required_codes:
        stock_write_results = tuple(by_code.get(stock_code, ()))
        if not stock_write_results:
            continue
        code_results.append(
            GoldStkMinsQfqFactorRepairCodeResult(
                ts_code=stock_code,
                rewritten_file_count=len(stock_write_results),
                rewritten_row_count=sum(
                    result.replacement_row_count for result in stock_write_results
                ),
                write_results=stock_write_results,
            )
        )
    return tuple(code_results)


def _non_empty_batch_keys(
    write_results: Sequence[GoldStkMinsQfqWriteResult],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                (write_result.path.parent.parent.parent.name, write_result.year)
                for write_result in write_results
            }
        )
    )


def _select_repair_partition_keys(
    registered_partition_keys: Sequence[str],
    *,
    trade_date: str,
) -> tuple[str, ...]:
    selected = tuple(
        key
        for key in sorted(
            {
                date.fromisoformat(str(partition_key).strip()).isoformat()
                for partition_key in registered_partition_keys
            }
        )
        if key <= trade_date
    )
    if not selected:
        raise ValueError("No registered stk_mins silver partitions available for qfq repair.")
    if trade_date not in selected:
        raise ValueError(
            "QFQ repair trade date must be registered in cn_a_stock_mins_silver_trade_days: "
            f"{trade_date}."
        )
    return selected


def _previous_trade_date(
    selected_partition_keys: Sequence[str],
    *,
    trade_date: str,
) -> str:
    previous_keys = tuple(key for key in selected_partition_keys if key < trade_date)
    if not previous_keys:
        raise ValueError(f"No previous stk_mins silver trade date before {trade_date}.")
    return previous_keys[-1]


def _partition_keys_by_year(partition_keys: Sequence[str]) -> dict[str, tuple[str, ...]]:
    years = sorted({partition_key[:4] for partition_key in partition_keys})
    return {
        year: tuple(
            partition_key
            for partition_key in partition_keys
            if partition_key[:4] == year
        )
        for year in years
    }


def _discover_silver_adj_factor_paths(lake_root: Path) -> tuple[Path, ...]:
    adj_factor_root = Path(lake_root) / "silver" / "quote" / "adj_factor"
    return tuple(sorted(adj_factor_root.glob("trade_date=*/part-000.parquet")))


def _string_values_sql(values: Sequence[str]) -> str:
    normalized_values = tuple(dict.fromkeys(str(value).strip() for value in values))
    if not normalized_values:
        raise ValueError("At least one string value is required.")
    return ", ".join(duckdb_string(value) for value in normalized_values)
