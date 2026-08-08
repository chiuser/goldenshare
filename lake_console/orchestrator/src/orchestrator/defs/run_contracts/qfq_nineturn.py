"""Stable contracts for the QFQ nine-turn asset family."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


QFQ_NINETURN_COMPARISON_LAG = 4
QFQ_NINETURN_SIGNAL_THRESHOLD = 9
QFQ_NINETURN_VERSION = 1
QFQ_NINETURN_MINUTE_FREQS = (30, 60, 90, 120)
QFQ_NINETURN_HISTORY_CHECK_WINDOW = 20
QFQ_NINETURN_SENSOR_WINDOW_DAILY = 10
QFQ_NINETURN_SENSOR_WINDOW_MINUTE = 5
QFQ_NINETURN_FALLBACK_CODE_LIMIT = 500
QFQ_NINETURN_SOURCE_CONTEXT_TRADE_DAYS = 20


def normalize_qfq_nineturn_minute_freq(freq: int | str) -> int:
    """Return a supported QFQ nine-turn minute frequency."""

    try:
        normalized = int(freq)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Unsupported QFQ nine-turn minute frequency: {freq!r}."
        ) from exc
    if normalized not in QFQ_NINETURN_MINUTE_FREQS:
        allowed = ", ".join(str(value) for value in QFQ_NINETURN_MINUTE_FREQS)
        raise ValueError(
            "Unsupported QFQ nine-turn minute frequency: "
            f"{freq!r}; expected one of {allowed}."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class QfqNineturnPartitionWriteResult:
    target_path: Path
    source_row_count: int
    output_row_count: int
    stock_code_count: int
    fallback_recomputed_code_count: int
    source_file_count: int
    source_fingerprint: str
    observed_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QfqNineturnSourcePlan:
    source_paths: tuple[Path, ...]
    fingerprint_source_paths: tuple[Path, ...]
    fallback_source_paths: tuple[Path, ...]
    fallback_codes: tuple[str, ...]
    previous_partition_path: Path | None
    source_row_count: int
