from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProgressSnapshot:
    execution_id: int | None
    dataset_key: str
    unit_total: int
    unit_done: int
    unit_failed: int
    rows_fetched: int
    rows_written: int
    rows_rejected: int = 0
    rejected_reason_counts: dict[str, int] = field(default_factory=dict)


class SyncV2Observer:
    def __init__(self, progress_reporter=None) -> None:  # type: ignore[no-untyped-def]
        self.progress_reporter = progress_reporter

    def report_progress(
        self,
        *,
        execution_id: int | None,
        dataset_key: str,
        unit_total: int,
        unit_done: int,
        unit_failed: int,
        rows_fetched: int,
        rows_written: int,
        message: str,
        rows_rejected: int = 0,
        rejected_reason_counts: dict[str, int] | None = None,
    ) -> None:
        if self.progress_reporter is None:
            return
        snapshot = ProgressSnapshot(
            execution_id=execution_id,
            dataset_key=dataset_key,
            unit_total=unit_total,
            unit_done=unit_done,
            unit_failed=unit_failed,
            rows_fetched=rows_fetched,
            rows_written=rows_written,
            rows_rejected=rows_rejected,
            rejected_reason_counts=dict(rejected_reason_counts or {}),
        )
        self.progress_reporter(snapshot, message)
