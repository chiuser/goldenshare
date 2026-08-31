from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    SectorAnalysisDailyFactsPlanDriftError,
)
from src.ops.action_catalog import get_maintenance_action
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher


FIRST = date(2025, 1, 2)
SECOND = date(2025, 1, 3)
REPLAY_ACTION = "maintenance.replay_wealth_sector_analysis_history"


@dataclass
class _ReplayExecutorStub:
    planned: MaintenanceExecutionPlan
    fail_with_drift: bool = False
    plan_calls: list[MaintenanceExecutionRequest] = field(default_factory=list)
    execute_calls: list[MaintenanceExecutionUnit] = field(default_factory=list)

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        self.plan_calls.append(request)
        return self.planned

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        self.execute_calls.append(unit)
        if self.fail_with_drift:
            raise SectorAnalysisDailyFactsPlanDriftError("frozen source changed")
        return MaintenanceExecutionResult(rows_fetched=10, rows_saved=10)


def _maintenance_plan() -> MaintenanceExecutionPlan:
    return MaintenanceExecutionPlan(
        plan_hash="frozen-analysis-plan",
        units=(
            MaintenanceExecutionUnit(
                unit_key=f"wealth-sector-analysis-daily:{FIRST.isoformat()}",
                payload={"trade_date": FIRST.isoformat(), "replay_unit": True},
            ),
        ),
        apply_ready=True,
        expected_rows=10,
        metadata={
            "start_date": FIRST.isoformat(),
            "end_date": SECOND.isoformat(),
            "gaps": [],
        },
    )


def _plan_task_run(task_run_factory, *, status: str):  # type: ignore[no-untyped-def]
    return task_run_factory(
        task_type="maintenance_action",
        status=status,
        time_input_json={
            "mode": "range",
            "start_date": FIRST.isoformat(),
            "end_date": SECOND.isoformat(),
        },
        filters_json={"execution_mode": "PLAN"},
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": REPLAY_ACTION,
            "time_input": {
                "mode": "range",
                "start_date": FIRST.isoformat(),
                "end_date": SECOND.isoformat(),
            },
            "filters": {"execution_mode": "PLAN"},
        },
    )


def _apply_task_run(task_run_factory, *, plan_task_run_id: int):  # type: ignore[no-untyped-def]
    return task_run_factory(
        task_type="maintenance_action",
        status="running",
        time_input_json={"mode": "none"},
        filters_json={
            "execution_mode": "APPLY",
            "plan_task_run_id": plan_task_run_id,
            "plan_hash": "frozen-analysis-plan",
        },
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": REPLAY_ACTION,
            "time_input": {"mode": "none"},
            "filters": {
                "execution_mode": "APPLY",
                "plan_task_run_id": plan_task_run_id,
                "plan_hash": "frozen-analysis-plan",
            },
        },
    )


def test_analysis_replay_plan_and_apply_use_the_shared_frozen_snapshot_contract(
    db_session,
    task_run_factory,
) -> None:
    executor = _ReplayExecutorStub(_maintenance_plan())
    plan_task_run = _plan_task_run(task_run_factory, status="running")
    dispatcher = TaskRunDispatcher(
        maintenance_executors={"wealth_sector_analysis_daily": executor}
    )

    plan_outcome = dispatcher.dispatch(db_session, plan_task_run)

    assert plan_outcome.status == "success"
    assert len(executor.plan_calls) == 1
    assert executor.execute_calls == []
    assert plan_task_run.plan_snapshot_json["plan_hash"] == "frozen-analysis-plan"
    plan_task_run.status = "success"
    db_session.commit()

    apply_task_run = _apply_task_run(
        task_run_factory,
        plan_task_run_id=plan_task_run.id,
    )
    apply_outcome = dispatcher.dispatch(db_session, apply_task_run)

    assert apply_outcome.status == "success"
    assert len(executor.plan_calls) == 1
    assert executor.execute_calls == list(_maintenance_plan().units)


def test_analysis_replay_surfaces_plan_drift_code_without_later_execution(
    db_session,
    task_run_factory,
) -> None:
    frozen_plan = _maintenance_plan()
    action = get_maintenance_action(REPLAY_ACTION)
    assert action is not None
    plan_task_run = _plan_task_run(task_run_factory, status="success")
    plan_task_run.plan_snapshot_json = TaskRunDispatcher._maintenance_plan_snapshot(
        action=action,
        plan=frozen_plan,
    )
    db_session.commit()
    apply_task_run = _apply_task_run(
        task_run_factory,
        plan_task_run_id=plan_task_run.id,
    )
    executor = _ReplayExecutorStub(frozen_plan, fail_with_drift=True)

    outcome = TaskRunDispatcher(
        maintenance_executors={"wealth_sector_analysis_daily": executor}
    ).dispatch(db_session, apply_task_run)

    assert outcome.status == "failed"
    assert outcome.status_reason_code == "SA_DAILY_FACT_PLAN_DRIFT"
    issue = db_session.get(TaskRunIssue, outcome.issue_id)
    assert issue is not None
    assert issue.code == "SA_DAILY_FACT_PLAN_DRIFT"
