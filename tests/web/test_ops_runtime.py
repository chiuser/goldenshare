from __future__ import annotations

from datetime import datetime, timezone

from src.operations.runtime import DispatchOutcome, OperationsDispatcher, OperationsScheduler, OperationsWorker


class StubDispatcher:
    def __init__(self, outcome: DispatchOutcome) -> None:
        self.outcome = outcome
        self.calls: list[int] = []

    def dispatch(self, session, execution):  # type: ignore[no-untyped-def]
        self.calls.append(execution.id)
        return self.outcome


def test_scheduler_enqueues_due_once_schedule(db_session, job_schedule_factory) -> None:
    schedule = job_schedule_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        schedule_type="once",
        next_run_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    assert created[0].schedule_id == schedule.id
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.status == "paused"
    assert refreshed.next_run_at is None


def test_scheduler_reschedules_cron_schedule_after_trigger(db_session, job_schedule_factory) -> None:
    schedule = job_schedule_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
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


def test_worker_claims_queued_execution_and_marks_success(db_session, job_execution_factory) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="queued",
    )
    dispatcher = StubDispatcher(DispatchOutcome(status="success", rows_fetched=10, rows_written=8, summary_message="done"))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.id == execution.id
    assert result.status == "success"
    assert result.rows_fetched == 10
    assert result.rows_written == 8
    assert dispatcher.calls == [execution.id]


def test_dispatcher_progress_snapshot_updates_execution_fields(db_session, job_execution_factory) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="backfill_equity_series.daily",
        status="running",
    )

    dispatcher = OperationsDispatcher()
    dispatcher._update_execution_progress(
        db_session,
        execution.id,
        dispatcher._build_progress_payload("daily: 651/5814 ts_code=002034.SZ fetched=6 written=6"),
    )
    db_session.commit()
    db_session.refresh(execution)

    assert execution.progress_current == 651
    assert execution.progress_total == 5814
    assert execution.progress_percent == 11
    assert execution.progress_message == "daily: 651/5814 ts_code=002034.SZ fetched=6 written=6"
    assert execution.last_progress_at is not None


def test_worker_cancels_queued_execution_before_dispatch(db_session, job_execution_factory) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="queued",
        requested_at=datetime(2026, 3, 30, 11, 0, tzinfo=timezone.utc),
    )
    execution.cancel_requested_at = datetime(2026, 3, 30, 11, 1, tzinfo=timezone.utc)
    db_session.commit()

    dispatcher = StubDispatcher(DispatchOutcome(status="success"))
    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.id == execution.id
    assert result.status == "canceled"
    assert dispatcher.calls == []
