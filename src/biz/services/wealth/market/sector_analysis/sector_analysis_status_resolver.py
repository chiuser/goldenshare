from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.biz.services.wealth.market.sector_analysis.sector_analysis_exception_builder import (
    SectorAnalysisExceptionBuilder,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorTradingDateResolution,
)


SectorAnalysisStatus = Literal["READY", "DELAYED", "EMPTY", "ERROR"]


@dataclass(frozen=True, slots=True)
class SectorAnalysisStatusResolution:
    status: SectorAnalysisStatus
    display_text: str
    message: str | None
    exception_code: str | None


class SectorAnalysisStatusResolver:
    def __init__(self) -> None:
        self._exceptions = SectorAnalysisExceptionBuilder()

    def resolve(
        self,
        *,
        trading_day: SectorTradingDateResolution,
        calculable_count: int,
    ) -> SectorAnalysisStatusResolution:
        if trading_day.observed is None or calculable_count <= 0:
            return self.empty()
        if trading_day.observed.trade_date < trading_day.expected.trade_date:
            exception = self._exceptions.build("SA_SOURCE_DELAYED")
            return SectorAnalysisStatusResolution(
                status="DELAYED",
                display_text=(
                    f"当前展示 {trading_day.observed.trade_date.isoformat()} 盘后数据"
                ),
                message=exception.message,
                exception_code=exception.code,
            )
        return SectorAnalysisStatusResolution(
            status="READY",
            display_text=f"{trading_day.observed.trade_date.isoformat()} 盘后数据",
            message=None,
            exception_code=None,
        )

    def empty(self) -> SectorAnalysisStatusResolution:
        exception = self._exceptions.build("SA_SOURCE_EMPTY")
        return SectorAnalysisStatusResolution(
            status="EMPTY",
            display_text="暂无数据",
            message=exception.message,
            exception_code=exception.code,
        )

    def error(
        self,
        code: Literal["SA_HIERARCHY_UNAVAILABLE", "SA_QUERY_FAILED"],
    ) -> SectorAnalysisStatusResolution:
        exception = self._exceptions.build(code)
        return SectorAnalysisStatusResolution(
            status="ERROR",
            display_text="数据读取失败",
            message=exception.message,
            exception_code=exception.code,
        )
