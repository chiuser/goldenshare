from __future__ import annotations

from datetime import date, datetime, timezone
import json
from types import SimpleNamespace

from sqlalchemy import select

from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.ops.models.ops.job_execution_step import JobExecutionStep
from src.ops.models.ops.job_execution_unit import JobExecutionUnit
from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.ops.runtime import DispatchOutcome, OperationsDispatcher, OperationsScheduler, OperationsWorker
from src.ops.specs.workflow_spec import WorkflowSpec, WorkflowStepSpec
from src.ops.services.operations_probe_runtime_service import ProbeTickResult


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
        from src.ops.services.operations_execution_service import OperationsExecutionService

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

    monkeypatch.setattr("src.ops.runtime.scheduler.ProbeRuntimeService.run_once", _stub_run_once)

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


def test_dispatcher_build_progress_payload_parses_rows_and_reason_counts() -> None:
    payload = OperationsDispatcher._build_progress_payload(
        "moneyflow_cnt_ths: 4/4 trade_date=2026-04-23 fetched=387 written=386 rejected=1 "
        "reasons=normalize.required_field_missing:ts_code:1"
    )

    assert payload["progress_current"] == 4
    assert payload["progress_total"] == 4
    assert payload["rows_fetched"] == 387
    assert payload["rows_written"] == 386
    assert payload["rows_rejected"] == 1
    assert payload["rejected_reason_counts"] == {"normalize.required_field_missing:ts_code": 1}
    assert payload["reason_stats_truncated"] is False
    assert payload["reason_stats_truncate_note"] is None


def test_dispatcher_build_progress_payload_caps_reason_buckets_and_size() -> None:
    payload = OperationsDispatcher._build_progress_payload(
        "moneyflow_cnt_ths: 4/4 fetched=387 written=380 rejected=7 "
        "reasons=reason_a:1|reason_b:2|reason_c:3|reason_d:4 reason_stats_truncated=1"
    )

    assert payload["rejected_reason_counts"] == {
        "reason_d": 4,
        "reason_c": 3,
        "reason_b": 2,
    }
    assert payload["reason_stats_truncated"] is True
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= OperationsDispatcher.MAX_PROGRESS_PAYLOAD_BYTES


def test_dispatcher_workflow_continue_on_error_keeps_following_steps(db_session, job_execution_factory, monkeypatch) -> None:
    execution = job_execution_factory(
        spec_type="workflow",
        spec_key="wf.mock",
        status="running",
        params_json={"run_profile": "snapshot_refresh"},
    )
    workflow_spec = WorkflowSpec(
        key="wf.mock",
        display_name="Mock Workflow",
        description="mock workflow",
        steps=(
            WorkflowStepSpec(
                step_key="s1",
                job_key="sync_daily.daily",
                display_name="Step 1",
                failure_policy_override="continue_on_error",
            ),
            WorkflowStepSpec(
                step_key="s2",
                job_key="sync_daily.daily_basic",
                display_name="Step 2",
            ),
        ),
    )
    monkeypatch.setattr(
        "src.ops.runtime.dispatcher.get_job_spec",
        lambda key: SimpleNamespace(key=key, display_name=key),
    )

    call_count = {"value": 0}

    def _stub_run_job(session, step_execution, job_spec, step_id):  # type: ignore[no-untyped-def]
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise RuntimeError("step failed")
        return 3, 2, "ok"

    dispatcher = OperationsDispatcher()
    monkeypatch.setattr(
        dispatcher,
        "_create_step_unit",
        lambda session, execution_id, step_id, unit_id: SimpleNamespace(id=step_id, unit_id=unit_id, started_at=datetime.now(timezone.utc)),
    )
    monkeypatch.setattr(dispatcher, "_finalize_step_unit", lambda unit, **kwargs: None)
    monkeypatch.setattr(dispatcher, "_run_job", _stub_run_job)
    original_get = db_session.get
    monkeypatch.setattr(
        db_session,
        "get",
        lambda model, ident, **kwargs: (
            SimpleNamespace(id=ident, unit_id=f"mock-unit-{ident}", started_at=datetime.now(timezone.utc))
            if model is JobExecutionUnit
            else original_get(model, ident, **kwargs)
        ),
    )

    outcome = dispatcher._dispatch_workflow(db_session, execution, workflow_spec)

    assert outcome.status == "partial_success"
    assert outcome.rows_fetched == 3
    assert outcome.rows_written == 2
    assert call_count["value"] == 2

    steps = list(db_session.scalars(select(JobExecutionStep).where(JobExecutionStep.execution_id == execution.id).order_by(JobExecutionStep.sequence_no)))
    assert len(steps) == 2
    assert steps[0].status == "failed"
    assert steps[0].failure_policy_effective == "continue_on_error"
    assert steps[0].unit_total == 1
    assert steps[0].unit_done == 0
    assert steps[0].unit_failed == 1
    assert steps[1].status == "success"


def test_dispatcher_blocks_dependent_step_after_failed_dependency(db_session, job_execution_factory, monkeypatch) -> None:
    execution = job_execution_factory(
        spec_type="workflow",
        spec_key="wf.dep",
        status="running",
    )
    workflow_spec = WorkflowSpec(
        key="wf.dep",
        display_name="Mock Workflow",
        description="mock workflow",
        steps=(
            WorkflowStepSpec(
                step_key="s1",
                job_key="sync_daily.daily",
                display_name="Step 1",
                failure_policy_override="continue_on_error",
            ),
            WorkflowStepSpec(
                step_key="s2",
                job_key="sync_daily.daily_basic",
                display_name="Step 2",
                depends_on=("s1",),
            ),
        ),
    )
    monkeypatch.setattr(
        "src.ops.runtime.dispatcher.get_job_spec",
        lambda key: SimpleNamespace(key=key, display_name=key),
    )

    dispatcher = OperationsDispatcher()
    monkeypatch.setattr(
        dispatcher,
        "_create_step_unit",
        lambda session, execution_id, step_id, unit_id: SimpleNamespace(id=step_id, unit_id=unit_id, started_at=datetime.now(timezone.utc)),
    )
    monkeypatch.setattr(dispatcher, "_finalize_step_unit", lambda unit, **kwargs: None)
    original_get = db_session.get
    monkeypatch.setattr(
        db_session,
        "get",
        lambda model, ident, **kwargs: (
            SimpleNamespace(id=ident, unit_id=f"mock-unit-{ident}", started_at=datetime.now(timezone.utc))
            if model is JobExecutionUnit
            else original_get(model, ident, **kwargs)
        ),
    )

    def _raise_failed(session, step_execution, job_spec, step_id):  # type: ignore[no-untyped-def]
        raise RuntimeError("failed")

    monkeypatch.setattr(dispatcher, "_run_job", _raise_failed)

    outcome = dispatcher._dispatch_workflow(db_session, execution, workflow_spec)

    assert outcome.status == "partial_success"
    steps = list(db_session.scalars(select(JobExecutionStep).where(JobExecutionStep.execution_id == execution.id).order_by(JobExecutionStep.sequence_no)))
    assert len(steps) == 2
    assert steps[0].status == "failed"
    assert steps[1].status == "blocked"
    assert steps[1].skip_reason_code == "dependency_failed"
    assert steps[1].depends_on_step_keys_json == ["s1"]


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
    monkeypatch.setattr(
        "src.ops.runtime.dispatcher.build_sync_service",
        lambda resource, session, **kwargs: stub_service,
    )

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
    monkeypatch.setattr(
        "src.ops.runtime.dispatcher.build_sync_service",
        lambda resource, session, **kwargs: stub_service,
    )

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


def test_dispatcher_passes_content_type_to_backfill_by_trade_date(db_session, job_execution_factory, monkeypatch) -> None:
    execution = job_execution_factory(
        spec_type="job",
        spec_key="backfill_by_trade_date.moneyflow_ind_dc",
        status="running",
        params_json={
            "start_date": "2026-04-01",
            "end_date": "2026-04-02",
            "ts_code": "BK1234",
            "content_type": ["行业", "概念"],
            "offset": 2,
            "limit": 5,
        },
    )
    backfill_service = SimpleNamespace(
        backfill_by_trade_dates=lambda **kwargs: SimpleNamespace(
            resource=kwargs["resource"],
            units_processed=1,
            rows_fetched=7,
            rows_written=6,
        )
    )
    captured_kwargs: dict[str, object] = {}

    def _stub_backfill_by_trade_dates(**kwargs):  # type: ignore[no-untyped-def]
        captured_kwargs.update(kwargs)
        return SimpleNamespace(resource="moneyflow_ind_dc", units_processed=1, rows_fetched=7, rows_written=6)

    backfill_service.backfill_by_trade_dates = _stub_backfill_by_trade_dates
    monkeypatch.setattr(
        "src.ops.runtime.dispatcher.HistoryBackfillService",
        lambda session, **kwargs: backfill_service,
    )

    rows_fetched, rows_written, summary = OperationsDispatcher()._run_backfill_job(
        db_session,
        execution,
        SimpleNamespace(key="backfill_by_trade_date.moneyflow_ind_dc", category="backfill_by_trade_date"),
        dict(execution.params_json or {}),
        step_id=10,
    )

    assert rows_fetched == 7
    assert rows_written == 6
    assert summary == "units=1"
    assert captured_kwargs["resource"] == "moneyflow_ind_dc"
    assert captured_kwargs["start_date"] == date(2026, 4, 1)
    assert captured_kwargs["end_date"] == date(2026, 4, 2)
    assert captured_kwargs["ts_code"] == "BK1234"
    assert captured_kwargs["content_type"] == ["行业", "概念"]
    assert captured_kwargs["offset"] == 2
    assert captured_kwargs["limit"] == 5
    assert captured_kwargs["execution_id"] == execution.id


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
    monkeypatch.setattr(
        "src.ops.runtime.dispatcher.build_sync_service",
        lambda resource, session, **kwargs: stub_service,
    )

    refresh_calls: list[dict] = []

    def _stub_refresh(self, session, **kwargs):  # type: ignore[no-untyped-def]
        refresh_calls.append(kwargs)
        return SimpleNamespace(touched_rows=12)

    monkeypatch.setattr(
        "src.ops.runtime.dispatcher.ServingLightRefreshService.refresh_equity_daily_bar",
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
