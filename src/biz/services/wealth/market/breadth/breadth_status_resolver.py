from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.breadth import ModuleStatusItemDto, PageStatusDto


EXPECTED_1M_POINTS = 22
EXPECTED_3M_POINTS = 62


@dataclass(frozen=True, slots=True)
class BreadthStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto
    history_incomplete: bool


class BreadthStatusResolver:
    """Resolve module/page status from source date and history completeness."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        metric_total_count: int,
        history_points_1m: int,
        history_points_3m: int,
        as_of_time: datetime,
    ) -> BreadthStatusResult:
        if observed_trade_date is None:
            module_status = ModuleStatusItemDto(
                moduleKey="breadth",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=None,
                lagDays=None,
                status="EMPTY",
                note="breadth source is empty",
            )
            return BreadthStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                history_incomplete=False,
            )

        lag_days = (expected_trade_date - observed_trade_date).days
        if lag_days > 0:
            module_status = ModuleStatusItemDto(
                moduleKey="breadth",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="breadth source date lagged",
            )
            return BreadthStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time),
                history_incomplete=False,
            )

        if metric_total_count == 0:
            module_status = ModuleStatusItemDto(
                moduleKey="breadth",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="EMPTY",
                note="target date has no breadth rows",
            )
            return BreadthStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                history_incomplete=False,
            )

        history_incomplete = history_points_1m < EXPECTED_1M_POINTS or history_points_3m < EXPECTED_3M_POINTS
        if history_incomplete:
            module_status = ModuleStatusItemDto(
                moduleKey="breadth",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="PARTIAL",
                note="history points incomplete",
            )
            return BreadthStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据缺失", asOfTime=as_of_time),
                history_incomplete=True,
            )

        module_status = ModuleStatusItemDto(
            moduleKey="breadth",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=0,
            status="READY",
            note="facts ready",
        )
        return BreadthStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
            history_incomplete=False,
        )
