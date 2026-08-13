from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.sector_overview import ModuleStatusItemDto, PageStatusDto


@dataclass(frozen=True, slots=True)
class SectorOverviewStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto


class SectorOverviewStatusResolver:
    """Fold source freshness and workspace quality into the stable panel states."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        has_display_rows: bool,
        has_error: bool,
        has_partial_data: bool,
        as_of_time: datetime,
        note: str | None = None,
    ) -> SectorOverviewStatusResult:
        lag_days = self._lag_days(expected_trade_date, observed_trade_date)
        if has_error:
            return self._result(
                expected_trade_date,
                observed_trade_date,
                lag_days,
                "ERROR",
                note or "sector overview contract failed",
                "模块查询失败",
                as_of_time,
            )
        if not has_display_rows:
            return self._result(
                expected_trade_date,
                observed_trade_date,
                lag_days,
                "EMPTY",
                note or "sector source bundle is empty",
                "模块数据为空",
                as_of_time,
            )
        if lag_days is not None and lag_days > 0:
            return self._result(
                expected_trade_date,
                observed_trade_date,
                lag_days,
                "DELAYED",
                note or "sector source bundle delayed",
                "部分模块数据延迟",
                as_of_time,
                page_status="PARTIAL",
            )
        if has_partial_data:
            return self._result(
                expected_trade_date,
                observed_trade_date,
                lag_days,
                "PARTIAL",
                note or "sector overview data is partially missing",
                "部分模块数据缺失",
                as_of_time,
            )
        return self._result(
            expected_trade_date,
            observed_trade_date,
            lag_days,
            "READY",
            note or "facts ready",
            "事实聚合已就绪",
            as_of_time,
        )

    @staticmethod
    def _result(
        expected_trade_date: date,
        observed_trade_date: date | None,
        lag_days: int | None,
        status: str,
        note: str,
        display_text: str,
        as_of_time: datetime,
        *,
        page_status: str | None = None,
    ) -> SectorOverviewStatusResult:
        return SectorOverviewStatusResult(
            module_status=ModuleStatusItemDto(
                moduleKey="sectorOverview",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status=status,  # type: ignore[arg-type]
                note=note,
            ),
            page_status=PageStatusDto(
                status=(page_status or status),  # type: ignore[arg-type]
                displayText=display_text,
                asOfTime=as_of_time,
            ),
        )

    @staticmethod
    def _lag_days(expected_trade_date: date, observed_trade_date: date | None) -> int | None:
        if observed_trade_date is None:
            return None
        return max((expected_trade_date - observed_trade_date).days, 0)
