from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.streak_ladder import (
    ModuleStatusItemDto,
    PageStatusDto,
    StreakLadderDebugInfoDto,
    StreakLadderResponseDto,
    TradingDayDto,
)
from src.biz.services.wealth.market.streak_ladder.streak_ladder_builder import StreakLadderBuilder
from src.biz.services.wealth.market.streak_ladder.streak_ladder_exception_builder import StreakLadderExceptionBuilder
from src.biz.services.wealth.market.streak_ladder.streak_ladder_status_resolver import StreakLadderStatusResolver
from .streak_ladder_query import StreakLadderQuery, StreakLadderRowsResult
from .streak_ladder_state_query import StreakLadderSourceState, StreakLadderStateQuery, StreakLadderTradingDayContext


class StreakLadderQueryService:
    """Orchestrate streak ladder response assembly."""

    def __init__(self) -> None:
        self._state_query = StreakLadderStateQuery()
        self._query = StreakLadderQuery()
        self._builder = StreakLadderBuilder()
        self._status_resolver = StreakLadderStatusResolver()
        self._exception_builder = StreakLadderExceptionBuilder()

    def build_streak_ladder(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> StreakLadderResponseDto:
        exceptions = []
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        source_state = self._state_query.load_source_state(session)

        try:
            today_result = self._query.load_rows(session, trade_date=trading_day_context.expected_trade_date)
            prev_result = self._query.load_rows(session, trade_date=trading_day_context.prev_trade_date)
            build_result = self._builder.build(
                trade_date=trading_day_context.expected_trade_date,
                prev_trade_date=trading_day_context.prev_trade_date,
                today_rows=today_result.rows,
                prev_rows=prev_result.rows,
            )
        except Exception as exc:  # noqa: BLE001
            exceptions.append(self._exception_builder.query_failed(message=f"streak ladder query failed: {exc}"))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                debug=debug,
                exceptions=exceptions,
            )

        has_invalid_board_count = today_result.invalid_board_count > 0 or prev_result.invalid_board_count > 0
        status_result = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=source_state.observed_trade_date,
            today_row_count=len(today_result.rows),
            has_invalid_board_count=has_invalid_board_count,
            has_metric_missing=build_result.has_metric_missing,
            as_of_time=trading_day_context.as_of_time,
        )

        if status_result.module_status.status == "DELAYED" and source_state.observed_trade_date is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="streak ladder source date lagged",
                    expected_trade_date=trading_day_context.expected_trade_date.isoformat(),
                    observed_trade_date=source_state.observed_trade_date.isoformat(),
                )
            )
        if status_result.module_status.status == "EMPTY":
            exceptions.append(self._exception_builder.source_empty(message="streak ladder source has no usable rows"))
        if has_invalid_board_count:
            sample = self._first_invalid_sample(today_result=today_result, prev_result=prev_result)
            exceptions.append(
                self._exception_builder.invalid_board_count(
                    message="board count parse failed for some rows",
                    sample_ts_code=sample[0],
                    raw_value=sample[1],
                )
            )
        if build_result.has_metric_missing:
            exceptions.append(
                self._exception_builder.join_metric_missing(
                    message="price/change metric missing on some rows",
                    sample_ts_code=build_result.metric_missing_sample,
                )
            )

        return StreakLadderResponseDto(
            tradingDay=self._build_trading_day(trading_day_context=trading_day_context),
            pageStatus=status_result.page_status,
            streakLadderV5=build_result.payload,
            debugInfo=(
                StreakLadderDebugInfoDto(
                    modules=[status_result.module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    @staticmethod
    def _build_trading_day(*, trading_day_context: StreakLadderTradingDayContext) -> TradingDayDto:
        return TradingDayDto(
            tradeDate=trading_day_context.expected_trade_date,
            prevTradeDate=trading_day_context.prev_trade_date,
            market="CN_A",
            isTradingDay=trading_day_context.is_trading_day,
            sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
            timezone="Asia/Shanghai",
        )

    def _build_error_response(
        self,
        *,
        trading_day_context: StreakLadderTradingDayContext,
        debug: bool,
        exceptions: list,
    ) -> StreakLadderResponseDto:
        empty_payload = self._builder.build(
            trade_date=trading_day_context.expected_trade_date,
            prev_trade_date=trading_day_context.prev_trade_date,
            today_rows=[],
            prev_rows=[],
        ).payload
        module_status = ModuleStatusItemDto(
            moduleKey="streakLadder",
            expectedTradeDate=trading_day_context.expected_trade_date,
            observedTradeDate=None,
            lagDays=None,
            status="ERROR",
            note="module failed to load",
        )
        return StreakLadderResponseDto(
            tradingDay=self._build_trading_day(trading_day_context=trading_day_context),
            pageStatus=PageStatusDto(status="ERROR", displayText="模块加载失败", asOfTime=trading_day_context.as_of_time),
            streakLadderV5=empty_payload,
            debugInfo=(
                StreakLadderDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    @staticmethod
    def _first_invalid_sample(
        *,
        today_result: StreakLadderRowsResult,
        prev_result: StreakLadderRowsResult,
    ) -> tuple[str | None, str | None]:
        if today_result.invalid_sample_ts_code is not None or today_result.invalid_sample_raw_value is not None:
            return (today_result.invalid_sample_ts_code, today_result.invalid_sample_raw_value)
        return (prev_result.invalid_sample_ts_code, prev_result.invalid_sample_raw_value)
