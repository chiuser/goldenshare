from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    normalize_stk_mins_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    GoldStkMinsQfqWriteResult,
    assert_canonical_gold_stk_mins_qfq_source_ready,
    build_canonical_gold_stk_mins_qfq_select_sql,
    build_daily_qfq_coverage_sql,
    gold_stk_mins_qfq_source_freq,
    write_gold_stk_mins_qfq_rows_to_year_files,
)

STK_MINS_QFQ_HISTORY_START_DATE = "2014-01-01"
GOLD_STK_MINS_QFQ_CHECK_COUNT = len(stk_mins_checks.GOLD_STK_MINS_QFQ_CHECK_NAMES)
GOLD_STK_MINS_QFQ_EVENT_COUNT_PER_ASSET_PARTITION = (
    1 + GOLD_STK_MINS_QFQ_CHECK_COUNT
)


@dataclass(frozen=True)
class StkMinsQfqHistoryBatch:
    freq: int
    year: str
    partition_keys: tuple[str, ...]


@dataclass(frozen=True)
class StkMinsQfqHistoryPlan:
    selected_partition_keys: tuple[str, ...]
    selected_freqs: tuple[int, ...]
    selected_years: tuple[str, ...]
    batches: tuple[StkMinsQfqHistoryBatch, ...]
    planned_target_file_count: int
    existing_target_file_count: int
    missing_input_count: int
    missing_input_samples: tuple[str, ...]
    planned_event_count: int
    target_file_counts_by_batch: Mapping[tuple[int, str], int]


@dataclass(frozen=True)
class StkMinsQfqHistoryBatchResult:
    freq: int
    year: str
    partition_keys: tuple[str, ...]
    silver_row_count: int
    written_file_count: int
    written_row_count: int
    write_results: tuple[GoldStkMinsQfqWriteResult, ...]


@dataclass(frozen=True)
class StkMinsQfqHistoryReport:
    plan: StkMinsQfqHistoryPlan
    batch_results: tuple[StkMinsQfqHistoryBatchResult, ...]

    @property
    def written_file_count(self) -> int:
        return sum(result.written_file_count for result in self.batch_results)

    @property
    def written_row_count(self) -> int:
        return sum(result.written_row_count for result in self.batch_results)


@dataclass(frozen=True)
class StkMinsQfqCanonicalRebuildReport:
    plan: StkMinsQfqHistoryPlan
    plan_fingerprint: str
    checkpoint_path: Path
    resumed_batch_count: int
    executed_batch_count: int
    batch_results: tuple[StkMinsQfqHistoryBatchResult, ...]


def plan_stk_mins_qfq_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
    duckdb_resource: DuckDBResource | None = None,
) -> StkMinsQfqHistoryPlan:
    normalized_freqs = _normalize_freqs(freqs)
    normalized_years = _normalize_years(years)
    selected_keys = _select_registered_partition_keys(
        registered_partition_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
        years=normalized_years,
    )
    selected_years = normalized_years or tuple(
        sorted({key[:4] for key in selected_keys})
    )
    batches = _build_batches(
        selected_keys,
        freqs=normalized_freqs,
        years=selected_years,
    )
    as_of_trade_date = selected_keys[-1]
    as_of_adj_factor_path = silver_adj_factor_path(lake_root, as_of_trade_date)
    missing_inputs = _missing_qfq_history_inputs(
        lake_root=lake_root,
        batches=batches,
        as_of_adj_factor_path=as_of_adj_factor_path,
        selected_partition_keys=selected_keys,
    )
    target_counts: dict[tuple[int, str], int] = {}
    existing_target_count = 0
    resource = duckdb_resource or DuckDBResource()
    if not missing_inputs:
        for batch in batches:
            targets = _target_paths_for_batch(
                lake_root=lake_root,
                batch=batch,
                duckdb_resource=resource,
            )
            target_counts[(batch.freq, batch.year)] = len(targets)
            existing_target_count += sum(1 for path in targets if path.exists())
    else:
        target_counts = {(batch.freq, batch.year): 0 for batch in batches}

    return StkMinsQfqHistoryPlan(
        selected_partition_keys=selected_keys,
        selected_freqs=normalized_freqs,
        selected_years=selected_years,
        batches=batches,
        planned_target_file_count=sum(target_counts.values()),
        existing_target_file_count=existing_target_count,
        missing_input_count=len(missing_inputs),
        missing_input_samples=tuple(missing_inputs[:20]),
        planned_event_count=(
            len(selected_keys)
            * len(normalized_freqs)
            * GOLD_STK_MINS_QFQ_EVENT_COUNT_PER_ASSET_PARTITION
        ),
        target_file_counts_by_batch=target_counts,
    )


def generate_stk_mins_qfq_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] | None = None,
    years: Sequence[int | str] | None = None,
) -> StkMinsQfqHistoryReport:
    plan = plan_stk_mins_qfq_history(
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
            "Gold qfq history inputs are missing: "
            f"{tuple(plan.missing_input_samples)}"
        )
    if plan.existing_target_file_count:
        raise FileExistsError(
            "Gold qfq history target files already exist; refusing baseline write: "
            f"{plan.existing_target_file_count}."
        )
    as_of_trade_date = plan.selected_partition_keys[-1]
    as_of_adj_factor_path = silver_adj_factor_path(lake_root, as_of_trade_date)
    batch_results: list[StkMinsQfqHistoryBatchResult] = []
    for batch in plan.batches:
        result = _generate_qfq_history_batch(
            lake_root=lake_root,
            duckdb_resource=duckdb_resource,
            batch=batch,
            as_of_adj_factor_path=as_of_adj_factor_path,
            fail_if_target_exists=True,
        )
        batch_results.append(result)

    return StkMinsQfqHistoryReport(
        plan=plan,
        batch_results=tuple(batch_results),
    )


def rebuild_stk_mins_qfq_canonical_history(
    *,
    checkpoint_path: Path,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    registered_partition_keys: Sequence[str],
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str | None = None,
    freqs: Sequence[int | str] = (5, 15, 30, 60),
    years: Sequence[int | str] | None = None,
) -> StkMinsQfqCanonicalRebuildReport:
    """Rebuild canonical QFQ stock-year files with resumable freq-year batches."""

    plan = plan_stk_mins_qfq_history(
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
            "Canonical Gold qfq rebuild inputs are missing: "
            f"{tuple(plan.missing_input_samples)}"
        )
    plan_fingerprint = _canonical_rebuild_plan_fingerprint(plan)
    completed_batch_keys = _load_canonical_rebuild_checkpoint(
        checkpoint_path=checkpoint_path,
        plan_fingerprint=plan_fingerprint,
    )
    as_of_adj_factor_path = silver_adj_factor_path(
        lake_root,
        plan.selected_partition_keys[-1],
    )
    batch_results: list[StkMinsQfqHistoryBatchResult] = []
    resumed_batch_count = 0
    for batch in plan.batches:
        batch_key = _history_batch_key(batch)
        if batch_key in completed_batch_keys:
            _assert_completed_rebuild_batch_exists(
                lake_root=lake_root,
                batch=batch,
                duckdb_resource=duckdb_resource,
            )
            resumed_batch_count += 1
            continue
        result = _generate_qfq_history_batch(
            lake_root=lake_root,
            duckdb_resource=duckdb_resource,
            batch=batch,
            as_of_adj_factor_path=as_of_adj_factor_path,
            fail_if_target_exists=False,
        )
        batch_results.append(result)
        completed_batch_keys.add(batch_key)
        _write_canonical_rebuild_checkpoint(
            checkpoint_path=checkpoint_path,
            plan_fingerprint=plan_fingerprint,
            completed_batch_keys=completed_batch_keys,
        )
    return StkMinsQfqCanonicalRebuildReport(
        plan=plan,
        plan_fingerprint=plan_fingerprint,
        checkpoint_path=checkpoint_path,
        resumed_batch_count=resumed_batch_count,
        executed_batch_count=len(batch_results),
        batch_results=tuple(batch_results),
    )


def _generate_qfq_history_batch(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    batch: StkMinsQfqHistoryBatch,
    as_of_adj_factor_path: Path,
    fail_if_target_exists: bool,
) -> StkMinsQfqHistoryBatchResult:
    silver_paths = _silver_paths_for_batch(lake_root, batch)
    trade_adj_paths = _trade_adj_factor_paths_for_keys(lake_root, batch.partition_keys)
    coverage_counts = _coverage_counts(
        duckdb_resource=duckdb_resource,
        silver_paths=silver_paths,
        trade_adj_paths=trade_adj_paths,
        as_of_adj_factor_path=as_of_adj_factor_path,
    )
    _validate_coverage_counts(batch=batch, coverage_counts=coverage_counts)
    assert_canonical_gold_stk_mins_qfq_source_ready(
        silver_paths=silver_paths,
        target_freq=batch.freq,
        partition_keys=batch.partition_keys,
    )
    qfq_select_sql = build_canonical_gold_stk_mins_qfq_select_sql(
        silver_paths=silver_paths,
        trade_adj_factor_paths=trade_adj_paths,
        as_of_adj_factor_paths=[as_of_adj_factor_path],
        target_freq=batch.freq,
        partition_keys=batch.partition_keys,
    )
    write_results = write_gold_stk_mins_qfq_rows_to_year_files(
        lake_root=lake_root,
        freq=batch.freq,
        qfq_select_sql=qfq_select_sql,
        replace_trade_dates=batch.partition_keys,
        fail_if_target_exists=fail_if_target_exists,
    )
    return StkMinsQfqHistoryBatchResult(
        freq=batch.freq,
        year=batch.year,
        partition_keys=batch.partition_keys,
        silver_row_count=coverage_counts["silver_row_count"],
        written_file_count=len(write_results),
        written_row_count=sum(result.row_count for result in write_results),
        write_results=tuple(write_results),
    )


def _canonical_rebuild_plan_fingerprint(plan: StkMinsQfqHistoryPlan) -> str:
    payload = {
        "partition_keys": plan.selected_partition_keys,
        "freqs": plan.selected_freqs,
        "years": plan.selected_years,
        "batches": tuple(_history_batch_key(batch) for batch in plan.batches),
        "contract": "cn_a_gold_minute_canonical_v1",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _history_batch_key(batch: StkMinsQfqHistoryBatch) -> str:
    return f"{batch.freq}:{batch.year}:{batch.partition_keys[0]}:{batch.partition_keys[-1]}"


def _load_canonical_rebuild_checkpoint(
    *,
    checkpoint_path: Path,
    plan_fingerprint: str,
) -> set[str]:
    if not checkpoint_path.exists():
        return set()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported canonical QFQ rebuild checkpoint schema.")
    if payload.get("plan_fingerprint") != plan_fingerprint:
        raise ValueError("Canonical QFQ rebuild checkpoint belongs to another plan.")
    completed = payload.get("completed_batch_keys")
    if not isinstance(completed, list) or not all(
        isinstance(item, str) for item in completed
    ):
        raise ValueError("Canonical QFQ rebuild checkpoint batch list is invalid.")
    return set(completed)


def _write_canonical_rebuild_checkpoint(
    *,
    checkpoint_path: Path,
    plan_fingerprint: str,
    completed_batch_keys: set[str],
) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = checkpoint_path.with_name(f".{checkpoint_path.name}.tmp")
    temp_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "plan_fingerprint": plan_fingerprint,
                "completed_batch_keys": sorted(completed_batch_keys),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, checkpoint_path)


def _assert_completed_rebuild_batch_exists(
    *,
    lake_root: Path,
    batch: StkMinsQfqHistoryBatch,
    duckdb_resource: DuckDBResource,
) -> None:
    paths = _target_paths_for_batch(
        lake_root=lake_root,
        batch=batch,
        duckdb_resource=duckdb_resource,
    )
    missing_paths = tuple(path for path in paths if not path.exists())
    if not paths or missing_paths:
        raise FileNotFoundError(
            "Canonical QFQ rebuild checkpoint target files are missing: "
            f"batch={_history_batch_key(batch)}, samples={missing_paths[:5]}."
        )


def _coverage_counts(
    *,
    duckdb_resource: DuckDBResource,
    silver_paths: Sequence[Path],
    trade_adj_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
) -> dict[str, int]:
    coverage_sql = build_daily_qfq_coverage_sql(
        silver_paths=silver_paths,
        trade_adj_factor_paths=trade_adj_paths,
        as_of_adj_factor_paths=[as_of_adj_factor_path],
    )
    with duckdb_resource.connect() as connection:
        row = connection.execute(coverage_sql).fetchone()
    if row is None:
        raise RuntimeError("Gold qfq history coverage query returned no rows.")
    return {
        "silver_row_count": int(row[0]),
        "qfq_output_row_count": int(row[1]),
        "missing_trade_adj_factor_row_count": int(row[2]),
        "missing_as_of_adj_factor_row_count": int(row[3]),
        "invalid_trade_adj_factor_row_count": int(row[4]),
        "invalid_as_of_adj_factor_row_count": int(row[5]),
    }


def _validate_coverage_counts(
    *,
    batch: StkMinsQfqHistoryBatch,
    coverage_counts: Mapping[str, int],
) -> None:
    if coverage_counts["silver_row_count"] <= 0:
        raise RuntimeError(
            "Gold qfq history source silver rows are empty: "
            f"freq={batch.freq}, year={batch.year}."
        )
    if (
        coverage_counts["missing_trade_adj_factor_row_count"]
        or coverage_counts["missing_as_of_adj_factor_row_count"]
        or coverage_counts["invalid_trade_adj_factor_row_count"]
        or coverage_counts["invalid_as_of_adj_factor_row_count"]
    ):
        raise RuntimeError(
            "Gold qfq history factor coverage failed before write: "
            f"freq={batch.freq}, year={batch.year}, counts={dict(coverage_counts)}."
        )


def _target_paths_for_batch(
    *,
    lake_root: Path,
    batch: StkMinsQfqHistoryBatch,
    duckdb_resource: DuckDBResource,
) -> tuple[Path, ...]:
    silver_paths = _silver_paths_for_batch(lake_root, batch)
    source = _read_parquet_paths(silver_paths)
    with duckdb_resource.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT
              CAST(ts_code AS VARCHAR) AS ts_code,
              strftime(CAST(trade_date AS DATE), '%Y') AS year
            FROM {source}
            ORDER BY ts_code, year
            """
        ).fetchall()
    return tuple(
        gold_stk_mins_qfq_path(lake_root, batch.freq, str(ts_code), str(year))
        for ts_code, year in rows
    )


def _missing_qfq_history_inputs(
    *,
    lake_root: Path,
    batches: Sequence[StkMinsQfqHistoryBatch],
    as_of_adj_factor_path: Path,
    selected_partition_keys: Sequence[str],
) -> list[str]:
    missing: list[str] = []
    if not as_of_adj_factor_path.exists():
        missing.append(f"as_of_adj_factor:{as_of_adj_factor_path}")

    for partition_key in selected_partition_keys:
        adj_path = silver_adj_factor_path(lake_root, partition_key)
        if not adj_path.exists():
            missing.append(f"{partition_key}:silver_adj_factor:{adj_path}")

    for batch in batches:
        for path in _silver_paths_for_batch(lake_root, batch):
            if not path.exists():
                missing.append(f"{batch.freq}:{batch.year}:silver_stk_mins:{path}")
    return missing


def _build_batches(
    partition_keys: Sequence[str],
    *,
    freqs: Sequence[int],
    years: Sequence[str],
) -> tuple[StkMinsQfqHistoryBatch, ...]:
    batches: list[StkMinsQfqHistoryBatch] = []
    keys_by_year = {
        year: tuple(key for key in partition_keys if key[:4] == year)
        for year in years
    }
    for freq in freqs:
        for year in years:
            keys = keys_by_year[year]
            if keys:
                batches.append(
                    StkMinsQfqHistoryBatch(
                        freq=freq,
                        year=year,
                        partition_keys=keys,
                    )
                )
    return tuple(batches)


def _select_registered_partition_keys(
    registered_partition_keys: Sequence[str],
    *,
    partition_keys: Sequence[str] | None,
    start_date: str,
    end_date: str | None,
    years: Sequence[str] | None,
) -> tuple[str, ...]:
    registered = tuple(sorted({_normalize_partition_key(key) for key in registered_partition_keys}))
    registered_set = set(registered)
    if partition_keys is not None:
        requested = tuple(sorted({_normalize_partition_key(key) for key in partition_keys}))
        missing = tuple(key for key in requested if key not in registered_set)
        if missing:
            raise ValueError(
                "Requested qfq history partitions are not registered in "
                f"cn_a_stock_mins_silver_trade_days: {missing}."
            )
        selected = requested
    else:
        normalized_start = _normalize_partition_key(start_date)
        normalized_end = _normalize_partition_key(end_date) if end_date else None
        selected = tuple(
            key
            for key in registered
            if key >= normalized_start
            and (normalized_end is None or key <= normalized_end)
        )
    if years:
        year_set = set(years)
        selected = tuple(key for key in selected if key[:4] in year_set)
    if not selected:
        raise ValueError("No registered stk_mins silver partitions selected for qfq history.")
    return selected


def _normalize_freqs(freqs: Sequence[int | str] | None) -> tuple[int, ...]:
    if freqs is None:
        return tuple(STK_MINS_FREQS)
    normalized = tuple(sorted({normalize_stk_mins_freq(freq) for freq in freqs}))
    if not normalized:
        raise ValueError("At least one stk_mins qfq freq is required.")
    return normalized


def _normalize_years(years: Sequence[int | str] | None) -> tuple[str, ...] | None:
    if years is None:
        return None
    normalized = tuple(sorted({_normalize_year(year) for year in years}))
    if not normalized:
        raise ValueError("At least one stk_mins qfq year is required.")
    return normalized


def _normalize_year(year: int | str) -> str:
    value = str(year).strip()
    if len(value) != 4 or not value.isdigit():
        raise ValueError("stk_mins qfq history year must be a four-digit year.")
    return value


def _normalize_partition_key(partition_key: str | None) -> str:
    if partition_key is None:
        raise ValueError("partition key must not be empty.")
    return date.fromisoformat(str(partition_key).strip()).isoformat()


def _silver_paths_for_batch(
    lake_root: Path,
    batch: StkMinsQfqHistoryBatch,
) -> tuple[Path, ...]:
    return tuple(
        silver_stk_mins_path(
            lake_root,
            gold_stk_mins_qfq_source_freq(batch.freq),
            partition_key,
        )
        for partition_key in batch.partition_keys
    )


def _trade_adj_factor_paths_for_keys(
    lake_root: Path,
    partition_keys: Sequence[str],
) -> tuple[Path, ...]:
    return tuple(silver_adj_factor_path(lake_root, key) for key in partition_keys)


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("At least one parquet path is required.")
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    path_list = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{path_list}], hive_partitioning=false, union_by_name=true)"
