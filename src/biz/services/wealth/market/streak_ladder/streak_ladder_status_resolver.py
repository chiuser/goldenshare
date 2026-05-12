from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.biz.schemas.wealth.market.streak_ladder import ModuleStatusItemDto, PageStatusDto


@dataclass(frozen=True, slots=True)
class StreakLadderStatusResult:
    module_status: ModuleStatusItemDto
    page_status: PageStatusDto
    has_invalid_board_count: bool
    has_metric_missing: bool


class StreakLadderStatusResolver:
    """Resolve module/page status for streak ladder payload."""

    def resolve(
        self,
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        today_row_count: int,
        has_invalid_board_count: bool,
        has_metric_missing: bool,
        as_of_time: datetime,
    ) -> StreakLadderStatusResult:
        if observed_trade_date is None:
            module_status = ModuleStatusItemDto(
                moduleKey="streakLadder",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=None,
                lagDays=None,
                status="EMPTY",
                note="streak ladder source is empty",
            )
            return StreakLadderStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                has_invalid_board_count=False,
                has_metric_missing=False,
            )

        lag_days = (expected_trade_date - observed_trade_date).days
        if lag_days > 0:
            module_status = ModuleStatusItemDto(
                moduleKey="streakLadder",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=lag_days,
                status="DELAYED",
                note="streak ladder source date lagged",
            )
            return StreakLadderStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据延迟", asOfTime=as_of_time),
                has_invalid_board_count=False,
                has_metric_missing=False,
            )

        if today_row_count == 0:
            module_status = ModuleStatusItemDto(
                moduleKey="streakLadder",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="EMPTY",
                note="target trade date has no limit-up rows",
            )
            return StreakLadderStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="EMPTY", displayText="模块数据为空", asOfTime=as_of_time),
                has_invalid_board_count=False,
                has_metric_missing=False,
            )

        if has_invalid_board_count or has_metric_missing:
            note_parts: list[str] = []
            if has_invalid_board_count:
                note_parts.append("invalid board count")
            if has_metric_missing:
                note_parts.append("join metric missing")
            module_status = ModuleStatusItemDto(
                moduleKey="streakLadder",
                expectedTradeDate=expected_trade_date,
                observedTradeDate=observed_trade_date,
                lagDays=0,
                status="PARTIAL",
                note="; ".join(note_parts),
            )
            return StreakLadderStatusResult(
                module_status=module_status,
                page_status=PageStatusDto(status="PARTIAL", displayText="部分模块数据缺失", asOfTime=as_of_time),
                has_invalid_board_count=has_invalid_board_count,
                has_metric_missing=has_metric_missing,
            )

        module_status = ModuleStatusItemDto(
            moduleKey="streakLadder",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=0,
            status="READY",
            note="facts ready",
        )
        return StreakLadderStatusResult(
            module_status=module_status,
            page_status=PageStatusDto(status="READY", displayText="事实聚合已就绪", asOfTime=as_of_time),
            has_invalid_board_count=False,
            has_metric_missing=False,
        )
