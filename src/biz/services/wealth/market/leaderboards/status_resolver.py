from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.leaderboards import ModuleStatusItemDto, PageStatusDto


@dataclass(frozen=True, slots=True)
class LeaderboardBoardStatusResult:
    status: str
    expected_trade_date: date
    observed_trade_date: date | None
    lag_days: int | None
    note: str


class LeaderboardStatusResolver:
    """Resolve board-level status and page-level aggregate status."""

    def resolve_board_status(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        row_count: int,
        delayed_as_empty: bool,
    ) -> LeaderboardBoardStatusResult:
        if observed_trade_date is None:
            return LeaderboardBoardStatusResult(
                status="EMPTY",
                expected_trade_date=expected_trade_date,
                observed_trade_date=None,
                lag_days=None,
                note="source empty",
            )

        lag_days = (expected_trade_date - observed_trade_date).days
        if lag_days > 0:
            if row_count == 0 and delayed_as_empty:
                return LeaderboardBoardStatusResult(
                    status="DELAYED",
                    expected_trade_date=expected_trade_date,
                    observed_trade_date=observed_trade_date,
                    lag_days=lag_days,
                    note="source delayed with empty rows",
                )
            return LeaderboardBoardStatusResult(
                status="DELAYED",
                expected_trade_date=expected_trade_date,
                observed_trade_date=observed_trade_date,
                lag_days=lag_days,
                note="source delayed",
            )

        if row_count == 0:
            return LeaderboardBoardStatusResult(
                status="EMPTY",
                expected_trade_date=expected_trade_date,
                observed_trade_date=observed_trade_date,
                lag_days=0,
                note="rows empty",
            )

        return LeaderboardBoardStatusResult(
            status="READY",
            expected_trade_date=expected_trade_date,
            observed_trade_date=observed_trade_date,
            lag_days=0,
            note="facts ready",
        )

    def resolve_page_status(
        self,
        *,
        board_statuses: list[str],
        as_of_time: datetime,
    ) -> PageStatusDto:
        if not board_statuses:
            return PageStatusDto(status="ERROR", displayText="模块加载失败", asOfTime=as_of_time)

        unique = set(board_statuses)
        if len(unique) == 1:
            only = board_statuses[0]
            if only == "READY":
                return PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time)
            if only == "DELAYED":
                return PageStatusDto(status="DELAYED", displayText="模块数据延迟", asOfTime=as_of_time)
            if only == "EMPTY":
                return PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time)
            if only == "ERROR":
                return PageStatusDto(status="ERROR", displayText="模块加载失败", asOfTime=as_of_time)

        return PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time)

    @staticmethod
    def build_module_status(
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        status: str,
        note: str,
    ) -> ModuleStatusItemDto:
        lag_days = None
        if observed_trade_date is not None:
            lag_days = (expected_trade_date - observed_trade_date).days
            if lag_days < 0:
                lag_days = 0
        return ModuleStatusItemDto(
            moduleKey="leaderboards",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=lag_days,
            status=status,  # type: ignore[arg-type]
            note=note,
        )

