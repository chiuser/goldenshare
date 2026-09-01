from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from collections.abc import Callable

from sqlalchemy import select

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    SectorAnalysisDailyFactsPlanDriftError,
)
from src.ops.action_catalog import get_maintenance_action
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenancePlanCheckpoint,
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


@dataclass
class _TaskAwareReplayExecutorStub:
    planned: MaintenanceExecutionPlan
    cancel_after_first: Callable[[], None] | None = None
    plan_calls: list[MaintenanceExecutionRequest] = field(default_factory=list)

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        raise AssertionError(f"opaque plan path must not be used: {request.action_key}")

    def plan_for_task_run(self, request, *, context):  # type: ignore[no-untyped-def]
        self.plan_calls.append(request)
        total = len(self.planned.units)
        context.update_phase(
            unit_done=0,
            unit_total=total,
            phase="SCOPE_RESOLVED",
            current_object={"time": {"trade_date": FIRST.isoformat()}},
        )
        for index, unit in enumerate(self.planned.units, start=1):
            context.save_checkpoint(
                MaintenancePlanCheckpoint(
                    unit_done=index,
                    unit_total=total,
                    units=self.planned.units[:index],
                    gaps=(),
                    metadata={
                        **dict(self.planned.metadata),
                        "open_trade_dates": [FIRST.isoformat(), SECOND.isoformat()],
                    },
                    expected_rows=index * 10,
                    phase="CHECKPOINT_SAVED",
                    current_object={"time": {"trade_date": unit.payload["trade_date"]}},
                )
            )
            if index == 1 and self.cancel_after_first is not None:
                self.cancel_after_first()
            if context.is_cancel_requested():
                from src.foundation.ingestion.run_errors import IngestionCanceledError

                raise IngestionCanceledError("cancel after first checkpoint")
        return self.planned

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
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


def _two_day_maintenance_plan() -> MaintenanceExecutionPlan:
    units = tuple(
        MaintenanceExecutionUnit(
            unit_key=f"wealth-sector-analysis-daily:{trade_date.isoformat()}",
            payload={"trade_date": trade_date.isoformat(), "replay_unit": True},
        )
        for trade_date in (FIRST, SECOND)
    )
    return MaintenanceExecutionPlan(
        plan_hash="two-day-frozen-plan",
        units=units,
        apply_ready=True,
        expected_rows=20,
        metadata={
            "start_date": FIRST.isoformat(),
            "end_date": SECOND.isoformat(),
            "open_trade_dates": [FIRST.isoformat(), SECOND.isoformat()],
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


def test_task_aware_replay_plan_checkpoints_then_freezes_at_one_hundred_percent(
    db_session,
    task_run_factory,
) -> None:
    task_run = _plan_task_run(task_run_factory, status="running")
    executor = _TaskAwareReplayExecutorStub(_two_day_maintenance_plan())

    outcome = TaskRunDispatcher(
        maintenance_executors={"wealth_sector_analysis_daily": executor}
    ).dispatch(db_session, task_run)

    db_session.refresh(task_run)
    node = db_session.scalar(select(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id))
    assert outcome.status == "success"
    assert task_run.unit_total == 2
    assert task_run.unit_done == 2
    assert task_run.progress_percent == 100
    assert task_run.plan_snapshot_json["snapshot_state"] == "FROZEN"
    assert node is not None and node.status == "success"


def test_task_aware_replay_cancel_preserves_last_building_checkpoint_and_cancels_node(
    db_session,
    task_run_factory,
) -> None:
    task_run = _plan_task_run(task_run_factory, status="running")

    def request_cancel() -> None:
        task_run.cancel_requested_at = datetime.now(timezone.utc)
        task_run.status = "canceling"
        db_session.commit()

    executor = _TaskAwareReplayExecutorStub(
        _two_day_maintenance_plan(),
        cancel_after_first=request_cancel,
    )
    outcome = TaskRunDispatcher(
        maintenance_executors={"wealth_sector_analysis_daily": executor}
    ).dispatch(db_session, task_run)

    db_session.refresh(task_run)
    node = db_session.scalar(select(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id))
    assert outcome.status == "canceled"
    assert outcome.issue_id is None
    assert task_run.unit_total == 2
    assert task_run.unit_done == 1
    assert task_run.progress_percent == 50
    assert task_run.plan_snapshot_json["snapshot_state"] == "BUILDING"
    assert task_run.plan_snapshot_json["apply_ready"] is False
    assert task_run.plan_snapshot_json["plan_hash"] is None
    assert len(task_run.plan_snapshot_json["units"]) == 1
    assert task_run.plan_snapshot_json["snapshot_integrity_hash"] == TaskRunDispatcher._maintenance_snapshot_hash(
        task_run.plan_snapshot_json
    )
    assert node is not None and node.status == "canceled"


def test_replay_apply_rejects_building_snapshot_even_if_outer_status_is_tampered_to_success(
    db_session,
    task_run_factory,
) -> None:
    action = get_maintenance_action(REPLAY_ACTION)
    assert action is not None
    plan_task_run = _plan_task_run(task_run_factory, status="success")
    snapshot = {
        "schema_version": 1,
        "snapshot_state": "BUILDING",
        "action_key": action.key,
        "executor_key": action.executor_key,
        "plan_hash": None,
        "apply_ready": False,
        "expected_rows": 10,
        "units": [
            {
                "unit_key": f"wealth-sector-analysis-daily:{FIRST.isoformat()}",
                "payload": {"trade_date": FIRST.isoformat(), "replay_unit": True},
            }
        ],
        "metadata": {
            "start_date": FIRST.isoformat(),
            "end_date": SECOND.isoformat(),
            "gaps": [],
        },
    }
    snapshot["snapshot_integrity_hash"] = TaskRunDispatcher._maintenance_snapshot_hash(snapshot)
    plan_task_run.plan_snapshot_json = snapshot
    db_session.commit()
    apply_task_run = _apply_task_run(task_run_factory, plan_task_run_id=plan_task_run.id)
    executor = _ReplayExecutorStub(_maintenance_plan())

    outcome = TaskRunDispatcher(
        maintenance_executors={"wealth_sector_analysis_daily": executor}
    ).dispatch(db_session, apply_task_run)

    assert outcome.status == "failed"
    assert executor.execute_calls == []
