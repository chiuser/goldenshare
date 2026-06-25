from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.runtime.task_completion_worker import TaskRunCompletionWorker
from src.ops.services.index_daily_completeness_repair_service import INDEX_DAILY_GAP_REPAIR_RUN_SCOPE
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

    def create_index_daily_completion_audit_run(self, session, task_run, *, now=None):  # type: ignore[no-untyped-def]
        return super().create_index_daily_completion_audit_run(session, task_run, now=now)


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


def test_completion_worker_creates_index_daily_audit_after_non_repair_success(db_session, task_run_factory) -> None:
    local_today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date()
    base = datetime.now(timezone.utc).replace(microsecond=0)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=local_today,
            is_open=True,
            pretrade_date=local_today - timedelta(days=1),
        )
    )
    task_run = task_run_factory(
        status="success",
        resource_key="index_daily",
        action="maintain",
        title="指数日线行情",
        trigger_source="schedule",
        time_input_json={"mode": "point", "trade_date": local_today.isoformat()},
        request_payload_json={},
        ended_at=base + timedelta(seconds=1),
        started_at=base,
    )
    completion_service = FakeCompletionService()
    notification_service = FakeNotificationService()
    worker = TaskRunCompletionWorker(completion_service=completion_service, notification_service=notification_service)
    worker._cursor = TaskRunCompletionCursor(ended_at=base, task_run_id=0)

    processed = worker.run_cycle(db_session, batch_size=10)

    assert processed == 1
    audit_run = db_session.scalar(select(DatasetDateCompletenessRun).where(DatasetDateCompletenessRun.dataset_key == "index_daily"))
    assert audit_run is not None
    assert audit_run.run_mode == "scheduled"
    assert audit_run.run_status == "queued"
    assert audit_run.schedule_id is None
    assert audit_run.audit_scope == "date_subject_matrix"
    assert audit_run.start_date == local_today
    assert audit_run.end_date == local_today
    assert notification_service.sent_task_run_ids == [task_run.id]


def test_completion_worker_skips_index_daily_audit_for_repair_success(db_session, task_run_factory) -> None:
    local_today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date()
    base = datetime.now(timezone.utc).replace(microsecond=0)
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=local_today,
            is_open=True,
            pretrade_date=local_today - timedelta(days=1),
        )
    )
    task_run_factory(
        status="success",
        resource_key="index_daily",
        action="maintain",
        title="指数日线行情",
        trigger_source="system",
        time_input_json={"mode": "point", "trade_date": local_today.isoformat()},
        request_payload_json={"run_scope": INDEX_DAILY_GAP_REPAIR_RUN_SCOPE},
        ended_at=base + timedelta(seconds=1),
        started_at=base,
    )
    completion_service = FakeCompletionService()
    notification_service = FakeNotificationService()
    worker = TaskRunCompletionWorker(completion_service=completion_service, notification_service=notification_service)
    worker._cursor = TaskRunCompletionCursor(ended_at=base, task_run_id=0)

    processed = worker.run_cycle(db_session, batch_size=10)

    assert processed == 1
    assert db_session.scalar(select(DatasetDateCompletenessRun).where(DatasetDateCompletenessRun.dataset_key == "index_daily")) is None
