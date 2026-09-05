from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyQuery,
    SectorHierarchySnapshot,
)
from src.foundation.models.core.trade_calendar import TradeCalendar

from .source_query import ensure_repeatable_read_only_transaction


MIN_PUBLISH_DATE = date(2025, 8, 22)


@dataclass(frozen=True, slots=True)
class SectorAnalysisReplayScope:
    requested_start_date: date
    requested_end_date: date
    start_date: date
    end_date: date
    open_trade_dates: tuple[date, ...]
    hierarchy: SectorHierarchySnapshot

    @property
    def hierarchy_version(self) -> str:
        return self.hierarchy.baseline_version


class SectorAnalysisReplayPlanner:
    """Resolve only the immutable replay scope; formula preview is deliberately forbidden."""

    def __init__(self, hierarchy_query: SectorHierarchyQuery | None = None) -> None:
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()

    def resolve_scope(
        self,
        session: Session,
        *,
        start_date: date,
        end_date: date,
    ) -> SectorAnalysisReplayScope:
        if start_date > end_date:
            raise ValueError("start_date must not be later than end_date")
        ensure_repeatable_read_only_transaction(session)
        requested_floor = max(start_date, MIN_PUBLISH_DATE)
        open_trade_dates = tuple(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date >= requested_floor,
                    TradeCalendar.trade_date <= end_date,
                )
                .order_by(TradeCalendar.trade_date)
            )
        )
        if not open_trade_dates:
            raise ValueError("sector-analysis history audit has no SSE open trade dates")
        hierarchy = self._hierarchy_query.load(session)
        return SectorAnalysisReplayScope(
            requested_start_date=start_date,
            requested_end_date=end_date,
            start_date=open_trade_dates[0],
            end_date=open_trade_dates[-1],
            open_trade_dates=open_trade_dates,
            hierarchy=hierarchy,
        )
