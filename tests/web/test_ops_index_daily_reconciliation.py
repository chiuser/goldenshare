from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.task_run import TaskRun
from src.ops.runtime.scheduler import OperationsScheduler
from src.ops.services.date_completeness_audit_service import DateCompletenessAuditWorker
from src.ops.services.date_completeness_run_service import DateCompletenessRunCommandService
from src.ops.services.index_daily_completeness_reconciliation_service import IndexDailyCompletenessReconciliationService
from src.ops.services.index_daily_reconciliation_policy import (
    INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
    INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
    INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
    INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL,
    previous_open_day_repair_slot_for_time,
)


def _create_main_task(task_run_factory, **overrides):
    # Persist the real TaskRun contract; 11:00 UTC is the agreed Shanghai 19:00.
    values = dict(
        resource_key="index_daily", action="maintain", status="success", trigger_source="probe",
        time_input_json={"mode": "point", "trade_date": "2026-04-24"},
        request_payload_json={"run_scope": "probe_triggered"},
        requested_at=datetime(2026, 4, 24, 9, 30, tzinfo=timezone.utc),
        started_at=datetime(2026, 4, 24, 9, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 4, 24, 9, 40, tzinfo=timezone.utc),
    )
    values.update(overrides)
    return task_run_factory(**values)


@pytest.mark.parametrize("now,expected_count", [
    (datetime(2026, 4, 24, 10, 59, 59, tzinfo=timezone.utc), 0),
    (datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc), 1),
])
def test_same_day_initial_audit_starts_at_shanghai_1900(db_session, task_run_factory, now, expected_count):
    _seed_open_days(db_session, date(2026, 4, 24))
    _create_main_task(task_run_factory)

    runs = IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now)

    assert len(runs) == expected_count
    if runs:
        assert runs[0].start_date == runs[0].end_date == date(2026, 4, 24)
        assert runs[0].requested_at.replace(tzinfo=timezone.utc) == now


@pytest.mark.parametrize("status", ["queued", "running", "canceling"])
@pytest.mark.parametrize("run_scope", ["probe_triggered", INDEX_DAILY_GAP_REPAIR_RUN_SCOPE])
def test_same_day_initial_waits_for_open_maintenance_then_resumes(db_session, task_run_factory, status, run_scope):
    _seed_open_days(db_session, date(2026, 4, 24))
    _create_main_task(task_run_factory)  # An earlier success must not hide another open task.
    pending = _create_main_task(task_run_factory, status=status, ended_at=None,
                                request_payload_json={"run_scope": run_scope})
    now = datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc)
    assert IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now) == []

    pending.status = "success"
    pending.ended_at = now + timedelta(minutes=5)
    db_session.commit()

    runs = IndexDailyCompletenessReconciliationService().enqueue_due_audits(
        db_session, now=now + timedelta(minutes=5),
    )
    assert len(runs) == 1


@pytest.mark.parametrize("overrides", [
    {"status": "partial_success"}, {"status": "failed"}, {"status": "canceled"},
    {"ended_at": None}, {"task_type": "workflow"}, {"resource_key": "equity_daily"},
    {"request_payload_json": {"run_scope": INDEX_DAILY_GAP_REPAIR_RUN_SCOPE}},
    {"time_input_json": {"mode": "point", "trade_date": "2026-04-23"}},
    {"time_input_json": {"mode": "range", "start_date": "2026-04-24", "end_date": "2026-04-24"}},
])
def test_same_day_initial_requires_successful_current_day_main_task(db_session, task_run_factory, overrides):
    _seed_open_days(db_session, date(2026, 4, 24))
    _create_main_task(task_run_factory, **overrides)
    assert IndexDailyCompletenessReconciliationService().enqueue_due_audits(
        db_session, now=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
    ) == []


@pytest.mark.parametrize("open_day", [None, False])
def test_same_day_initial_skips_missing_calendar_or_closed_day(db_session, task_run_factory, open_day):
    if open_day is not None:
        db_session.add(TradeCalendar(exchange="SSE", trade_date=date(2026, 4, 24), is_open=open_day))
        db_session.commit()
    _create_main_task(task_run_factory)
    assert IndexDailyCompletenessReconciliationService().enqueue_due_audits(
        db_session, now=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
    ) == []


def test_same_day_initial_requires_a_main_task(db_session):
    _seed_open_days(db_session, date(2026, 4, 24))
    db_session.commit()
    assert IndexDailyCompletenessReconciliationService().enqueue_due_audits(
        db_session, now=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
    ) == []


@pytest.mark.parametrize("payload", [{}, {"run_scope": None}])
def test_same_day_initial_accepts_ordinary_task_without_repair_scope(db_session, task_run_factory, payload):
    _seed_open_days(db_session, date(2026, 4, 24))
    _create_main_task(task_run_factory, request_payload_json=payload)
    # A different target date does not block today's audit.
    _create_main_task(task_run_factory, status="running", ended_at=None,
                     time_input_json={"mode": "point", "trade_date": "2026-04-23"})
    assert len(IndexDailyCompletenessReconciliationService().enqueue_due_audits(
        db_session, now=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
    )) == 1


@pytest.mark.parametrize("status,result", [
    ("queued", None), ("running", None), ("succeeded", "passed"),
    ("succeeded", "failed"), ("failed", "error"), ("canceled", None),
])
def test_same_day_initial_does_not_repeat_after_audit_or_service_restart(
    db_session, task_run_factory, status, result,
):
    _seed_open_days(db_session, date(2026, 4, 24))
    _create_main_task(task_run_factory)
    now = datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc)
    runs = IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now)
    assert len(runs) == 1
    run = runs[0]
    run.run_status, run.result_status = status, result
    run.missing_cell_count = 1 if result == "failed" else 0
    db_session.commit()

    assert IndexDailyCompletenessReconciliationService().enqueue_due_audits(
        db_session, now=now + timedelta(minutes=1),
    ) == []


def test_same_day_initial_reaudits_after_early_system_audit(db_session, task_run_factory):
    _seed_open_days(db_session, date(2026, 4, 24))
    _create_main_task(task_run_factory)
    _create_failed_audit(db_session, trade_date=date(2026, 4, 24),
                         finished_at=datetime(2026, 4, 24, 9, 41, tzinfo=timezone.utc))
    assert len(IndexDailyCompletenessReconciliationService().enqueue_due_audits(
        db_session, now=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
    )) == 1


@pytest.mark.parametrize("attributes", [
    {"run_mode": "manual", "requested_by_user_id": 7}, {"schedule_id": 29},
])
def test_same_day_initial_does_not_count_manual_or_configured_audit(db_session, task_run_factory, attributes):
    _seed_open_days(db_session, date(2026, 4, 24))
    _create_main_task(task_run_factory)
    now = datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc)
    other = DateCompletenessRunCommandService().create_system_run(
        db_session, dataset_key="index_daily", start_date=date(2026, 4, 24), end_date=date(2026, 4, 24), now=now,
    )
    for key, value in attributes.items():
        setattr(other, key, value)
    other.run_status, other.result_status = "succeeded", "passed"
    db_session.commit()
    assert len(IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now)) == 1


def test_same_day_initial_waits_for_early_audit_to_finish(db_session, task_run_factory):
    _seed_open_days(db_session, date(2026, 4, 24))
    _create_main_task(task_run_factory)
    run = DateCompletenessRunCommandService().create_system_run(
        db_session, dataset_key="index_daily", start_date=date(2026, 4, 24), end_date=date(2026, 4, 24),
        now=datetime(2026, 4, 24, 10, 59, tzinfo=timezone.utc),
    )
    now = datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc)
    assert IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now) == []
    run.run_status, run.result_status = "succeeded", "passed"
    db_session.commit()
    assert len(IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now)) == 1


def test_same_day_initial_resumes_when_audit_creation_did_not_commit(db_session, task_run_factory, monkeypatch):
    _seed_open_days(db_session, date(2026, 4, 24))
    _create_main_task(task_run_factory)
    now = datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc)
    with monkeypatch.context() as patch:
        def interrupted(*args, **kwargs):
            raise RuntimeError("interrupted before audit creation")
        patch.setattr(DateCompletenessRunCommandService, "create_system_run", interrupted)
        with pytest.raises(RuntimeError, match="interrupted before audit creation"):
            IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now)
    assert list(db_session.scalars(select(DatasetDateCompletenessRun))) == []
    assert len(IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now)) == 1


@pytest.mark.parametrize("already_complete", [False, True])
def test_scheduler_1900_runs_real_audit_and_creates_repair_intention(
    db_session, task_run_factory, monkeypatch, already_complete,
):
    # Real ORM producers and audit executor; literal two-code expected gap.
    _seed_open_days(db_session, date(2026, 4, 24), date(2026, 4, 23))
    for code in ("000001.SH", "399001.SZ"):
        _seed_active_raw(db_session, ts_code=code, trade_date=date(2026, 4, 23))
        if already_complete:
            db_session.add(IndexDailyServing(ts_code=code, trade_date=date(2026, 4, 24)))
    _create_main_task(task_run_factory)
    now = datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("src.ops.services.date_completeness_audit_service._utcnow", lambda: now)
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    monkeypatch.setattr("src.ops.services.index_daily_completeness_repair_service.datetime", FixedDateTime)

    assert OperationsScheduler().run_once(db_session, now=now) == []
    audit = DateCompletenessAuditWorker().run_next(db_session)

    assert audit is not None
    assert audit.run_status == "succeeded"
    assert audit.result_status == ("passed" if already_complete else "failed")
    assert audit.expected_cell_count == 2
    assert audit.missing_cell_count == (0 if already_complete else 2)
    repairs = list(db_session.scalars(select(TaskRun).where(TaskRun.trigger_source == "system")))
    if already_complete:
        assert repairs == []
        assert IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now) == []
        return
    assert len(repairs) == 1
    assert repairs[0].time_input_json == {"mode": "point", "trade_date": "2026-04-24"}
    assert repairs[0].filters_json == {"ts_code": "000001.SH,399001.SZ"}
    assert repairs[0].request_payload_json["repair_slot"] == INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL
    assert repairs[0].request_payload_json["source_date_completeness_run_id"] == audit.id
    assert IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now) == []


def _seed_open_days(session: Session, *trade_dates: date) -> None:
    session.add_all(
        [
            TradeCalendar(exchange="SSE", trade_date=trade_date, is_open=True, pretrade_date=None)
            for trade_date in trade_dates
        ]
    )


def _seed_active_raw(session: Session, *, ts_code: str, trade_date: date) -> None:
    session.add(
        IndexSeriesActive(
            resource="index_daily",
            ts_code=ts_code,
            first_seen_date=trade_date,
            last_seen_date=trade_date,
            last_checked_at=datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc),
        )
    )
    session.add(
        RawIndexDaily(
            ts_code=ts_code,
            trade_date=trade_date,
            api_name="index_daily",
            fetched_at=datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc),
        )
    )


def _create_failed_audit(
    session: Session,
    *,
    trade_date: date,
    finished_at: datetime,
    requested_at: datetime | None = None,
) -> DatasetDateCompletenessRun:
    run = DateCompletenessRunCommandService().create_system_run(
        session,
        dataset_key="index_daily",
        start_date=trade_date,
        end_date=trade_date,
        now=requested_at or finished_at - timedelta(minutes=1),
    )
    run.run_status = "succeeded"
    run.result_status = "failed"
    run.missing_cell_count = 1
    run.affected_bucket_count = 1
    run.affected_subject_count = 1
    run.finished_at = finished_at
    session.commit()
    session.refresh(run)
    return run


def _create_repair(
    session: Session,
    *,
    trade_date: date,
    status: str,
    repair_slot: str,
    worker_claimed: bool,
) -> None:
    occurred_at = datetime(2026, 4, 24, 2, 0, tzinfo=timezone.utc)
    session.add(
        TaskRun(
            task_type="dataset_action",
            resource_key="index_daily",
            action="maintain",
            title="指数日线",
            trigger_source="system",
            status=status,
            time_input_json={"mode": "point", "trade_date": trade_date.isoformat()},
            filters_json={"ts_code": "000001.SH"},
            request_payload_json={
                "run_scope": INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
                "repair_slot": repair_slot,
            },
            plan_snapshot_json={},
            current_object_json={},
            requested_at=occurred_at,
            started_at=occurred_at if worker_claimed else None,
            ended_at=occurred_at if status in {"success", "partial_success", "failed", "canceled"} else None,
        )
    )
    session.commit()


def test_previous_open_day_repair_slot_windows_are_exact() -> None:
    assert previous_open_day_repair_slot_for_time(time(8, 59)) is None
    assert previous_open_day_repair_slot_for_time(time(9, 0)) == INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING
    assert previous_open_day_repair_slot_for_time(time(12, 0)) == INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING
    assert previous_open_day_repair_slot_for_time(time(12, 1)) is None
    assert previous_open_day_repair_slot_for_time(time(13, 30)) == INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON
    assert previous_open_day_repair_slot_for_time(time(16, 30)) == INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON
    assert previous_open_day_repair_slot_for_time(time(16, 31)) is None


def test_reconciliation_enqueues_previous_open_day_audit_in_morning_window(db_session: Session) -> None:
    previous_open_day = date(2026, 4, 23)
    _seed_open_days(db_session, date(2026, 4, 24), previous_open_day, date(2026, 4, 22))
    _seed_active_raw(db_session, ts_code="000001.SH", trade_date=date(2026, 4, 22))
    db_session.commit()
    now = datetime(2026, 4, 24, 2, 0, tzinfo=timezone.utc)
    _create_failed_audit(db_session, trade_date=previous_open_day, finished_at=now - timedelta(hours=1))

    runs = IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now)

    assert len(runs) == 1
    assert runs[0].start_date == previous_open_day
    assert runs[0].end_date == previous_open_day
    assert runs[0].run_status == "queued"
    assert runs[0].requested_at.replace(tzinfo=timezone.utc) == now


def test_reconciliation_does_not_enqueue_current_day_audit_in_evening_window(db_session: Session) -> None:
    current_day = date(2026, 4, 24)
    _seed_open_days(db_session, current_day, date(2026, 4, 23), date(2026, 4, 22))
    _seed_active_raw(db_session, ts_code="000001.SH", trade_date=date(2026, 4, 23))
    db_session.commit()
    now = datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc)
    _create_failed_audit(db_session, trade_date=current_day, finished_at=now - timedelta(hours=1))

    runs = IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now)

    assert runs == []


def test_reconciliation_skips_outside_window_non_open_day_and_p_minus_one(db_session: Session) -> None:
    current_day = date(2026, 4, 24)
    _seed_open_days(db_session, current_day, date(2026, 4, 23), date(2026, 4, 22), date(2026, 4, 21))
    _seed_active_raw(db_session, ts_code="000001.SH", trade_date=date(2026, 4, 21))
    db_session.commit()
    _create_failed_audit(
        db_session,
        trade_date=date(2026, 4, 22),
        finished_at=datetime(2026, 4, 24, 0, 0, tzinfo=timezone.utc),
    )

    service = IndexDailyCompletenessReconciliationService()
    assert service.enqueue_due_audits(db_session, now=datetime(2026, 4, 24, 4, 0, tzinfo=timezone.utc)) == []
    assert service.enqueue_due_audits(db_session, now=datetime(2026, 4, 25, 2, 0, tzinfo=timezone.utc)) == []
    assert session_rows(db_session, trade_date=date(2026, 4, 22)) == 1


def test_reconciliation_preserves_afternoon_slot_after_morning_repair(db_session: Session) -> None:
    target_day = date(2026, 4, 23)
    _seed_open_days(db_session, date(2026, 4, 24), target_day, date(2026, 4, 22))
    _seed_active_raw(db_session, ts_code="000001.SH", trade_date=date(2026, 4, 22))
    db_session.commit()
    morning_now = datetime(2026, 4, 24, 2, 0, tzinfo=timezone.utc)
    _create_failed_audit(db_session, trade_date=target_day, finished_at=morning_now - timedelta(hours=1))
    service = IndexDailyCompletenessReconciliationService()

    _create_repair(
        db_session,
        trade_date=target_day,
        status="success",
        repair_slot=INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
        worker_claimed=True,
    )
    assert service.enqueue_due_audits(db_session, now=morning_now) == []

    afternoon_now = datetime(2026, 4, 24, 6, 0, tzinfo=timezone.utc)
    runs = service.enqueue_due_audits(db_session, now=afternoon_now)
    assert len(runs) == 1
    assert runs[0].start_date == target_day
    assert runs[0].requested_at.replace(tzinfo=timezone.utc) == afternoon_now


def test_reconciliation_skips_open_audit_or_repair(db_session: Session) -> None:
    target_day = date(2026, 4, 23)
    _seed_open_days(db_session, date(2026, 4, 24), target_day, date(2026, 4, 22))
    _seed_active_raw(db_session, ts_code="000001.SH", trade_date=date(2026, 4, 22))
    db_session.commit()
    morning_now = datetime(2026, 4, 24, 2, 0, tzinfo=timezone.utc)
    _create_failed_audit(db_session, trade_date=target_day, finished_at=morning_now - timedelta(hours=1))

    DateCompletenessRunCommandService().create_system_run(
        db_session,
        dataset_key="index_daily",
        start_date=target_day,
        end_date=target_day,
        now=morning_now,
    )
    service = IndexDailyCompletenessReconciliationService()
    assert service.enqueue_due_audits(db_session, now=morning_now) == []

    open_audit = db_session.scalar(
        select(DatasetDateCompletenessRun)
        .where(DatasetDateCompletenessRun.dataset_key == "index_daily")
        .where(DatasetDateCompletenessRun.run_status == "queued")
    )
    assert open_audit is not None
    db_session.delete(open_audit)
    db_session.commit()
    _create_repair(
        db_session,
        trade_date=target_day,
        status="queued",
        repair_slot=INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
        worker_claimed=False,
    )

    assert service.enqueue_due_audits(db_session, now=morning_now) == []


def test_reconciliation_does_not_loop_only_serving_projection_gaps(db_session: Session) -> None:
    target_day = date(2026, 4, 23)
    _seed_open_days(db_session, date(2026, 4, 24), target_day, date(2026, 4, 22))
    _seed_active_raw(db_session, ts_code="000001.SH", trade_date=target_day)
    db_session.commit()
    now = datetime(2026, 4, 24, 2, 0, tzinfo=timezone.utc)
    _create_failed_audit(db_session, trade_date=target_day, finished_at=now - timedelta(hours=1))

    runs = IndexDailyCompletenessReconciliationService().enqueue_due_audits(db_session, now=now)

    assert runs == []


def test_scheduler_runs_index_daily_reconciliation_after_existing_schedule_paths(db_session: Session) -> None:
    target_day = date(2026, 4, 23)
    _seed_open_days(db_session, date(2026, 4, 24), target_day, date(2026, 4, 22))
    _seed_active_raw(db_session, ts_code="000001.SH", trade_date=date(2026, 4, 22))
    db_session.commit()
    now = datetime(2026, 4, 24, 2, 0, tzinfo=timezone.utc)
    _create_failed_audit(db_session, trade_date=target_day, finished_at=now - timedelta(hours=1))

    scheduled_task_runs = OperationsScheduler().run_once(db_session, now=now)

    assert scheduled_task_runs == []
    queued_audits = list(
        db_session.scalars(
            select(DatasetDateCompletenessRun)
            .where(DatasetDateCompletenessRun.start_date == target_day)
            .where(DatasetDateCompletenessRun.run_status == "queued")
        )
    )
    assert len(queued_audits) == 1


def session_rows(session: Session, *, trade_date: date) -> int:
    return int(
        session.scalar(
            select(DatasetDateCompletenessRun.id)
            .where(DatasetDateCompletenessRun.start_date == trade_date)
            .where(DatasetDateCompletenessRun.end_date == trade_date)
        )
        is not None
    )
