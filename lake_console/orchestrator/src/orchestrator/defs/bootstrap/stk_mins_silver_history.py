from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.assets.stk_mins import (
    SilverStkMinsWriteResult,
    write_silver_stk_mins_partition,
)
from orchestrator.defs.checks.stk_mins_checks import SILVER_STK_MINS_CHECK_NAMES
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    raw_stk_mins_path,
    silver_namechange_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS

STK_MINS_SILVER_HISTORY_START_DATE = "2014-01-01"


@dataclass(frozen=True)
class StkMinsSilverHistoryPlan:
    selected_partition_keys: tuple[str, ...]
    raw_partition_counts: Mapping[int, int]
    existing_silver_partition_counts: Mapping[int, int]
    planned_write_count: int
    planned_event_count: int
    missing_input_count: int
    missing_input_samples: tuple[str, ...]
    sample_partition_keys: tuple[str, ...]


@dataclass(frozen=True)
class StkMinsSilverHistoryReport:
    selected_partition_keys: tuple[str, ...]
    written_asset_partitions: tuple[tuple[int, str], ...]
    skipped_existing_asset_partitions: tuple[tuple[int, str], ...]
    write_results: tuple[SilverStkMinsWriteResult, ...]


def discover_raw_stk_mins_partitions(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> dict[int, tuple[str, ...]]:
    partitions_by_freq: dict[int, tuple[str, ...]] = {}
    for freq in STK_MINS_FREQS:
        raw_root = Path(lake_root) / "raw" / "tushare" / "stk_mins" / f"freq={freq}"
        partition_keys = sorted(
            path.parent.name.removeprefix("trade_date=")
            for path in raw_root.glob("trade_date=*/part-000.parquet")
            if path.is_file()
        )
        partitions_by_freq[freq] = tuple(partition_keys)
    return partitions_by_freq


def all_raw_stk_mins_partition_keys(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> tuple[str, ...]:
    raw_by_freq = discover_raw_stk_mins_partitions(lake_root)
    _validate_stk_mins_partition_alignment(raw_by_freq)
    return raw_by_freq[STK_MINS_FREQS[0]]


def _validate_stk_mins_partition_alignment(
    partitions_by_freq: Mapping[int, tuple[str, ...]],
) -> None:
    expected = set(partitions_by_freq[STK_MINS_FREQS[0]])
    mismatches = {
        freq: {
            "missing_from_freq": sorted(expected - set(partitions)),
            "extra_in_freq": sorted(set(partitions) - expected),
        }
        for freq, partitions in partitions_by_freq.items()
        if set(partitions) != expected
    }
    if mismatches:
        raise ValueError(f"stk_mins partition sets are not aligned by freq: {mismatches}")


def discover_silver_stk_mins_partitions(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> dict[int, tuple[str, ...]]:
    partitions_by_freq: dict[int, tuple[str, ...]] = {}
    for freq in STK_MINS_FREQS:
        silver_root = (
            Path(lake_root)
            / "silver"
            / "quote"
            / "stk_mins"
            / f"freq={freq}"
        )
        partition_keys = sorted(
            path.parent.name.removeprefix("trade_date=")
            for path in silver_root.glob("trade_date=*/part-000.parquet")
            if path.is_file()
        )
        partitions_by_freq[freq] = tuple(partition_keys)
    return partitions_by_freq


def all_silver_partition_keys(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    *,
    start_date: str = STK_MINS_SILVER_HISTORY_START_DATE,
    end_date: str | None = None,
) -> tuple[str, ...]:
    silver_by_freq = discover_silver_stk_mins_partitions(lake_root)
    _validate_stk_mins_partition_alignment(silver_by_freq)
    return _filter_partition_keys(
        silver_by_freq[STK_MINS_FREQS[0]],
        start_date=start_date,
        end_date=end_date,
    )


def plan_stk_mins_silver_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_SILVER_HISTORY_START_DATE,
    end_date: str | None = None,
) -> StkMinsSilverHistoryPlan:
    raw_by_freq = discover_raw_stk_mins_partitions(lake_root)
    _validate_stk_mins_partition_alignment(raw_by_freq)
    selected_keys = _select_history_partition_keys(
        raw_by_freq[STK_MINS_FREQS[0]],
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
    )
    silver_by_freq = discover_silver_stk_mins_partitions(lake_root)
    existing_silver_counts = {
        freq: sum(1 for key in selected_keys if key in set(silver_by_freq[freq]))
        for freq in STK_MINS_FREQS
    }
    missing_inputs = _missing_history_input_samples(lake_root, selected_keys)
    total_existing = sum(existing_silver_counts.values())
    planned_asset_partitions = len(selected_keys) * len(STK_MINS_FREQS)
    return StkMinsSilverHistoryPlan(
        selected_partition_keys=selected_keys,
        raw_partition_counts={
            freq: len(partitions) for freq, partitions in raw_by_freq.items()
        },
        existing_silver_partition_counts=existing_silver_counts,
        planned_write_count=planned_asset_partitions - total_existing,
        planned_event_count=planned_asset_partitions
        * (1 + len(SILVER_STK_MINS_CHECK_NAMES)),
        missing_input_count=len(missing_inputs),
        missing_input_samples=tuple(missing_inputs[:20]),
        sample_partition_keys=_sample_partition_keys(selected_keys),
    )


def generate_stk_mins_silver_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb: DuckDBResource,
    partition_keys: Sequence[str],
    skip_existing: bool = True,
    overwrite: bool = False,
) -> StkMinsSilverHistoryReport:
    selected_keys = tuple(sorted(set(partition_keys)))
    if not selected_keys:
        raise ValueError("At least one stk_mins partition key is required.")
    missing_inputs = _missing_history_input_samples(lake_root, selected_keys)
    if missing_inputs:
        raise FileNotFoundError(
            "stk_mins silver history inputs are missing: "
            f"{tuple(missing_inputs[:20])}"
        )

    written: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []
    write_results: list[SilverStkMinsWriteResult] = []
    for partition_key in selected_keys:
        for freq in STK_MINS_FREQS:
            target_path = silver_stk_mins_path(lake_root, freq, partition_key)
            if target_path.exists() and skip_existing and not overwrite:
                skipped.append((freq, partition_key))
                continue
            result = write_silver_stk_mins_partition(
                lake_root=lake_root,
                duckdb=duckdb,
                freq=freq,
                partition_key=partition_key,
                overwrite=overwrite,
            )
            written.append((freq, partition_key))
            write_results.append(result)
    return StkMinsSilverHistoryReport(
        selected_partition_keys=selected_keys,
        written_asset_partitions=tuple(written),
        skipped_existing_asset_partitions=tuple(skipped),
        write_results=tuple(write_results),
    )


def _select_history_partition_keys(
    all_keys: Sequence[str],
    *,
    partition_keys: Sequence[str] | None,
    start_date: str,
    end_date: str | None,
) -> tuple[str, ...]:
    available = tuple(all_keys)
    if partition_keys is not None:
        requested = tuple(sorted(set(partition_keys)))
        missing = tuple(key for key in requested if key not in set(available))
        if missing:
            raise ValueError(f"Requested stk_mins raw partitions are missing: {missing}")
        return requested
    return _filter_partition_keys(available, start_date=start_date, end_date=end_date)


def _filter_partition_keys(
    partition_keys: Sequence[str],
    *,
    start_date: str,
    end_date: str | None,
) -> tuple[str, ...]:
    return tuple(
        key
        for key in partition_keys
        if key >= start_date and (end_date is None or key <= end_date)
    )


def _missing_history_input_samples(
    lake_root: Path,
    partition_keys: Sequence[str],
) -> list[str]:
    missing: list[str] = []
    for partition_key in partition_keys:
        common_paths = (
            ("identity_map", silver_stock_identity_map_path(lake_root)),
            ("stock_daily", silver_stock_daily_path(lake_root, partition_key)),
            ("suspend", silver_stock_suspend_daily_path(lake_root, partition_key)),
            ("stock_basic", silver_stock_basic_path(lake_root)),
            ("namechange", silver_namechange_path(lake_root)),
        )
        for label, path in common_paths:
            if not path.exists():
                missing.append(f"{partition_key}:{label}:{path}")
        for freq in STK_MINS_FREQS:
            raw_path = raw_stk_mins_path(lake_root, freq, partition_key)
            if not raw_path.exists():
                missing.append(f"{partition_key}:raw_{freq}m:{raw_path}")
            if freq != 1:
                one_minute_path = raw_stk_mins_path(lake_root, 1, partition_key)
                if not one_minute_path.exists():
                    missing.append(
                        f"{partition_key}:one_minute_raw_for_{freq}m:{one_minute_path}"
                    )
    return missing


def _sample_partition_keys(partition_keys: Sequence[str]) -> tuple[str, ...]:
    if not partition_keys:
        return ()
    ordered = tuple(partition_keys)
    return tuple(dict.fromkeys((ordered[0], ordered[len(ordered) // 2], ordered[-1])))
