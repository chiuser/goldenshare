from __future__ import annotations

from src.foundation.services.sync_v2.observer import ProgressSnapshot, SyncV2Observer


def test_observer_emits_progress_without_execution_id() -> None:
    captured: list[tuple[ProgressSnapshot, str]] = []

    def reporter(snapshot: ProgressSnapshot, message: str) -> None:
        captured.append((snapshot, message))

    observer = SyncV2Observer(progress_reporter=reporter)
    observer.report_progress(
        execution_id=None,
        dataset_key="index_daily",
        unit_total=100,
        unit_done=1,
        unit_failed=0,
        rows_fetched=2000,
        rows_written=2000,
        message="index_daily: 1/100 fetched=2000 written=2000",
    )

    assert len(captured) == 1
    snapshot, message = captured[0]
    assert snapshot.execution_id is None
    assert snapshot.dataset_key == "index_daily"
    assert snapshot.unit_total == 100
    assert snapshot.unit_done == 1
    assert snapshot.unit_failed == 0
    assert snapshot.rows_fetched == 2000
    assert snapshot.rows_written == 2000
    assert message == "index_daily: 1/100 fetched=2000 written=2000"
