from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, text

from src.biz.services.wealth.market.sector_overview import (
    SectorHeatMaterializationService,
    SectorHeatReplayPlanner,
    SourceCompletionEvidence,
    canonical_json_hash,
)
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)


class SectorSourceCompletionEvidenceProvider:
    """Read successful source TaskRuns in a session separate from business materialization."""

    DATASET_KEYS = ("limit_list_d", "suspend_d")

    def __init__(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        self._session_factory = session_factory

    def load(self, *, start_date: date, end_date: date) -> tuple[SourceCompletionEvidence, ...]:
        start_text = start_date.isoformat()
        end_text = end_date.isoformat()
        with self._session_factory() as session:
            task_rows = tuple(
                session.scalars(
                    select(TaskRun)
                    .where(
                        TaskRun.task_type == "dataset_action",
                        TaskRun.resource_key.in_(self.DATASET_KEYS),
                        TaskRun.status == "success",
                        TaskRun.time_input_json["trade_date"].as_string() >= start_text,
                        TaskRun.time_input_json["trade_date"].as_string() <= end_text,
                    )
                    .order_by(TaskRun.resource_key, TaskRun.id)
                )
            )
            node_rows = tuple(
                session.execute(
                    select(TaskRunNode, TaskRun)
                    .join(TaskRun, TaskRun.id == TaskRunNode.task_run_id)
                    .where(
                        TaskRun.task_type == "workflow",
                        TaskRunNode.resource_key.in_(self.DATASET_KEYS),
                        TaskRunNode.status == "success",
                        TaskRunNode.time_input_json["trade_date"].as_string() >= start_text,
                        TaskRunNode.time_input_json["trade_date"].as_string() <= end_text,
                    )
                    .order_by(TaskRunNode.resource_key, TaskRunNode.id)
                )
            )
        evidence = []
        for row in task_rows:
            raw_trade_date = (row.time_input_json or {}).get("trade_date")
            if not raw_trade_date:
                continue
            trade_date = date.fromisoformat(str(raw_trade_date))
            evidence_hash = canonical_json_hash(
                {
                    "taskRunId": row.id,
                    "datasetKey": row.resource_key,
                    "tradeDate": trade_date.isoformat(),
                    "status": row.status,
                    "endedAt": row.ended_at.isoformat() if row.ended_at else None,
                }
            )
            evidence.append(
                SourceCompletionEvidence(
                    dataset_key=str(row.resource_key),
                    trade_date=trade_date,
                    status="SUCCESS",
                    evidence_type="task_run",
                    evidence_id=str(row.id),
                    evidence_hash=evidence_hash,
                )
            )
        for node, task_run in node_rows:
            raw_trade_date = (node.time_input_json or {}).get("trade_date")
            if not raw_trade_date or not node.resource_key:
                continue
            trade_date = date.fromisoformat(str(raw_trade_date))
            evidence_hash = canonical_json_hash(
                {
                    "taskRunId": task_run.id,
                    "nodeId": node.id,
                    "datasetKey": node.resource_key,
                    "tradeDate": trade_date.isoformat(),
                    "status": node.status,
                    "endedAt": node.ended_at.isoformat() if node.ended_at else None,
                }
            )
            evidence.append(
                SourceCompletionEvidence(
                    dataset_key=str(node.resource_key),
                    trade_date=trade_date,
                    status="SUCCESS",
                    evidence_type="task_run_node",
                    evidence_id=f"{task_run.id}:{node.id}",
                    evidence_hash=evidence_hash,
                )
            )
        return tuple(evidence)


class SectorHeatTaskExecutor:
    def __init__(
        self,
        *,
        session_factory,  # type: ignore[no-untyped-def]
        evidence_provider: SectorSourceCompletionEvidenceProvider | None = None,
        materialization_service: SectorHeatMaterializationService | None = None,
        replay_planner: SectorHeatReplayPlanner | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._evidence_provider = evidence_provider or SectorSourceCompletionEvidenceProvider(session_factory)
        self._materialization_service = materialization_service or SectorHeatMaterializationService()
        self._replay_planner = replay_planner or SectorHeatReplayPlanner(self._materialization_service)

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        if request.action_key != "maintenance.replay_wealth_sector_heat_history":
            raise ValueError(f"unsupported Heat plan action: {request.action_key}")
        start_date = self._required_date(request.params, "start_date")
        end_date = self._required_date(request.params, "end_date")
        evidence = self._evidence_provider.load(start_date=start_date - timedelta(days=60), end_date=end_date)
        with self._session_factory() as business_session:
            self._start_business_transaction(business_session, read_only=True)
            plan = self._replay_planner.plan(
                business_session,
                start_date=start_date,
                end_date=end_date,
                completion_evidence=evidence,
            )
        units = tuple(
            MaintenanceExecutionUnit(
                unit_key=f"wealth-sector-heat:{unit.trade_date.isoformat()}",
                payload={
                    "trade_date": unit.trade_date.isoformat(),
                    "expected_plan_hash": unit.plan_hash,
                    "expected_content_hash": unit.content_hash,
                    "config_version": unit.config_version,
                    "score_version": unit.score_version,
                    "config_hash": unit.config_hash,
                    "source_hash": unit.source_hash,
                    "expected_rows": unit.expected_rows,
                    "expected_valid_count": unit.expected_valid_count,
                    "expected_invalid_count": unit.expected_invalid_count,
                    "source_dates": dict(unit.source_dates),
                    "source_row_counts": dict(unit.source_row_counts),
                },
            )
            for unit in plan.units
        )
        return MaintenanceExecutionPlan(
            plan_hash=plan.plan_hash,
            units=units,
            apply_ready=plan.apply_ready,
            expected_rows=plan.expected_rows,
            metadata={
                "start_date": plan.start_date.isoformat(),
                "end_date": plan.end_date.isoformat(),
                "open_trade_dates": [item.isoformat() for item in plan.open_trade_dates],
                "gaps": [
                    {
                        "trade_date": gap.trade_date.isoformat(),
                        "reason_code": gap.reason_code,
                        "message": gap.message,
                    }
                    for gap in plan.gaps
                ],
            },
        )

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        trade_date = self._required_date(unit.payload, "trade_date")
        evidence = self._evidence_provider.load(
            start_date=trade_date - timedelta(days=60),
            end_date=trade_date,
        )
        with self._session_factory() as business_session:
            self._start_business_transaction(business_session, read_only=False)
            result = self._materialization_service.materialize_trade_date(
                business_session,
                trade_date=trade_date,
                expected_plan_hash=self._optional_text(unit.payload.get("expected_plan_hash")),
                expected_content_hash=self._optional_text(unit.payload.get("expected_content_hash")),
                completion_evidence=evidence,
            )
        action_text = "已核验并跳过" if result.skipped_existing else "已发布"
        return MaintenanceExecutionResult(
            rows_fetched=result.rows_fetched,
            rows_saved=result.rows_written,
            rows_rejected=result.invalid_count,
            rejected_reason_counts=result.invalid_reason_counts,
            summary_message=(
                f"Heat {trade_date.isoformat()} {action_text}：rows={result.rows_written} "
                f"valid={result.valid_count} invalid={result.invalid_count} elapsed_ms={result.elapsed_ms}"
            ),
            metadata={
                "trade_date": trade_date.isoformat(),
                "config_hash": result.config_hash,
                "source_hash": result.source_hash,
                "plan_hash": result.plan_hash,
                "content_hash": result.content_hash,
                "skipped_existing": result.skipped_existing,
            },
        )

    @staticmethod
    def _required_date(values: Any, key: str) -> date:
        raw_value = values.get(key) if hasattr(values, "get") else None
        if isinstance(raw_value, date):
            return raw_value
        if raw_value in (None, ""):
            raise ValueError(f"{key} is required")
        return date.fromisoformat(str(raw_value))

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        text = str(value).strip() if value not in (None, "") else ""
        return text or None

    @staticmethod
    def _start_business_transaction(session, *, read_only: bool) -> None:  # type: ignore[no-untyped-def]
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        statement = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
        if read_only:
            statement += ", READ ONLY"
        session.execute(text(statement))
