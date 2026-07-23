from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.task_run import TaskRun
from src.ops.runtime.scheduler import OperationsScheduler
from src.ops.services.date_completeness_run_service import DateCompletenessRunCommandService
from src.ops.services.index_daily_completeness_reconciliation_service import IndexDailyCompletenessReconciliationService
from src.ops.services.index_daily_reconciliation_policy import (
    INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
    INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
    INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
    previous_open_day_repair_slot_for_time,
)


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
