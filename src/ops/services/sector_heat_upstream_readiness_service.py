from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.heat_readiness import (
    HEAT_NON_TRADING_DAY,
    HEAT_READY,
    HEAT_UPSTREAM_NOT_READY,
    HeatReadinessResult,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class _WorkflowRequirement:
    workflow_key: str
    node_keys: tuple[str, ...]


class SectorHeatUpstreamReadinessService:
    REQUIREMENTS = (
        _WorkflowRequirement(
            workflow_key="daily_market_close_maintenance",
            node_keys=("daily", "dc_index", "dc_member", "dc_daily", "limit_list", "suspend_d"),
        ),
        _WorkflowRequirement(
            workflow_key="daily_moneyflow_maintenance",
            node_keys=("moneyflow_ind_dc",),
        ),
    )

    def __init__(self, *, workflow_not_before_local_times: Mapping[str, time]) -> None:
        expected_workflows = {requirement.workflow_key for requirement in self.REQUIREMENTS}
        configured_workflows = set(workflow_not_before_local_times)
        if configured_workflows != expected_workflows:
            raise ValueError(
                "Heat upstream timing contract mismatch: "
                f"expected={sorted(expected_workflows)}, configured={sorted(configured_workflows)}"
            )
        self._workflow_not_before_local_times = {
            workflow_key: workflow_not_before_local_times[workflow_key]
            for workflow_key in expected_workflows
        }

    def evaluate(self, session: Session, *, trade_date: date, checked_at: datetime) -> HeatReadinessResult:
        if not bool(
            session.scalar(
                select(TradeCalendar.is_open).where(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.trade_date == trade_date,
                )
            )
        ):
            return HeatReadinessResult(
                ready=False,
                reason_code=HEAT_NON_TRADING_DAY,
                message=f"{trade_date.isoformat()} 不是 SSE 开放日",
                evidence={"tradeDate": trade_date.isoformat(), "exchange": "SSE", "isOpen": False},
            )

        evidence: dict[str, Any] = {
            "tradeDate": trade_date.isoformat(),
            "checkedAt": self._aware_utc(checked_at).isoformat(),
            "workflows": [],
        }
        for requirement in self.REQUIREMENTS:
            workflow_evidence = self._latest_qualifying_workflow(
                session,
                trade_date=trade_date,
                checked_at=checked_at,
                requirement=requirement,
            )
            if workflow_evidence is None:
                not_before = self._workflow_not_before_local_times[requirement.workflow_key]
                return HeatReadinessResult(
                    ready=False,
                    reason_code=HEAT_UPSTREAM_NOT_READY,
                    message=(
                        f"{requirement.workflow_key} 缺少 "
                        f"{not_before.strftime('%H:%M')} 后同日必需节点成功证据"
                    ),
                    evidence={
                        **evidence,
                        "missingWorkflow": requirement.workflow_key,
                        "requiredNodes": list(requirement.node_keys),
                    },
                )
            evidence["workflows"].append(workflow_evidence)

        return HeatReadinessResult(
            ready=True,
            reason_code=HEAT_READY,
            message="Heat 上游工作流证据已齐备",
            evidence=evidence,
        )

    def _latest_qualifying_workflow(
        self,
        session: Session,
        *,
        trade_date: date,
        checked_at: datetime,
        requirement: _WorkflowRequirement,
    ) -> dict[str, Any] | None:
        local_not_before = datetime.combine(
            trade_date,
            self._workflow_not_before_local_times[requirement.workflow_key],
            tzinfo=SHANGHAI,
        )
        not_before_utc = local_not_before.astimezone(timezone.utc)
        candidates = tuple(
            session.scalars(
                select(TaskRun)
                .where(
                    TaskRun.task_type == "workflow",
                    TaskRun.requested_at >= not_before_utc,
                    TaskRun.requested_at <= self._aware_utc(checked_at),
                    TaskRun.request_payload_json["target_key"].as_string() == requirement.workflow_key,
                )
                .order_by(TaskRun.requested_at.desc(), TaskRun.id.desc())
            )
        )
        for task_run in candidates:
            nodes = tuple(
                session.scalars(
                    select(TaskRunNode)
                    .where(
                        TaskRunNode.task_run_id == task_run.id,
                        TaskRunNode.node_key.in_(requirement.node_keys),
                    )
                    .order_by(TaskRunNode.sequence_no, TaskRunNode.id)
                )
            )
            by_key = {node.node_key: node for node in nodes}
            if any(
                by_key.get(node_key) is None
                or by_key[node_key].status != "success"
                or by_key[node_key].ended_at is None
                or self._aware_utc(by_key[node_key].ended_at) > self._aware_utc(checked_at)
                or self._node_trade_date(by_key[node_key]) != trade_date
                for node_key in requirement.node_keys
            ):
                continue
            return {
                "workflowKey": requirement.workflow_key,
                "taskRunId": task_run.id,
                "taskStatus": task_run.status,
                "requestedAt": self._aware_utc(task_run.requested_at).isoformat(),
                "endedAt": self._aware_utc(task_run.ended_at).isoformat() if task_run.ended_at else None,
                "nodes": [
                    {
                        "nodeKey": node_key,
                        "status": by_key[node_key].status,
                        "tradeDate": trade_date.isoformat(),
                        "endedAt": self._aware_utc(by_key[node_key].ended_at).isoformat()
                        if by_key[node_key].ended_at
                        else None,
                    }
                    for node_key in requirement.node_keys
                ],
            }
        return None

    @staticmethod
    def _node_trade_date(node: TaskRunNode) -> date | None:
        raw_value = dict(node.time_input_json or {}).get("trade_date")
        if raw_value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(raw_value))
        except ValueError:
            return None

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
