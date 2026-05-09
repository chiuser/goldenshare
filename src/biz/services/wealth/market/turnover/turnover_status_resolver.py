from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.turnover import ModuleStatusItemDto, PageStatusDto


EXPECTED_1M_POINTS = 22
EXPECTED_3M_POINTS = 62


@dataclass(frozen=True, slots=True)
class TurnoverStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto
    intraday_missing: bool


class TurnoverStatusResolver:
    """Resolve module/page status from source dates and payload completeness."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        has_core_metrics: bool,
        history_points_1m: int,
        history_points_3m: int,
        has_intraday_points: bool,
        as_of_time: datetime,
    ) -> TurnoverStatusResult:
        if observed_trade_date is None:
            module_status = ModuleStatusItemDto(
                moduleKey="turnover",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=None,
                lagDays=None,
                status="EMPTY",
                note="turnover source is empty",
            )
            return TurnoverStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                intraday_missing=not has_intraday_points,
            )

        lag_days = (expected_trade_date - observed_trade_date).days
        if lag_days > 0:
            module_status = ModuleStatusItemDto(
                moduleKey="turnover",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="turnover source date lagged",
            )
            return TurnoverStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time),
                intraday_missing=not has_intraday_points,
            )

        if not has_core_metrics and history_points_1m == 0 and history_points_3m == 0:
            module_status = ModuleStatusItemDto(
                moduleKey="turnover",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="EMPTY",
                note="turnover has no usable values",
            )
            return TurnoverStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                intraday_missing=not has_intraday_points,
            )

        history_incomplete = history_points_1m < EXPECTED_1M_POINTS or history_points_3m < EXPECTED_3M_POINTS
        intraday_missing = not has_intraday_points
        if history_incomplete or intraday_missing:
            module_status = ModuleStatusItemDto(
                moduleKey="turnover",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="PARTIAL",
                note="turnover data is partially missing",
            )
            return TurnoverStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据缺失", asOfTime=as_of_time),
                intraday_missing=intraday_missing,
            )

        module_status = ModuleStatusItemDto(
            moduleKey="turnover",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=0,
            status="READY",
            note="facts ready",
        )
        return TurnoverStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
            intraday_missing=False,
        )
