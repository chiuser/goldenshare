from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.turnover import (
    ModuleStatusItemDto,
    PageStatusDto,
    TradingDayDto,
    TurnoverDebugInfoDto,
    TurnoverHistoryPointDto,
    TurnoverIntradayPointDto,
    TurnoverMetricsDto,
    TurnoverPayloadDto,
    TurnoverResponseDto,
)
from src.biz.services.wealth.market.turnover.turnover_exception_builder import TurnoverExceptionBuilder
from src.biz.services.wealth.market.turnover.turnover_status_resolver import (
    EXPECTED_1M_POINTS,
    EXPECTED_3M_POINTS,
    TurnoverStatusResolver,
)
from .turnover_query import TurnoverQuery
from .turnover_state_query import TurnoverSourceState, TurnoverStateQuery, TurnoverTradingDayContext


class MarketTurnoverQueryService:
    """Orchestrate turnover module response assembly."""

    def __init__(self) -> None:
        self._state_query = TurnoverStateQuery()
        self._query = TurnoverQuery()
        self._status_resolver = TurnoverStatusResolver()
        self._exception_builder = TurnoverExceptionBuilder()

    def build_turnover(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> TurnoverResponseDto:
        exceptions = []
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        source_state = self._state_query.load_source_state(session)

        try:
            metrics = self._query.load_metrics(
                session,
                trade_date=trading_day_context.expected_trade_date,
                prev_trade_date=trading_day_context.prev_trade_date,
            )
            recent_3m_trade_dates = self._query.load_recent_trade_dates(
                session,
                end_trade_date=trading_day_context.expected_trade_date,
                limit_days=EXPECTED_3M_POINTS,
            )
            history_3m = self._query.load_history_points(session, trade_dates=recent_3m_trade_dates)
            one_month_trade_dates = set(recent_3m_trade_dates[-EXPECTED_1M_POINTS:])
            history_1m = [point for point in history_3m if point.trade_date in one_month_trade_dates]
            intraday = self._query.load_intraday_cumulative(
                session,
                trade_date=trading_day_context.expected_trade_date,
            )
        except Exception as exc:  # noqa: BLE001
            exceptions.append(self._exception_builder.query_failed(message=f"turnover query failed: {exc}"))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=source_state,
                debug=debug,
                exceptions=exceptions,
            )

        history_1m_effective_points = sum(1 for point in history_1m if point.amount is not None)
        history_3m_effective_points = sum(1 for point in history_3m if point.amount is not None)
        status_result = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=source_state.observed_trade_date,
            has_core_metrics=metrics.has_any_value,
            history_points_1m=history_1m_effective_points,
            history_points_3m=history_3m_effective_points,
            has_intraday_points=intraday.has_points,
            as_of_time=trading_day_context.as_of_time,
        )

        if status_result.module_status.status == "DELAYED" and source_state.observed_trade_date is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="turnover source date lagged",
                    expected_trade_date=trading_day_context.expected_trade_date.isoformat(),
                    observed_trade_date=source_state.observed_trade_date.isoformat(),
                )
            )
        if status_result.module_status.status == "EMPTY":
            exceptions.append(
                self._exception_builder.source_empty(
                    message="turnover source has no usable rows",
                )
            )
        if status_result.intraday_missing and status_result.module_status.status != "EMPTY":
            exceptions.append(
                self._exception_builder.intraday_missing(
                    message="intraday cumulative source is empty",
                    trade_date=trading_day_context.expected_trade_date.isoformat(),
                )
            )

        return TurnoverResponseDto(
            tradingDay=TradingDayDto(
                tradeDate=trading_day_context.expected_trade_date,
                prevTradeDate=trading_day_context.prev_trade_date,
                market="CN_A",
                isTradingDay=trading_day_context.is_trading_day,
                sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
                timezone="Asia/Shanghai",
            ),
            pageStatus=status_result.page_status,
            turnover=TurnoverPayloadDto(
                tradeDate=trading_day_context.expected_trade_date,
                metrics=TurnoverMetricsDto(
                    todayAmount=metrics.today_amount,
                    prevAmount=metrics.prev_amount,
                    amountDelta=metrics.amount_delta,
                    amountDeltaPct=metrics.amount_delta_pct,
                    avg5dAmount=metrics.avg5d_amount,
                    avg20dAmount=metrics.avg20d_amount,
                    unit="thousand_yuan",
                ),
                intradayCumulative=[
                    TurnoverIntradayPointDto(time=point.time, cumAmount=point.cum_amount)
                    for point in intraday.points
                ],
                historyByRange={
                    "oneMonth": [
                        TurnoverHistoryPointDto(tradeDate=point.trade_date, amount=point.amount)
                        for point in history_1m
                    ],
                    "threeMonth": [
                        TurnoverHistoryPointDto(tradeDate=point.trade_date, amount=point.amount)
                        for point in history_3m
                    ],
                },
            ),
            debugInfo=(
                TurnoverDebugInfoDto(
                    modules=[status_result.module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    def _build_error_response(
        self,
        *,
        trading_day_context: TurnoverTradingDayContext,
        source_state: TurnoverSourceState,
        debug: bool,
        exceptions: list,
    ) -> TurnoverResponseDto:
        lag_days = None
        if source_state.observed_trade_date is not None:
            lag_days = (trading_day_context.expected_trade_date - source_state.observed_trade_date).days
            if lag_days < 0:
                lag_days = 0
        module_status = ModuleStatusItemDto(
            moduleKey="turnover",
            expectedTradeDate=trading_day_context.expected_trade_date,
            observedTradeDate=source_state.observed_trade_date,
            lagDays=lag_days,
            status="ERROR",
            note="module failed to load",
        )
        return TurnoverResponseDto(
            tradingDay=TradingDayDto(
                tradeDate=trading_day_context.expected_trade_date,
                prevTradeDate=trading_day_context.prev_trade_date,
                market="CN_A",
                isTradingDay=trading_day_context.is_trading_day,
                sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
                timezone="Asia/Shanghai",
            ),
            pageStatus=PageStatusDto(
                status="ERROR",
                displayText="模块加载失败",
                asOfTime=trading_day_context.as_of_time,
            ),
            turnover=TurnoverPayloadDto(
                tradeDate=trading_day_context.expected_trade_date,
                metrics=TurnoverMetricsDto(
                    todayAmount=None,
                    prevAmount=None,
                    amountDelta=None,
                    amountDeltaPct=None,
                    avg5dAmount=None,
                    avg20dAmount=None,
                    unit="thousand_yuan",
                ),
                intradayCumulative=[
                    TurnoverIntradayPointDto(time=time_point, cumAmount=None)
                    for time_point in ("09:30", "10:30", "11:30", "14:00", "15:00")
                ],
                historyByRange={"oneMonth": [], "threeMonth": []},
            ),
            debugInfo=(
                TurnoverDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )
