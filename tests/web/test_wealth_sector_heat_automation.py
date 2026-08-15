from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.app.exceptions import WebAppError
from src.app.runtime.ops_scheduler_factory import build_operations_scheduler, build_ops_runtime_command_service
from src.app.runtime.sector_heat_readiness_evaluator import SectorHeatReadinessEvaluator
from src.app.runtime.sector_heat_task_executor import SectorSourceCompletionEvidenceProvider
from src.biz.services.wealth.market.sector_overview import SectorHeatSourceNotReadyError
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.runtime.heat_readiness import (
    HEAT_AUTOMATION_SOURCE_TIMEOUT,
    HEAT_NON_TRADING_DAY,
    HEAT_PREVIEW_FAILED,
    HEAT_READY,
    HEAT_SOURCE_NOT_READY,
    HEAT_UPSTREAM_NOT_READY,
    HeatReadinessResult,
)
from src.ops.runtime.scheduler import OperationsScheduler
from src.ops.services.operations_schedule_service import OperationsScheduleService
from src.ops.services.sector_heat_upstream_readiness_service import SectorHeatUpstreamReadinessService


HEAT_ACTION = "maintenance.materialize_wealth_sector_heat_daily"
TARGET_DATE = date(2026, 8, 14)
CHECK_AT = datetime(2026, 8, 14, 13, 15, tzinfo=timezone.utc)


class StubReadinessEvaluator:
    def __init__(self, result: HeatReadinessResult) -> None:
        self.result = result
        self.calls = []

    def evaluate(self, session, *, request):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        return self.result


def _heat_schedule(ops_schedule_factory, *, next_run_at=CHECK_AT):  # type: ignore[no-untyped-def]
    return ops_schedule_factory(
        target_type="maintenance_action",
        target_key=HEAT_ACTION,
        display_name="每日板块热度",
        schedule_type="cron",
        cron_expr="15 21 * * 1-5",
        timezone_name="Asia/Shanghai",
        next_run_at=next_run_at,
    )


def _workflow_run_with_nodes(
    task_run_factory,
    task_run_node_factory,
    *,
    workflow_key: str,
    node_keys: tuple[str, ...],
    requested_at: datetime,
    failed_node: str | None = None,
    node_trade_date: date | None = TARGET_DATE,
):  # type: ignore[no-untyped-def]
    task_run = task_run_factory(
        task_type="workflow",
        resource_key=None,
        title=workflow_key,
        status="partial_success" if failed_node else "success",
        requested_at=requested_at,
        time_input_json={"mode": "point"},
        request_payload_json={
            "target_type": "workflow",
            "target_key": workflow_key,
            "time_input": {"mode": "point"},
        },
    )
    for sequence_no, node_key in enumerate(node_keys, start=1):
        task_run_node_factory(
            task_run_id=task_run.id,
            node_key=node_key,
            sequence_no=sequence_no,
            status="failed" if node_key == failed_node else "success",
            time_input_json=(
                {"mode": "point", "trade_date": node_trade_date.isoformat()}
                if node_trade_date is not None
                else {"mode": "point"}
            ),
            ended_at=requested_at + timedelta(minutes=5),
        )
    return task_run


def test_heat_schedule_hit_stages_one_task_with_frozen_readiness_and_advances(
    db_session,
    ops_schedule_factory,
) -> None:
    schedule = _heat_schedule(ops_schedule_factory)
    evaluator = StubReadinessEvaluator(
        HeatReadinessResult(
            ready=True,
            reason_code=HEAT_READY,
            message="ready",
            evidence={"workflows": [{"taskRunId": 11}]},
            config_version="v2",
            config_hash="a" * 64,
            source_hash="b" * 64,
            plan_hash="c" * 64,
            content_hash="d" * 64,
        )
    )

    created = OperationsScheduler(heat_readiness_evaluator=evaluator).run_once(db_session, now=CHECK_AT)

    assert len(created) == 1
    task_run = created[0]
    assert task_run.task_type == "maintenance_action"
    assert task_run.schedule_id == schedule.id
    assert task_run.trigger_source == "scheduled"
    assert task_run.time_input_json == {"mode": "point", "trade_date": TARGET_DATE.isoformat()}
    readiness = task_run.request_payload_json["readiness"]
    assert readiness["reasonCode"] == HEAT_READY
    assert readiness["planHash"] == "c" * 64
    assert readiness["contentHash"] == "d" * 64
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.last_triggered_at is not None
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) > CHECK_AT

    duplicate = OperationsScheduler(heat_readiness_evaluator=evaluator).run_once(
        db_session,
        now=CHECK_AT + timedelta(minutes=10),
    )
    assert duplicate == []
    assert len(db_session.scalars(select(TaskRun).where(TaskRun.schedule_id == schedule.id)).all()) == 1


@pytest.mark.parametrize("status", ["queued", "running", "success", "failed", "canceled"])
def test_heat_schedule_never_repeats_any_existing_automatic_attempt(
    db_session,
    ops_schedule_factory,
    task_run_factory,
    status: str,
) -> None:
    schedule = _heat_schedule(ops_schedule_factory)
    task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        title="生成单日板块热度",
        trigger_source="scheduled",
        status=status,
        schedule_id=schedule.id,
        time_input_json={"mode": "point", "trade_date": TARGET_DATE.isoformat()},
        request_payload_json={"target_type": "maintenance_action", "target_key": HEAT_ACTION},
    )
    evaluator = StubReadinessEvaluator(HeatReadinessResult(True, HEAT_READY, "ready"))

    created = OperationsScheduler(heat_readiness_evaluator=evaluator).run_once(db_session, now=CHECK_AT)

    assert created == []
    assert evaluator.calls == []
    assert len(db_session.scalars(select(TaskRun).where(TaskRun.schedule_id == schedule.id)).all()) == 1


def test_heat_schedule_miss_retries_without_task_then_times_out_once(
    db_session,
    ops_schedule_factory,
) -> None:
    schedule = _heat_schedule(ops_schedule_factory)
    evaluator = StubReadinessEvaluator(
        HeatReadinessResult(False, HEAT_SOURCE_NOT_READY, "dc_member missing", {"missing": ["dc_member"]})
    )
    scheduler = OperationsScheduler(heat_readiness_evaluator=evaluator)

    first = scheduler.run_once(db_session, now=CHECK_AT)

    assert first == []
    assert db_session.scalar(select(TaskRun).where(TaskRun.schedule_id == schedule.id)) is None
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == CHECK_AT + timedelta(minutes=10)

    deadline = datetime(2026, 8, 14, 16, 30, tzinfo=timezone.utc)
    refreshed.next_run_at = deadline
    db_session.commit()
    timed_out = scheduler.run_once(db_session, now=deadline)

    assert len(timed_out) == 1
    assert timed_out[0].status == "failed"
    assert timed_out[0].status_reason_code == HEAT_AUTOMATION_SOURCE_TIMEOUT
    issue = db_session.get(TaskRunIssue, timed_out[0].primary_issue_id)
    assert issue is not None
    assert issue.code == HEAT_AUTOMATION_SOURCE_TIMEOUT
    assert issue.technical_payload_json["readiness"]["reasonCode"] == HEAT_SOURCE_NOT_READY

    rerun = scheduler.run_once(db_session, now=deadline + timedelta(minutes=10))
    assert rerun == []
    assert len(db_session.scalars(select(TaskRun).where(TaskRun.schedule_id == schedule.id)).all()) == 1


def test_heat_schedule_late_restart_keeps_original_due_trade_date(
    db_session,
    ops_schedule_factory,
) -> None:
    original_due = CHECK_AT
    restarted_at = datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc)
    schedule = _heat_schedule(ops_schedule_factory, next_run_at=original_due)
    evaluator = StubReadinessEvaluator(
        HeatReadinessResult(False, HEAT_SOURCE_NOT_READY, "missing", {"missing": ["dc_daily"]})
    )

    created = OperationsScheduler(heat_readiness_evaluator=evaluator).run_once(db_session, now=restarted_at)

    assert len(created) == 1
    assert evaluator.calls[0].trade_date == TARGET_DATE
    assert created[0].time_input_json["trade_date"] == TARGET_DATE.isoformat()
    assert created[0].status_reason_code == HEAT_AUTOMATION_SOURCE_TIMEOUT
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) > restarted_at


def test_heat_schedule_non_trading_day_skips_without_task(db_session, ops_schedule_factory) -> None:
    schedule = _heat_schedule(ops_schedule_factory)
    evaluator = StubReadinessEvaluator(
        HeatReadinessResult(False, HEAT_NON_TRADING_DAY, "closed", {"isOpen": False})
    )

    created = OperationsScheduler(heat_readiness_evaluator=evaluator).run_once(db_session, now=CHECK_AT)

    assert created == []
    assert db_session.scalar(select(TaskRun).where(TaskRun.schedule_id == schedule.id)) is None
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) > CHECK_AT


def test_heat_schedule_contract_rejects_wrong_time_params_and_duplicate(db_session) -> None:
    service = OperationsScheduleService()
    common = {
        "target_type": "maintenance_action",
        "target_key": HEAT_ACTION,
        "display_name": "每日板块热度",
        "schedule_type": "cron",
        "trigger_mode": "schedule",
        "timezone_name": "Asia/Shanghai",
        "calendar_policy": None,
        "probe_config_json": {},
        "params_json": {},
        "retry_policy_json": {},
        "concurrency_policy_json": {},
        "next_run_at": None,
        "created_by_user_id": 1,
    }
    with pytest.raises(WebAppError) as wrong_time:
        service.create_schedule(db_session, cron_expr="0 21 * * 1-5", **common)
    assert wrong_time.value.code == "heat_schedule.contract_invalid"
    with pytest.raises(WebAppError) as fixed_date:
        service.create_schedule(
            db_session,
            cron_expr="15 21 * * 1-5",
            **{**common, "params_json": {"trade_date": TARGET_DATE.isoformat()}},
        )
    assert fixed_date.value.code == "heat_schedule.contract_invalid"

    service.create_schedule(db_session, cron_expr="15 21 * * 1,2,3,4,5", **common)
    with pytest.raises(WebAppError) as duplicate:
        service.create_schedule(db_session, cron_expr="15 21 * * 1-5", **common)
    assert duplicate.value.code == "heat_schedule.already_exists"


def test_upstream_gate_requires_same_21_after_run_and_all_required_nodes(
    db_session,
    trade_calendar_factory,
    task_run_factory,
    task_run_node_factory,
) -> None:
    trade_calendar_factory(trade_date=TARGET_DATE, is_open=True)
    early = datetime(2026, 8, 14, 12, 59, tzinfo=timezone.utc)
    late = datetime(2026, 8, 14, 13, 1, tzinfo=timezone.utc)
    close_nodes = ("daily", "dc_index", "dc_member", "dc_daily", "limit_list", "suspend_d")
    _workflow_run_with_nodes(
        task_run_factory,
        task_run_node_factory,
        workflow_key="daily_market_close_maintenance",
        node_keys=close_nodes,
        requested_at=early,
    )
    _workflow_run_with_nodes(
        task_run_factory,
        task_run_node_factory,
        workflow_key="daily_market_close_maintenance",
        node_keys=close_nodes,
        requested_at=late,
        failed_node="dc_member",
    )
    _workflow_run_with_nodes(
        task_run_factory,
        task_run_node_factory,
        workflow_key="daily_moneyflow_maintenance",
        node_keys=("moneyflow_ind_dc",),
        requested_at=late,
    )
    _workflow_run_with_nodes(
        task_run_factory,
        task_run_node_factory,
        workflow_key="daily_market_close_maintenance",
        node_keys=close_nodes,
        requested_at=late + timedelta(seconds=30),
        node_trade_date=TARGET_DATE - timedelta(days=1),
    )
    _workflow_run_with_nodes(
        task_run_factory,
        task_run_node_factory,
        workflow_key="daily_market_close_maintenance",
        node_keys=close_nodes,
        requested_at=late + timedelta(seconds=45),
        node_trade_date=None,
    )

    service = SectorHeatUpstreamReadinessService(not_before_local_time=datetime.strptime("21:00", "%H:%M").time())
    not_ready = service.evaluate(
        db_session,
        trade_date=TARGET_DATE,
        checked_at=CHECK_AT,
    )
    assert not_ready.reason_code == HEAT_UPSTREAM_NOT_READY

    ready_close = _workflow_run_with_nodes(
        task_run_factory,
        task_run_node_factory,
        workflow_key="daily_market_close_maintenance",
        node_keys=close_nodes,
        requested_at=late + timedelta(minutes=1),
    )
    ready = service.evaluate(
        db_session,
        trade_date=TARGET_DATE,
        checked_at=CHECK_AT,
    )
    assert ready.ready is True
    assert {item["taskRunId"] for item in ready.evidence["workflows"]} >= {ready_close.id}
    assert all(
        node["tradeDate"] == TARGET_DATE.isoformat()
        for workflow in ready.evidence["workflows"]
        for node in workflow["nodes"]
    )


def test_upstream_gate_non_open_day_does_not_query_workflows(db_session, trade_calendar_factory) -> None:
    trade_calendar_factory(trade_date=TARGET_DATE, is_open=False)

    result = SectorHeatUpstreamReadinessService(
        not_before_local_time=datetime.strptime("21:00", "%H:%M").time()
    ).evaluate(
        db_session,
        trade_date=TARGET_DATE,
        checked_at=CHECK_AT,
    )

    assert result.reason_code == HEAT_NON_TRADING_DAY
    assert result.evidence["isOpen"] is False


def test_app_readiness_maps_source_wait_and_unexpected_preview_error(db_session, web_engine) -> None:
    upstream = SimpleNamespace(
        evaluate=lambda *_args, **_kwargs: HeatReadinessResult(True, HEAT_READY, "upstream", {"taskRunId": 1})
    )
    evidence = SimpleNamespace(load=lambda **_kwargs: ())
    session_factory = sessionmaker(bind=web_engine, autoflush=False, autocommit=False, future=True)
    source_wait_service = SimpleNamespace(
        preview_trade_date=lambda *_args, **_kwargs: (_ for _ in ()).throw(SectorHeatSourceNotReadyError("dc_daily missing"))
    )
    source_wait = SectorHeatReadinessEvaluator(
        session_factory=session_factory,
        upstream_service=upstream,
        materialization_service=source_wait_service,
        evidence_provider=evidence,
    ).evaluate(db_session, request=SimpleNamespace(trade_date=TARGET_DATE, checked_at=CHECK_AT))
    assert source_wait.reason_code == HEAT_SOURCE_NOT_READY

    broken_service = SimpleNamespace(
        preview_trade_date=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad config"))
    )
    broken = SectorHeatReadinessEvaluator(
        session_factory=session_factory,
        upstream_service=upstream,
        materialization_service=broken_service,
        evidence_provider=evidence,
    ).evaluate(db_session, request=SimpleNamespace(trade_date=TARGET_DATE, checked_at=CHECK_AT))
    assert broken.reason_code == HEAT_PREVIEW_FAILED


def test_scheduler_factory_injects_heat_readiness(web_engine) -> None:
    session_factory = sessionmaker(bind=web_engine, autoflush=False, autocommit=False, future=True)

    scheduler = build_operations_scheduler(session_factory=session_factory)

    assert scheduler.schedule_service.heat_readiness_evaluator is not None

    runtime_service = build_ops_runtime_command_service(session_factory=session_factory)
    assert runtime_service.scheduler.schedule_service.heat_readiness_evaluator is not None
    assert "wealth_sector_heat" in runtime_service.worker.dispatcher.maintenance_executors


def test_zero_row_completion_evidence_uses_successful_nodes_when_unrelated_workflow_node_failed(
    web_engine,
    task_run_factory,
    task_run_node_factory,
) -> None:
    task_run = task_run_factory(
        task_type="workflow",
        resource_key=None,
        title="每日收盘后维护",
        status="failed",
        time_input_json={"mode": "point"},
        request_payload_json={"target_type": "workflow", "target_key": "daily_market_close_maintenance"},
    )
    limit_node = task_run_node_factory(
        task_run_id=task_run.id,
        node_key="limit_list",
        resource_key="limit_list_d",
        status="success",
        time_input_json={"mode": "point", "trade_date": TARGET_DATE.isoformat()},
        rows_saved=0,
    )
    suspend_node = task_run_node_factory(
        task_run_id=task_run.id,
        node_key="suspend_d",
        resource_key="suspend_d",
        status="success",
        time_input_json={"mode": "point", "trade_date": TARGET_DATE.isoformat()},
        rows_saved=0,
    )
    session_factory = sessionmaker(bind=web_engine, autoflush=False, autocommit=False, future=True)

    evidence = SectorSourceCompletionEvidenceProvider(session_factory).load(
        start_date=TARGET_DATE,
        end_date=TARGET_DATE,
    )

    assert {(item.dataset_key, item.evidence_id, item.evidence_type) for item in evidence} == {
        ("limit_list_d", f"{task_run.id}:{limit_node.id}", "task_run_node"),
        ("suspend_d", f"{task_run.id}:{suspend_node.id}", "task_run_node"),
    }
