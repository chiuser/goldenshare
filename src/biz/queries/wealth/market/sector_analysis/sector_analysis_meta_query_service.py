from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyQuery,
    SectorHierarchySnapshot,
)
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_meta_query import (
    SectorAnalysisMetaQuery,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDateAvailabilityFact,
)


@dataclass(frozen=True, slots=True)
class SectorAnalysisMetaFacts:
    context: MarketPageContext
    hierarchy: SectorHierarchySnapshot
    coverage_start_date: date
    coverage_end_date: date
    trade_dates: tuple[SectorDateAvailabilityFact, ...]


class SectorAnalysisMetaQueryService:
    """Load page-neutral sector-analysis metadata in exactly three queries."""

    def __init__(
        self,
        *,
        context_query: MarketPageContextQuery | None = None,
        hierarchy_query: SectorHierarchyQuery | None = None,
        meta_query: SectorAnalysisMetaQuery | None = None,
    ) -> None:
        self._context_query = context_query or MarketPageContextQuery()
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()
        self._meta_query = meta_query or SectorAnalysisMetaQuery()

    def load(self, session: Session, *, market: str) -> SectorAnalysisMetaFacts:
        context = self._context_query.resolve_context(
            session,
            market=market,
            requested_trade_date=None,
        )
        hierarchy = self._hierarchy_query.load(session)
        coverage_start, coverage = self._meta_query.load_coverage(
            session,
            coverage_end_date=context.trade_date,
            sector_codes=tuple(node.sector_code for node in hierarchy.nodes),
        )
        return SectorAnalysisMetaFacts(
            context=context,
            hierarchy=hierarchy,
            coverage_start_date=coverage_start,
            coverage_end_date=context.trade_date,
            trade_dates=coverage,
        )
