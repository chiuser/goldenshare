from __future__ import annotations

from src.biz.services.wealth.market.sector_analysis.daily_facts import (
    SectorAnalysisDailyFactsMaterializationService,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    SectorAnalysisDailyFactsSourceNotReadyError,
)
from src.ops.runtime.maintenance_readiness import (
    MaintenanceReadinessRequest,
    MaintenanceReadinessResult,
)
from src.ops.runtime.sector_analysis_daily_readiness import (
    SECTOR_ANALYSIS_DAILY_PREVIEW_FAILED,
    SECTOR_ANALYSIS_DAILY_READY,
    SECTOR_ANALYSIS_DAILY_SOURCE_NOT_READY,
)
from src.ops.services.sector_analysis_daily_upstream_readiness_service import (
    SectorAnalysisDailyUpstreamReadinessService,
)


class SectorAnalysisDailyReadinessEvaluator:
    def __init__(
        self,
        *,
        session_factory,  # type: ignore[no-untyped-def]
        upstream_service: SectorAnalysisDailyUpstreamReadinessService | None = None,
        materialization_service: SectorAnalysisDailyFactsMaterializationService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._upstream = upstream_service or SectorAnalysisDailyUpstreamReadinessService()
        self._service = materialization_service or SectorAnalysisDailyFactsMaterializationService(
            session_factory=session_factory
        )

    def evaluate(
        self,
        session,  # type: ignore[no-untyped-def]
        *,
        request: MaintenanceReadinessRequest,
    ) -> MaintenanceReadinessResult:
        upstream = self._upstream.evaluate(
            session,
            trade_date=request.trade_date,
            checked_at=request.checked_at,
        )
        if not upstream.ready:
            return upstream
        try:
            with self._session_factory() as business_session:
                preview = self._service.preview_trade_date(
                    business_session,
                    trade_date=request.trade_date,
                )
                business_session.rollback()
        except SectorAnalysisDailyFactsSourceNotReadyError as exc:
            return MaintenanceReadinessResult(
                False,
                SECTOR_ANALYSIS_DAILY_SOURCE_NOT_READY,
                str(exc),
                dict(upstream.evidence),
            )
        except Exception as exc:
            return MaintenanceReadinessResult(
                False,
                SECTOR_ANALYSIS_DAILY_PREVIEW_FAILED,
                f"板块分析每日事实preview失败：{type(exc).__name__}",
                dict(upstream.evidence),
            )
        return MaintenanceReadinessResult(
            True,
            SECTOR_ANALYSIS_DAILY_READY,
            "板块分析每日事实上游证据和业务预检均通过",
            {
                **dict(upstream.evidence),
                "hierarchyVersion": preview.hierarchy_version,
                "sourceDates": dict(preview.source_dates),
                "sourceRowCounts": dict(preview.source_row_counts),
                "expectedFactCounts": dict(preview.expected_fact_counts),
                "missingCounts": dict(preview.missing_counts),
            },
            source_hash=preview.source_hash,
            plan_hash=preview.plan_hash,
            content_hash=preview.content_hash,
        )
