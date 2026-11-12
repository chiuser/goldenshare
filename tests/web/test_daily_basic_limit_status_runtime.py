"""Real dispatcher/worker/HTTP view with isolated SQLite; source fetch is replaced.

The row and connector-added api_name/fetched_at follow the observed producer.
Non-daily-basic workflow steps are isolated with literal result counts.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from src.foundation.ingestion.errors import IngestionNormalizeError, StructuredError
from src.foundation.ingestion.source_client import DatasetSourceClient
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.raw.raw_daily_basic import RawDailyBasic
from src.ops.action_catalog import WorkflowDefinition, WorkflowStepDefinition
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)
from src.ops.runtime.task_run_dispatcher import (
    TaskRunDispatcher,
    TaskRunDispatchOutcome,
)
from src.ops.runtime.worker import OperationsWorker
from src.ops.services.news_stock_linking_service import NEWS_STOCK_LINKING_ACTION_KEY
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
from tests.test_daily_basic_limit_status import DAY, ERROR_CODE, SOURCE_ROW, Source


@pytest.fixture
def runtime_data(db_session, monkeypatch):
    for model in (TradeCalendar, EquityDailyBasic, RawDailyBasic, Security):
        model.__table__.create(db_session.get_bind(), checkfirst=True)
    for day in (10, 11, 12):
        db_session.add(TradeCalendar(exchange="SSE", trade_date=date(2026, 11, day), is_open=True))
    db_session.add(Security(ts_code="000001.SZ", name="平安银行", security_type="EQUITY", list_status="L"))
    db_session.commit()
    metadata = {"api_name": "daily_basic", "fetched_at": datetime(2026, 11, 12, tzinfo=UTC)}
    source = Source({
        DAY: [{**SOURCE_ROW, **metadata}],
        date(2026, 11, 11): [
            {**SOURCE_ROW, **metadata, "trade_date": "20261111", "ts_code": "000002.SZ"},
            {**SOURCE_ROW, **metadata, "trade_date": "20261111", "limit_status": 1.5},
        ],
        date(2026, 11, 12): [{**SOURCE_ROW, **metadata, "trade_date": "20261112"}],
    })
    monkeypatch.setattr(DatasetSourceClient, "fetch", lambda _self, **kw: source.fetch(**kw))
    return source


def range_task(task_run_factory, **overrides):
    return task_run_factory(resource_key="daily_basic", title="每日指标", time_input_json={
        "mode": "range", "start_date": "2026-11-10", "end_date": "2026-11-12",
    }, **overrides)


def test_healthy_range_accepts_new_dates_zero_and_normal_value_changes(db_session, runtime_data, task_run_factory):
    changed = runtime_data.rows_by_day[date(2026, 11, 11)][1]
    changed.update(limit_status=0, close=12.0, pe=-2.5, pb=None)
    runtime_data.rows_by_day[date(2026, 11, 12)][0]["limit_status"] = 6
    result = OperationsWorker().run_task_run(db_session, range_task(task_run_factory).id)
    assert result.status == "success" and result.primary_issue_id is None
    assert (result.unit_done, result.unit_total, result.unit_failed, result.rows_saved) == (3, 3, 0, 4)
    assert result.progress_percent == 100
    for model in (RawDailyBasic, EquityDailyBasic):
        rows = db_session.scalars(select(model)).all()
        assert len(rows) == 4
        row = db_session.get(model, ("000001.SZ", date(2026, 11, 11)))
        assert row.limit_status == 0 and row.close == 12 and row.pe == -2.5 and row.pb is None
        assert db_session.get(model, ("000001.SZ", date(2026, 11, 12))).limit_status == 6
    assert db_session.get(TaskRunNode, result.current_node_id).status == "success"


@pytest.mark.parametrize("observation_fails", [False, True])
def test_normal_maintenance_keeps_commits_and_exposes_value_error_in_http_view(
    db_session, runtime_data, task_run_factory, app_client, user_factory, monkeypatch, observation_fails,
):
    if observation_fails:
        def fail_observation(*args, **kwargs):
            raise SQLAlchemyError("deliberate observation failure")
        monkeypatch.setattr(TaskRunIngestionContext, "update_progress", fail_observation)
    task = range_task(task_run_factory)
    result = OperationsWorker().run_task_run(db_session, task.id)
    assert result.status == "failed" and result.status_reason_code == ERROR_CODE
    assert (result.unit_done, result.unit_failed, result.rows_fetched, result.rows_saved, result.rows_rejected) == (1, 1, 1, 1, 0)
    assert runtime_data.called == [DAY, date(2026, 11, 11)]
    for model in (RawDailyBasic, EquityDailyBasic):
        rows = db_session.scalars(select(model)).all()
        assert len(rows) == 1 and rows[0].trade_date == DAY and rows[0].limit_status == 4
    node = db_session.get(TaskRunNode, result.current_node_id)
    assert node.status == "failed" and node.rows_saved == 1
    issue = db_session.get(TaskRunIssue, result.primary_issue_id)
    for text in ("2026-11-11", "000001.SZ", "平安银行", "limit_status", "1.5", "float"):
        assert text in issue.operator_message
    details = issue.technical_payload_json["structured_error"]["details"]
    assert details["rows_fetched"] == 2 and details["rows_rejected"] == 1
    assert details["committed_progress"]["rows_committed"] == 1
    user_factory(username="admin", password="secret", is_admin=True)
    login = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    response = app_client.get(f"/api/v1/ops/task-runs/{result.id}/view", headers={"Authorization": f"Bearer {login.json()['token']}"})
    assert response.status_code == 200
    assert "平安银行" in response.text and "limit_status" in response.text
    assert "normalize.source_validation_failed" in response.text
    issue_response = app_client.get(
        f"/api/v1/ops/task-runs/{result.id}/issues/{issue.id}",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert issue_response.status_code == 200 and "committed_progress" in issue_response.text


@pytest.mark.parametrize("failure_policy", ["fail_fast", "continue_on_error"])
def test_workflow_stops_and_counts_steps_separately_from_failed_step_dates(
    db_session, runtime_data, task_run_factory, monkeypatch, failure_policy,
):
    from src.ops.runtime import task_run_dispatcher as module

    workflow = WorkflowDefinition(key="stage2-test", display_name="校验工作流", description="isolated fixture", steps=(
        WorkflowStepDefinition("first", "stk_limit.maintain", "步骤一", dataset_key="stk_limit"),
        WorkflowStepDefinition("second", "stk_limit.maintain", "步骤二", dataset_key="stk_limit"),
        WorkflowStepDefinition("daily-basic", "daily_basic.maintain", "每日指标", dataset_key="daily_basic", failure_policy_override=failure_policy),
        WorkflowStepDefinition("must-not-run", "stk_limit.maintain", "后续步骤", dataset_key="stk_limit"),
    ), failure_policy_default=failure_policy)
    monkeypatch.setattr(module, "get_workflow_definition", lambda _: workflow)
    dispatcher = TaskRunDispatcher()
    real_run = dispatcher._run_dataset_action_plan
    calls = []

    def run(session, task, request, plan):
        calls.append(plan.dataset_key)
        if plan.dataset_key == "daily_basic":
            return real_run(session, task, request, plan)
        count = len(calls) + 1
        return count + 1, count, 1, {"existing.reason": 1}, {}, "existing step"

    monkeypatch.setattr(dispatcher, "_run_dataset_action_plan", run)
    task = task_run_factory(task_type="workflow", resource_key=None, title="校验工作流",
        request_payload_json={"target_key": workflow.key},
        time_input_json={"mode": "range", "start_date": "2026-11-10", "end_date": "2026-11-12"})
    result = OperationsWorker(dispatcher).run_task_run(db_session, task.id)
    assert result.status == "failed" and result.status_reason_code == ERROR_CODE
    assert calls == ["stk_limit", "stk_limit", "daily_basic"]
    assert (result.unit_total, result.unit_done, result.unit_failed) == (4, 2, 1)
    # Previous steps: fetched 3+4, saved 2+3, rejected 1+1; failed step committed 1.
    assert (result.rows_fetched, result.rows_saved, result.rows_rejected) == (8, 6, 2)
    nodes = db_session.scalars(select(TaskRunNode).where(TaskRunNode.task_run_id == task.id).order_by(TaskRunNode.sequence_no)).all()
    assert [node.status for node in nodes] == ["success", "success", "failed"]
    assert [node.rows_saved for node in nodes] == [2, 3, 1]
    assert nodes[-1].ingestion_diagnostics_json["unit_done"] == 1
    assert nodes[-1].ingestion_diagnostics_json["unit_total"] == 3


@pytest.mark.parametrize("case", ["missing_name", "query_failed", "missing_code"])
def test_error_reporting_survives_missing_identity_or_name_query_failure(
    db_session, runtime_data, task_run_factory, case,
):
    row = runtime_data.rows_by_day[DAY][0]
    row["limit_status"] = 1.5
    if case == "missing_name":
        row["ts_code"] = "999999.SZ"
    elif case == "missing_code":
        del row["ts_code"]
    engine = db_session.get_bind()
    queries = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT core_serving.security_serving.ts_code, core_serving.security_serving.name"):
            queries.append(statement)
            if case == "query_failed":
                raise OperationalError("name query", {}, RuntimeError("deliberate query failure"))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = OperationsWorker().run_task_run(db_session, range_task(task_run_factory).id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result.status == "failed" and result.status_reason_code == ERROR_CODE
    issue = db_session.get(TaskRunIssue, result.primary_issue_id)
    assert ("股票代码缺失" if case == "missing_code" else "名称未找到") in issue.operator_message
    assert len(queries) == (0 if case == "missing_code" else 1)
    assert issue.technical_payload_json["structured_error"]["error_code"] == ERROR_CODE


def test_registered_maintenance_reuses_the_same_error_presentation_without_new_action(
    db_session, runtime_data, task_run_factory,
):
    error = IngestionNormalizeError(StructuredError(
        error_code=ERROR_CODE, error_type="normalize", phase="normalizer", retryable=False,
        message="源数据校验失败", details={"trade_date": "2026-11-11", "rows_fetched": 1, "rows_rejected": 1,
            "rejected_samples": {"normalize.daily_basic_limit_status_invalid:limit_status": [{
                "row": {"ts_code": "000001.SZ"}, "field": "limit_status", "value": 1.5,
                "message": "不允许小数类型 float；只允许原生整数 0～6",
            }]}},
    ))

    class Executor:
        def plan(self, request):
            return MaintenanceExecutionPlan(plan_hash="stage2", units=(
                MaintenanceExecutionUnit(unit_key="first", payload={}),
                MaintenanceExecutionUnit(unit_key="second", payload={}),
            ))

        def execute_unit(self, unit):
            if unit.unit_key == "second":
                raise error
            return MaintenanceExecutionResult(rows_fetched=2, rows_saved=2, summary_message="first")

    dispatcher = TaskRunDispatcher(maintenance_executors={"stage2": Executor()})
    from src.ops.action_catalog import get_maintenance_action
    action = get_maintenance_action(NEWS_STOCK_LINKING_ACTION_KEY)
    task = task_run_factory(task_type="maintenance_action", resource_key=None,
        request_payload_json={"target_key": action.key})
    outcome = dispatcher._dispatch_registered_maintenance_action(session=db_session, task_run=task, action=action, executor=Executor())
    result = OperationsWorker()._finalize_task_run(db_session, task.id, outcome)
    assert result.status == "failed" and result.rows_saved == 2 and result.unit_done == 1
    issue = db_session.get(TaskRunIssue, result.primary_issue_id)
    assert issue.code == ERROR_CODE and "平安银行" in issue.operator_message and "1.5" in issue.operator_message
    assert issue.technical_payload_json["structured_error"]["details"]["rows_rejected"] == 1


@pytest.mark.parametrize("task_type", ["dataset_action", "workflow"])
def test_worker_preserves_monotonic_counts_without_copying_total_to_the_node(
    db_session, task_run_factory, task_run_node_factory, task_type,
):
    task = task_run_factory(task_type=task_type, status="running", rows_saved=7, rows_fetched=9)
    node = task_run_node_factory(task_run_id=task.id, status="running", rows_saved=2)
    task.current_node_id = node.id
    db_session.commit()
    result = OperationsWorker()._finalize_task_run(db_session, task.id, TaskRunDispatchOutcome(
        status="failed", status_reason_code=ERROR_CODE, rows_saved=5, rows_fetched=6))
    assert result.rows_saved == 7 and result.rows_fetched == 9
    assert db_session.get(TaskRunNode, node.id).status == "failed"
    assert db_session.get(TaskRunNode, node.id).rows_saved == 2


@pytest.mark.parametrize("failure_policy,completed,calls_expected", [("fail_fast", 1, 2), ("continue_on_error", 2, 3)])
def test_other_workflow_errors_keep_the_existing_partial_success_policy(
    db_session, runtime_data, task_run_factory, monkeypatch, failure_policy, completed, calls_expected,
):
    from src.ops.runtime import task_run_dispatcher as module

    workflow = WorkflowDefinition(key="ordinary-failure", display_name="原工作流", description="literal fixture", steps=tuple(
        WorkflowStepDefinition(str(i), "stk_limit.maintain", str(i), dataset_key="stk_limit") for i in range(3)
    ), failure_policy_default=failure_policy)
    monkeypatch.setattr(module, "get_workflow_definition", lambda _: workflow)
    dispatcher = TaskRunDispatcher()
    calls = []

    def run(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("ordinary failure, not a source validation error")
        return 1, 1, 0, {}, {}, "success"

    monkeypatch.setattr(dispatcher, "_run_dataset_action_plan", run)
    task = task_run_factory(task_type="workflow", resource_key=None,
        request_payload_json={"target_key": workflow.key},
        time_input_json={"mode": "range", "start_date": "2026-11-10", "end_date": "2026-11-12"})
    result = OperationsWorker(dispatcher).run_task_run(db_session, task.id)
    assert result.status == "partial_success" and result.status_reason_code == "workflow_step_failed"
    assert result.unit_done == result.rows_saved == completed
    assert len(calls) == calls_expected and runtime_data.called == []
