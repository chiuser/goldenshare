from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.style import ModuleStatusItemDto, PageStatusDto


@dataclass(frozen=True, slots=True)
class MarketStyleStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto


class MarketStyleStatusResolver:
    """Resolve module/page status from source dates and payload completeness."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        has_current_values: bool,
        has_history_values: bool,
        as_of_time: datetime,
    ) -> MarketStyleStatusResult:
        if observed_trade_date is None:
            module_status = ModuleStatusItemDto(
                moduleKey="marketStyle",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=None,
                lagDays=None,
                status="EMPTY",
                note="style source is empty",
            )
            return MarketStyleStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
            )

        lag_days = (expected_trade_date - observed_trade_date).days
        if lag_days > 0:
            module_status = ModuleStatusItemDto(
                moduleKey="marketStyle",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="style source date lagged",
            )
            return MarketStyleStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time),
            )

        if not has_current_values and not has_history_values:
            module_status = ModuleStatusItemDto(
                moduleKey="marketStyle",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="EMPTY",
                note="style module has no usable values",
            )
            return MarketStyleStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
            )

        if not has_current_values or not has_history_values:
            module_status = ModuleStatusItemDto(
                moduleKey="marketStyle",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="PARTIAL",
                note="style data is partially missing",
            )
            return MarketStyleStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据缺失", asOfTime=as_of_time),
            )

        module_status = ModuleStatusItemDto(
            moduleKey="marketStyle",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=0,
            status="READY",
            note="facts ready",
        )
        return MarketStyleStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
        )
