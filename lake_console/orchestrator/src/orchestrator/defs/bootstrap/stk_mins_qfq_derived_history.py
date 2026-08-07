from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import orchestrator.defs.checks.stk_mins_checks as stk_mins_checks
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
    _normalize_years,
    _select_registered_partition_keys,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, gold_stk_mins_qfq_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_QFQ_DERIVED_FREQS,
    normalize_stk_mins_qfq_freq,
    qfq_source_freq_for_derived_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    GoldStkMinsQfqWriteResult,
    build_gold_stk_mins_qfq_derived_diagnostics_sql,
    build_gold_stk_mins_qfq_derived_select_sql,
    write_gold_stk_mins_qfq_rows_to_year_files,
)


GOLD_STK_MINS_QFQ_DERIVED_CHECK_COUNT = len(
    stk_mins_checks.GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES
)
GOLD_STK_MINS_QFQ_DERIVED_EVENT_COUNT_PER_ASSET_PARTITION = (
    1 + GOLD_STK_MINS_QFQ_DERIVED_CHECK_COUNT
)


@dataclass(frozen=True)
class StkMinsQfqDerivedHistoryBatch:
    target_freq: int
    source_freq: int
    year: str
    partition_keys: tuple[str, ...]


@dataclass(frozen=True)
class StkMinsQfqDerivedHistoryBatchEstimate:
    target_freq: int
    source_freq: int
    year: str
    source_file_count: int
    source_row_count: int
    source_stock_day_count: int
    expected_window_count: int
    generated_window_count: int
    incomplete_window_count: int
    exchange_mismatch_window_count: int
    planned_target_file_count: int
    existing_target_file_count: int


@dataclass(frozen=True)
class StkMinsQfqDerivedHistoryPlan:
    selected_partition_keys: tuple[str, ...]
    selected_target_freqs: tuple[int, ...]
    selected_years: tuple[str, ...]
    batches: tuple[StkMinsQfqDerivedHistoryBatch, ...]
    planned_source_file_count: int
    planned_source_row_count: int
    planned_source_stock_day_count: int
    planned_target_file_count: int
    planned_target_row_count: int
    existing_target_file_count: int
    missing_input_count: int
    missing_input_samples: tuple[str, ...]
    planned_event_count: int
    estimates_by_batch: Mapping[tuple[int, str], StkMinsQfqDerivedHistoryBatchEstimate]


@dataclass(frozen=True)
class StkMinsQfqDerivedHistoryBatchResult:
    target_freq: int
    source_freq: int
    year: str
    partition_keys: tuple[str, ...]
    source_row_count: int
    source_stock_day_count: int
    generated_window_count: int
    written_file_count: int
    written_row_count: int
    write_results: tuple[GoldStkMinsQfqWriteResult, ...]


@dataclass(frozen=True)
class StkMinsQfqDerivedHistoryReport:
    plan: StkMinsQfqDerivedHistoryPlan
    batch_results: tuple[StkMinsQfqDerivedHistoryBatchResult, ...]

    @property
    def written_file_count(self) -> int:
        return sum(result.written_file_count for result in self.batch_results)

    @property
    def written_row_count(self) -> int:
        return sum(result.written_row_count for result in self.batch_results)


def plan_stk_mins_qfq_derived_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    duckdb_resource: DuckDBResource | None = None,
) -> StkMinsQfqDerivedHistoryPlan:
    normalized_freqs = _normalize_derived_freqs(freqs)
    normalized_years = _normalize_years(years)
    selected_keys = _select_registered_partition_keys(
        registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        years=normalized_years,
    )
    selected_years = normalized_years or tuple(
        sorted({partition_key[:4] for partition_key in selected_keys})
    )
    batches = _build_derived_history_batches(
        selected_keys,
        target_freqs=normalized_freqs,
        years=selected_years,
    )
    resource = duckdb_resource or DuckDBResource()
    estimates: dict[
        tuple[int, str], StkMinsQfqDerivedHistoryBatchEstimate
    ] = {}
    missing_inputs: list[str] = []

    for batch in batches:
        source_paths = _source_qfq_paths_for_batch(lake_root, batch)
        if not source_paths:
            missing_inputs.append(
                f"{batch.target_freq}:{batch.year}:gold_stk_mins_qfq_"
                f"{batch.source_freq}m:no source stock-year files"
            )
            estimates[(batch.target_freq, batch.year)] = (
                StkMinsQfqDerivedHistoryBatchEstimate(
                    target_freq=batch.target_freq,
                    source_freq=batch.source_freq,
                    year=batch.year,
                    source_file_count=0,
                    source_row_count=0,
                    source_stock_day_count=0,
                    expected_window_count=0,
                    generated_window_count=0,
                    incomplete_window_count=0,
                    exchange_mismatch_window_count=0,
                    planned_target_file_count=0,
                    existing_target_file_count=0,
                )
            )
            continue
        estimates[(batch.target_freq, batch.year)] = _estimate_derived_history_batch(
            lake_root=lake_root,
            duckdb_resource=resource,
            batch=batch,
            source_paths=source_paths,
        )

    planned_target_file_count = sum(
        estimate.planned_target_file_count for estimate in estimates.values()
    )
    return StkMinsQfqDerivedHistoryPlan(
        selected_partition_keys=selected_keys,
        selected_target_freqs=normalized_freqs,
        selected_years=selected_years,
        batches=batches,
        planned_source_file_count=sum(
            estimate.source_file_count for estimate in estimates.values()
        ),
        planned_source_row_count=sum(
            estimate.source_row_count for estimate in estimates.values()
        ),
        planned_source_stock_day_count=sum(
            estimate.source_stock_day_count for estimate in estimates.values()
        ),
        planned_target_file_count=planned_target_file_count,
        planned_target_row_count=sum(
            estimate.generated_window_count for estimate in estimates.values()
        ),
        existing_target_file_count=sum(
            estimate.existing_target_file_count for estimate in estimates.values()
        ),
        missing_input_count=len(missing_inputs),
        missing_input_samples=tuple(missing_inputs[:20]),
        planned_event_count=(
            len(selected_keys)
            * len(normalized_freqs)
            * GOLD_STK_MINS_QFQ_DERIVED_EVENT_COUNT_PER_ASSET_PARTITION
        ),
        estimates_by_batch=estimates,
    )


def generate_stk_mins_qfq_derived_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
) -> StkMinsQfqDerivedHistoryReport:
    plan = plan_stk_mins_qfq_derived_history(
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb_resource,
    )
    if plan.missing_input_count:
        raise FileNotFoundError(
            "Gold qfq derived history inputs are missing: "
            f"{tuple(plan.missing_input_samples)}"
        )
    if plan.existing_target_file_count:
        raise FileExistsError(
            "Gold qfq derived history target files already exist; "
            "refusing baseline write: "
            f"{plan.existing_target_file_count}."
        )

    batch_results: list[StkMinsQfqDerivedHistoryBatchResult] = []
    for batch in plan.batches:
        estimate = plan.estimates_by_batch[(batch.target_freq, batch.year)]
        _validate_derived_history_estimate(estimate)
        result = _generate_derived_history_batch(
            lake_root=lake_root,
            batch=batch,
            estimate=estimate,
        )
        batch_results.append(result)

    return StkMinsQfqDerivedHistoryReport(
        plan=plan,
        batch_results=tuple(batch_results),
    )


def _build_derived_history_batches(
    partition_keys: Sequence[str],
    *,
    target_freqs: Sequence[int],
    years: Sequence[str],
) -> tuple[StkMinsQfqDerivedHistoryBatch, ...]:
    keys_by_year = {
        year: tuple(key for key in partition_keys if key[:4] == year)
        for year in years
    }
    batches: list[StkMinsQfqDerivedHistoryBatch] = []
    for target_freq in target_freqs:
        source_freq = qfq_source_freq_for_derived_freq(target_freq)
        for year in years:
            keys = keys_by_year[year]
            if not keys:
                continue
            batches.append(
                StkMinsQfqDerivedHistoryBatch(
                    target_freq=target_freq,
                    source_freq=source_freq,
                    year=year,
                    partition_keys=keys,
                )
            )
    return tuple(batches)


def _estimate_derived_history_batch(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    batch: StkMinsQfqDerivedHistoryBatch,
    source_paths: Sequence[Path],
) -> StkMinsQfqDerivedHistoryBatchEstimate:
    diagnostics_sql = build_gold_stk_mins_qfq_derived_diagnostics_sql(
        source_qfq_paths=source_paths,
        target_freq=batch.target_freq,
        partition_keys=batch.partition_keys,
    )
    target_sql = build_gold_stk_mins_qfq_derived_select_sql(
        source_qfq_paths=source_paths,
        target_freq=batch.target_freq,
        partition_keys=batch.partition_keys,
    )
    with duckdb_resource.connect() as connection:
        diagnostics = connection.execute(diagnostics_sql).fetchone()
        if diagnostics is None:
            raise RuntimeError(
                "Gold qfq derived history diagnostics query returned no rows: "
                f"target_freq={batch.target_freq}, year={batch.year}."
            )
        target_rows = connection.execute(
            f"""
            SELECT DISTINCT
              CAST(ts_code AS VARCHAR) AS ts_code,
              strftime(CAST(trade_date AS DATE), '%Y') AS year
            FROM ({target_sql})
            ORDER BY ts_code, year
            """
        ).fetchall()

    (
        _source_freq,
        _target_freq,
        source_row_count,
        source_stock_day_count,
        expected_window_count,
        generated_window_count,
        incomplete_window_count,
        exchange_mismatch_window_count,
    ) = (int(value or 0) for value in diagnostics)
    target_paths = tuple(
        gold_stk_mins_qfq_path(lake_root, batch.target_freq, str(ts_code), str(year))
        for ts_code, year in target_rows
    )
    return StkMinsQfqDerivedHistoryBatchEstimate(
        target_freq=batch.target_freq,
        source_freq=batch.source_freq,
        year=batch.year,
        source_file_count=len(source_paths),
        source_row_count=source_row_count,
        source_stock_day_count=source_stock_day_count,
        expected_window_count=expected_window_count,
        generated_window_count=generated_window_count,
        incomplete_window_count=incomplete_window_count,
        exchange_mismatch_window_count=exchange_mismatch_window_count,
        planned_target_file_count=len(target_paths),
        existing_target_file_count=sum(1 for path in target_paths if path.exists()),
    )


def _generate_derived_history_batch(
    *,
    lake_root: Path,
    batch: StkMinsQfqDerivedHistoryBatch,
    estimate: StkMinsQfqDerivedHistoryBatchEstimate,
) -> StkMinsQfqDerivedHistoryBatchResult:
    source_paths = _source_qfq_paths_for_batch(lake_root, batch)
    derived_select_sql = build_gold_stk_mins_qfq_derived_select_sql(
        source_qfq_paths=source_paths,
        target_freq=batch.target_freq,
        partition_keys=batch.partition_keys,
    )
    write_results = write_gold_stk_mins_qfq_rows_to_year_files(
        lake_root=lake_root,
        freq=batch.target_freq,
        qfq_select_sql=derived_select_sql,
        replace_trade_dates=batch.partition_keys,
        fail_if_target_exists=True,
    )
    if not write_results:
        raise RuntimeError(
            "Gold qfq derived history write produced no output files: "
            f"target_freq={batch.target_freq}, year={batch.year}."
        )
    return StkMinsQfqDerivedHistoryBatchResult(
        target_freq=batch.target_freq,
        source_freq=batch.source_freq,
        year=batch.year,
        partition_keys=batch.partition_keys,
        source_row_count=estimate.source_row_count,
        source_stock_day_count=estimate.source_stock_day_count,
        generated_window_count=estimate.generated_window_count,
        written_file_count=len(write_results),
        written_row_count=sum(result.row_count for result in write_results),
        write_results=tuple(write_results),
    )


def _validate_derived_history_estimate(
    estimate: StkMinsQfqDerivedHistoryBatchEstimate,
) -> None:
    if estimate.source_row_count <= 0 or estimate.source_stock_day_count <= 0:
        raise RuntimeError(
            "Gold qfq derived history source rows are empty: "
            f"target_freq={estimate.target_freq}, year={estimate.year}."
        )
    if estimate.exchange_mismatch_window_count:
        raise RuntimeError(
            "Gold qfq derived history source windows contain mixed exchanges: "
            f"target_freq={estimate.target_freq}, year={estimate.year}, "
            f"mismatch_window_count={estimate.exchange_mismatch_window_count}."
        )
    if estimate.incomplete_window_count:
        raise RuntimeError(
            "Gold qfq derived history source windows are incomplete or invalid: "
            f"target_freq={estimate.target_freq}, year={estimate.year}, "
            f"incomplete_window_count={estimate.incomplete_window_count}."
        )
    if estimate.generated_window_count <= 0:
        raise RuntimeError(
            "Gold qfq derived history generation would produce no rows: "
            f"target_freq={estimate.target_freq}, year={estimate.year}, "
            f"expected_window_count={estimate.expected_window_count}, "
            f"incomplete_window_count={estimate.incomplete_window_count}."
        )


def _source_qfq_paths_for_batch(
    lake_root: Path,
    batch: StkMinsQfqDerivedHistoryBatch,
) -> tuple[Path, ...]:
    source_root = gold_stk_mins_qfq_path(
        lake_root,
        batch.source_freq,
        "{ts_code}",
        batch.year,
    ).parents[2]
    return tuple(sorted(source_root.glob(f"ts_code=*/year={batch.year}/part-000.parquet")))


def _normalize_derived_freqs(freqs: Sequence[int | str] | None) -> tuple[int, ...]:
    if freqs is None:
        return tuple(STK_MINS_QFQ_DERIVED_FREQS)
    normalized = tuple(sorted({normalize_stk_mins_qfq_freq(freq) for freq in freqs}))
    unsupported = tuple(
        freq for freq in normalized if freq not in STK_MINS_QFQ_DERIVED_FREQS
    )
    if unsupported:
        allowed = ", ".join(str(freq) for freq in STK_MINS_QFQ_DERIVED_FREQS)
        raise ValueError(
            "Gold qfq derived history only supports derived freqs: "
            f"{allowed}. Got: {unsupported}."
        )
    if not normalized:
        raise ValueError("At least one gold qfq derived history freq is required.")
    return normalized
