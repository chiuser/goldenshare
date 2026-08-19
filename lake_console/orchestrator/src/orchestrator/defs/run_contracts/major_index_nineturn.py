"""Stable contracts for major-index daily and minute nine-turn assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_COMPARISON_LAG,
    QFQ_NINETURN_SIGNAL_THRESHOLD,
    QFQ_NINETURN_VERSION,
)

MAJOR_INDEX_NINETURN_COMPARISON_LAG = QFQ_NINETURN_COMPARISON_LAG
MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD = QFQ_NINETURN_SIGNAL_THRESHOLD
MAJOR_INDEX_NINETURN_VERSION = QFQ_NINETURN_VERSION
MAJOR_INDEX_NINETURN_MINUTE_FREQS = (5, 15, 30, 60, 90, 120)
MAJOR_INDEX_NINETURN_DAILY_ASSET_KEY = "gold_major_index_daily_nineturn"
MAJOR_INDEX_NINETURN_MINUTE_ASSET_KEYS = tuple(
    f"gold_major_index_mins_nineturn_{freq}m"
    for freq in MAJOR_INDEX_NINETURN_MINUTE_FREQS
)
MAJOR_INDEX_NINETURN_ASSET_KEYS = (
    MAJOR_INDEX_NINETURN_DAILY_ASSET_KEY,
    *MAJOR_INDEX_NINETURN_MINUTE_ASSET_KEYS,
)
MAJOR_INDEX_NINETURN_CHECK_NAMES = tuple(
    f"{asset_key}_integrity_check" for asset_key in MAJOR_INDEX_NINETURN_ASSET_KEYS
)
MAJOR_INDEX_NINETURN_DAILY_JOB_NAME = "gold_major_index_daily_nineturn_update_job"
MAJOR_INDEX_NINETURN_MINUTE_JOB_NAME = "gold_major_index_mins_nineturn_update_job"
MAJOR_INDEX_NINETURN_DAILY_SENSOR_NAME = (
    "gold_major_index_daily_nineturn_update_job_sensor"
)
MAJOR_INDEX_NINETURN_MINUTE_SENSOR_NAME = (
    "gold_major_index_mins_nineturn_update_job_sensor"
)
MAJOR_INDEX_NINETURN_SOURCE_CONTEXT_TRADE_DAYS = 20
MAJOR_INDEX_NINETURN_SENSOR_WINDOW_DAILY = 10
MAJOR_INDEX_NINETURN_SENSOR_WINDOW_MINUTE = 5
MAJOR_INDEX_NINETURN_HISTORY_BATCH_TRADE_DAYS = 20
MAJOR_INDEX_NINETURN_HISTORY_CHECK_WINDOW = 20
MAJOR_INDEX_NINETURN_HISTORY_MEMORY_LIMIT = "256MB"
MAJOR_INDEX_NINETURN_HISTORY_THREADS = 1


def normalize_major_index_nineturn_minute_freq(freq: int | str) -> int:
    try:
        normalized = int(str(freq).lower().removesuffix("min").removesuffix("m"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Unsupported major-index nine-turn minute frequency: {freq!r}."
        ) from exc
    if normalized not in MAJOR_INDEX_NINETURN_MINUTE_FREQS:
        allowed = ", ".join(str(value) for value in MAJOR_INDEX_NINETURN_MINUTE_FREQS)
        raise ValueError(
            "Unsupported major-index nine-turn minute frequency: "
            f"{freq!r}; expected one of {allowed}."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class MajorIndexNineturnSourcePlan:
    source_paths: tuple[Path, ...]
    previous_partition_path: Path | None
    source_row_count: int


@dataclass(frozen=True, slots=True)
class MajorIndexNineturnPartitionWriteResult:
    target_path: Path
    source_row_count: int
    output_row_count: int
    index_code_count: int
    source_file_count: int
    source_fingerprint: str
    observed_columns: tuple[str, ...]


__all__ = [
    "MAJOR_INDEX_NINETURN_ASSET_KEYS",
    "MAJOR_INDEX_NINETURN_CHECK_NAMES",
    "MAJOR_INDEX_NINETURN_COMPARISON_LAG",
    "MAJOR_INDEX_NINETURN_DAILY_ASSET_KEY",
    "MAJOR_INDEX_NINETURN_DAILY_JOB_NAME",
    "MAJOR_INDEX_NINETURN_DAILY_SENSOR_NAME",
    "MAJOR_INDEX_NINETURN_HISTORY_BATCH_TRADE_DAYS",
    "MAJOR_INDEX_NINETURN_HISTORY_CHECK_WINDOW",
    "MAJOR_INDEX_NINETURN_HISTORY_MEMORY_LIMIT",
    "MAJOR_INDEX_NINETURN_HISTORY_THREADS",
    "MAJOR_INDEX_NINETURN_MINUTE_ASSET_KEYS",
    "MAJOR_INDEX_NINETURN_MINUTE_FREQS",
    "MAJOR_INDEX_NINETURN_MINUTE_JOB_NAME",
    "MAJOR_INDEX_NINETURN_MINUTE_SENSOR_NAME",
    "MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD",
    "MAJOR_INDEX_NINETURN_SOURCE_CONTEXT_TRADE_DAYS",
    "MAJOR_INDEX_NINETURN_VERSION",
    "MajorIndexNineturnPartitionWriteResult",
    "MajorIndexNineturnSourcePlan",
    "normalize_major_index_nineturn_minute_freq",
]
