from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.ops.runtime.task_completion_worker import TaskRunCompletionWorker
from src.ops.services.task_run_completion_service import TaskRunCompletionCursor, TaskRunCompletionService


class FakeNotificationService:
    def __init__(self) -> None:
        self.sent_task_run_ids: list[int] = []
        self.fail_task_run_ids: set[int] = set()

    def send_task_completion(self, summary):  # type: ignore[no-untyped-def]
        self.sent_task_run_ids.append(summary.task_run_id)
        if summary.task_run_id in self.fail_task_run_ids:
            raise RuntimeError("notify boom")
        return True


class FakeCompletionService(TaskRunCompletionService):
    def __init__(self) -> None:
        super().__init__()
        self.refreshed_task_run_ids: list[int] = []
        self.fail_refresh_task_run_ids: set[int] = set()

    def refresh_snapshot_for_task_run(self, session, task_run):  # type: ignore[no-untyped-def]
        self.refreshed_task_run_ids.append(task_run.id)
        if task_run.id in self.fail_refresh_task_run_ids:
            raise RuntimeError("snapshot boom")
        return 1


def test_completion_worker_initializes_cursor_without_replaying_history(db_session, task_run_factory) -> None:
    now = datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc)
    history = task_run_factory(status="success", ended_at=now, started_at=now - timedelta(minutes=1))
    completion_service = FakeCompletionService()
    notification_service = FakeNotificationService()
    worker = TaskRunCompletionWorker(completion_service=completion_service, notification_service=notification_service)

    processed = worker.run_cycle(db_session, batch_size=10)

    assert processed == 0
    assert completion_service.refreshed_task_run_ids == []
    assert notification_service.sent_task_run_ids == []

    fresh = task_run_factory(status="success", ended_at=now + timedelta(seconds=1), started_at=now)
    processed = worker.run_cycle(db_session, batch_size=10)

    assert processed == 1
    assert completion_service.refreshed_task_run_ids == [fresh.id]
    assert notification_service.sent_task_run_ids == [fresh.id]
    assert history.id not in notification_service.sent_task_run_ids


def test_completion_worker_scans_terminal_statuses_in_cursor_order(db_session, task_run_factory) -> None:
    base = datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc)
    running = task_run_factory(status="running", ended_at=None, started_at=base)
    items = [
        task_run_factory(status=status, ended_at=base + timedelta(seconds=index), started_at=base)
        for index, status in enumerate(("success", "partial_success", "failed", "canceled"), start=1)
    ]
    completion_service = FakeCompletionService()
    notification_service = FakeNotificationService()
    worker = TaskRunCompletionWorker(completion_service=completion_service, notification_service=notification_service)
    worker._cursor = TaskRunCompletionCursor(ended_at=base, task_run_id=0)

    processed = worker.run_cycle(db_session, batch_size=10)

    assert processed == 4
    assert notification_service.sent_task_run_ids == [item.id for item in items]
    assert running.id not in notification_service.sent_task_run_ids


def test_completion_worker_isolates_snapshot_and_notification_failures(db_session, task_run_factory) -> None:
    base = datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc)
    first = task_run_factory(status="success", ended_at=base + timedelta(seconds=1), started_at=base)
    second = task_run_factory(status="failed", ended_at=base + timedelta(seconds=2), started_at=base)
    completion_service = FakeCompletionService()
    notification_service = FakeNotificationService()
    completion_service.fail_refresh_task_run_ids.add(first.id)
    notification_service.fail_task_run_ids.add(second.id)
    worker = TaskRunCompletionWorker(completion_service=completion_service, notification_service=notification_service)
    worker._cursor = TaskRunCompletionCursor(ended_at=base, task_run_id=0)

    processed = worker.run_cycle(db_session, batch_size=10)
    processed_again = worker.run_cycle(db_session, batch_size=10)

    assert processed == 2
    assert processed_again == 0
    assert completion_service.refreshed_task_run_ids == [first.id, second.id]
    assert notification_service.sent_task_run_ids == [first.id, second.id]
