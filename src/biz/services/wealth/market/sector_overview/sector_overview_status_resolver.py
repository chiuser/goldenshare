from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.sector_overview import ModuleStatusItemDto, PageStatusDto


@dataclass(frozen=True, slots=True)
class SectorOverviewStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto


class SectorOverviewStatusResolver:
    """Resolve sector-overview module/page status from source freshness and payload completeness."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        has_display_rows: bool,
        all_sources_available: bool,
        column_count: int,
        min_column_row_count: int,
        heatmap_count: int,
        as_of_time: datetime,
    ) -> SectorOverviewStatusResult:
        if not has_display_rows:
            module_status = ModuleStatusItemDto(
                moduleKey="sectorOverview",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=self._lag_days(expected_trade_date, observed_trade_date),
                status="EMPTY",
                note="sector source bundle is empty",
            )
            return SectorOverviewStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
            )

        lag_days = self._lag_days(expected_trade_date, observed_trade_date)
        if lag_days is not None and lag_days > 0:
            module_status = ModuleStatusItemDto(
                moduleKey="sectorOverview",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="dc source bundle delayed",
            )
            return SectorOverviewStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time),
            )

        if not all_sources_available or column_count < 8 or min_column_row_count < 5 or heatmap_count < 20:
            module_status = ModuleStatusItemDto(
                moduleKey="sectorOverview",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="PARTIAL",
                note="sector overview data is partially missing",
            )
            return SectorOverviewStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据缺失", asOfTime=as_of_time),
            )

        module_status = ModuleStatusItemDto(
            moduleKey="sectorOverview",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=lag_days,
            status="READY",
            note="facts ready",
        )
        return SectorOverviewStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
        )

    @staticmethod
    def _lag_days(expected_trade_date: date, observed_trade_date: date | None) -> int | None:
        if observed_trade_date is None:
            return None
        return max((expected_trade_date - observed_trade_date).days, 0)
