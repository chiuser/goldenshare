from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_readiness import MaintenanceReadinessResult
from src.ops.runtime.sector_analysis_daily_readiness import (
    SECTOR_ANALYSIS_DAILY_NON_TRADING_DAY,
    SECTOR_ANALYSIS_DAILY_READY,
    SECTOR_ANALYSIS_DAILY_UPSTREAM_NOT_READY,
)


class SectorAnalysisDailyUpstreamReadinessService:
    WORKFLOW_KEY = "daily_market_close_maintenance"
    REQUIRED_NODES = ("daily", "adj_factor", "dc_member", "dc_daily")

    def evaluate(
        self,
        session: Session,
        *,
        trade_date: date,
        checked_at: datetime,
    ) -> MaintenanceReadinessResult:
        if not bool(
            session.scalar(
                select(TradeCalendar.is_open).where(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.trade_date == trade_date,
                )
            )
        ):
            return MaintenanceReadinessResult(
                False,
                SECTOR_ANALYSIS_DAILY_NON_TRADING_DAY,
                f"{trade_date.isoformat()} 不是SSE开放日",
                {"tradeDate": trade_date.isoformat(), "exchange": "SSE", "isOpen": False},
            )
        checked_utc = self._aware_utc(checked_at)
        candidates = tuple(
            session.scalars(
                select(TaskRun)
                .where(
                    TaskRun.task_type == "workflow",
                    TaskRun.request_payload_json["target_key"].as_string() == self.WORKFLOW_KEY,
                    TaskRun.requested_at <= checked_utc,
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
                        TaskRunNode.node_key.in_(self.REQUIRED_NODES),
                    )
                    .order_by(TaskRunNode.sequence_no, TaskRunNode.id)
                )
            )
            by_key = {node.node_key: node for node in nodes}
            if any(
                by_key.get(key) is None
                or by_key[key].status != "success"
                or by_key[key].ended_at is None
                or self._aware_utc(by_key[key].ended_at) > checked_utc
                or self._node_trade_date(by_key[key]) != trade_date
                for key in self.REQUIRED_NODES
            ):
                continue
            return MaintenanceReadinessResult(
                True,
                SECTOR_ANALYSIS_DAILY_READY,
                "板块分析每日事实上游工作流证据已齐备",
                {
                    "tradeDate": trade_date.isoformat(),
                    "checkedAt": checked_utc.isoformat(),
                    "workflowKey": self.WORKFLOW_KEY,
                    "taskRunId": task_run.id,
                    "requiredNodes": list(self.REQUIRED_NODES),
                    "nodeEndedAt": {
                        key: self._aware_utc(by_key[key].ended_at).isoformat()
                        for key in self.REQUIRED_NODES
                    },
                },
            )
        return MaintenanceReadinessResult(
            False,
            SECTOR_ANALYSIS_DAILY_UPSTREAM_NOT_READY,
            f"{trade_date.isoformat()} 缺少同日必需节点成功证据",
            {
                "tradeDate": trade_date.isoformat(),
                "workflowKey": self.WORKFLOW_KEY,
                "requiredNodes": list(self.REQUIRED_NODES),
            },
        )

    @staticmethod
    def _node_trade_date(node: TaskRunNode) -> date | None:
        raw = dict(node.time_input_json or {}).get("trade_date")
        try:
            return date.fromisoformat(str(raw)) if raw not in (None, "") else None
        except ValueError:
            return None

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
