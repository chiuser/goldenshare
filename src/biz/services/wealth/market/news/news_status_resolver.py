from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.biz.schemas.wealth.market.news_briefs import ModuleStatusItemDto, PageStatusDto


@dataclass(frozen=True, slots=True)
class MarketNewsStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto


class MarketNewsStatusResolver:
    """Resolve status for a single market news panel response."""

    def resolve(
        self,
        *,
        module_key: str,
        window_start_at: datetime,
        window_end_at: datetime,
        observed_at: datetime | None,
        row_count: int,
        as_of_time: datetime,
    ) -> MarketNewsStatusResult:
        expected_trade_date = window_end_at.date()
        if observed_at is None:
            module_status = ModuleStatusItemDto(
                moduleKey=module_key,
                expectedTradeDate=expected_trade_date,
                observedTradeDate=None,
                lagDays=None,
                status="EMPTY",
                note="news source is empty",
            )
            return MarketNewsStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
            )

        observed_trade_date = observed_at.date()
        lag_days = (expected_trade_date - observed_trade_date).days
        if row_count == 0 and observed_trade_date < window_start_at.date():
            module_status = ModuleStatusItemDto(
                moduleKey=module_key,
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="news source date lagged",
            )
            return MarketNewsStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="DELAYED", displayText="模块数据延迟", asOfTime=as_of_time),
            )

        if row_count == 0:
            module_status = ModuleStatusItemDto(
                moduleKey=module_key,
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=max(lag_days, 0),
                status="EMPTY",
                note="target date has no displayable news",
            )
            return MarketNewsStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
            )

        module_status = ModuleStatusItemDto(
            moduleKey=module_key,
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=0,
            status="READY",
            note="facts ready",
        )
        return MarketNewsStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
        )
