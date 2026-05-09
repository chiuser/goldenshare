from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.queries.wealth.market.summary.summary_state_query import SummarySourceState
from src.biz.schemas.wealth.market.summary import ModuleStatusItemDto, PageStatusDto


@dataclass(frozen=True, slots=True)
class SummaryStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto
    missing_sources: tuple[str, ...]


class SummaryStatusResolver:
    """Resolve module/page status from source observed dates."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        source_state: SummarySourceState,
        as_of_time: datetime,
    ) -> SummaryStatusResult:
        source_map = {
            "equity_daily_bar": source_state.equity_daily_bar_date,
            "market_moneyflow_dc": source_state.market_moneyflow_date,
            "limit_list_ths": source_state.limit_list_ths_date,
            "index_daily_serving": source_state.index_daily_date,
        }
        missing_sources = tuple(key for key, observed in source_map.items() if observed is None)
        observed_trade_date = source_state.observed_trade_date

        if observed_trade_date is None:
            module_status = ModuleStatusItemDto(
                moduleKey="marketSummary",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=None,
                lagDays=None,
                status="EMPTY",
                note="all key sources are empty",
            )
            return SummaryStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                missing_sources=missing_sources,
            )

        lag_days = (expected_trade_date - observed_trade_date).days
        if lag_days > 0:
            module_status = ModuleStatusItemDto(
                moduleKey="marketSummary",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="key source date lagged",
            )
            return SummaryStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time),
                missing_sources=missing_sources,
            )

        if missing_sources:
            module_status = ModuleStatusItemDto(
                moduleKey="marketSummary",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="PARTIAL",
                note="some key source dates are missing",
            )
            return SummaryStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据缺失", asOfTime=as_of_time),
                missing_sources=missing_sources,
            )

        module_status = ModuleStatusItemDto(
            moduleKey="marketSummary",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=0,
            status="READY",
            note="facts ready",
        )
        return SummaryStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
            missing_sources=missing_sources,
        )
