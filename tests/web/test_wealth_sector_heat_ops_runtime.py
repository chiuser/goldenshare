from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.app.runtime.sector_heat_task_executor import SectorSourceCompletionEvidenceProvider
from src.ops.action_catalog import get_maintenance_action
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher


REPLAY_ACTION = "maintenance.replay_wealth_sector_heat_history"
SINGLE_ACTION = "maintenance.materialize_wealth_sector_heat_daily"


@dataclass
class _HeatExecutorStub:
    planned: MaintenanceExecutionPlan
    fail_unit_key: str | None = None
    plan_calls: list[MaintenanceExecutionRequest] = field(default_factory=list)
    execute_calls: list[MaintenanceExecutionUnit] = field(default_factory=list)

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        self.plan_calls.append(request)
        return self.planned

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        self.execute_calls.append(unit)
        if unit.unit_key == self.fail_unit_key:
            raise RuntimeError(f"failed:{unit.unit_key}")
        return MaintenanceExecutionResult(
            rows_fetched=10,
            rows_saved=8,
            rows_rejected=2,
            rejected_reason_counts={"FEATURE_MISSING": 2},
            summary_message=f"done:{unit.unit_key}",
        )


def _unit(day: str) -> MaintenanceExecutionUnit:
    return MaintenanceExecutionUnit(
        unit_key=f"wealth-sector-heat:{day}",
        payload={
            "trade_date": day,
            "expected_plan_hash": f"plan-{day}",
            "expected_content_hash": f"content-{day}",
            "source_dates": {"target": day},
            "source_row_counts": {"dc_index": 120},
        },
    )


def _plan(*, apply_ready: bool = True) -> MaintenanceExecutionPlan:
    return MaintenanceExecutionPlan(
        plan_hash="frozen-plan-hash",
        units=(_unit("2026-05-20"), _unit("2026-05-21")),
        apply_ready=apply_ready,
        expected_rows=240,
        metadata={
            "start_date": "2026-05-20",
            "end_date": "2026-08-12",
            "gaps": [] if apply_ready else [{"reason_code": "SOURCE_NOT_READY"}],
        },
    )


def test_replay_plan_freezes_snapshot_without_executing_units(db_session, task_run_factory) -> None:
    executor = _HeatExecutorStub(_plan())
    task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        title="回放板块热度历史",
        status="running",
        time_input_json={"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
        filters_json={"execution_mode": "PLAN"},
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": REPLAY_ACTION,
            "time_input": {"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
            "filters": {"execution_mode": "PLAN"},
        },
    )

    outcome = TaskRunDispatcher(maintenance_executors={"wealth_sector_heat": executor}).dispatch(
        db_session, task_run
    )

    assert outcome.status == "success"
    assert len(executor.plan_calls) == 1
    assert executor.execute_calls == []
    assert task_run.plan_snapshot_json["plan_hash"] == "frozen-plan-hash"
    assert task_run.plan_snapshot_json["apply_ready"] is True
    assert task_run.plan_snapshot_json["units"][0]["payload"]["source_dates"] == {
        "target": "2026-05-20"
    }
    assert task_run.unit_total == 1
    assert task_run.unit_done == 1
    node = db_session.scalar(select(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id))
    assert node is not None
    assert node.node_type == "maintenance_plan"
    assert node.status == "success"


def test_replay_apply_executes_only_frozen_units_without_replanning(db_session, task_run_factory) -> None:
    frozen_plan = _plan()
    plan_task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        title="回放板块热度历史",
        status="success",
        time_input_json={"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
        filters_json={"execution_mode": "PLAN"},
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": REPLAY_ACTION,
            "time_input": {"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
            "filters": {"execution_mode": "PLAN"},
        },
    )
    action = get_maintenance_action(REPLAY_ACTION)
    assert action is not None
    plan_task_run.plan_snapshot_json = TaskRunDispatcher._maintenance_plan_snapshot(action=action, plan=frozen_plan)
    db_session.commit()
    executor = _HeatExecutorStub(frozen_plan)
    task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        title="回放板块热度历史",
        status="running",
        time_input_json={"mode": "none"},
        filters_json={
            "execution_mode": "APPLY",
            "plan_task_run_id": plan_task_run.id,
            "plan_hash": frozen_plan.plan_hash,
        },
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": REPLAY_ACTION,
            "time_input": {"mode": "none"},
            "filters": {
                "execution_mode": "APPLY",
                "plan_task_run_id": plan_task_run.id,
                "plan_hash": frozen_plan.plan_hash,
            },
        },
    )

    outcome = TaskRunDispatcher(maintenance_executors={"wealth_sector_heat": executor}).dispatch(
        db_session, task_run
    )

    assert outcome.status == "success"
    assert executor.plan_calls == []
    assert executor.execute_calls == list(frozen_plan.units)
    assert task_run.unit_total == 2
    assert task_run.unit_done == 2
    assert outcome.rows_fetched == 20
    assert outcome.rows_saved == 16
    assert outcome.rows_rejected == 4
    assert outcome.rejected_reason_counts == {"FEATURE_MISSING": 4}
    nodes = db_session.scalars(
        select(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id).order_by(TaskRunNode.sequence_no)
    ).all()
    assert [node.node_key for node in nodes] == [unit.unit_key for unit in frozen_plan.units]


def test_replay_apply_rejects_plan_with_source_gaps_before_business_execution(
    db_session, task_run_factory
) -> None:
    frozen_plan = _plan(apply_ready=False)
    plan_task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        status="success",
        time_input_json={"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
        filters_json={"execution_mode": "PLAN"},
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": REPLAY_ACTION,
            "time_input": {"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
            "filters": {"execution_mode": "PLAN"},
        },
    )
    action = get_maintenance_action(REPLAY_ACTION)
    assert action is not None
    plan_task_run.plan_snapshot_json = TaskRunDispatcher._maintenance_plan_snapshot(
        action=action,
        plan=frozen_plan,
    )
    db_session.commit()
    executor = _HeatExecutorStub(frozen_plan)
    task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        status="running",
        time_input_json={"mode": "none"},
        filters_json={
            "execution_mode": "APPLY",
            "plan_task_run_id": plan_task_run.id,
            "plan_hash": frozen_plan.plan_hash,
        },
        request_payload_json={"target_type": "maintenance_action", "target_key": REPLAY_ACTION},
    )

    outcome = TaskRunDispatcher(maintenance_executors={"wealth_sector_heat": executor}).dispatch(
        db_session, task_run
    )

    assert outcome.status == "failed"
    assert outcome.status_reason_code == "maintenance_executor_failed"
    assert executor.plan_calls == []
    assert executor.execute_calls == []
    issue = db_session.get(TaskRunIssue, outcome.issue_id)
    assert issue is not None
    assert "not apply-ready" in (issue.technical_message or "")


def test_replay_apply_stops_at_first_failed_frozen_unit(db_session, task_run_factory) -> None:
    frozen_plan = _plan()
    action = get_maintenance_action(REPLAY_ACTION)
    assert action is not None
    plan_task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        status="success",
        time_input_json={"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
        filters_json={"execution_mode": "PLAN"},
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": REPLAY_ACTION,
            "time_input": {"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
            "filters": {"execution_mode": "PLAN"},
        },
    )
    plan_task_run.plan_snapshot_json = TaskRunDispatcher._maintenance_plan_snapshot(
        action=action,
        plan=frozen_plan,
    )
    db_session.commit()
    executor = _HeatExecutorStub(frozen_plan, fail_unit_key=frozen_plan.units[0].unit_key)
    task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        status="running",
        time_input_json={"mode": "none"},
        filters_json={
            "execution_mode": "APPLY",
            "plan_task_run_id": plan_task_run.id,
            "plan_hash": frozen_plan.plan_hash,
        },
        request_payload_json={"target_type": "maintenance_action", "target_key": REPLAY_ACTION},
    )

    outcome = TaskRunDispatcher(maintenance_executors={"wealth_sector_heat": executor}).dispatch(
        db_session, task_run
    )

    assert outcome.status == "failed"
    assert executor.execute_calls == [frozen_plan.units[0]]
    assert task_run.unit_done == 0
    assert task_run.unit_failed == 1


def test_replay_apply_rejects_tampered_frozen_unit_before_business_execution(
    db_session, task_run_factory
) -> None:
    frozen_plan = _plan()
    action = get_maintenance_action(REPLAY_ACTION)
    assert action is not None
    plan_task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        status="success",
        time_input_json={"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
        filters_json={"execution_mode": "PLAN"},
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": REPLAY_ACTION,
            "time_input": {"mode": "range", "start_date": "2026-05-20", "end_date": "2026-08-12"},
            "filters": {"execution_mode": "PLAN"},
        },
    )
    snapshot = TaskRunDispatcher._maintenance_plan_snapshot(action=action, plan=frozen_plan)
    snapshot["units"][0]["payload"]["expected_content_hash"] = "tampered"
    plan_task_run.plan_snapshot_json = snapshot
    db_session.commit()
    executor = _HeatExecutorStub(frozen_plan)
    task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        status="running",
        time_input_json={"mode": "none"},
        filters_json={
            "execution_mode": "APPLY",
            "plan_task_run_id": plan_task_run.id,
            "plan_hash": frozen_plan.plan_hash,
        },
        request_payload_json={"target_type": "maintenance_action", "target_key": REPLAY_ACTION},
    )

    outcome = TaskRunDispatcher(maintenance_executors={"wealth_sector_heat": executor}).dispatch(
        db_session, task_run
    )

    assert outcome.status == "failed"
    assert executor.execute_calls == []
    issue = db_session.get(TaskRunIssue, outcome.issue_id)
    assert issue is not None
    assert "integrity check failed" in (issue.technical_message or "")


def test_single_day_heat_uses_one_date_unit_and_missing_executor_fails_closed(
    db_session, task_run_factory
) -> None:
    task_run = task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        status="running",
        time_input_json={"mode": "point", "trade_date": "2026-08-12"},
        request_payload_json={"target_type": "maintenance_action", "target_key": SINGLE_ACTION},
    )

    outcome = TaskRunDispatcher().dispatch(db_session, task_run)

    assert outcome.status == "failed"
    issue = db_session.get(TaskRunIssue, outcome.issue_id)
    assert issue is not None
    assert "wealth_sector_heat" in (issue.technical_message or "")


def test_completion_evidence_provider_reads_only_successful_point_source_task_runs(
    db_session, task_run_factory
) -> None:
    successful = task_run_factory(
        resource_key="limit_list_d",
        status="success",
        time_input_json={"mode": "point", "trade_date": "2026-08-12"},
        ended_at=datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
    )
    task_run_factory(
        resource_key="suspend_d",
        status="failed",
        time_input_json={"mode": "point", "trade_date": "2026-08-12"},
        ended_at=datetime(2026, 8, 12, 10, 1, tzinfo=timezone.utc),
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)

    evidence = SectorSourceCompletionEvidenceProvider(factory).load(
        start_date=date(2026, 8, 12),
        end_date=date(2026, 8, 12),
    )

    assert len(evidence) == 1
    assert evidence[0].dataset_key == "limit_list_d"
    assert evidence[0].trade_date == date(2026, 8, 12)
    assert evidence[0].evidence_id == str(successful.id)
    assert len(evidence[0].evidence_hash) == 64
