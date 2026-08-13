from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Timer
from time import perf_counter
from typing import Any

from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
    _normalize_years,
    _select_registered_partition_keys,
)
from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    expected_gold_minute_times,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_QFQ_DERIVED_FREQS,
    normalize_stk_mins_qfq_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    GoldStkMinsQfqWriteResult,
    build_canonical_gold_stk_mins_qfq_select_sql,
    gold_stk_mins_qfq_source_freq,
    write_gold_stk_mins_qfq_rows_to_year_files,
)

GOLD_STK_MINS_QFQ_DERIVED_CHECK_COUNT = len(
    stk_mins_checks.GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES
)
GOLD_STK_MINS_QFQ_DERIVED_EVENT_COUNT_PER_ASSET_PARTITION = (
    1 + GOLD_STK_MINS_QFQ_DERIVED_CHECK_COUNT
)
GOLD_STK_MINS_QFQ_DERIVED_AMOUNT_ABS_TOLERANCE = 1e-6
GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES = 7
GOLD_STK_MINS_QFQ_DERIVED_OHLC_ABS_TOLERANCE = 1e-7
GOLD_STK_MINS_QFQ_DERIVED_AUDIT_MAX_SECONDS = 300.0


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


@dataclass(frozen=True)
class StkMinsQfqDerivedEquivalenceBatchAudit:
    target_freq: int
    year: str
    candidate_row_count: int
    existing_row_count: int
    candidate_key_hash: int
    existing_key_hash: int
    candidate_value_hash: int
    existing_value_hash: int
    missing_key_count: int
    extra_key_count: int
    value_mismatch_count: int
    max_ohlc_abs_difference: float
    max_amount_abs_difference: float

    @property
    def passed(self) -> bool:
        return (
            self.candidate_row_count == self.existing_row_count
            and self.candidate_key_hash == self.existing_key_hash
            and self.missing_key_count == 0
            and self.extra_key_count == 0
            and self.value_mismatch_count == 0
        )


@dataclass(frozen=True)
class StkMinsQfqDerivedEquivalenceReport:
    plan: StkMinsQfqDerivedHistoryPlan
    batch_audits: tuple[StkMinsQfqDerivedEquivalenceBatchAudit, ...]

    @property
    def passed(self) -> bool:
        return bool(self.batch_audits) and all(
            audit.passed for audit in self.batch_audits
        )


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
    query_deadline_monotonic: float | None = None,
    as_of_adj_factor_paths: Sequence[Path] | None = None,
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
    selected_as_of_adj_factor_paths = tuple(as_of_adj_factor_paths or ()) or (
        silver_adj_factor_path(lake_root, selected_keys[-1]),
    )
    missing_inputs.extend(
        f"as_of_adj_factor:{path}"
        for path in selected_as_of_adj_factor_paths
        if not path.exists()
    )

    for batch in batches:
        source_paths = _source_silver_paths_for_batch(lake_root, batch)
        trade_adj_factor_paths = _trade_adj_factor_paths_for_batch(lake_root, batch)
        missing_batch_paths = tuple(
            path
            for path in (*source_paths, *trade_adj_factor_paths)
            if not path.exists()
        )
        if missing_batch_paths:
            missing_inputs.extend(
                f"{batch.target_freq}:{batch.year}:missing:{path}"
                for path in missing_batch_paths[:20]
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
            trade_adj_factor_paths=trade_adj_factor_paths,
            as_of_adj_factor_paths=selected_as_of_adj_factor_paths,
            query_deadline_monotonic=query_deadline_monotonic,
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
            as_of_adj_factor_path=silver_adj_factor_path(
                lake_root, plan.selected_partition_keys[-1]
            ),
        )
        batch_results.append(result)

    return StkMinsQfqDerivedHistoryReport(
        plan=plan,
        batch_results=tuple(batch_results),
    )


def audit_stk_mins_qfq_derived_canonical_equivalence(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] = (90, 120),
    years: Sequence[int | str] | None = None,
    max_elapsed_seconds: float = GOLD_STK_MINS_QFQ_DERIVED_AUDIT_MAX_SECONDS,
    as_of_adj_factor_paths: Sequence[Path] | None = None,
) -> StkMinsQfqDerivedEquivalenceReport:
    """Compare Silver-direct candidates with existing 90m/120m Gold in batches."""

    if max_elapsed_seconds <= 0:
        raise ValueError("Derived equivalence max elapsed seconds must be positive.")
    query_deadline_monotonic = perf_counter() + max_elapsed_seconds
    plan = plan_stk_mins_qfq_derived_history(
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb_resource,
        query_deadline_monotonic=query_deadline_monotonic,
        as_of_adj_factor_paths=as_of_adj_factor_paths,
    )
    if plan.missing_input_count:
        raise FileNotFoundError(
            "Gold qfq derived equivalence inputs are missing: "
            f"{tuple(plan.missing_input_samples)}"
        )
    selected_as_of_adj_factor_paths = tuple(as_of_adj_factor_paths or ()) or (
        silver_adj_factor_path(lake_root, plan.selected_partition_keys[-1]),
    )
    audits: list[StkMinsQfqDerivedEquivalenceBatchAudit] = []
    for batch in plan.batches:
        estimate = plan.estimates_by_batch[(batch.target_freq, batch.year)]
        _validate_derived_equivalence_estimate(estimate)
        audits.append(
            _audit_derived_equivalence_batch(
                lake_root=lake_root,
                duckdb_resource=duckdb_resource,
                batch=batch,
                as_of_adj_factor_paths=selected_as_of_adj_factor_paths,
                query_deadline_monotonic=query_deadline_monotonic,
            )
        )
    return StkMinsQfqDerivedEquivalenceReport(
        plan=plan,
        batch_audits=tuple(audits),
    )


def _audit_derived_equivalence_batch(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    batch: StkMinsQfqDerivedHistoryBatch,
    as_of_adj_factor_paths: Sequence[Path],
    query_deadline_monotonic: float | None,
) -> StkMinsQfqDerivedEquivalenceBatchAudit:
    candidate_sql = build_canonical_gold_stk_mins_qfq_select_sql(
        silver_paths=_source_silver_paths_for_batch(lake_root, batch),
        trade_adj_factor_paths=_trade_adj_factor_paths_for_batch(lake_root, batch),
        as_of_adj_factor_paths=as_of_adj_factor_paths,
        target_freq=batch.target_freq,
        partition_keys=batch.partition_keys,
    )
    with duckdb_resource.connect() as connection:
        with _interrupt_at_query_deadline(
            connection,
            query_deadline_monotonic=query_deadline_monotonic,
            label=f"target discovery freq={batch.target_freq}, year={batch.year}",
        ):
            target_rows = connection.execute(
                f"""
                SELECT DISTINCT ts_code
                FROM ({candidate_sql})
                ORDER BY ts_code
                """
            ).fetchall()
        candidate_target_paths = tuple(
            gold_stk_mins_qfq_path(
                lake_root,
                batch.target_freq,
                str(ts_code),
                batch.year,
            )
            for (ts_code,) in target_rows
        )
        target_freq_root = gold_stk_mins_qfq_path(
            lake_root,
            batch.target_freq,
            "*",
            batch.year,
        ).parents[2]
        existing_target_paths = tuple(
            sorted(
                target_freq_root.glob(
                    f"ts_code=*/year={batch.year}/part-000.parquet"
                )
            )
        )
        target_paths = tuple(
            sorted({*candidate_target_paths, *existing_target_paths})
        )
        missing_paths = tuple(path for path in target_paths if not path.exists())
        if not target_paths or missing_paths:
            raise FileNotFoundError(
                "Gold qfq derived equivalence targets are missing: "
                f"freq={batch.target_freq}, year={batch.year}, "
                f"samples={missing_paths[:5]}."
            )
        with _interrupt_at_query_deadline(
            connection,
            query_deadline_monotonic=query_deadline_monotonic,
            label=f"value comparison freq={batch.target_freq}, year={batch.year}",
        ):
            row = connection.execute(
                f"""
            WITH candidate AS MATERIALIZED (
              {candidate_sql}
            ),
            existing AS MATERIALIZED (
              SELECT *
              FROM read_parquet(?, union_by_name=true)
              WHERE CAST(freq AS INTEGER) = {batch.target_freq}
                AND CAST(trade_date AS DATE) >= DATE '{batch.partition_keys[0]}'
                AND CAST(trade_date AS DATE) <= DATE '{batch.partition_keys[-1]}'
            ),
            comparison AS (
              SELECT
                candidate.ts_code AS candidate_code,
                existing.ts_code AS existing_code,
                (
                  candidate.open IS DISTINCT FROM existing.open
                  AND (
                    candidate.open IS NULL
                    OR existing.open IS NULL
                    OR abs(candidate.open - existing.open)
                      > {GOLD_STK_MINS_QFQ_DERIVED_OHLC_ABS_TOLERANCE}
                  )
                )
                  OR (
                    candidate.high IS DISTINCT FROM existing.high
                    AND (
                      candidate.high IS NULL
                      OR existing.high IS NULL
                      OR abs(candidate.high - existing.high)
                        > {GOLD_STK_MINS_QFQ_DERIVED_OHLC_ABS_TOLERANCE}
                    )
                  )
                  OR (
                    candidate.low IS DISTINCT FROM existing.low
                    AND (
                      candidate.low IS NULL
                      OR existing.low IS NULL
                      OR abs(candidate.low - existing.low)
                        > {GOLD_STK_MINS_QFQ_DERIVED_OHLC_ABS_TOLERANCE}
                    )
                  )
                  OR (
                    candidate.close IS DISTINCT FROM existing.close
                    AND (
                      candidate.close IS NULL
                      OR existing.close IS NULL
                      OR abs(candidate.close - existing.close)
                        > {GOLD_STK_MINS_QFQ_DERIVED_OHLC_ABS_TOLERANCE}
                    )
                  )
                  OR candidate.vol IS DISTINCT FROM existing.vol
                  OR (
                    candidate.amount IS DISTINCT FROM existing.amount
                    AND (
                      candidate.amount IS NULL
                      OR existing.amount IS NULL
                      OR abs(candidate.amount - existing.amount)
                        > {GOLD_STK_MINS_QFQ_DERIVED_AMOUNT_ABS_TOLERANCE}
                    )
                  )
                  OR candidate.exchange IS DISTINCT FROM existing.exchange
                  AS value_mismatch,
                CASE
                    WHEN candidate.open IS NULL OR existing.open IS NULL
                      OR candidate.high IS NULL OR existing.high IS NULL
                      OR candidate.low IS NULL OR existing.low IS NULL
                      OR candidate.close IS NULL OR existing.close IS NULL
                    THEN NULL
                    ELSE greatest(
                      abs(candidate.open - existing.open),
                      abs(candidate.high - existing.high),
                      abs(candidate.low - existing.low),
                      abs(candidate.close - existing.close)
                    )
                  END AS ohlc_abs_difference,
                CASE
                    WHEN candidate.amount IS NULL OR existing.amount IS NULL
                    THEN NULL
                    ELSE abs(candidate.amount - existing.amount)
                  END AS amount_abs_difference
              FROM candidate
              FULL OUTER JOIN existing
                ON candidate.ts_code = existing.ts_code
               AND candidate.freq = existing.freq
               AND candidate.trade_date = existing.trade_date
               AND candidate.trade_time = existing.trade_time
            )
            SELECT
              (SELECT count(*) FROM candidate),
              (SELECT count(*) FROM existing),
              (SELECT coalesce(bit_xor(hash(ts_code, freq, trade_date, trade_time)), 0)
                 FROM candidate),
              (SELECT coalesce(bit_xor(hash(ts_code, freq, trade_date, trade_time)), 0)
                 FROM existing),
              (SELECT coalesce(bit_xor(hash(
                   round(open, {GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES}),
                   round(high, {GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES}),
                   round(low, {GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES}),
                   round(close, {GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES}),
                   vol, round(amount, 6), exchange)), 0)
                 FROM candidate),
              (SELECT coalesce(bit_xor(hash(
                   round(open, {GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES}),
                   round(high, {GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES}),
                   round(low, {GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES}),
                   round(close, {GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES}),
                   vol, round(amount, 6), exchange)), 0)
                 FROM existing),
              count(*) FILTER (WHERE existing_code IS NULL),
              count(*) FILTER (WHERE candidate_code IS NULL),
              count(*) FILTER (
                WHERE candidate_code IS NOT NULL
                  AND existing_code IS NOT NULL
                  AND value_mismatch
              ),
              coalesce(max(ohlc_abs_difference), 0.0),
              coalesce(max(amount_abs_difference), 0.0)
            FROM comparison
            """,
                [[str(path) for path in target_paths]],
            ).fetchone()
    if row is None:
        raise RuntimeError("Gold qfq derived equivalence query returned no row.")
    return StkMinsQfqDerivedEquivalenceBatchAudit(
        target_freq=batch.target_freq,
        year=batch.year,
        candidate_row_count=int(row[0]),
        existing_row_count=int(row[1]),
        candidate_key_hash=int(row[2]),
        existing_key_hash=int(row[3]),
        candidate_value_hash=int(row[4]),
        existing_value_hash=int(row[5]),
        missing_key_count=int(row[6]),
        extra_key_count=int(row[7]),
        value_mismatch_count=int(row[8]),
        max_ohlc_abs_difference=float(row[9]),
        max_amount_abs_difference=float(row[10]),
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
        source_freq = gold_stk_mins_qfq_source_freq(target_freq)
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
    trade_adj_factor_paths: Sequence[Path],
    as_of_adj_factor_paths: Sequence[Path],
    query_deadline_monotonic: float | None = None,
) -> StkMinsQfqDerivedHistoryBatchEstimate:
    target_sql = build_canonical_gold_stk_mins_qfq_select_sql(
        silver_paths=source_paths,
        trade_adj_factor_paths=trade_adj_factor_paths,
        as_of_adj_factor_paths=as_of_adj_factor_paths,
        target_freq=batch.target_freq,
        partition_keys=batch.partition_keys,
    )
    with duckdb_resource.connect() as connection:
        with _interrupt_at_query_deadline(
            connection,
            query_deadline_monotonic=query_deadline_monotonic,
            label=f"source estimate freq={batch.target_freq}, year={batch.year}",
        ):
            source_stats = connection.execute(
                """
            SELECT
              coalesce(sum(source_row_count), 0) AS source_row_count,
              count(*) AS source_stock_day_count,
              count(*) FILTER (WHERE exchange_count > 1) AS exchange_mismatch_count
            FROM (
              SELECT
                ts_code,
                trade_date,
                count(*) AS source_row_count,
                count(DISTINCT upper(trim(CAST(exchange AS VARCHAR)))) AS exchange_count
              FROM read_parquet(?, union_by_name=true)
              GROUP BY ts_code, trade_date
            )
                """,
                [[str(path) for path in source_paths]],
            ).fetchone()
        if source_stats is None:
            raise RuntimeError(
                "Gold qfq derived history source diagnostics returned no rows: "
                f"target_freq={batch.target_freq}, year={batch.year}."
            )
        with _interrupt_at_query_deadline(
            connection,
            query_deadline_monotonic=query_deadline_monotonic,
            label=f"window estimate freq={batch.target_freq}, year={batch.year}",
        ):
            generated_window_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({target_sql})"
                ).fetchone()[0]
            )
        with _interrupt_at_query_deadline(
            connection,
            query_deadline_monotonic=query_deadline_monotonic,
            label=f"target estimate freq={batch.target_freq}, year={batch.year}",
        ):
            target_rows = connection.execute(
                f"""
            SELECT DISTINCT
              CAST(ts_code AS VARCHAR) AS ts_code,
              strftime(CAST(trade_date AS DATE), '%Y') AS year
            FROM ({target_sql})
            ORDER BY ts_code, year
                """
            ).fetchall()

    source_row_count = int(source_stats[0] or 0)
    source_stock_day_count = int(source_stats[1] or 0)
    exchange_mismatch_window_count = int(source_stats[2] or 0)
    expected_window_count = source_stock_day_count * len(
        expected_gold_minute_times("SSE", batch.target_freq)
    )
    incomplete_window_count = expected_window_count - generated_window_count
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
    as_of_adj_factor_path: Path,
) -> StkMinsQfqDerivedHistoryBatchResult:
    source_paths = _source_silver_paths_for_batch(lake_root, batch)
    trade_adj_factor_paths = _trade_adj_factor_paths_for_batch(lake_root, batch)
    derived_select_sql = build_canonical_gold_stk_mins_qfq_select_sql(
        silver_paths=source_paths,
        trade_adj_factor_paths=trade_adj_factor_paths,
        as_of_adj_factor_paths=[as_of_adj_factor_path],
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


def _validate_derived_equivalence_estimate(
    estimate: StkMinsQfqDerivedHistoryBatchEstimate,
) -> None:
    if estimate.source_row_count <= 0 or estimate.source_stock_day_count <= 0:
        raise RuntimeError(
            "Gold qfq derived equivalence source rows are empty: "
            f"target_freq={estimate.target_freq}, year={estimate.year}."
        )
    if estimate.exchange_mismatch_window_count:
        raise RuntimeError(
            "Gold qfq derived equivalence source contains mixed exchanges: "
            f"target_freq={estimate.target_freq}, year={estimate.year}, "
            f"mismatch_count={estimate.exchange_mismatch_window_count}."
        )
    if estimate.generated_window_count <= 0:
        raise RuntimeError(
            "Gold qfq derived equivalence candidate has no complete windows: "
            f"target_freq={estimate.target_freq}, year={estimate.year}."
        )


@contextmanager
def _interrupt_at_query_deadline(
    connection: Any,
    *,
    query_deadline_monotonic: float | None,
    label: str,
) -> Iterator[None]:
    if query_deadline_monotonic is None:
        yield
        return

    remaining_seconds = query_deadline_monotonic - perf_counter()
    if remaining_seconds <= 0:
        raise TimeoutError(
            f"Derived equivalence audit exhausted its time budget before {label}."
        )

    timer = Timer(remaining_seconds, connection.interrupt)
    timer.daemon = True
    timer.start()
    try:
        yield
    except Exception as error:
        if perf_counter() >= query_deadline_monotonic:
            raise TimeoutError(
                f"Derived equivalence audit exhausted its time budget during {label}."
            ) from error
        raise
    finally:
        timer.cancel()


def _source_silver_paths_for_batch(
    lake_root: Path,
    batch: StkMinsQfqDerivedHistoryBatch,
) -> tuple[Path, ...]:
    return tuple(
        silver_stk_mins_path(lake_root, batch.source_freq, partition_key)
        for partition_key in batch.partition_keys
    )


def _trade_adj_factor_paths_for_batch(
    lake_root: Path,
    batch: StkMinsQfqDerivedHistoryBatch,
) -> tuple[Path, ...]:
    return tuple(
        silver_adj_factor_path(lake_root, partition_key)
        for partition_key in batch.partition_keys
    )


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
