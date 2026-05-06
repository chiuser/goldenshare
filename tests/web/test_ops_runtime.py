from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from src.foundation.ingestion import DatasetActionRequest, DatasetTimeInput
from src.ops.action_catalog import END_DATE_PARAM, START_DATE_PARAM, TRADE_DATE_PARAM, WORKFLOW_DEFINITION_REGISTRY, WorkflowDefinition
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime import OperationsScheduler, OperationsWorker, TaskRunDispatchOutcome, TaskRunDispatcher
from src.ops.services.operations_serving_light_refresh_service import ServingLightRefreshResult
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext


class StubDispatcher:
    def __init__(self, outcome: TaskRunDispatchOutcome) -> None:
        self.outcome = outcome
        self.calls: list[int] = []

    def dispatch(self, session, task_run):  # type: ignore[no-untyped-def]
        self.calls.append(task_run.id)
        return self.outcome


def test_scheduler_enqueues_due_once_schedule(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
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
    assert "target_key" not in created[0].request_payload_json
    assert "target_type" not in created[0].request_payload_json
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.status == "paused"
    assert refreshed.next_run_at is None


def test_scheduler_dataset_task_uses_target_key_as_single_resource_fact(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="daily.maintain",
        schedule_type="once",
        params_json={
            "dataset_key": "stock_basic",
            "action": "wrong_action",
            "trade_date": "2026-04-24",
        },
        next_run_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "daily"
    assert task_run.action == "maintain"
    assert task_run.request_payload_json["resource_key"] == "daily"
    assert task_run.request_payload_json["action"] == "maintain"
    assert "dataset_key" not in task_run.request_payload_json


def test_scheduler_reschedules_cron_schedule_after_trigger(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
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


def test_scheduler_monthly_last_day_policy_uses_due_schedule_month_for_task_run(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stk_period_bar_month.maintain",
        display_name="股票月线自动维护",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="monthly_last_day",
        params_json={"time_input": {"mode": "point"}},
        next_run_at=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "stk_period_bar_month"
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-04-30"}
    assert task_run.request_payload_json["time_input"] == {"mode": "point", "trade_date": "2026-04-30"}
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == datetime(2026, 5, 31, 11, 0, tzinfo=timezone.utc)


def test_scheduler_monthly_window_policy_uses_due_schedule_month_for_task_run(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="index_weight.maintain",
        display_name="指数成分权重自动维护",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="monthly_window_current_month",
        params_json={"time_input": {"mode": "range"}, "filters": {"index_code": "000300.SH"}},
        next_run_at=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "index_weight"
    assert task_run.time_input_json == {
        "mode": "range",
        "start_month": "202604",
        "end_month": "202604",
    }
    assert task_run.filters_json == {"index_code": "000300.SH"}
    assert task_run.request_payload_json["time_input"] == {
        "mode": "range",
        "start_month": "202604",
        "end_month": "202604",
    }
    assert task_run.request_payload_json["filters"] == {"index_code": "000300.SH"}
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == datetime(2026, 5, 31, 11, 0, tzinfo=timezone.utc)


def test_scheduler_defaults_daily_workflow_to_point_mode_when_schedule_has_no_time_params(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="workflow",
        target_key="daily_moneyflow_maintenance",
        schedule_type="once",
        params_json={},
        next_run_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.task_type == "workflow"
    assert task_run.time_input_json == {"mode": "point"}
    assert task_run.request_payload_json["time_input"] == {"mode": "point"}


def test_scheduler_defaults_natural_day_workflow_to_local_calendar_date(db_session, ops_schedule_factory, monkeypatch) -> None:
    workflow = WorkflowDefinition(
        key="test_reference_data_natural_day_workflow",
        display_name="基础数据自然日测试流程",
        description="按自然日维护测试流程。",
        parameters=(TRADE_DATE_PARAM, START_DATE_PARAM, END_DATE_PARAM),
        steps=(),
        schedule_enabled=True,
        manual_enabled=True,
        time_regime="natural_day",
    )
    monkeypatch.setitem(WORKFLOW_DEFINITION_REGISTRY, workflow.key, workflow)
    schedule = ops_schedule_factory(
        target_type="workflow",
        target_key=workflow.key,
        schedule_type="once",
        timezone_name="Asia/Shanghai",
        params_json={},
        next_run_at=datetime(2026, 3, 30, 16, 30, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 16, 30, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.task_type == "workflow"
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-03-31"}
    assert task_run.request_payload_json["time_input"] == {"mode": "point", "trade_date": "2026-03-31"}


def test_scheduler_defaults_reference_data_refresh_workflow_to_snapshot_mode(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="workflow",
        target_key="reference_data_refresh",
        schedule_type="once",
        timezone_name="Asia/Shanghai",
        params_json={},
        next_run_at=datetime(2026, 3, 30, 16, 30, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 16, 30, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.task_type == "workflow"
    assert task_run.resource_key is None
    assert task_run.request_payload_json["target_key"] == "reference_data_refresh"
    assert task_run.time_input_json == {"mode": "none"}
    assert task_run.request_payload_json["time_input"] == {"mode": "none"}


def test_task_run_dispatcher_runs_daily_market_close_workflow_with_bak_basic_step(
    db_session,
    task_run_factory,
    monkeypatch,
) -> None:
    dispatched_dataset_keys: list[str] = []

    def fake_build_plan(self, request):  # type: ignore[no-untyped-def]
        return SimpleNamespace(dataset_key=request.dataset_key, run_profile="point_incremental")

    def fake_run_dataset_action_plan(self, session, task_run, action_request, plan):  # type: ignore[no-untyped-def]
        dispatched_dataset_keys.append(action_request.dataset_key)
        return 1, 1, 0, {}, {}, f"{action_request.dataset_key}:ok"

    monkeypatch.setattr("src.ops.runtime.task_run_dispatcher.DatasetActionResolver.build_plan", fake_build_plan)
    monkeypatch.setattr(TaskRunDispatcher, "_run_dataset_action_plan", fake_run_dataset_action_plan)

    task_run = task_run_factory(
        task_type="workflow",
        resource_key=None,
        title="每日收盘后维护",
        status="running",
        time_input_json={"mode": "point", "trade_date": "2026-04-24"},
        request_payload_json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "time_input": {"mode": "point", "trade_date": "2026-04-24"},
            "filters": {},
        },
    )

    outcome = TaskRunDispatcher().dispatch(db_session, task_run)
    nodes = db_session.scalars(
        select(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id).order_by(TaskRunNode.sequence_no)
    ).all()

    assert outcome.status == "success"
    assert "bak_basic" in dispatched_dataset_keys
    assert dispatched_dataset_keys[3] == "bak_basic"
    assert len(dispatched_dataset_keys) == len(WORKFLOW_DEFINITION_REGISTRY["daily_market_close_maintenance"].steps)
    assert [node.node_key for node in nodes][:4] == ["daily", "adj_factor", "daily_basic", "bak_basic"]
    assert task_run.unit_total == len(WORKFLOW_DEFINITION_REGISTRY["daily_market_close_maintenance"].steps)
    assert task_run.unit_done == len(WORKFLOW_DEFINITION_REGISTRY["daily_market_close_maintenance"].steps)
    assert task_run.progress_percent == 100


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


def test_worker_refreshes_snapshot_after_workflow_success(db_session, task_run_factory, monkeypatch) -> None:
    calls: list[tuple[str, str, bool]] = []

    class FakeSnapshotService:
        def refresh_for_target(self, session, *, target_type, target_key, strict, today=None):  # type: ignore[no-untyped-def]
            calls.append((target_type, target_key, strict))
            return 7

    monkeypatch.setattr("src.ops.runtime.worker.DatasetStatusSnapshotService", FakeSnapshotService)
    task_run_factory(
        task_type="workflow",
        resource_key=None,
        title="每日资金流向维护",
        status="queued",
        request_payload_json={
            "target_type": "workflow",
            "target_key": "daily_moneyflow_maintenance",
        },
    )
    dispatcher = StubDispatcher(TaskRunDispatchOutcome(status="success"))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.status == "success"
    assert calls == [("workflow", "daily_moneyflow_maintenance", True)]


def test_worker_skips_snapshot_refresh_for_maintenance_action(db_session, task_run_factory, monkeypatch) -> None:
    calls: list[tuple[str, str, bool]] = []

    class FakeSnapshotService:
        def refresh_for_target(self, session, *, target_type, target_key, strict, today=None):  # type: ignore[no-untyped-def]
            calls.append((target_type, target_key, strict))
            return 1

    monkeypatch.setattr("src.ops.runtime.worker.DatasetStatusSnapshotService", FakeSnapshotService)
    task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        title="刷新数据集市快照",
        status="queued",
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": "maintenance.rebuild_dm",
        },
    )
    dispatcher = StubDispatcher(TaskRunDispatchOutcome(status="success"))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.status == "success"
    assert calls == []


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

    task_run_factory(status="queued", resource_key="daily", title="股票日线")

    result = OperationsWorker(dispatcher=RaisingDispatcher()).run_next(db_session)  # type: ignore[arg-type]

    assert result is not None
    assert result.status == "failed"
    assert result.primary_issue_id is not None
    issue = db_session.get(TaskRunIssue, result.primary_issue_id)
    assert issue is not None
    assert issue.code == "worker_error"


def test_task_run_progress_updates_current_running_node_rows(db_session, task_run_factory, task_run_node_factory) -> None:
    task_run = task_run_factory(status="running", resource_key="limit_list_ths", title="同花顺涨跌停榜单")
    node = task_run_node_factory(
        task_run_id=task_run.id,
        node_key="limit_list_ths:maintain",
        title="维护 同花顺涨跌停榜单",
        status="running",
    )
    task_run.current_node_id = node.id
    db_session.commit()

    TaskRunIngestionContext(db_session).update_progress(
        run_id=task_run.id,
        current=1,
        total=5,
        message="unused structured progress",
        rows_fetched=10514,
        rows_saved=10514,
        rows_rejected=0,
        rejected_reason_counts={},
        current_object={"entity": {"kind": "date", "name": "2026-04-24"}, "time": {}, "attributes": {}},
    )

    db_session.refresh(task_run)
    db_session.refresh(node)
    assert task_run.rows_fetched == 10514
    assert task_run.rows_saved == 10514
    assert node.rows_fetched == 10514
    assert node.rows_saved == 10514
    assert node.rows_rejected == 0


def test_task_run_progress_updates_rejected_reason_counts(db_session, task_run_factory, task_run_node_factory) -> None:
    task_run = task_run_factory(status="running", resource_key="dc_hot", title="东方财富热榜")
    node = task_run_node_factory(
        task_run_id=task_run.id,
        node_key="dc_hot:maintain",
        title="维护 东方财富热榜",
        status="running",
    )
    task_run.current_node_id = node.id
    db_session.commit()

    TaskRunIngestionContext(db_session).update_progress(
        run_id=task_run.id,
        current=3,
        total=5,
        message="unused structured progress",
        rows_fetched=1530,
        rows_saved=1527,
        rows_rejected=3,
        rejected_reason_counts={"write.duplicate_conflict_key_in_batch:ts_code": 3},
        rejected_reason_samples={
            "write.duplicate_conflict_key_in_batch:ts_code": [
                {"unit_id": "u-dc-hot", "field": "ts_code", "value": "000001.SZ", "row": {"ts_code": "000001.SZ"}}
            ]
        },
        current_object={"entity": {"kind": "date", "name": "2026-04-24"}, "time": {}, "attributes": {}},
    )

    db_session.refresh(task_run)
    db_session.refresh(node)
    assert task_run.rows_rejected == 3
    assert task_run.rejected_reason_counts_json == {"write.duplicate_conflict_key_in_batch:ts_code": 3}
    assert task_run.rejected_reason_samples_json["write.duplicate_conflict_key_in_batch:ts_code"][0]["value"] == "000001.SZ"
    assert node.rejected_reason_counts_json == {"write.duplicate_conflict_key_in_batch:ts_code": 3}
    assert node.rejected_reason_samples_json == task_run.rejected_reason_samples_json


def test_finish_node_preserves_observed_rows_when_final_rows_not_provided(db_session, task_run_factory, task_run_node_factory) -> None:
    task_run = task_run_factory(status="running", resource_key="daily", title="股票日线")
    node = task_run_node_factory(
        task_run_id=task_run.id,
        node_key="daily:maintain",
        title="维护 股票日线",
        status="running",
        rows_fetched=9000,
        rows_saved=8990,
        rows_rejected=10,
        started_at=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    TaskRunDispatcher._finish_node(node, status="failed")
    db_session.commit()
    db_session.refresh(node)

    assert node.status == "failed"
    assert node.rows_fetched == 9000
    assert node.rows_saved == 8990
    assert node.rows_rejected == 10


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


def test_task_run_dispatcher_returns_readable_closed_trade_date_skip_message(
    db_session,
    task_run_factory,
    trade_calendar_factory,
) -> None:
    task_run = task_run_factory(status="running", resource_key="daily", title="股票日线")
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 4, 25), is_open=False)
    plan = SimpleNamespace(dataset_key="daily", run_profile="point_incremental")
    action_request = DatasetActionRequest(
        dataset_key="daily",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 25)),
        filters={},
        trigger_source="manual",
        run_id=task_run.id,
    )

    rows_fetched, rows_saved, rows_rejected, rejected_reason_counts, rejected_reason_samples, summary_message = TaskRunDispatcher()._run_dataset_action_plan(
        db_session,
        task_run,
        action_request,
        plan,
    )

    assert (rows_fetched, rows_saved, rows_rejected) == (0, 0, 0)
    assert rejected_reason_counts == {}
    assert rejected_reason_samples == {}
    assert summary_message == "股票日线：2026-04-25 非交易日，已跳过维护。"


def test_task_run_dispatcher_does_not_skip_natural_day_point_on_closed_trade_date(
    db_session,
    task_run_factory,
    trade_calendar_factory,
    monkeypatch,
) -> None:
    calls: list[DatasetActionRequest] = []

    class StubDatasetMaintainService:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def maintain(self, *, _action_request, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(_action_request)
            return SimpleNamespace(
                rows_fetched=5507,
                rows_written=5507,
                rows_rejected=0,
                rejected_reason_counts={},
                message="units=1",
            )

    monkeypatch.setattr("src.ops.runtime.task_run_dispatcher.DatasetMaintainService", StubDatasetMaintainService)
    task_run = task_run_factory(status="running", resource_key="stk_period_bar_week", title="股票周线行情")
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 1), is_open=False)
    plan = SimpleNamespace(dataset_key="stk_period_bar_week", run_profile="point_incremental")
    action_request = DatasetActionRequest(
        dataset_key="stk_period_bar_week",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 5, 1)),
        filters={},
        trigger_source="manual",
        run_id=task_run.id,
    )

    rows_fetched, rows_saved, rows_rejected, rejected_reason_counts, rejected_reason_samples, summary_message = TaskRunDispatcher()._run_dataset_action_plan(
        db_session,
        task_run,
        action_request,
        plan,
    )

    assert (rows_fetched, rows_saved, rows_rejected) == (5507, 5507, 0)
    assert rejected_reason_counts == {}
    assert rejected_reason_samples == {}
    assert summary_message == "units=1"
    assert len(calls) == 1
    assert calls[0].time_input.trade_date == date(2026, 5, 1)
