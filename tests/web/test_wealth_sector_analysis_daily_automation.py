from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from src.app.runtime.ops_scheduler_factory import build_operations_scheduler
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.action_catalog import get_maintenance_action
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_readiness import MaintenanceReadinessResult
from src.ops.runtime.scheduler import OperationsScheduler
from src.ops.runtime.sector_analysis_daily_readiness import (
    SECTOR_ANALYSIS_DAILY_NON_TRADING_DAY,
    SECTOR_ANALYSIS_DAILY_READY,
    SECTOR_ANALYSIS_DAILY_SOURCE_NOT_READY,
)
from src.ops.services.operations_schedule_service import SECTOR_ANALYSIS_DAILY_ACTION_KEY
from src.ops.services.sector_analysis_daily_upstream_readiness_service import (
    SectorAnalysisDailyUpstreamReadinessService,
)


TARGET_DATE = date(2026, 8, 31)
CHECK_AT = datetime(2026, 8, 31, 12, 5, tzinfo=timezone.utc)


class ReadinessStub:
    def __init__(self, result: MaintenanceReadinessResult) -> None:
        self.result = result
        self.calls = []

    def evaluate(self, session, *, request):  # type: ignore[no-untyped-def]
        del session
        self.calls.append(request)
        return self.result


def _schedule(ops_schedule_factory):  # type: ignore[no-untyped-def]
    return ops_schedule_factory(
        target_type="maintenance_action",
        target_key=SECTOR_ANALYSIS_DAILY_ACTION_KEY,
        display_name="每日板块分析事实",
        schedule_type="cron",
        cron_expr="5 20 * * 1-5",
        timezone_name="Asia/Shanghai",
        next_run_at=CHECK_AT,
    )


def test_daily_action_is_registered_with_frozen_hdd_targets_and_schedule() -> None:
    action = get_maintenance_action(SECTOR_ANALYSIS_DAILY_ACTION_KEY)

    assert action is not None
    assert action.executor_key == "wealth_sector_analysis_daily"
    assert action.readiness_policy == {
        "timezone": "Asia/Shanghai",
        "initial_check_local_time": "20:05",
        "retry_interval_seconds": 600,
        "deadline_next_day_local_time": "00:30",
    }
    assert len(action.execution_config["target_tables"]) == 9
    assert all(table.startswith("core_serving.wealth_sector_") for table in action.execution_config["target_tables"])


def test_daily_schedule_stages_one_task_with_frozen_hashes(db_session, ops_schedule_factory) -> None:
    schedule = _schedule(ops_schedule_factory)
    evaluator = ReadinessStub(
        MaintenanceReadinessResult(
            True,
            SECTOR_ANALYSIS_DAILY_READY,
            "ready",
            {"taskRunId": 42},
            source_hash="a" * 64,
            plan_hash="b" * 64,
            content_hash="c" * 64,
        )
    )

    created = OperationsScheduler(
        readiness_evaluators={SECTOR_ANALYSIS_DAILY_ACTION_KEY: evaluator}
    ).run_once(db_session, now=CHECK_AT)

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.time_input_json == {"mode": "point", "trade_date": TARGET_DATE.isoformat()}
    assert task_run.request_payload_json["readiness"]["sourceHash"] == "a" * 64
    assert task_run.request_payload_json["readiness"]["planHash"] == "b" * 64
    assert task_run.request_payload_json["readiness"]["contentHash"] == "c" * 64


def test_daily_schedule_retries_then_times_out_without_business_execution(db_session, ops_schedule_factory) -> None:
    schedule = _schedule(ops_schedule_factory)
    evaluator = ReadinessStub(
        MaintenanceReadinessResult(
            False,
            SECTOR_ANALYSIS_DAILY_SOURCE_NOT_READY,
            "dc_daily missing",
            {"missing": ["dc_daily"]},
        )
    )
    scheduler = OperationsScheduler(
        readiness_evaluators={SECTOR_ANALYSIS_DAILY_ACTION_KEY: evaluator}
    )

    assert scheduler.run_once(db_session, now=CHECK_AT) == []
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == CHECK_AT + timedelta(seconds=600)
    assert db_session.scalar(select(TaskRun).where(TaskRun.schedule_id == schedule.id)) is None

    deadline = datetime(2026, 8, 31, 16, 30, tzinfo=timezone.utc)
    refreshed.next_run_at = deadline
    db_session.commit()
    [failed] = scheduler.run_once(db_session, now=deadline)
    assert failed.status == "failed"
    assert failed.status_reason_code == SECTOR_ANALYSIS_DAILY_SOURCE_NOT_READY
    issue = db_session.get(TaskRunIssue, failed.primary_issue_id)
    assert issue is not None and issue.code == SECTOR_ANALYSIS_DAILY_SOURCE_NOT_READY


def test_daily_schedule_skips_non_trading_day_without_task(db_session, ops_schedule_factory) -> None:
    schedule = _schedule(ops_schedule_factory)
    evaluator = ReadinessStub(
        MaintenanceReadinessResult(False, SECTOR_ANALYSIS_DAILY_NON_TRADING_DAY, "closed")
    )

    created = OperationsScheduler(
        readiness_evaluators={SECTOR_ANALYSIS_DAILY_ACTION_KEY: evaluator}
    ).run_once(db_session, now=CHECK_AT)

    assert created == []
    assert db_session.scalar(select(TaskRun).where(TaskRun.schedule_id == schedule.id)) is None


def test_upstream_readiness_requires_same_day_success_for_all_four_nodes(
    db_session,
    task_run_factory,
    task_run_node_factory,
) -> None:
    db_session.add(TradeCalendar(exchange="SSE", trade_date=TARGET_DATE, is_open=True))
    db_session.commit()
    run = task_run_factory(
        task_type="workflow",
        resource_key=None,
        title="收盘维护",
        status="success",
        requested_at=CHECK_AT - timedelta(hours=1),
        request_payload_json={"target_key": "daily_market_close_maintenance"},
    )
    for sequence, node_key in enumerate(("daily", "adj_factor", "dc_member", "dc_daily"), start=1):
        task_run_node_factory(
            task_run_id=run.id,
            node_key=node_key,
            sequence_no=sequence,
            status="success",
            time_input_json={"trade_date": TARGET_DATE.isoformat()},
            ended_at=CHECK_AT - timedelta(minutes=1),
        )

    service = SectorAnalysisDailyUpstreamReadinessService()
    ready = service.evaluate(db_session, trade_date=TARGET_DATE, checked_at=CHECK_AT)
    assert ready.ready is True
    assert ready.evidence["requiredNodes"] == ["daily", "adj_factor", "dc_member", "dc_daily"]

    node = db_session.scalar(
        select(TaskRunNode).where(
            TaskRunNode.task_run_id == run.id,
            TaskRunNode.node_key == "adj_factor",
        )
    )
    assert node is not None
    node.time_input_json = {"trade_date": "2026-08-28"}
    db_session.commit()
    blocked = service.evaluate(db_session, trade_date=TARGET_DATE, checked_at=CHECK_AT)
    assert blocked.ready is False


def test_scheduler_factory_injects_both_heat_and_daily_analysis_evaluators(web_engine) -> None:
    from sqlalchemy.orm import sessionmaker

    scheduler = build_operations_scheduler(
        session_factory=sessionmaker(bind=web_engine, autoflush=False, autocommit=False, future=True)
    )

    assert SECTOR_ANALYSIS_DAILY_ACTION_KEY in scheduler.schedule_service.readiness_evaluators
