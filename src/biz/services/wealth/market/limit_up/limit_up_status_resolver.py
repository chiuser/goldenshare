from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.limit_up import ModuleStatusItemDto, PageStatusDto


EXPECTED_1M_POINTS = 22
EXPECTED_3M_POINTS = 62


@dataclass(frozen=True, slots=True)
class LimitUpStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto
    history_incomplete: bool
    structure_incomplete: bool


class LimitUpStatusResolver:
    """Resolve module/page status from source date and payload completeness."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        has_summary_data: bool,
        history_points_1m: int,
        history_points_3m: int,
        has_today_structure: bool,
        has_yesterday_structure: bool,
        as_of_time: datetime,
    ) -> LimitUpStatusResult:
        if observed_trade_date is None:
            module_status = ModuleStatusItemDto(
                moduleKey="limitUp",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=None,
                lagDays=None,
                status="EMPTY",
                note="limit-up source is empty",
            )
            return LimitUpStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                history_incomplete=False,
                structure_incomplete=False,
            )

        lag_days = (expected_trade_date - observed_trade_date).days
        if lag_days > 0:
            module_status = ModuleStatusItemDto(
                moduleKey="limitUp",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="limit-up source date lagged",
            )
            return LimitUpStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time),
                history_incomplete=False,
                structure_incomplete=False,
            )

        if not has_summary_data:
            module_status = ModuleStatusItemDto(
                moduleKey="limitUp",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="EMPTY",
                note="target date has no summary rows",
            )
            return LimitUpStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                history_incomplete=False,
                structure_incomplete=False,
            )

        history_incomplete = history_points_1m < EXPECTED_1M_POINTS or history_points_3m < EXPECTED_3M_POINTS
        structure_incomplete = not has_today_structure or not has_yesterday_structure
        if history_incomplete or structure_incomplete:
            note_parts = []
            if structure_incomplete:
                note_parts.append("distribution structure incomplete")
            if history_incomplete:
                note_parts.append("history points incomplete")
            module_status = ModuleStatusItemDto(
                moduleKey="limitUp",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="PARTIAL",
                note="; ".join(note_parts),
            )
            return LimitUpStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据缺失", asOfTime=as_of_time),
                history_incomplete=history_incomplete,
                structure_incomplete=structure_incomplete,
            )

        module_status = ModuleStatusItemDto(
            moduleKey="limitUp",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=0,
            status="READY",
            note="facts ready",
        )
        return LimitUpStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
            history_incomplete=False,
            structure_incomplete=False,
        )
