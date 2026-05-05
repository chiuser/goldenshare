from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProgressSnapshot:
    run_id: int | None
    dataset_key: str
    unit_total: int
    unit_done: int
    unit_failed: int
    rows_fetched: int
    rows_written: int
    rows_committed: int = 0
    rows_rejected: int = 0
    current_object: dict[str, Any] = field(default_factory=dict)
    rejected_reason_counts: dict[str, int] = field(default_factory=dict)
    rejected_reason_samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


class IngestionObserver:
    def __init__(self, progress_reporter=None) -> None:  # type: ignore[no-untyped-def]
        self.progress_reporter = progress_reporter

    def report_progress(
        self,
        *,
        run_id: int | None,
        dataset_key: str,
        unit_total: int,
        unit_done: int,
        unit_failed: int,
        rows_fetched: int,
        rows_written: int,
        message: str,
        rows_committed: int = 0,
        rows_rejected: int = 0,
        current_object: dict[str, Any] | None = None,
        rejected_reason_counts: dict[str, int] | None = None,
        rejected_reason_samples: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        if self.progress_reporter is None:
            return
        snapshot = ProgressSnapshot(
            run_id=run_id,
            dataset_key=dataset_key,
            unit_total=unit_total,
            unit_done=unit_done,
            unit_failed=unit_failed,
            rows_fetched=rows_fetched,
            rows_written=rows_written,
            rows_committed=rows_committed,
            rows_rejected=rows_rejected,
            current_object=dict(current_object or {}),
            rejected_reason_counts=dict(rejected_reason_counts or {}),
            rejected_reason_samples=dict(rejected_reason_samples or {}),
        )
        self.progress_reporter(snapshot, message)
