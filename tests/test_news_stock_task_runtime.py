from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.exceptions import WebAppError
from src.ops.action_catalog import get_maintenance_action
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.services.news_stock_linking_service import NEWS_STOCK_LINKING_ACTION_KEY
from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        TaskRun.__table__.create(connection, checkfirst=True)
        TaskRunNode.__table__.create(connection, checkfirst=True)
    return Session(engine)


def _context() -> TaskRunCreateContext:
    return TaskRunCreateContext(
        task_type="maintenance_action",
        resource_key=None,
        action="maintain",
        time_input={"mode": "none"},
        filters={"mode": "incremental"},
        request_payload={"target_key": NEWS_STOCK_LINKING_ACTION_KEY, "mode": "incremental"},
        trigger_source="manual",
        requested_by_user_id=1,
    )


def test_news_task_freezes_full_initialization_then_incremental_overlap() -> None:
    session = _session()
    service = TaskRunCommandService()

    first = service.stage_task_run(session, context=_context())
    assert first.request_payload_json["mode"] == "full"
    assert first.request_payload_json["window_start"] is None
    first.status = "success"
    session.commit()

    previous_end = datetime.fromisoformat(first.request_payload_json["window_end"])
    failed = service.stage_task_run(session, context=_context())
    failed.status = "failed"
    failed.request_payload_json["window_end"] = (previous_end + timedelta(days=1)).isoformat()
    session.commit()

    second = service.stage_task_run(session, context=_context())
    assert second.request_payload_json["mode"] == "incremental"
    assert datetime.fromisoformat(second.request_payload_json["window_start"]) == previous_end - timedelta(hours=1)
    assert second.request_payload_json["news_scope"] == "all"


def test_news_task_rejects_concurrent_active_run() -> None:
    session = _session()
    service = TaskRunCommandService()
    service.stage_task_run(session, context=_context())

    with pytest.raises(WebAppError) as error:
        service.stage_task_run(session, context=_context())
    assert error.value.status_code == 409


class _FakeNewsExecutor:
    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        assert request.action_key == NEWS_STOCK_LINKING_ACTION_KEY
        return MaintenanceExecutionPlan(
            plan_hash="news-plan",
            units=(MaintenanceExecutionUnit(unit_key="news-window", payload={"window_end": "2026-08-23T00:00:00+00:00"}),),
        )

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        return MaintenanceExecutionResult(
            rows_fetched=10,
            rows_saved=8,
            rows_rejected=0,
            metadata={
                "matched_news_count": 8,
                "links_inserted": 6,
                "links_updated": 2,
                "links_deleted": 1,
                "rows_deduplicated": 3,
                "overlap_seconds": 3600,
                "batch_count": 2,
                "last_cursor": {"fetched_at": "2026-08-23T00:00:00+00:00", "row_key_hash": "z"},
            },
        )


def test_dispatcher_maps_news_executor_diagnostics_to_node_and_outcome() -> None:
    session = _session()
    task_run = TaskRun(
        task_type="maintenance_action",
        resource_key=None,
        action="maintain",
        title="物化新闻—个股关联",
        trigger_source="manual",
        status="running",
        request_payload_json={
            "target_key": NEWS_STOCK_LINKING_ACTION_KEY,
            "mode": "full",
            "window_start": None,
            "window_end": "2026-08-23T00:00:00+00:00",
            "overlap_seconds": 0,
            "rule_version": "news-stock-rule-v1",
            "news_scope": "all",
        },
        time_input_json={"mode": "none"},
        filters_json={},
        requested_at=datetime.now(timezone.utc),
    )
    session.add(task_run)
    session.commit()

    action = get_maintenance_action(NEWS_STOCK_LINKING_ACTION_KEY)
    assert action is not None
    outcome = TaskRunDispatcher(maintenance_executors={"news_stock_linking": _FakeNewsExecutor()}).dispatch(
        session,
        task_run,
    )

    assert outcome.status == "success"
    assert outcome.rows_fetched == 10
    assert outcome.rows_saved == 8
    assert outcome.rows_deduplicated == 3
    assert outcome.ingestion_diagnostics["links_deleted"] == 1
    node = session.scalar(select(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id))
    assert node is not None
    assert node.rows_deduplicated == 3
    assert node.ingestion_diagnostics_json["batch_count"] == 2
