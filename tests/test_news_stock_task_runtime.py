from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.exceptions import WebAppError
from src.app.runtime.news_stock_linking_task_executor import NewsStockLinkingTaskExecutor
from src.ops.action_catalog import get_maintenance_action
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
    MaintenanceTaskRunContext,
)
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.services.news_stock_linking_service import (
    NEWS_STOCK_LINKING_ACTION_KEY,
    NewsStockLinkingStats,
)
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


def _manual_context(*, start_date: str = "2026-08-23", end_date: str = "2026-08-23") -> TaskRunCreateContext:
    return TaskRunCreateContext(
        task_type="maintenance_action",
        resource_key=None,
        action="maintain",
        time_input={"mode": "range", "start_date": start_date, "end_date": end_date},
        filters={},
        request_payload={
            "target_type": "maintenance_action",
            "target_key": NEWS_STOCK_LINKING_ACTION_KEY,
        },
        trigger_source="manual",
        requested_by_user_id=1,
    )


def _scheduled_context() -> TaskRunCreateContext:
    return TaskRunCreateContext(
        task_type="maintenance_action",
        resource_key=None,
        action="maintain",
        time_input={"mode": "none"},
        filters={},
        request_payload={
            "target_type": "maintenance_action",
            "target_key": NEWS_STOCK_LINKING_ACTION_KEY,
        },
        trigger_source="scheduled",
        requested_by_user_id=None,
        schedule_id=9,
    )


def test_news_task_freezes_manual_shanghai_day_then_scheduled_success_cursor() -> None:
    session = _session()
    service = TaskRunCommandService()
    first_frozen_at = datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc)

    first = service.stage_task_run(
        session,
        context=_manual_context(),
        task_frozen_at=first_frozen_at,
    )
    assert first.request_payload_json["run_mode"] == "manual_range"
    assert first.request_payload_json["window_field"] == "news_time"
    assert first.request_payload_json["window_start"] == "2026-08-22T16:00:00+00:00"
    assert first.request_payload_json["window_end"] == "2026-08-23T16:00:00+00:00"
    assert first.request_payload_json["cursor_end"] == first_frozen_at.isoformat()
    first.status = "success"
    session.commit()

    failed = service.stage_task_run(
        session,
        context=_manual_context(start_date="2026-08-24", end_date="2026-08-24"),
        task_frozen_at=datetime(2026, 8, 24, 11, 0, tzinfo=timezone.utc),
    )
    failed.status = "failed"
    session.commit()

    second_frozen_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    second = service.stage_task_run(
        session,
        context=_scheduled_context(),
        task_frozen_at=second_frozen_at,
    )
    assert second.request_payload_json["run_mode"] == "scheduled_incremental"
    assert second.request_payload_json["window_start"] == first_frozen_at.isoformat()
    assert second.request_payload_json["window_end"] == second_frozen_at.isoformat()
    assert second.request_payload_json["cursor_end"] == second_frozen_at.isoformat()
    assert second.request_payload_json["news_scope"] == "all"
    assert "overlap_seconds" not in second.request_payload_json


def test_news_task_retry_reuses_new_frozen_window_and_rejects_legacy_payload() -> None:
    session = _session()
    service = TaskRunCommandService()
    payload = {
        "task_type": "maintenance_action",
        "resource_key": None,
        "action": "maintain",
        "target_type": "maintenance_action",
        "target_key": NEWS_STOCK_LINKING_ACTION_KEY,
        "time_input": {"mode": "range", "start_date": "2026-08-22", "end_date": "2026-08-22"},
        "filters": {},
        "run_mode": "manual_range",
        "window_field": "news_time",
        "window_start": "2026-08-21T16:00:00+00:00",
        "window_end": "2026-08-22T16:00:00+00:00",
        "cursor_end": "2026-08-22T16:00:00+00:00",
        "task_frozen_at": "2026-08-23T11:00:00+00:00",
        "rule_version": "news-stock-rule-v1",
        "news_scope": "all",
    }
    retry_context = TaskRunCreateContext(
        task_type="maintenance_action",
        resource_key=None,
        action="maintain",
        time_input=dict(payload["time_input"]),
        filters={},
        request_payload=payload,
        trigger_source="retry",
        requested_by_user_id=1,
    )

    retried = service.stage_task_run(
        session,
        context=retry_context,
        task_frozen_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert retried.request_payload_json == payload
    retried.status = "failed"
    session.commit()

    legacy_context = replace(retry_context, request_payload={**payload, "mode": "full"})
    with pytest.raises(WebAppError) as error:
        service.stage_task_run(session, context=legacy_context)
    assert error.value.code == "news_stock_linking.legacy_payload_forbidden"


def test_news_task_scheduled_success_chain_is_not_replaced_by_later_manual_range() -> None:
    session = _session()
    service = TaskRunCommandService()
    manual_cursor = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    baseline = service.stage_task_run(
        session,
        context=_manual_context(),
        task_frozen_at=manual_cursor,
    )
    baseline.status = "success"
    session.commit()

    first_auto_cursor = datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc)
    first_auto = service.stage_task_run(
        session,
        context=_scheduled_context(),
        task_frozen_at=first_auto_cursor,
    )
    first_auto.status = "success"
    session.commit()

    later_manual = service.stage_task_run(
        session,
        context=_manual_context(),
        task_frozen_at=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
    )
    later_manual.status = "success"
    session.commit()

    next_auto = service.stage_task_run(
        session,
        context=_scheduled_context(),
        task_frozen_at=datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc),
    )

    assert next_auto.request_payload_json["window_start"] == first_auto_cursor.isoformat()


def test_news_task_old_full_success_is_not_an_automatic_baseline() -> None:
    session = _session()
    session.add(
        TaskRun(
            task_type="maintenance_action",
            resource_key=None,
            action="maintain",
            title="旧版新闻关联 Full",
            trigger_source="manual",
            status="success",
            time_input_json={"mode": "none"},
            filters_json={},
            request_payload_json={
                "target_key": NEWS_STOCK_LINKING_ACTION_KEY,
                "mode": "full",
                "window_end": "2026-08-23T10:00:00+00:00",
            },
            requested_at=datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc),
        )
    )
    session.commit()

    with pytest.raises(WebAppError) as error:
        TaskRunCommandService().stage_task_run(
            session,
            context=_scheduled_context(),
            task_frozen_at=datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc),
        )

    assert error.value.code == "news_stock_linking.baseline_required"


def test_news_task_rejects_concurrent_active_run() -> None:
    session = _session()
    service = TaskRunCommandService()
    service.stage_task_run(
        session,
        context=_manual_context(),
        task_frozen_at=datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(WebAppError) as error:
        service.stage_task_run(
            session,
            context=_manual_context(),
            task_frozen_at=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
        )
    assert error.value.status_code == 409


class _FakeNewsExecutor:
    def __init__(self) -> None:
        self.task_run_ids: list[int] = []

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        assert request.action_key == NEWS_STOCK_LINKING_ACTION_KEY
        return MaintenanceExecutionPlan(
            plan_hash="news-plan",
            units=(MaintenanceExecutionUnit(unit_key="news-window", payload={"window_end": "2026-08-23T00:00:00+00:00"}),),
        )

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        raise AssertionError("news action must use the TaskRun-aware execution path")

    def execute_unit_for_task_run(
        self,
        unit: MaintenanceExecutionUnit,
        *,
        context: MaintenanceTaskRunContext,
    ) -> MaintenanceExecutionResult:
        self.task_run_ids.append(context.task_run_id)
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
                "batch_count": 2,
                "last_cursor": {"news_time": "2026-08-23T00:00:00+00:00", "row_key_hash": "z"},
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
            "run_mode": "manual_range",
            "window_field": "news_time",
            "window_start": "2026-08-22T16:00:00+00:00",
            "window_end": "2026-08-23T00:00:00+00:00",
            "cursor_end": "2026-08-23T00:00:00+00:00",
            "task_frozen_at": "2026-08-23T00:00:00+00:00",
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
    executor = _FakeNewsExecutor()
    outcome = TaskRunDispatcher(maintenance_executors={"news_stock_linking": executor}).dispatch(
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
    assert executor.task_run_ids == [task_run.id]


class _CapturingRunContext:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.snapshots: list[dict] = []

    def is_cancel_requested(self, *, run_id: int) -> bool:
        return False

    def update_progress(self, **snapshot) -> None:  # type: ignore[no-untyped-def]
        if self.fail:
            raise RuntimeError("synthetic TaskRun observer failure")
        self.snapshots.append(snapshot)


def _news_unit() -> MaintenanceExecutionUnit:
    return MaintenanceExecutionUnit(
        unit_key="news-window",
        payload={
            "run_mode": "manual_range",
            "window_field": "news_time",
            "window_start": "2026-08-22T16:00:00+00:00",
            "window_end": "2026-08-23T11:01:16+00:00",
            "cursor_end": "2026-08-23T11:01:16+00:00",
            "task_frozen_at": "2026-08-23T11:01:16+00:00",
            "rule_version": "news-stock-rule-v1",
            "news_scope": "all",
        },
    )


def _stats(*, batch_count: int, rows_fetched: int, rows_saved: int) -> NewsStockLinkingStats:
    return NewsStockLinkingStats(
        rows_fetched=rows_fetched,
        matched_news_count=rows_fetched,
        links_inserted=rows_saved,
        rows_deduplicated=batch_count,
        batch_count=batch_count,
        last_cursor={
            "news_time": f"2026-08-23T11:01:{batch_count:02d}+00:00",
            "row_key_hash": str(batch_count),
        },
    )


def test_news_executor_throttles_progress_and_forces_final_flush(monkeypatch) -> None:
    now = [0.0]
    run_context = _CapturingRunContext()
    emitted = [
        _stats(batch_count=1, rows_fetched=10, rows_saved=8),
        _stats(batch_count=2, rows_fetched=20, rows_saved=16),
        _stats(batch_count=3, rows_fetched=30, rows_saved=24),
        _stats(batch_count=4, rows_fetched=40, rows_saved=32),
    ]

    def fake_materialize(self, **kwargs):  # type: ignore[no-untyped-def]
        sink = kwargs["progress_sink"]
        sink(emitted[0])
        now[0] = 1.0
        sink(emitted[1])
        now[0] = 3.1
        sink(emitted[2])
        now[0] = 3.2
        sink(emitted[3])
        return emitted[3]

    monkeypatch.setattr(
        "src.app.runtime.news_stock_linking_task_executor.NewsStockLinkingService.materialize",
        fake_materialize,
    )
    executor = NewsStockLinkingTaskExecutor(session_factory=lambda: None, progress_clock=lambda: now[0])

    result = executor.execute_unit_for_task_run(
        _news_unit(),
        context=MaintenanceTaskRunContext(task_run_id=9148, run_context=run_context),
    )

    assert result.rows_fetched == 40
    assert [snapshot["rows_fetched"] for snapshot in run_context.snapshots] == [10, 30, 40]
    assert all(snapshot["unit_done"] == 0 and snapshot["total"] == 1 for snapshot in run_context.snapshots)
    assert run_context.snapshots[-1]["rows_saved"] == 32
    assert run_context.snapshots[-1]["current_object"] == {
        "entity": {"kind": "enum", "name": "新闻—个股关联"},
        "time": {
            "start": "2026-08-22T16:00:00+00:00",
            "end": "2026-08-23T11:01:16+00:00",
            "field": "news_time",
        },
        "attributes": {"enum_value": "批次 4：已处理新闻 40，已生成关联 32"},
    }


def test_news_executor_flushes_last_committed_snapshot_on_failure(monkeypatch) -> None:
    now = [0.0]
    run_context = _CapturingRunContext()
    first = _stats(batch_count=1, rows_fetched=10, rows_saved=8)
    second = _stats(batch_count=2, rows_fetched=20, rows_saved=16)

    def fail_after_second_commit(self, **kwargs):  # type: ignore[no-untyped-def]
        sink = kwargs["progress_sink"]
        sink(first)
        now[0] = 1.0
        sink(second)
        raise RuntimeError("synthetic materialization failure")

    monkeypatch.setattr(
        "src.app.runtime.news_stock_linking_task_executor.NewsStockLinkingService.materialize",
        fail_after_second_commit,
    )
    executor = NewsStockLinkingTaskExecutor(session_factory=lambda: None, progress_clock=lambda: now[0])

    with pytest.raises(RuntimeError, match="synthetic materialization failure"):
        executor.execute_unit_for_task_run(
            _news_unit(),
            context=MaintenanceTaskRunContext(task_run_id=9148, run_context=run_context),
        )

    assert [snapshot["rows_fetched"] for snapshot in run_context.snapshots] == [10, 20]


def test_news_executor_observer_failure_is_fail_soft(monkeypatch) -> None:
    final_stats = _stats(batch_count=1, rows_fetched=10, rows_saved=8)

    def fake_materialize(self, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["progress_sink"](final_stats)
        return final_stats

    monkeypatch.setattr(
        "src.app.runtime.news_stock_linking_task_executor.NewsStockLinkingService.materialize",
        fake_materialize,
    )
    executor = NewsStockLinkingTaskExecutor(session_factory=lambda: None)

    result = executor.execute_unit_for_task_run(
        _news_unit(),
        context=MaintenanceTaskRunContext(
            task_run_id=9148,
            run_context=_CapturingRunContext(fail=True),
        ),
    )

    assert result.rows_fetched == 10
    assert result.rows_saved == 8
