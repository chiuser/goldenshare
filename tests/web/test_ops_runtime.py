from __future__ import annotations

from datetime import date, datetime, timezone

from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.runtime import OperationsScheduler, OperationsWorker, TaskRunDispatchOutcome, TaskRunDispatcher
from src.ops.services.operations_serving_light_refresh_service import ServingLightRefreshResult


class StubDispatcher:
    def __init__(self, outcome: TaskRunDispatchOutcome) -> None:
        self.outcome = outcome
        self.calls: list[int] = []

    def dispatch(self, session, task_run):  # type: ignore[no-untyped-def]
        self.calls.append(task_run.id)
        return self.outcome


def test_scheduler_enqueues_due_once_schedule(db_session, job_schedule_factory) -> None:
    schedule = job_schedule_factory(
        spec_type="dataset_action",
        spec_key="stock_basic.maintain",
        schedule_type="once",
        next_run_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    assert created[0].schedule_id == schedule.id
    assert created[0].task_type == "dataset_action"
    assert created[0].resource_key == "stock_basic"
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.status == "paused"
    assert refreshed.next_run_at is None


def test_scheduler_reschedules_cron_schedule_after_trigger(db_session, job_schedule_factory) -> None:
    schedule = job_schedule_factory(
        spec_type="dataset_action",
        spec_key="stock_basic.maintain",
        schedule_type="cron",
        cron_expr="5 * * * *",
        timezone_name="UTC",
        next_run_at=datetime(2026, 3, 30, 10, 5, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 10, 5, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.status == "active"
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == datetime(2026, 3, 30, 11, 5, tzinfo=timezone.utc)


def test_worker_claims_queued_task_run_and_marks_success(db_session, task_run_factory) -> None:
    task_run = task_run_factory(status="queued", resource_key="daily", title="股票日线")
    dispatcher = StubDispatcher(TaskRunDispatchOutcome(status="success", rows_fetched=10, rows_saved=8, rows_rejected=2))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.id == task_run.id
    assert result.status == "success"
    assert result.rows_fetched == 10
    assert result.rows_saved == 8
    assert result.rows_rejected == 2
    assert dispatcher.calls == [task_run.id]


def test_worker_cancels_queued_task_run_before_dispatch(db_session, task_run_factory) -> None:
    requested_at = datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc)
    task_run = task_run_factory(
        status="queued",
        requested_at=requested_at,
        cancel_requested_at=requested_at,
    )
    dispatcher = StubDispatcher(TaskRunDispatchOutcome(status="success"))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.id == task_run.id
    assert result.status == "canceled"
    assert result.status_reason_code == "canceled_before_start"
    assert dispatcher.calls == []


def test_worker_records_issue_when_dispatcher_raises(db_session, task_run_factory) -> None:
    class RaisingDispatcher:
        def dispatch(self, session, task_run):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    task_run = task_run_factory(status="queued", resource_key="daily", title="股票日线")

    result = OperationsWorker(dispatcher=RaisingDispatcher()).run_next(db_session)  # type: ignore[arg-type]

    assert result is not None
    assert result.status == "failed"
    assert result.primary_issue_id is not None
    issue = db_session.get(TaskRunIssue, result.primary_issue_id)
    assert issue is not None
    assert issue.code == "worker_error"


def test_task_run_dispatcher_refreshes_daily_serving_light_with_current_service_api(db_session) -> None:
    class StubServingLightRefreshService:
        def __init__(self) -> None:
            self.calls = []

        def refresh_equity_daily_bar(self, session, *, start_date, end_date, ts_code, commit):  # type: ignore[no-untyped-def]
            self.calls.append(
                {
                    "session": session,
                    "start_date": start_date,
                    "end_date": end_date,
                    "ts_code": ts_code,
                    "commit": commit,
                }
            )
            return ServingLightRefreshResult(touched_rows=12)

    light_service = StubServingLightRefreshService()
    dispatcher = TaskRunDispatcher(serving_light_refresh_service=light_service)  # type: ignore[arg-type]

    note = dispatcher._refresh_serving_light_if_needed(
        db_session,
        task_run_id=123,
        resource="daily",
        rows_saved=8,
        trade_date=date(2026, 4, 24),
        ts_code="000001.SZ",
    )

    assert note == "轻量层刷新 12 行"
    assert light_service.calls == [
        {
            "session": db_session,
            "start_date": date(2026, 4, 24),
            "end_date": date(2026, 4, 24),
            "ts_code": "000001.SZ",
            "commit": True,
        }
    ]
