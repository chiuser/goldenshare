from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable

from sqlalchemy import select

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
)
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher


FIRST = date(2025, 8, 22)
SECOND = date(2025, 8, 25)
REPLAY_ACTION = "maintenance.replay_wealth_sector_analysis_history"


def _unit(trade_date: date, index: int, total: int) -> MaintenanceExecutionUnit:
    return MaintenanceExecutionUnit(
        unit_key=f"wealth-sector-analysis-daily:{trade_date.isoformat()}",
        payload={
            "replay_unit": True,
            "trade_date": trade_date.isoformat(),
            "audit_contract_version": HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
            "audit_hash": "a" * 64,
            "expected_hierarchy_version": "hierarchy-v1",
            "expected_formula_bundle_version": "sector-analysis-daily-facts@1",
            "expected_template_version": "sector-daily-insight-template@2",
            "unit_index": index,
            "unit_total": total,
        },
    )


def _audit_plan(*, apply_ready: bool = True) -> MaintenanceExecutionPlan:
    units = (_unit(FIRST, 1, 2), _unit(SECOND, 2, 2))
    return MaintenanceExecutionPlan(
        plan_hash="a" * 64,
        units=units,
        apply_ready=apply_ready,
        expected_rows=0,
        metadata={
            "audit_contract_version": HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
            "audit_state": "AUDIT_PASSED" if apply_ready else "BLOCKED",
            "requested_start_date": FIRST.isoformat(),
            "requested_end_date": SECOND.isoformat(),
            "effective_start_date": FIRST.isoformat(),
            "effective_end_date": SECOND.isoformat(),
            "warmup_start_date": "2025-05-30",
            "ordered_trade_dates": [FIRST.isoformat(), SECOND.isoformat()],
            "trade_dates_hash": "b" * 64,
            "hierarchy_version": "hierarchy-v1",
            "formula_bundle_version": "sector-analysis-daily-facts@1",
            "template_version": "sector-daily-insight-template@2",
            "target_tables": ["core_serving.wealth_sector_analysis_publish_batch"],
            "source_coverage_summary": {"dc_daily": {"row_count": 100}},
            "audit_issues": (
                []
                if apply_ready
                else [
                    {
                        "code": "SA_DAILY_FACT_SOURCE_NOT_READY",
                        "blocking": True,
                    }
                ]
            ),
        },
    )


@dataclass
class _AuditThenApplyExecutorStub:
    planned: MaintenanceExecutionPlan
    after_execute: Callable[[int], None] | None = None
    audit_calls: list[MaintenanceExecutionRequest] = field(default_factory=list)
    execute_calls: list[MaintenanceExecutionUnit] = field(default_factory=list)

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        raise AssertionError(f"full PLAN must not run: {request.action_key}")

    def audit_for_task_run(self, request, *, context):  # type: ignore[no-untyped-def]
        self.audit_calls.append(request)
        context.update_audit_phase(
            audit_done=0,
            audit_total=6,
            phase="AUDITING_INPUT",
            current_object={"entity": {"type": "source", "value": "trade_calendar"}},
        )
        context.update_audit_phase(
            audit_done=6,
            audit_total=6,
            phase="AUDITING_INPUT",
            current_object={"entity": {"type": "source", "value": "equity_adj_factor"}},
        )
        return self.planned

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        self.execute_calls.append(unit)
        if self.after_execute:
            self.after_execute(len(self.execute_calls))
        return MaintenanceExecutionResult(
            rows_fetched=10,
            rows_saved=10,
            metadata={"phase": "READBACK_COMPLETE"},
        )


def _task_run(task_run_factory, *, filters=None):  # type: ignore[no-untyped-def]
    return task_run_factory(
        task_type="maintenance_action",
        status="running",
        time_input_json={
            "mode": "range",
            "start_date": FIRST.isoformat(),
            "end_date": SECOND.isoformat(),
        },
        filters_json=dict(filters or {}),
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": REPLAY_ACTION,
            "time_input": {
                "mode": "range",
                "start_date": FIRST.isoformat(),
                "end_date": SECOND.isoformat(),
            },
            "filters": dict(filters or {}),
        },
    )


def test_history_audit_and_apply_share_one_task_run_and_schema_v2_snapshot(
    db_session,
    task_run_factory,
) -> None:
    executor = _AuditThenApplyExecutorStub(_audit_plan())
    task_run = _task_run(task_run_factory)

    outcome = TaskRunDispatcher(
        maintenance_executors={"wealth_sector_analysis_daily": executor}
    ).dispatch(db_session, task_run)

    db_session.refresh(task_run)
    nodes = tuple(
        db_session.scalars(
            select(TaskRunNode)
            .where(TaskRunNode.task_run_id == task_run.id)
            .order_by(TaskRunNode.sequence_no)
        )
    )
    assert outcome.status == "success"
    assert len(executor.audit_calls) == 1
    assert executor.execute_calls == list(_audit_plan().units)
    assert task_run.unit_total == 2
    assert task_run.unit_done == 2
    assert task_run.progress_percent == 100
    assert task_run.plan_snapshot_json["schema_version"] == 2
    assert task_run.plan_snapshot_json["snapshot_state"] == "AUDIT_PASSED"
    assert task_run.plan_snapshot_json["audit_hash"] == "a" * 64
    assert task_run.plan_snapshot_json["snapshot_integrity_hash"] == (
        TaskRunDispatcher._maintenance_snapshot_hash(task_run.plan_snapshot_json)
    )
    assert [node.node_type for node in nodes] == [
        "maintenance_plan",
        "maintenance_unit",
        "maintenance_unit",
    ]
    assert all(node.status == "success" for node in nodes)


def test_blocked_history_audit_writes_snapshot_and_executes_zero_units(
    db_session,
    task_run_factory,
) -> None:
    executor = _AuditThenApplyExecutorStub(_audit_plan(apply_ready=False))
    task_run = _task_run(task_run_factory)

    outcome = TaskRunDispatcher(
        maintenance_executors={"wealth_sector_analysis_daily": executor}
    ).dispatch(db_session, task_run)

    db_session.refresh(task_run)
    assert outcome.status == "failed"
    assert executor.execute_calls == []
    assert task_run.plan_snapshot_json["schema_version"] == 2
    assert task_run.plan_snapshot_json["snapshot_state"] == "BLOCKED"
    assert outcome.status_reason_code == "SA_DAILY_FACT_SOURCE_NOT_READY"
    issue = db_session.get(TaskRunIssue, outcome.issue_id)
    assert issue is not None
    assert issue.code == "SA_DAILY_FACT_SOURCE_NOT_READY"


def test_history_action_rejects_legacy_plan_apply_request_before_audit(
    db_session,
    task_run_factory,
) -> None:
    executor = _AuditThenApplyExecutorStub(_audit_plan())
    task_run = _task_run(task_run_factory, filters={"execution_mode": "PLAN"})

    outcome = TaskRunDispatcher(
        maintenance_executors={"wealth_sector_analysis_daily": executor}
    ).dispatch(db_session, task_run)

    assert outcome.status == "failed"
    assert executor.audit_calls == []
    assert executor.execute_calls == []


def test_cancel_after_committed_date_stops_before_next_date(
    db_session,
    task_run_factory,
) -> None:
    task_run = _task_run(task_run_factory)

    def cancel_after_first(index: int) -> None:
        if index == 1:
            task_run.cancel_requested_at = datetime.now(timezone.utc)
            task_run.status = "canceling"
            db_session.commit()

    executor = _AuditThenApplyExecutorStub(
        _audit_plan(),
        after_execute=cancel_after_first,
    )
    outcome = TaskRunDispatcher(
        maintenance_executors={"wealth_sector_analysis_daily": executor}
    ).dispatch(db_session, task_run)

    db_session.refresh(task_run)
    assert outcome.status == "canceled"
    assert len(executor.execute_calls) == 1
    assert task_run.unit_done == 1
    assert task_run.unit_total == 2
