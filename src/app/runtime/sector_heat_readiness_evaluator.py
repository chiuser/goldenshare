from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from src.app.runtime.sector_heat_task_executor import SectorSourceCompletionEvidenceProvider
from src.biz.services.wealth.market.sector_overview import (
    SectorHeatMaterializationService,
    SectorHeatSourceNotReadyError,
)
from src.ops.runtime.sector_heat_readiness import (
    HEAT_PREVIEW_FAILED,
    HEAT_READY,
    HEAT_SOURCE_NOT_READY,
    HeatReadinessRequest,
    HeatReadinessResult,
)
from src.ops.services.sector_heat_upstream_readiness_service import SectorHeatUpstreamReadinessService


class SectorHeatReadinessEvaluator:
    """App composition adapter: combine Ops evidence with a read-only Biz preview."""

    def __init__(
        self,
        *,
        session_factory,  # type: ignore[no-untyped-def]
        upstream_service: SectorHeatUpstreamReadinessService,
        materialization_service: SectorHeatMaterializationService | None = None,
        evidence_provider: SectorSourceCompletionEvidenceProvider | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._upstream_service = upstream_service
        self._materialization_service = materialization_service or SectorHeatMaterializationService()
        self._evidence_provider = evidence_provider or SectorSourceCompletionEvidenceProvider(session_factory)

    def evaluate(self, session, *, request: HeatReadinessRequest) -> HeatReadinessResult:  # type: ignore[no-untyped-def]
        upstream = self._upstream_service.evaluate(
            session,
            trade_date=request.trade_date,
            checked_at=request.checked_at,
        )
        if not upstream.ready:
            return upstream

        completion_evidence = self._evidence_provider.load(
            start_date=request.trade_date - timedelta(days=60),
            end_date=request.trade_date,
        )
        try:
            with self._session_factory() as business_session:
                self._start_read_only_transaction(business_session)
                preview = self._materialization_service.preview_trade_date(
                    business_session,
                    trade_date=request.trade_date,
                    completion_evidence=completion_evidence,
                )
                business_session.rollback()
        except SectorHeatSourceNotReadyError as exc:
            return HeatReadinessResult(
                ready=False,
                reason_code=HEAT_SOURCE_NOT_READY,
                message=str(exc),
                evidence=dict(upstream.evidence),
            )
        except Exception as exc:
            return HeatReadinessResult(
                ready=False,
                reason_code=HEAT_PREVIEW_FAILED,
                message=f"Heat biz preview failed: {type(exc).__name__}",
                evidence=dict(upstream.evidence),
            )

        return HeatReadinessResult(
            ready=True,
            reason_code=HEAT_READY,
            message="Heat 上游证据和业务预检均通过",
            evidence={
                **dict(upstream.evidence),
                "sourceDates": dict(preview.source_dates),
                "sourceRowCounts": dict(preview.source_row_counts),
                "rows": preview.rows_written,
                "validCount": preview.valid_count,
                "invalidCount": preview.invalid_count,
                "invalidReasonCounts": dict(preview.invalid_reason_counts),
                "scoreVersion": preview.score_version,
            },
            config_version=preview.config_version,
            config_hash=preview.config_hash,
            source_hash=preview.source_hash,
            plan_hash=preview.plan_hash,
            content_hash=preview.content_hash,
        )

    @staticmethod
    def _start_read_only_transaction(session) -> None:  # type: ignore[no-untyped-def]
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
