from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
    _normalize_years,
    _select_registered_partition_keys,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_QFQ_FREQS,
    normalize_stk_mins_qfq_freq,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GoldStkMinsQfqMacdKdjStateWriteResult,
    GoldStkMinsQfqMacdKdjWriteResult,
    discover_gold_stk_mins_qfq_source_year_paths,
    discover_latest_macd_kdj_state_path_before_trade_date,
    write_gold_stk_mins_qfq_macd_kdj_rows,
)


GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_COUNT_PER_FREQ_PARTITION = 6
GOLD_STK_MINS_QFQ_MACD_KDJ_EVENT_COUNT_PER_FREQ_PARTITION = (
    2 + GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_COUNT_PER_FREQ_PARTITION
)


@dataclass(frozen=True)
class StkMinsQfqMacdKdjHistoryBatch:
    freq: int
    year: str
    partition_keys: tuple[str, ...]


@dataclass(frozen=True)
class StkMinsQfqMacdKdjHistoryBatchEstimate:
    freq: int
    year: str
    source_file_count: int
    source_row_count: int
    planned_indicator_file_count: int
    existing_indicator_file_count: int
    planned_state_file_count: int
    existing_state_file_count: int


@dataclass(frozen=True)
class StkMinsQfqMacdKdjHistoryPlan:
    selected_partition_keys: tuple[str, ...]
    selected_freqs: tuple[int, ...]
    selected_years: tuple[str, ...]
    batches: tuple[StkMinsQfqMacdKdjHistoryBatch, ...]
    planned_source_file_count: int
    planned_source_row_count: int
    planned_indicator_file_count: int
    existing_indicator_file_count: int
    planned_state_file_count: int
    existing_state_file_count: int
    missing_input_count: int
    missing_input_samples: tuple[str, ...]
    planned_event_count: int
    estimates_by_batch: Mapping[tuple[int, str], StkMinsQfqMacdKdjHistoryBatchEstimate]

    @property
    def planned_target_file_count(self) -> int:
        return self.planned_indicator_file_count + self.planned_state_file_count

    @property
    def existing_target_file_count(self) -> int:
        return self.existing_indicator_file_count + self.existing_state_file_count


@dataclass(frozen=True)
class StkMinsQfqMacdKdjHistoryBatchResult:
    freq: int
    year: str
    partition_keys: tuple[str, ...]
    indicator_file_count: int
    indicator_row_count: int
    state_file_count: int
    state_row_count: int
    initialized_without_previous_state: bool
    indicator_write_results: tuple[GoldStkMinsQfqMacdKdjWriteResult, ...]
    state_write_results: tuple[GoldStkMinsQfqMacdKdjStateWriteResult, ...]


@dataclass(frozen=True)
class StkMinsQfqMacdKdjHistoryReport:
    plan: StkMinsQfqMacdKdjHistoryPlan
    batch_results: tuple[StkMinsQfqMacdKdjHistoryBatchResult, ...]

    @property
    def written_file_count(self) -> int:
        return sum(
            result.indicator_file_count + result.state_file_count
            for result in self.batch_results
        )

    @property
    def written_row_count(self) -> int:
        return sum(
            result.indicator_row_count + result.state_row_count
            for result in self.batch_results
        )


@dataclass(frozen=True)
class StkMinsQfqMacdKdjFileAuditReport:
    selected_partition_count: int
    selected_freqs: tuple[int, ...]
    selected_years: tuple[str, ...]
    planned_indicator_file_count: int
    existing_indicator_file_count: int
    planned_state_file_count: int
    existing_state_file_count: int
    source_row_count: int
    indicator_row_count: int
    state_row_count: int
    missing_input_count: int
    row_count_mismatch_count: int

    @property
    def passed(self) -> bool:
        return (
            self.missing_input_count == 0
            and self.planned_indicator_file_count == self.existing_indicator_file_count
            and self.planned_state_file_count == self.existing_state_file_count
            and self.row_count_mismatch_count == 0
        )


def plan_stk_mins_qfq_macd_kdj_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    duckdb_resource: DuckDBResource | None = None,
) -> StkMinsQfqMacdKdjHistoryPlan:
    normalized_freqs = _normalize_qfq_freqs(freqs)
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
    batches = _build_macd_kdj_history_batches(
        selected_keys,
        freqs=normalized_freqs,
        years=selected_years,
    )
    resource = duckdb_resource or DuckDBResource()
    estimates: dict[tuple[int, str], StkMinsQfqMacdKdjHistoryBatchEstimate] = {}
    missing_inputs: list[str] = []
    for batch in batches:
        source_paths = discover_gold_stk_mins_qfq_source_year_paths(
            lake_root,
            freq=batch.freq,
            trade_dates=batch.partition_keys,
        )
        if not source_paths:
            missing_inputs.append(
                f"{batch.freq}:{batch.year}:gold_stk_mins_qfq:no source stock-year files"
            )
            estimates[(batch.freq, batch.year)] = StkMinsQfqMacdKdjHistoryBatchEstimate(
                freq=batch.freq,
                year=batch.year,
                source_file_count=0,
                source_row_count=0,
                planned_indicator_file_count=0,
                existing_indicator_file_count=0,
                planned_state_file_count=len(batch.partition_keys),
                existing_state_file_count=0,
            )
            continue
        estimates[(batch.freq, batch.year)] = _estimate_macd_kdj_history_batch(
            lake_root=lake_root,
            duckdb_resource=resource,
            batch=batch,
            source_paths=source_paths,
        )
    return StkMinsQfqMacdKdjHistoryPlan(
        selected_partition_keys=selected_keys,
        selected_freqs=normalized_freqs,
        selected_years=selected_years,
        batches=batches,
        planned_source_file_count=sum(
            estimate.source_file_count for estimate in estimates.values()
        ),
        planned_source_row_count=sum(
            estimate.source_row_count for estimate in estimates.values()
        ),
        planned_indicator_file_count=sum(
            estimate.planned_indicator_file_count for estimate in estimates.values()
        ),
        existing_indicator_file_count=sum(
            estimate.existing_indicator_file_count for estimate in estimates.values()
        ),
        planned_state_file_count=sum(
            estimate.planned_state_file_count for estimate in estimates.values()
        ),
        existing_state_file_count=sum(
            estimate.existing_state_file_count for estimate in estimates.values()
        ),
        missing_input_count=len(missing_inputs),
        missing_input_samples=tuple(missing_inputs[:20]),
        planned_event_count=(
            len(selected_keys)
            * len(normalized_freqs)
            * GOLD_STK_MINS_QFQ_MACD_KDJ_EVENT_COUNT_PER_FREQ_PARTITION
        ),
        estimates_by_batch=estimates,
    )


def generate_stk_mins_qfq_macd_kdj_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
) -> StkMinsQfqMacdKdjHistoryReport:
    plan = plan_stk_mins_qfq_macd_kdj_history(
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
            "Gold qfq MACD/KDJ history inputs are missing: "
            f"{tuple(plan.missing_input_samples)}"
        )
    if plan.existing_target_file_count:
        raise FileExistsError(
            "Gold qfq MACD/KDJ history target files already exist; "
            "refusing baseline write: "
            f"{plan.existing_target_file_count}."
        )

    batch_results: list[StkMinsQfqMacdKdjHistoryBatchResult] = []
    for batch in plan.batches:
        source_paths = discover_gold_stk_mins_qfq_source_year_paths(
            lake_root,
            freq=batch.freq,
            trade_dates=batch.partition_keys,
        )
        previous_state_path = discover_latest_macd_kdj_state_path_before_trade_date(
            lake_root,
            freq=batch.freq,
            trade_date=batch.partition_keys[0],
        )
        indicator_results, state_results, initialized_without_previous_state = (
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=batch.freq,
                source_qfq_paths=source_paths,
                target_trade_dates=batch.partition_keys,
                previous_state_paths=(
                    (previous_state_path,) if previous_state_path is not None else ()
                ),
                fail_if_target_exists=True,
            )
        )
        batch_results.append(
            StkMinsQfqMacdKdjHistoryBatchResult(
                freq=batch.freq,
                year=batch.year,
                partition_keys=batch.partition_keys,
                indicator_file_count=len(indicator_results),
                indicator_row_count=sum(
                    result.replacement_row_count for result in indicator_results
                ),
                state_file_count=len(state_results),
                state_row_count=sum(result.row_count for result in state_results),
                initialized_without_previous_state=initialized_without_previous_state,
                indicator_write_results=tuple(indicator_results),
                state_write_results=tuple(state_results),
            )
        )
    return StkMinsQfqMacdKdjHistoryReport(
        plan=plan,
        batch_results=tuple(batch_results),
    )


def audit_stk_mins_qfq_macd_kdj_files(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    duckdb_resource: DuckDBResource | None = None,
) -> StkMinsQfqMacdKdjFileAuditReport:
    plan = plan_stk_mins_qfq_macd_kdj_history(
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=freqs,
        years=years,
        duckdb_resource=duckdb_resource,
    )
    indicator_rows = 0
    state_rows = 0
    row_count_mismatches = 0
    resource = duckdb_resource or DuckDBResource()
    for batch in plan.batches:
        source_paths = discover_gold_stk_mins_qfq_source_year_paths(
            lake_root,
            freq=batch.freq,
            trade_dates=batch.partition_keys,
        )
        if not source_paths:
            continue
        indicator_paths = _expected_indicator_paths_for_batch(
            lake_root=lake_root,
            duckdb_resource=resource,
            batch=batch,
            source_paths=source_paths,
        )
        existing_indicator_paths = tuple(path for path in indicator_paths if path.exists())
        state_paths = _state_paths_for_batch(lake_root, batch)
        existing_state_paths = tuple(path for path in state_paths if path.exists())
        counts = _file_audit_counts(
            duckdb_resource=resource,
            batch=batch,
            source_paths=source_paths,
            indicator_paths=existing_indicator_paths,
            state_paths=existing_state_paths,
        )
        indicator_rows += counts["indicator_row_count"]
        state_rows += counts["state_row_count"]
        if counts["source_row_count"] != counts["indicator_row_count"]:
            row_count_mismatches += 1
    return StkMinsQfqMacdKdjFileAuditReport(
        selected_partition_count=len(plan.selected_partition_keys),
        selected_freqs=plan.selected_freqs,
        selected_years=plan.selected_years,
        planned_indicator_file_count=plan.planned_indicator_file_count,
        existing_indicator_file_count=plan.existing_indicator_file_count,
        planned_state_file_count=plan.planned_state_file_count,
        existing_state_file_count=plan.existing_state_file_count,
        source_row_count=plan.planned_source_row_count,
        indicator_row_count=indicator_rows,
        state_row_count=state_rows,
        missing_input_count=plan.missing_input_count,
        row_count_mismatch_count=row_count_mismatches,
    )


def _normalize_qfq_freqs(freqs: Sequence[int | str] | None) -> tuple[int, ...]:
    if freqs is None:
        return tuple(STK_MINS_QFQ_FREQS)
    normalized = tuple(sorted({normalize_stk_mins_qfq_freq(freq) for freq in freqs}))
    if not normalized:
        raise ValueError("At least one stk_mins qfq MACD/KDJ freq is required.")
    return normalized


def _build_macd_kdj_history_batches(
    partition_keys: Sequence[str],
    *,
    freqs: Sequence[int],
    years: Sequence[str],
) -> tuple[StkMinsQfqMacdKdjHistoryBatch, ...]:
    keys_by_year = {
        year: tuple(key for key in partition_keys if key[:4] == year)
        for year in years
    }
    batches: list[StkMinsQfqMacdKdjHistoryBatch] = []
    for freq in freqs:
        for year in years:
            keys = keys_by_year[year]
            if keys:
                batches.append(
                    StkMinsQfqMacdKdjHistoryBatch(
                        freq=freq,
                        year=year,
                        partition_keys=keys,
                    )
                )
    return tuple(batches)


def _estimate_macd_kdj_history_batch(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    batch: StkMinsQfqMacdKdjHistoryBatch,
    source_paths: Sequence[Path],
) -> StkMinsQfqMacdKdjHistoryBatchEstimate:
    indicator_paths = _expected_indicator_paths_for_batch(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        batch=batch,
        source_paths=source_paths,
    )
    state_paths = _state_paths_for_batch(lake_root, batch)
    source = _read_parquet_paths(source_paths)
    selected_dates = _date_values_sql(batch.partition_keys)
    with duckdb_resource.connect() as connection:
        source_row_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {source}
                WHERE CAST(freq AS INTEGER) = {batch.freq}
                  AND CAST(trade_date AS DATE) IN (
                    SELECT trade_date FROM {selected_dates}
                  )
                """
            ).fetchone()[0]
        )
    return StkMinsQfqMacdKdjHistoryBatchEstimate(
        freq=batch.freq,
        year=batch.year,
        source_file_count=len(source_paths),
        source_row_count=source_row_count,
        planned_indicator_file_count=len(indicator_paths),
        existing_indicator_file_count=sum(1 for path in indicator_paths if path.exists()),
        planned_state_file_count=len(state_paths),
        existing_state_file_count=sum(1 for path in state_paths if path.exists()),
    )


def _expected_indicator_paths_for_batch(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    batch: StkMinsQfqMacdKdjHistoryBatch,
    source_paths: Sequence[Path],
) -> tuple[Path, ...]:
    source = _read_parquet_paths(source_paths)
    selected_dates = _date_values_sql(batch.partition_keys)
    with duckdb_resource.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT
              CAST(ts_code AS VARCHAR) AS ts_code,
              strftime(CAST(trade_date AS DATE), '%Y') AS year
            FROM {source}
            WHERE CAST(freq AS INTEGER) = {batch.freq}
              AND CAST(trade_date AS DATE) IN (
                SELECT trade_date FROM {selected_dates}
              )
            ORDER BY ts_code, year
            """
        ).fetchall()
    return tuple(
        gold_stk_mins_qfq_macd_kdj_path(lake_root, batch.freq, str(ts_code), str(year))
        for ts_code, year in rows
    )


def _state_paths_for_batch(
    lake_root: Path,
    batch: StkMinsQfqMacdKdjHistoryBatch,
) -> tuple[Path, ...]:
    return tuple(
        gold_stk_mins_qfq_macd_kdj_state_path(lake_root, batch.freq, partition_key)
        for partition_key in batch.partition_keys
    )


def _file_audit_counts(
    *,
    duckdb_resource: DuckDBResource,
    batch: StkMinsQfqMacdKdjHistoryBatch,
    source_paths: Sequence[Path],
    indicator_paths: Sequence[Path],
    state_paths: Sequence[Path],
) -> dict[str, int]:
    source = _read_parquet_paths(source_paths)
    selected_dates = _date_values_sql(batch.partition_keys)
    indicator_source = _optional_read_parquet_paths(indicator_paths)
    state_source = _optional_read_parquet_paths(state_paths)
    with duckdb_resource.connect() as connection:
        row = connection.execute(
            f"""
            WITH source_rows AS (
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(trade_date AS DATE) AS trade_date
              FROM {source}
              WHERE CAST(freq AS INTEGER) = {batch.freq}
                AND CAST(trade_date AS DATE) IN (
                  SELECT trade_date FROM {selected_dates}
                )
            ),
            indicator_rows AS (
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(trade_date AS DATE) AS trade_date
              FROM {indicator_source}
              WHERE CAST(freq AS INTEGER) = {batch.freq}
                AND CAST(trade_date AS DATE) IN (
                  SELECT trade_date FROM {selected_dates}
                )
            ),
            state_rows AS (
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(trade_date AS DATE) AS trade_date
              FROM {state_source}
              WHERE CAST(freq AS INTEGER) = {batch.freq}
                AND CAST(trade_date AS DATE) IN (
                  SELECT trade_date FROM {selected_dates}
                )
            )
            SELECT
              (SELECT count(*) FROM source_rows) AS source_row_count,
              (SELECT count(*) FROM indicator_rows) AS indicator_row_count,
              (SELECT count(DISTINCT ts_code || '|' || CAST(trade_date AS VARCHAR))
               FROM indicator_rows) AS indicator_stock_day_count,
              (SELECT count(*) FROM state_rows) AS state_row_count
            """
        ).fetchone()
    return {
        "source_row_count": int(row[0] or 0),
        "indicator_row_count": int(row[1] or 0),
        "indicator_stock_day_count": int(row[2] or 0),
        "state_row_count": int(row[3] or 0),
    }


def _date_values_sql(trade_dates: Sequence[str]) -> str:
    values = ", ".join(f"(DATE {duckdb_string(trade_date)})" for trade_date in trade_dates)
    if not values:
        raise ValueError("At least one trade date is required.")
    return f"(VALUES {values}) AS selected_dates(trade_date)"


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("At least one parquet path is required.")
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False, union_by_name=True)
    path_list = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{path_list}], hive_partitioning=false, union_by_name=true)"


def _optional_read_parquet_paths(paths: Sequence[Path]) -> str:
    if paths:
        return _read_parquet_paths(paths)
    return "(SELECT NULL AS ts_code, NULL AS freq, NULL AS trade_date WHERE false)"


def source_partition_keys_from_macd_kdj_state_files(
    lake_root: Path,
    *,
    freq: int | str,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
) -> tuple[str, ...]:
    normalized_freq = normalize_stk_mins_qfq_freq(freq)
    root = gold_stk_mins_qfq_macd_kdj_state_path(
        lake_root,
        normalized_freq,
        start_date,
    ).parents[1]
    keys: list[str] = []
    for path in sorted(root.glob("trade_date=*/part-000.parquet")):
        partition_key = path.parent.name.removeprefix("trade_date=")
        if partition_key >= start_date and (end_date is None or partition_key <= end_date):
            keys.append(partition_key)
    return tuple(keys)


def count_indicator_rows_for_partition(
    *,
    lake_root: Path,
    freq: int,
    partition_key: str,
) -> tuple[int, tuple[Path, ...]]:
    source_paths = discover_gold_stk_mins_qfq_source_year_paths(
        lake_root,
        freq=freq,
        trade_dates=[partition_key],
    )
    if not source_paths:
        return 0, ()
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT
              CAST(ts_code AS VARCHAR) AS ts_code,
              strftime(CAST(trade_date AS DATE), '%Y') AS year
            FROM {_read_parquet_paths(source_paths)}
            WHERE CAST(freq AS INTEGER) = {freq}
              AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
            ORDER BY ts_code, year
            """
        ).fetchall()
        paths = tuple(
            gold_stk_mins_qfq_macd_kdj_path(lake_root, freq, str(ts_code), str(year))
            for ts_code, year in rows
        )
        if not paths:
            return 0, ()
        row_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {_read_parquet_paths(tuple(path for path in paths if path.exists()))}
                WHERE CAST(freq AS INTEGER) = {freq}
                  AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
                """
            ).fetchone()[0]
        ) if all(path.exists() for path in paths) else 0
    return row_count, paths
