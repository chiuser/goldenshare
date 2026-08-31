from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from src.biz.services.wealth.market.sector_analysis.daily_facts import (
    SectorAnalysisDailyFactsMaterializationService,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    SectorAnalysisDailyFactsPlanDriftError,
    canonical_json_hash,
)
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)


DAILY_ACTION_KEY = "maintenance.materialize_wealth_sector_analysis_daily"
REPLAY_ACTION_KEY = "maintenance.replay_wealth_sector_analysis_history"


class SectorAnalysisDailyTaskExecutor:
    def __init__(
        self,
        *,
        session_factory,  # type: ignore[no-untyped-def]
        materialization_service: SectorAnalysisDailyFactsMaterializationService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._service = materialization_service or SectorAnalysisDailyFactsMaterializationService(
            session_factory=session_factory
        )

    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan:
        if request.action_key == REPLAY_ACTION_KEY:
            raise ValueError("板块分析历史回补在M23前不可执行")
        if request.action_key != DAILY_ACTION_KEY:
            raise ValueError(f"unsupported sector-analysis action: {request.action_key}")
        trade_date = self._required_date(request.params, "trade_date")
        with self._session_factory() as session:
            preview = self._service.preview_trade_date(session, trade_date=trade_date)
            session.rollback()
        readiness = request.params.get("readiness")
        if isinstance(readiness, Mapping):
            expected = (
                readiness.get("sourceHash"),
                readiness.get("planHash"),
                readiness.get("contentHash"),
            )
            actual = (preview.source_hash, preview.plan_hash, preview.content_hash)
            if any(value not in (None, "") for value in expected) and tuple(
                None if value in (None, "") else str(value) for value in expected
            ) != actual:
                raise SectorAnalysisDailyFactsPlanDriftError(
                    "scheduler readiness与executor plan不一致"
                )
        unit = MaintenanceExecutionUnit(
            unit_key=f"wealth-sector-analysis-daily:{trade_date.isoformat()}",
            payload={
                "trade_date": trade_date.isoformat(),
                "expected_source_hash": preview.source_hash,
                "expected_plan_hash": preview.plan_hash,
                "expected_content_hash": preview.content_hash,
                "expected_fact_counts": dict(preview.expected_fact_counts),
            },
        )
        return MaintenanceExecutionPlan(
            plan_hash=canonical_json_hash(
                {
                    "actionKey": request.action_key,
                    "unitKey": unit.unit_key,
                    "payload": dict(unit.payload),
                }
            ),
            units=(unit,),
            expected_rows=sum(preview.expected_fact_counts.values()),
            metadata={
                "trade_date": trade_date.isoformat(),
                "hierarchy_version": preview.hierarchy_version,
                "source_hash": preview.source_hash,
                "content_hash": preview.content_hash,
            },
        )

    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult:
        trade_date = self._required_date(unit.payload, "trade_date")
        result = self._service.materialize_trade_date(
            trade_date=trade_date,
            expected_source_hash=self._required_text(unit.payload, "expected_source_hash"),
            expected_plan_hash=self._required_text(unit.payload, "expected_plan_hash"),
            expected_content_hash=self._required_text(unit.payload, "expected_content_hash"),
        )
        return MaintenanceExecutionResult(
            rows_fetched=result.rows_saved,
            rows_saved=result.rows_saved,
            summary_message=(
                f"板块分析每日事实 {trade_date.isoformat()} "
                f"{'幂等跳过' if result.idempotent else '已发布'}：rows={result.rows_saved}"
            ),
            metadata={
                "trade_date": trade_date.isoformat(),
                "batch_id": str(result.batch_id) if result.batch_id else None,
                "plan_hash": result.plan_hash,
                "content_hash": result.content_hash,
                "idempotent": result.idempotent,
            },
        )

    @staticmethod
    def _required_date(values: Mapping[str, Any], key: str) -> date:
        value = values.get(key)
        if isinstance(value, date):
            return value
        if value in (None, ""):
            raise ValueError(f"{key} is required")
        return date.fromisoformat(str(value))

    @staticmethod
    def _required_text(values: Mapping[str, Any], key: str) -> str:
        value = str(values.get(key) or "").strip()
        if not value:
            raise ValueError(f"{key} is required")
        return value
