from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    assert_expected_dates_registered,
    previous_expected_trade_date,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import (
    silver_adj_factor_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_QFQ_NATIVE_FREQS,
    normalize_stk_mins_freq,
    normalize_stk_mins_qfq_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    GoldStkMinsQfqFactorRepairPlan,
    GoldStkMinsQfqWriteResult,
    assert_canonical_gold_stk_mins_qfq_source_ready,
    build_canonical_gold_stk_mins_qfq_select_sql,
    build_gold_stk_mins_qfq_factor_repair_plan,
    gold_stk_mins_qfq_source_freq,
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
    repair_start_trade_date: str
    repair_end_trade_date: str
    selected_partition_count: int
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
    derived_rewrite_required: bool
    derived_planned_batch_count: int
    derived_executed_batch_count: int
    derived_non_empty_batch_count: int
    derived_rewritten_file_count: int
    derived_rewritten_row_count: int
    derived_repaired_code_count: int
    derived_failed_code_count: int


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
    expected_trade_dates: Sequence[str],
    registered_partition_keys: Sequence[str],
    freqs: Sequence[int | str] = STK_MINS_QFQ_NATIVE_FREQS,
) -> GoldStkMinsQfqFactorRepairResult:
    normalized_trade_date = date.fromisoformat(trade_date).isoformat()
    expected_trade_dates = _normalize_expected_trade_dates(expected_trade_dates)
    if normalized_trade_date not in expected_trade_dates:
        raise dg.Failure(
            description=(
                "QFQ repair trade date is not in stock mins expected calendar: "
                f"trade_date={normalized_trade_date}."
            ),
            metadata={"trade_date": normalized_trade_date},
        )
    previous_trade_date = previous_expected_trade_date(
        expected_trade_dates,
        normalized_trade_date,
    )
    if previous_trade_date is None:
        raise dg.Failure(
            description=(
                "QFQ repair trade date has no previous expected trade date: "
                f"trade_date={normalized_trade_date}."
            ),
            metadata={"trade_date": normalized_trade_date},
        )
    selected_partition_keys = assert_expected_dates_registered(
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_partition_keys,
        partition_set_name=cn_a_stock_mins_silver_trade_days.name,
        start_trade_date=expected_trade_dates[0],
        end_trade_date=normalized_trade_date,
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
            repair_start_trade_date=selected_partition_keys[0],
            repair_end_trade_date=normalized_trade_date,
            selected_partition_count=len(selected_partition_keys),
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
            derived_rewrite_required=False,
            derived_planned_batch_count=0,
            derived_executed_batch_count=0,
            derived_non_empty_batch_count=0,
            derived_rewritten_file_count=0,
            derived_rewritten_row_count=0,
            derived_repaired_code_count=0,
            derived_failed_code_count=0,
        )

    normalized_freqs = tuple(normalize_stk_mins_freq(freq) for freq in freqs)
    as_of_adj_factor_path = silver_adj_factor_path(lake_root, normalized_trade_date)
    _require_existing_paths("as_of_adj_factor", (as_of_adj_factor_path,))

    batches = _build_repair_batches(
        freqs=normalized_freqs,
        selected_partition_keys=selected_partition_keys,
    )
    write_results: list[GoldStkMinsQfqWriteResult] = []
    for batch in batches:
        batch_select_sql = _build_stock_year_batch_repair_select_sql(
            lake_root=lake_root,
            freq=batch.freq,
            stock_codes=plan.repair_required_codes,
            partition_keys=batch.partition_keys,
            as_of_adj_factor_path=as_of_adj_factor_path,
        )
        batch_write_results = write_gold_stk_mins_qfq_rows_to_year_files(
            lake_root=lake_root,
            freq=batch.freq,
            qfq_select_sql=batch_select_sql,
            replace_trade_dates=batch.partition_keys,
            allow_empty_replacement=True,
        )
        write_results.extend(batch_write_results)

    derived_target_freqs = _derived_target_freqs_for_native_freqs(normalized_freqs)
    derived_write_results = _execute_derived_qfq_rebuild(
        lake_root=lake_root,
        target_freqs=derived_target_freqs,
        stock_codes=plan.repair_required_codes,
        selected_partition_keys=selected_partition_keys,
        as_of_adj_factor_path=as_of_adj_factor_path,
    )
    all_write_results = tuple(write_results) + derived_write_results
    code_results = _build_repair_code_results(
        repair_required_codes=plan.repair_required_codes,
        write_results=all_write_results,
    )
    repaired_file_samples = tuple(str(result.path) for result in write_results[:20])
    derived_repaired_codes = {
        write_result.ts_code for write_result in derived_write_results
    }
    derived_failed_code_count = (
        len(plan.repair_required_codes) - len(derived_repaired_codes)
        if derived_target_freqs
        else 0
    )

    return GoldStkMinsQfqFactorRepairResult(
        plan=plan,
        repair_start_trade_date=selected_partition_keys[0],
        repair_end_trade_date=normalized_trade_date,
        selected_partition_count=len(selected_partition_keys),
        repaired_code_count=len(
            _build_repair_code_results(
                repair_required_codes=plan.repair_required_codes,
                write_results=write_results,
            )
        ),
        skipped_code_count=0,
        rewritten_file_count=len(write_results),
        rewritten_row_count=sum(result.replacement_row_count for result in write_results),
        repaired_file_samples=repaired_file_samples,
        code_results=code_results,
        execution_model="freq_year_batch",
        planned_batch_count=len(batches),
        executed_batch_count=len(batches),
        non_empty_batch_count=len(_non_empty_batch_keys(write_results)),
        derived_rewrite_required=bool(derived_target_freqs),
        derived_planned_batch_count=len(derived_target_freqs)
        * len(_partition_keys_by_year(selected_partition_keys)),
        derived_executed_batch_count=len(derived_target_freqs)
        * len(_partition_keys_by_year(selected_partition_keys)),
        derived_non_empty_batch_count=len(_non_empty_batch_keys(derived_write_results)),
        derived_rewritten_file_count=len(derived_write_results),
        derived_rewritten_row_count=sum(
            result.replacement_row_count for result in derived_write_results
        ),
        derived_repaired_code_count=len(derived_repaired_codes),
        derived_failed_code_count=derived_failed_code_count,
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


def _derived_target_freqs_for_native_freqs(freqs: Sequence[int]) -> tuple[int, ...]:
    normalized_freqs = {normalize_stk_mins_freq(freq) for freq in freqs}
    target_freqs: list[int] = []
    if 30 in normalized_freqs:
        target_freqs.append(90)
    if 60 in normalized_freqs:
        target_freqs.append(120)
    return tuple(target_freqs)


def _execute_derived_qfq_rebuild(
    *,
    lake_root: Path,
    target_freqs: Sequence[int],
    stock_codes: Sequence[str],
    selected_partition_keys: Sequence[str],
    as_of_adj_factor_path: Path,
) -> tuple[GoldStkMinsQfqWriteResult, ...]:
    write_results: list[GoldStkMinsQfqWriteResult] = []
    if not target_freqs:
        return ()
    for target_freq in target_freqs:
        normalized_target_freq = normalize_stk_mins_qfq_freq(target_freq)
        source_freq = gold_stk_mins_qfq_source_freq(normalized_target_freq)
        for year_partition_keys in _partition_keys_by_year(
            selected_partition_keys
        ).values():
            silver_paths = tuple(
                silver_stk_mins_path(lake_root, source_freq, partition_key)
                for partition_key in year_partition_keys
            )
            trade_adj_factor_paths = tuple(
                silver_adj_factor_path(lake_root, partition_key)
                for partition_key in year_partition_keys
            )
            _require_existing_paths("silver_stk_mins", silver_paths)
            _require_existing_paths("silver_adj_factor", trade_adj_factor_paths)
            assert_canonical_gold_stk_mins_qfq_source_ready(
                silver_paths=silver_paths,
                target_freq=normalized_target_freq,
                partition_keys=year_partition_keys,
                stock_codes=stock_codes,
                allow_empty=True,
            )
            batch_select_sql = build_canonical_gold_stk_mins_qfq_select_sql(
                silver_paths=silver_paths,
                trade_adj_factor_paths=trade_adj_factor_paths,
                as_of_adj_factor_paths=[as_of_adj_factor_path],
                target_freq=normalized_target_freq,
                partition_keys=year_partition_keys,
                stock_codes=stock_codes,
            )
            batch_write_results = write_gold_stk_mins_qfq_rows_to_year_files(
                lake_root=lake_root,
                freq=normalized_target_freq,
                qfq_select_sql=batch_select_sql,
                replace_trade_dates=year_partition_keys,
                allow_empty_replacement=True,
            )
            write_results.extend(batch_write_results)
    return tuple(write_results)


def _build_stock_year_batch_repair_select_sql(
    *,
    lake_root: Path,
    freq: int,
    stock_codes: Sequence[str],
    partition_keys: Sequence[str],
    as_of_adj_factor_path: Path,
) -> str:
    source_freq = gold_stk_mins_qfq_source_freq(freq)
    silver_paths = tuple(
        silver_stk_mins_path(lake_root, source_freq, partition_key)
        for partition_key in partition_keys
    )
    trade_adj_factor_paths = tuple(
        silver_adj_factor_path(lake_root, partition_key)
        for partition_key in partition_keys
    )
    _require_existing_paths("silver_stk_mins", silver_paths)
    _require_existing_paths("silver_adj_factor", trade_adj_factor_paths)
    assert_canonical_gold_stk_mins_qfq_source_ready(
        silver_paths=silver_paths,
        target_freq=freq,
        partition_keys=partition_keys,
        stock_codes=stock_codes,
        allow_empty=True,
    )
    return build_canonical_gold_stk_mins_qfq_select_sql(
        silver_paths=silver_paths,
        trade_adj_factor_paths=trade_adj_factor_paths,
        as_of_adj_factor_paths=[as_of_adj_factor_path],
        target_freq=freq,
        partition_keys=partition_keys,
        stock_codes=stock_codes,
    )


def _require_existing_paths(label: str, paths: Sequence[Path]) -> None:
    missing_paths = tuple(path for path in paths if not path.exists())
    if missing_paths:
        samples = ", ".join(str(path) for path in missing_paths[:5])
        raise FileNotFoundError(f"Missing qfq repair {label} input files: {samples}")


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


def _normalize_expected_trade_dates(
    expected_trade_dates: Sequence[str],
) -> tuple[str, ...]:
    normalized_trade_dates = tuple(
        sorted(
            {
                date.fromisoformat(str(trade_date).strip()).isoformat()
                for trade_date in expected_trade_dates
            }
        )
    )
    if not normalized_trade_dates:
        raise dg.Failure(
            description="QFQ repair expected trade date calendar is empty.",
            metadata={},
        )
    return normalized_trade_dates


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
