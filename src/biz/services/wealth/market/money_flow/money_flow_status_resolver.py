from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.money_flow import ModuleStatusItemDto, PageStatusDto


EXPECTED_1M_POINTS = 22
EXPECTED_3M_POINTS = 62


@dataclass(frozen=True, slots=True)
class MoneyFlowStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto
    history_incomplete: bool


class MoneyFlowStatusResolver:
    """Resolve money-flow module/page status from source freshness and payload completeness."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        has_core_metrics: bool,
        order_size_complete: bool,
        history_points_1m: int,
        history_points_3m: int,
        as_of_time: datetime,
    ) -> MoneyFlowStatusResult:
        history_incomplete = history_points_1m < EXPECTED_1M_POINTS or history_points_3m < EXPECTED_3M_POINTS

        if observed_trade_date is None:
            module_status = ModuleStatusItemDto(
                moduleKey="moneyFlow",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=None,
                lagDays=None,
                status="EMPTY",
                note="money-flow source is empty",
            )
            return MoneyFlowStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                history_incomplete=history_incomplete,
            )

        lag_days = (expected_trade_date - observed_trade_date).days
        if lag_days > 0:
            module_status = ModuleStatusItemDto(
                moduleKey="moneyFlow",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="money-flow source date lagged",
            )
            return MoneyFlowStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time),
                history_incomplete=history_incomplete,
            )

        if not has_core_metrics and history_points_1m == 0 and history_points_3m == 0:
            module_status = ModuleStatusItemDto(
                moduleKey="moneyFlow",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=max(lag_days, 0),
                status="EMPTY",
                note="money-flow has no usable values",
            )
            return MoneyFlowStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                history_incomplete=history_incomplete,
            )

        if history_incomplete or not order_size_complete:
            module_status = ModuleStatusItemDto(
                moduleKey="moneyFlow",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=max(lag_days, 0),
                status="PARTIAL",
                note="money-flow data is partially missing",
            )
            return MoneyFlowStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据缺失", asOfTime=as_of_time),
                history_incomplete=history_incomplete,
            )

        module_status = ModuleStatusItemDto(
            moduleKey="moneyFlow",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=max(lag_days, 0),
            status="READY",
            note="facts ready",
        )
        return MoneyFlowStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
            history_incomplete=False,
        )
