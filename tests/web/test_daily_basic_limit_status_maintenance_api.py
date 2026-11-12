"""Real maintenance runtime and HTTP view on the temporary PostgreSQL fixture.

Authentication and source I/O are replaced; resolver, snapshot, dispatcher,
worker, business transactions, progress persistence and HTTP schemas are real.
"""

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.app.exceptions import install_exception_handlers
from src.app.models.app_user import AppUser
from src.app.runtime.daily_basic_limit_status_task_executor import ACTION_KEY, DailyBasicLimitStatusTaskExecutor
from src.app.runtime.ops_worker_factory import build_operations_worker, build_stk_mins_worker
from src.foundation.config.settings import get_settings
from src.ops import action_catalog
from src.ops.api.task_runs import router
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.runtime.worker import OperationsWorker
from src.ops.runtime.maintenance_executor import MaintenanceExecutionRequest
from tests.test_daily_basic_limit_status_backfill import (
    DAY, NEXT_DAY, read_rows, service, source_rows,
)

pytest_plugins = ("tests.test_daily_basic_limit_status_backfill",)


@pytest.fixture
def runtime(database, monkeypatch):
    engine, factory = database
    monkeypatch.setattr(get_settings(), "sync_batch_size", 2)
    value = service(factory)
    value.connector.call_bounded.side_effect = lambda **kw: source_rows(
        datetime.strptime(kw["params"]["trade_date"], "%Y%m%d").date())
    executor = DailyBasicLimitStatusTaskExecutor(session_factory=factory, service=value)
    worker = OperationsWorker(TaskRunDispatcher(maintenance_executors={"daily_basic_limit_status": executor}))
    return engine, factory, value, executor, worker


def task(session, **params):
    row = TaskRun(task_type="maintenance_action", action="maintain", title="每日指标补录验收",
                  trigger_source="manual", status="queued", requested_at=datetime.now(timezone.utc),
                  request_payload_json={"target_key": ACTION_KEY, **params}, time_input_json={}, filters_json={})
    session.add(row)
    session.commit()
    return row


def freeze(session, worker):
    planned = task(session, execution_mode="PLAN", start_date=str(DAY), end_date=str(NEXT_DAY))
    result = worker.run_task_run(session, planned.id)
    assert result.status == "success"
    assert result.plan_snapshot_json["snapshot_state"] == "FROZEN"
    assert result.plan_snapshot_json["apply_ready"] is True
    return result


def apply_task(session, plan):
    return task(session, execution_mode="APPLY", plan_task_run_id=plan.id, plan_hash=plan.plan_snapshot_json["plan_hash"])


def test_freeze_cancel_after_commit_then_new_apply_uses_frozen_config_once(runtime, monkeypatch):
    engine, factory, value, executor, worker = runtime
    observed = []
    with factory() as session:
        plan = freeze(session, worker)
        metadata = plan.plan_snapshot_json["metadata"]
        assert metadata["dates"] == ["2026-11-10", "2026-11-11"]
        assert metadata["date_counts"] == {
            "2026-11-10": {"raw_count": 2, "serving_count": 2},
            "2026-11-11": {"raw_count": 2, "serving_count": 2},
        }
        assert metadata["key_fields"] == ["ts_code", "trade_date"]
        assert metadata["update_columns"] == ["limit_status"]
        assert len(metadata["source_fields"]) == 19 and metadata["source_fields"][-1] == "limit_status"
        frozen = metadata["execution_config"]
        assert frozen["sync_batch_size"] == 2
        assert "max_response_bytes" not in frozen
        monkeypatch.setattr(get_settings(), "sync_batch_size", 1)
        pending = apply_task(session, plan)
        original = value.execute_day

        def cancel_after_date(payload, **kwargs):
            result = original(payload, **kwargs)
            if payload["trade_date"] == str(DAY):
                with factory() as control:
                    current = control.get(TaskRun, pending.id)
                    current.cancel_requested_at = datetime.now(timezone.utc)
                    control.commit()
            return result

        monkeypatch.setattr(value, "execute_day", cancel_after_date)
        canceled = worker.run_task_run(session, pending.id)
        assert (canceled.status, canceled.unit_done, canceled.rows_saved) == ("canceled", 1, 2)
        nodes = session.scalars(select(TaskRunNode).where(TaskRunNode.task_run_id == pending.id).order_by(TaskRunNode.sequence_no)).all()
        assert [(node.status, node.rows_saved) for node in nodes] == [("success", 2), ("canceled", 0)]
        assert value.connector.call_bounded.call_count == 1

        fresh = DailyBasicLimitStatusTaskExecutor(session_factory=factory, service=service(factory, source_rows(NEXT_DAY)))
        restarted = OperationsWorker(TaskRunDispatcher(maintenance_executors={"daily_basic_limit_status": fresh}))
        event.listen(engine, "before_cursor_execute", lambda c, u, sql, p, ctx, many: observed.append(sql))
        retry = restarted.run_task_run(session, apply_task(session, plan).id)
        assert (retry.status, retry.unit_done, retry.rows_fetched, retry.rows_saved) == ("success", 2, 2, 4)
        assert [node.rows_saved for node in session.scalars(select(TaskRunNode).where(
            TaskRunNode.task_run_id == retry.id).order_by(TaskRunNode.sequence_no))] == [2, 2]
        assert len([sql for sql in observed if sql.startswith("UPDATE raw_tushare.daily_basic")]) == 1
        assert get_settings().sync_batch_size == 1
        assert all([row["limit_status"] for row in rows] == [4, 0, 4, 0] for rows in read_rows(engine))


def test_repeated_progress_ticks_preserve_per_date_counts_and_are_visible_in_http(runtime):
    engine, factory, value, executor, worker = runtime
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA app"))
        AppUser.__table__.create(connection)
        OpsSchedule.__table__.create(connection)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    install_exception_handlers(app)
    app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(
        id=1, username="isolated-admin", display_name=None, email=None,
        account_state="active", is_admin=True, is_active=True)
    with factory() as session:
        plan = freeze(session, worker)
        pending = apply_task(session, plan)

        def connection():
            with factory() as observation:
                yield observation

        app.dependency_overrides[get_db_session] = connection
        progress = []
        executor._clock = iter(range(0, 10000, 5)).__next__
        with TestClient(app) as client:
            def source(**kwargs):
                for _ in range(3):
                    kwargs["tick"]()
                    view = client.get(f"/api/v1/ops/task-runs/{pending.id}/view")
                    assert view.status_code == 200
                    progress.append(view.json())
                return source_rows(datetime.strptime(kwargs["params"]["trade_date"], "%Y%m%d").date())

            value.connector.call_bounded.side_effect = source
            result = worker.run_task_run(session, pending.id)
            view = client.get(f"/api/v1/ops/task-runs/{pending.id}/view")
        assert (result.status, result.rows_saved) == ("success", 4)
        assert [item["progress"]["rows_saved"] for item in progress] == [0, 0, 0, 2, 2, 2]
        assert all(item["nodes"][-1]["rows_saved"] == 0 for item in progress)
        assert all("读取源数据" in str(item) and "暂无法估算" in str(item) for item in progress)
        assert view.status_code == 200
        assert [node["rows_saved"] for node in view.json()["nodes"]] == [2, 2]


def test_bad_value_stops_the_task_after_previous_date_and_names_stock(runtime):
    engine, factory, value, executor, worker = runtime
    value.connector.call_bounded.side_effect = lambda **kw: (
        source_rows() if kw["params"]["trade_date"] == "20261110"
        else [{**source_rows(NEXT_DAY)[0], "limit_status": 1.5}, source_rows(NEXT_DAY)[1]])
    with factory() as session:
        plan = freeze(session, worker)
        failed = worker.run_task_run(session, apply_task(session, plan).id)
        assert (failed.status, failed.rows_saved, failed.unit_done) == ("failed", 2, 1)
        issue = session.get(TaskRunIssue, failed.primary_issue_id)
        assert all(word in issue.operator_message for word in ("2026-11-11", "000001.SZ", "平安银行", "1.5", "float"))
        node = session.get(TaskRunNode, failed.current_node_id)
        assert node.status == "failed" and node.rows_saved == 0
    assert all([row["limit_status"] for row in rows] == [4, 0, None, None] for rows in read_rows(engine))


def test_observation_failure_cannot_rollback_business(runtime):
    engine, factory, value, executor, worker = runtime

    class BrokenObservation(Session):
        def execute(self, statement, *args, **kwargs):
            if getattr(statement, "is_update", False) and statement.table.name == "task_run":
                raise SQLAlchemyError("deliberate observation failure")
            return super().execute(statement, *args, **kwargs)

    executor._session_factory = sessionmaker(engine, class_=BrokenObservation)
    with factory() as session:
        plan = freeze(session, worker)
        result = worker.run_task_run(session, apply_task(session, plan).id)
        assert (result.status, result.rows_saved) == ("success", 4)
    assert all([row["limit_status"] for row in rows] == [4, 0, 4, 0] for rows in read_rows(engine))


def test_dispatcher_status_failure_retains_committed_date_and_retry_reads_back(runtime, monkeypatch):
    engine, factory, value, executor, worker = runtime
    with factory() as session:
        plan = freeze(session, worker)
        pending = apply_task(session, plan)
        commit = session.commit
        failed_once = False

        def fail_status():
            nonlocal failed_once
            if not failed_once and any(isinstance(row, TaskRunNode) and row.status == "success" for row in session.dirty):
                failed_once = True
                raise SQLAlchemyError("deliberate post-business status failure")
            return commit()

        monkeypatch.setattr(session, "commit", fail_status)
        result = worker.run_task_run(session, pending.id)
        assert failed_once and (result.status, result.rows_saved, result.unit_done) == ("failed", 2, 1)
        assert session.get(TaskRunNode, result.current_node_id).rows_saved == 2
        retry = worker.run_task_run(session, apply_task(session, plan).id)
        assert (retry.status, retry.rows_saved) == ("success", 4)


def test_plan_and_apply_need_no_response_byte_configuration(runtime):
    engine, factory, value, executor, worker = runtime
    with factory() as session:
        plan = freeze(session, worker)
        assert "max_response_bytes" not in plan.plan_snapshot_json["metadata"]["execution_config"]
        result = worker.run_task_run(session, apply_task(session, plan).id)
        assert (result.status, result.rows_saved) == ("success", 4)
    assert all(call.kwargs["maximum"] is None for call in value.connector.call_bounded.call_args_list)


def test_plan_requires_dates_and_cancelled_draft_cannot_apply(runtime, monkeypatch):
    engine, factory, value, executor, worker = runtime
    with factory() as session:
        missing = task(session, execution_mode="PLAN")
        assert worker.run_task_run(session, missing.id).status == "failed"

        from src.ops.services.task_run_maintenance_plan_context import TaskRunMaintenancePlanContext

        original = TaskRunMaintenancePlanContext.save_checkpoint

        def cancel_draft(context, checkpoint):
            original(context, checkpoint)
            with factory() as other:
                row = other.get(TaskRun, context.task_run_id)
                row.cancel_requested_at = datetime.now(timezone.utc)
                other.commit()

        monkeypatch.setattr(TaskRunMaintenancePlanContext, "save_checkpoint", cancel_draft)
        planned = task(session, execution_mode="PLAN", start_date=str(DAY), end_date=str(NEXT_DAY))
        result = worker.run_task_run(session, planned.id)
        assert result.status == "canceled"
        assert result.plan_snapshot_json["snapshot_state"] == "BUILDING"
        assert result.plan_snapshot_json["apply_ready"] is False
        bad = task(session, execution_mode="APPLY", plan_task_run_id=planned.id, plan_hash="draft")
        assert worker.run_task_run(session, bad.id).status == "failed"
    value.connector.call_bounded.assert_not_called()


@pytest.mark.parametrize("exit_stage,fetched,requests", [("before_commit", 4, 2), ("after_commit", 2, 1)])
def test_real_process_exit_has_no_observation_but_resume_recovers(runtime, tmp_path, exit_stage, fetched, requests):
    engine, factory, value, executor, worker = runtime
    with factory() as session:
        plan = freeze(session, worker)
        script = tmp_path / "exit_after_date.py"
        script.write_text('''import os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from tests.test_daily_basic_limit_status_backfill import CONFIG, execute, service
engine = create_engine(sys.argv[1])
class ExitBeforeCommit(Session):
    def commit(self):
        os._exit(17)
execute(service(sessionmaker(engine, class_=ExitBeforeCommit if sys.argv[2] == 'before_commit' else Session)))
os._exit(17)
''')
        result = subprocess.run([sys.executable, "-B", str(script), str(engine.url), exit_stage], cwd=Path(__file__).resolve().parents[2],
                                env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 17, result.stderr
        # No previous APPLY state exists: only physical values can decide resume.
        retry = worker.run_task_run(session, apply_task(session, plan).id)
        assert (retry.status, retry.rows_fetched, retry.rows_saved) == ("success", fetched, 4)
        assert value.connector.call_bounded.call_count == requests


def test_registration_only_adds_manual_general_worker_action(database):
    engine, factory = database
    action = action_catalog.get_maintenance_action(ACTION_KEY)
    assert action.manual_enabled and action.retry_enabled and not action.schedule_enabled
    assert action.default_params == {"execution_mode": "PLAN"}
    assert action.target_tables == ("raw_tushare.daily_basic", "core_serving.equity_daily_basic")
    general = build_operations_worker(session_factory=factory)
    minutes = build_stk_mins_worker(session_factory=factory)
    assert "daily_basic_limit_status" in general.dispatcher.maintenance_executors
    assert "daily_basic_limit_status" not in minutes.dispatcher.maintenance_executors
    executor = general.dispatcher.maintenance_executors["daily_basic_limit_status"]
    with pytest.raises(ValueError):
        executor.plan(MaintenanceExecutionRequest(ACTION_KEY, {}))
    with pytest.raises(ValueError):
        executor.execute_unit(None)


def test_existing_catalog_and_manual_http_entry_accept_only_registered_parameters(app_client, auth_token):
    headers = {"Authorization": f"Bearer {auth_token}"}
    catalog = app_client.get("/api/v1/ops/catalog", headers=headers)
    assert catalog.status_code == 200
    action = next(item for item in catalog.json()["actions"] if item["key"] == ACTION_KEY)
    assert {parameter["key"] for parameter in action["parameters"]} == {
        "execution_mode", "start_date", "end_date", "plan_task_run_id", "plan_hash"}
    response = app_client.post("/api/v1/ops/task-runs", headers=headers, json={
        "task_type": "maintenance_action", "request_payload": {"target_key": ACTION_KEY,
            "execution_mode": "PLAN", "start_date": str(DAY), "end_date": str(NEXT_DAY)}})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
