from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.money_flow import (
    ModuleStatusItemDto,
    MoneyFlowDebugInfoDto,
    MoneyFlowHistoryPointDto,
    MoneyFlowMetricsDto,
    MoneyFlowPayloadDto,
    MoneyFlowResponseDto,
    OrderSizeFlowDto,
    OrderSizeFlowItemDto,
    PageStatusDto,
    TradingDayDto,
)
from src.biz.services.wealth.market.money_flow.money_flow_exception_builder import MoneyFlowExceptionBuilder
from src.biz.services.wealth.market.money_flow.money_flow_status_resolver import (
    EXPECTED_1M_POINTS,
    EXPECTED_3M_POINTS,
    MoneyFlowStatusResolver,
)
from .money_flow_query import MoneyFlowQuery
from .money_flow_state_query import MoneyFlowSourceState, MoneyFlowStateQuery, MoneyFlowTradingDayContext


class MarketMoneyFlowQueryService:
    """Orchestrate money-flow module response assembly."""

    def __init__(self) -> None:
        self._state_query = MoneyFlowStateQuery()
        self._query = MoneyFlowQuery()
        self._status_resolver = MoneyFlowStatusResolver()
        self._exception_builder = MoneyFlowExceptionBuilder()

    def build_money_flow(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> MoneyFlowResponseDto:
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
        except Exception as exc:  # noqa: BLE001
            exceptions.append(self._exception_builder.query_failed(message=f"money-flow query failed: {exc}"))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=source_state,
                debug=debug,
                exceptions=exceptions,
            )

        history_1m_effective_points = sum(1 for point in history_1m if point.net_amount is not None)
        history_3m_effective_points = sum(1 for point in history_3m if point.net_amount is not None)
        status_result = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=source_state.observed_trade_date,
            has_core_metrics=metrics.has_core_metrics,
            order_size_complete=metrics.by_order_size.is_complete,
            history_points_1m=history_1m_effective_points,
            history_points_3m=history_3m_effective_points,
            as_of_time=trading_day_context.as_of_time,
        )

        if status_result.module_status.status == "DELAYED" and source_state.observed_trade_date is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="money-flow source date lagged",
                    expected_trade_date=trading_day_context.expected_trade_date.isoformat(),
                    observed_trade_date=source_state.observed_trade_date.isoformat(),
                )
            )
        if status_result.module_status.status == "EMPTY":
            exceptions.append(
                self._exception_builder.source_empty(
                    message="money-flow source has no usable rows",
                )
            )
        if status_result.history_incomplete and status_result.module_status.status != "EMPTY":
            exceptions.append(
                self._exception_builder.history_incomplete(
                    message="money-flow history is incomplete",
                    one_month_points=history_1m_effective_points,
                    three_month_points=history_3m_effective_points,
                )
            )

        return MoneyFlowResponseDto(
            tradingDay=TradingDayDto(
                tradeDate=trading_day_context.expected_trade_date,
                prevTradeDate=trading_day_context.prev_trade_date,
                market="CN_A",
                isTradingDay=trading_day_context.is_trading_day,
                sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
                timezone="Asia/Shanghai",
            ),
            pageStatus=status_result.page_status,
            moneyFlow=MoneyFlowPayloadDto(
                tradeDate=trading_day_context.expected_trade_date,
                metrics=MoneyFlowMetricsDto(
                    todayNetAmount=metrics.today_net_amount,
                    prevNetAmount=metrics.prev_net_amount,
                    unit="yuan",
                ),
                byOrderSize=OrderSizeFlowDto(
                    elg=OrderSizeFlowItemDto(
                        amount=metrics.by_order_size.elg_amount,
                        rate=metrics.by_order_size.elg_rate,
                    ),
                    lg=OrderSizeFlowItemDto(
                        amount=metrics.by_order_size.lg_amount,
                        rate=metrics.by_order_size.lg_rate,
                    ),
                    md=OrderSizeFlowItemDto(
                        amount=metrics.by_order_size.md_amount,
                        rate=metrics.by_order_size.md_rate,
                    ),
                    sm=OrderSizeFlowItemDto(
                        amount=metrics.by_order_size.sm_amount,
                        rate=metrics.by_order_size.sm_rate,
                    ),
                ),
                historyByRange={
                    "oneMonth": [
                        MoneyFlowHistoryPointDto(tradeDate=point.trade_date, netAmount=point.net_amount)
                        for point in history_1m
                    ],
                    "threeMonth": [
                        MoneyFlowHistoryPointDto(tradeDate=point.trade_date, netAmount=point.net_amount)
                        for point in history_3m
                    ],
                },
            ),
            debugInfo=(
                MoneyFlowDebugInfoDto(
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
        trading_day_context: MoneyFlowTradingDayContext,
        source_state: MoneyFlowSourceState,
        debug: bool,
        exceptions: list,
    ) -> MoneyFlowResponseDto:
        lag_days = None
        if source_state.observed_trade_date is not None:
            lag_days = (trading_day_context.expected_trade_date - source_state.observed_trade_date).days
            if lag_days < 0:
                lag_days = 0
        module_status = ModuleStatusItemDto(
            moduleKey="moneyFlow",
            expectedTradeDate=trading_day_context.expected_trade_date,
            observedTradeDate=source_state.observed_trade_date,
            lagDays=lag_days,
            status="ERROR",
            note="module failed to load",
        )
        empty_order_size = OrderSizeFlowItemDto(amount=None, rate=None)
        return MoneyFlowResponseDto(
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
            moneyFlow=MoneyFlowPayloadDto(
                tradeDate=trading_day_context.expected_trade_date,
                metrics=MoneyFlowMetricsDto(todayNetAmount=None, prevNetAmount=None, unit="yuan"),
                byOrderSize=OrderSizeFlowDto(
                    elg=empty_order_size,
                    lg=empty_order_size,
                    md=empty_order_size,
                    sm=empty_order_size,
                ),
                historyByRange={"oneMonth": [], "threeMonth": []},
            ),
            debugInfo=(
                MoneyFlowDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )
