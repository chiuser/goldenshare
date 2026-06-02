from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from orchestrator.defs.duckdb_sql import duckdb_string
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
    rewrite_qfq_year_file_for_stock_code,
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
        )

    normalized_freqs = tuple(normalize_stk_mins_freq(freq) for freq in freqs)
    latest_adj_factor_paths = _discover_silver_adj_factor_paths(lake_root)
    if not latest_adj_factor_paths:
        raise FileNotFoundError("No silver_adj_factor files available for qfq repair.")

    code_results: list[GoldStkMinsQfqFactorRepairCodeResult] = []
    repaired_file_samples: list[str] = []
    for stock_code in plan.repair_required_codes:
        code_result = _repair_qfq_for_stock_code(
            lake_root=lake_root,
            duckdb_resource=duckdb_resource,
            stock_code=stock_code,
            freqs=normalized_freqs,
            selected_partition_keys=selected_partition_keys,
            latest_adj_factor_paths=latest_adj_factor_paths,
        )
        code_results.append(code_result)
        for write_result in code_result.write_results:
            if len(repaired_file_samples) < 20:
                repaired_file_samples.append(str(write_result.path))

    return GoldStkMinsQfqFactorRepairResult(
        plan=plan,
        repaired_code_count=len(code_results),
        skipped_code_count=0,
        rewritten_file_count=sum(result.rewritten_file_count for result in code_results),
        rewritten_row_count=sum(result.rewritten_row_count for result in code_results),
        repaired_file_samples=tuple(repaired_file_samples),
        code_results=tuple(code_results),
    )


def _repair_qfq_for_stock_code(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    stock_code: str,
    freqs: Sequence[int],
    selected_partition_keys: Sequence[str],
    latest_adj_factor_paths: Sequence[Path],
) -> GoldStkMinsQfqFactorRepairCodeResult:
    write_results: list[GoldStkMinsQfqWriteResult] = []
    for freq in freqs:
        for year, year_partition_keys in _partition_keys_by_year(
            selected_partition_keys
        ).items():
            replacement_select_sql = _build_stock_year_repair_select_sql(
                lake_root=lake_root,
                freq=freq,
                stock_code=stock_code,
                partition_keys=year_partition_keys,
                latest_adj_factor_paths=latest_adj_factor_paths,
            )
            replacement_row_count = _replacement_row_count(
                duckdb_resource,
                replacement_select_sql,
            )
            if replacement_row_count == 0:
                continue
            write_results.append(
                rewrite_qfq_year_file_for_stock_code(
                    lake_root=lake_root,
                    freq=freq,
                    stock_code=stock_code,
                    year=year,
                    replacement_select_sql=replacement_select_sql,
                    replace_trade_dates=year_partition_keys,
                )
            )

    if not write_results:
        raise RuntimeError(
            "QFQ factor repair found changed adj factor but no silver rows to rewrite: "
            f"ts_code={stock_code}."
        )
    return GoldStkMinsQfqFactorRepairCodeResult(
        ts_code=stock_code,
        rewritten_file_count=len(write_results),
        rewritten_row_count=sum(result.replacement_row_count for result in write_results),
        write_results=tuple(write_results),
    )


def _build_stock_year_repair_select_sql(
    *,
    lake_root: Path,
    freq: int,
    stock_code: str,
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
    return f"""
SELECT *
FROM ({qfq_select_sql})
WHERE ts_code = {duckdb_string(stock_code)}
"""


def _require_existing_paths(label: str, paths: Sequence[Path]) -> None:
    missing_paths = tuple(path for path in paths if not path.exists())
    if missing_paths:
        samples = ", ".join(str(path) for path in missing_paths[:5])
        raise FileNotFoundError(f"Missing qfq repair {label} input files: {samples}")


def _replacement_row_count(
    duckdb_resource: DuckDBResource,
    replacement_select_sql: str,
) -> int:
    with duckdb_resource.connect() as connection:
        return int(
            connection.execute(
                f"SELECT count(*) FROM ({replacement_select_sql})"
            ).fetchone()[0]
        )


def _select_repair_partition_keys(
    registered_partition_keys: Sequence[str],
    *,
    trade_date: str,
) -> tuple[str, ...]:
    selected = tuple(
        key
        for key in sorted(
            {date.fromisoformat(str(partition_key).strip()).isoformat() for partition_key in registered_partition_keys}
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
        year: tuple(partition_key for partition_key in partition_keys if partition_key[:4] == year)
        for year in years
    }


def _discover_silver_adj_factor_paths(lake_root: Path) -> tuple[Path, ...]:
    adj_factor_root = Path(lake_root) / "silver" / "quote" / "adj_factor"
    return tuple(sorted(adj_factor_root.glob("trade_date=*/part-000.parquet")))
