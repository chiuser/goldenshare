from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.major_indices import ModuleStatusItemDto, PageStatusDto


@dataclass(frozen=True, slots=True)
class MajorIndicesStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto


class MajorIndicesStatusResolver:
    """Resolve module/page status from expected/observed and row completeness."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        row_count: int,
        expected_count: int,
        as_of_time: datetime,
    ) -> MajorIndicesStatusResult:
        if observed_trade_date is None:
            module_status = ModuleStatusItemDto(
                moduleKey="majorIndices",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=None,
                lagDays=None,
                status="EMPTY",
                note="index source is empty",
            )
            return MajorIndicesStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
            )

        lag_days = (expected_trade_date - observed_trade_date).days
        if lag_days > 0:
            module_status = ModuleStatusItemDto(
                moduleKey="majorIndices",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="index source date lagged",
            )
            return MajorIndicesStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time),
            )

        if row_count < expected_count:
            module_status = ModuleStatusItemDto(
                moduleKey="majorIndices",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="PARTIAL",
                note="some configured indices are missing",
            )
            return MajorIndicesStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分指数数据缺失", asOfTime=as_of_time),
            )

        module_status = ModuleStatusItemDto(
            moduleKey="majorIndices",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=0,
            status="READY",
            note="facts ready",
        )
        return MajorIndicesStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
        )

