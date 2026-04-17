from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.operations.runtime import DispatchOutcome, OperationsDispatcher, OperationsScheduler, OperationsWorker
from src.operations.services.probe_runtime_service import ProbeTickResult


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


def test_scheduler_skips_due_schedule_when_trigger_mode_is_probe_only(db_session, job_schedule_factory) -> None:
    schedule = job_schedule_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        schedule_type="cron",
        trigger_mode="probe",
        cron_expr="5 * * * *",
        timezone_name="UTC",
        next_run_at=datetime(2026, 3, 30, 10, 5, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 10, 5, tzinfo=timezone.utc),
    )

    assert created == []
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at is not None


def test_scheduler_creates_probe_execution_when_rule_matches(
    db_session,
    probe_rule_factory,
    monkeypatch,
) -> None:
    rule = probe_rule_factory(
        dataset_key="daily",
        source_key="tushare",
        window_start=None,
        window_end=None,
        probe_interval_seconds=30,
        on_success_action_json={
            "spec_type": "job",
            "spec_key": "sync_daily.daily",
            "params_json": {"run_scope": "probe_triggered"},
        },
    )

    def _stub_run_once(self, session, *, now=None, limit=100):  # type: ignore[no-untyped-def]
        from src.operations.services.execution_service import OperationsExecutionService

        execution = OperationsExecutionService().create_execution(
            session,
                spec_type="job",
                spec_key="sync_daily.daily",
                params_json={"run_scope": "probe_triggered"},
            trigger_source="probe",
            requested_by_user_id=None,
            schedule_id=None,
        )
        session.add(
            ProbeRunLog(
                probe_rule_id=rule.id,
                    status="success",
                    condition_matched=True,
                    message="命中探测条件",
                    payload_json={"dataset_key": "daily"},
                probed_at=datetime(2026, 3, 30, 10, 5, tzinfo=timezone.utc),
                triggered_execution_id=execution.id,
                duration_ms=1,
            )
        )
        session.commit()
        return [execution], ProbeTickResult(processed_rules=1, triggered_rules=1, created_executions=1)

    monkeypatch.setattr("src.operations.runtime.scheduler.ProbeRuntimeService.run_once", _stub_run_once)

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 10, 5, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    assert created[0].trigger_source == "probe"
    logs = list(db_session.scalars(select(ProbeRunLog)))
    assert len(logs) == 1
    assert logs[0].condition_matched is True


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


def test_dispatcher_passes_optional_sync_daily_params(db_session, job_execution_factory, monkeypatch) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_daily.dc_hot",
        status="running",
        params_json={
            "trade_date": "2026-04-02",
            "market": ["A股市场", "ETF基金"],
            "hot_type": ["人气榜", "飙升榜"],
            "is_new": "N",
        },
    )

    class StubSyncService:
        def run_incremental(self, **kwargs):  # type: ignore[no-untyped-def]
            self.kwargs = kwargs
            return SimpleNamespace(rows_fetched=5, rows_written=5, message="ok")

    stub_service = StubSyncService()
    monkeypatch.setattr("src.operations.runtime.dispatcher.build_sync_service", lambda resource, session: stub_service)

    rows_fetched, rows_written, summary = OperationsDispatcher()._run_sync_job(
        db_session,
        execution,
        SimpleNamespace(key="sync_daily.dc_hot", category="sync_daily", supported_params=()),
        dict(execution.params_json or {}),
    )

    assert rows_fetched == 5
    assert rows_written == 5
    assert summary == "ok"
    assert stub_service.kwargs == {
        "trade_date": datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc).date(),
        "market": ["A股市场", "ETF基金"],
        "hot_type": ["人气榜", "飙升榜"],
        "is_new": "N",
        "execution_id": execution.id,
    }


def test_dispatcher_skips_sync_daily_on_closed_trade_date(db_session, job_execution_factory, trade_calendar_factory, monkeypatch) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_daily.dc_hot",
        status="running",
        params_json={"trade_date": "2026-01-01"},
    )
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 1, 1), is_open=False)

    class StubSyncService:
        called = False

        def run_incremental(self, **kwargs):  # type: ignore[no-untyped-def]
            self.called = True
            return SimpleNamespace(rows_fetched=1, rows_written=1, message="unexpected")

    stub_service = StubSyncService()
    monkeypatch.setattr("src.operations.runtime.dispatcher.build_sync_service", lambda resource, session: stub_service)

    rows_fetched, rows_written, summary = OperationsDispatcher()._run_sync_job(
        db_session,
        execution,
        SimpleNamespace(key="sync_daily.dc_hot", category="sync_daily", supported_params=()),
        dict(execution.params_json or {}),
    )

    assert rows_fetched == 0
    assert rows_written == 0
    assert summary == "skip sync_daily.dc_hot trade_date=2026-01-01 非交易日"
    assert stub_service.called is False


def test_dispatcher_refreshes_serving_light_after_daily_sync(db_session, job_execution_factory, monkeypatch) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_daily.daily",
        status="running",
        params_json={"trade_date": "2026-04-02"},
    )

    class StubSyncService:
        def run_incremental(self, **kwargs):  # type: ignore[no-untyped-def]
            self.kwargs = kwargs
            return SimpleNamespace(rows_fetched=5, rows_written=5, message="ok")

    stub_service = StubSyncService()
    monkeypatch.setattr("src.operations.runtime.dispatcher.build_sync_service", lambda resource, session: stub_service)

    refresh_calls: list[dict] = []

    def _stub_refresh(self, session, **kwargs):  # type: ignore[no-untyped-def]
        refresh_calls.append(kwargs)
        return SimpleNamespace(touched_rows=12)

    monkeypatch.setattr(
        "src.operations.runtime.dispatcher.ServingLightRefreshService.refresh_equity_daily_bar",
        _stub_refresh,
    )

    rows_fetched, rows_written, summary = OperationsDispatcher()._run_sync_job(
        db_session,
        execution,
        SimpleNamespace(key="sync_daily.daily", category="sync_daily", supported_params=()),
        dict(execution.params_json or {}),
        step_id=101,
    )
    db_session.flush()

    assert rows_fetched == 5
    assert rows_written == 5
    assert "轻量层刷新完成" in (summary or "")
    assert refresh_calls
    assert refresh_calls[0]["start_date"] == date(2026, 4, 2)
    assert refresh_calls[0]["end_date"] == date(2026, 4, 2)
    assert refresh_calls[0]["commit"] is False

    events = list(
        db_session.scalars(
            select(JobExecutionEvent).where(JobExecutionEvent.execution_id == execution.id)
        )
    )
    event_types = {event.event_type for event in events}
    assert "serving_light_refreshed" in event_types


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


def test_worker_marks_running_execution_canceled_when_dispatcher_returns_canceled(db_session, job_execution_factory) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="queued",
        requested_at=datetime(2026, 3, 30, 11, 0, tzinfo=timezone.utc),
    )
    dispatcher = StubDispatcher(DispatchOutcome(status="canceled", summary_message="任务已收到停止请求，正在结束处理。"))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.id == execution.id
    assert result.status == "canceled"
    assert result.summary_message == "任务已收到停止请求，正在结束处理。"


def test_worker_failed_keeps_last_progress_message_for_diagnosis(db_session, job_execution_factory) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.biying_equity_daily",
        status="queued",
        requested_at=datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc),
    )
    dispatcher = StubDispatcher(
        DispatchOutcome(
            status="failed",
            summary_message="Biying equity_daily_bar response format invalid: expected list",
            error_message="Biying equity_daily_bar response format invalid: expected list",
            error_code="dispatcher_error",
        )
    )
    worker = OperationsWorker(dispatcher=dispatcher)

    result = worker.run_execution(db_session, execution.id)
    assert result is not None
    assert result.status == "failed"
    assert result.progress_message == "系统已经开始处理这次任务。"
    assert result.error_message == "Biying equity_daily_bar response format invalid: expected list"


def test_worker_emergency_fails_execution_when_finalize_raises(db_session, job_execution_factory, mocker) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="queued",
        requested_at=datetime(2026, 3, 30, 11, 0, tzinfo=timezone.utc),
    )
    dispatcher = StubDispatcher(DispatchOutcome(status="success", rows_fetched=1, rows_written=1, summary_message="ok"))
    worker = OperationsWorker(dispatcher=dispatcher)
    mocker.patch.object(worker, "_finalize_execution", side_effect=RuntimeError("boom"))

    result = worker.run_next(db_session)

    assert result is not None
    assert result.id == execution.id
    assert result.status == "failed"
    assert result.error_code == "worker_finalize_error"
    assert "worker_finalize_error" in (result.summary_message or "")
    assert result.progress_message == "系统已经开始处理这次任务。"


def test_worker_records_warning_event_when_snapshot_refresh_fails(db_session, job_execution_factory, monkeypatch) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="sync_history.stock_basic",
        status="queued",
        requested_at=datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc),
    )
    dispatcher = StubDispatcher(DispatchOutcome(status="success", rows_fetched=1, rows_written=1, summary_message="ok"))
    worker = OperationsWorker(dispatcher=dispatcher)

    def _stub_refresh(_session, *, spec_type, spec_key):  # type: ignore[no-untyped-def]
        assert spec_type == "job"
        assert spec_key == "sync_history.stock_basic"
        return "snapshot refresh boom"

    monkeypatch.setattr(worker, "_refresh_snapshot_for_execution", _stub_refresh)

    result = worker.run_next(db_session)
    assert result is not None
    assert result.status == "success"

    events = list(
        db_session.scalars(
            select(JobExecutionEvent)
            .where(JobExecutionEvent.execution_id == execution.id)
            .order_by(JobExecutionEvent.id.asc())
        )
    )
    warning_events = [event for event in events if event.event_type == "warning"]
    assert len(warning_events) == 1
    warning = warning_events[0]
    assert warning.level == "WARNING"
    assert warning.payload_json.get("code") == "dataset_snapshot_refresh_failed"
    assert "snapshot refresh boom" in str(warning.payload_json.get("detail") or "")
