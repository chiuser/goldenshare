from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.breadth.breadth_fact_query import (
    BreadthDistributionBuckets,
    BreadthFactDuplicatedError,
    BreadthFactQuery,
    BreadthFactRow,
)
from src.biz.schemas.wealth.market.breadth import (
    BreadthDebugInfoDto,
    BreadthDistributionBucketsDto,
    BreadthHistoryPointDto,
    BreadthMetricsDto,
    BreadthPayloadDto,
    BreadthResponseDto,
    ModuleStatusItemDto,
    PageStatusDto,
    TradingDayDto,
)
from src.biz.services.wealth.market.breadth.breadth_exception_builder import BreadthExceptionBuilder
from src.biz.services.wealth.market.breadth.breadth_status_resolver import (
    EXPECTED_1M_POINTS,
    EXPECTED_3M_POINTS,
    BreadthStatusResolver,
)
from .breadth_history_query import BreadthHistoryQuery
from .breadth_state_query import BreadthSourceState, BreadthStateQuery, BreadthTradingDayContext


class MarketBreadthQueryService:
    """Orchestrate breadth module response assembly."""

    def __init__(self, *, fact_query: BreadthFactQuery | None = None) -> None:
        self._state_query = BreadthStateQuery()
        self._fact_query = fact_query or BreadthFactQuery()
        self._history_query = BreadthHistoryQuery()
        self._status_resolver = BreadthStatusResolver()
        self._exception_builder = BreadthExceptionBuilder()

    def build_breadth(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> BreadthResponseDto:
        exceptions = []
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        source_state = BreadthSourceState(observed_trade_date=None)

        try:
            source_state = BreadthSourceState(observed_trade_date=self._fact_query.load_observed_trade_date())
            metrics_fact = self._fact_query.load_one(trade_date=trading_day_context.expected_trade_date)
            recent_trade_dates = self._history_query.load_recent_trade_dates(
                session,
                end_trade_date=trading_day_context.expected_trade_date,
                limit_days=EXPECTED_3M_POINTS,
            )
            history_facts = self._fact_query.load_many(trade_dates=recent_trade_dates)
        except BreadthFactDuplicatedError as exc:
            exceptions.append(
                self._exception_builder.fact_duplicated(
                    message="breadth fact table has duplicated rows for one trade date",
                    trade_date=exc.trade_date.isoformat(),
                    row_count=exc.row_count,
                )
            )
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=source_state,
                debug=debug,
                exceptions=exceptions,
            )
        except Exception as exc:  # noqa: BLE001
            exceptions.append(self._exception_builder.query_failed(message=f"breadth query failed: {exc}"))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=source_state,
                debug=debug,
                exceptions=exceptions,
            )

        metrics = metrics_fact or _empty_fact(trading_day_context.expected_trade_date)
        history_3m = [_history_point_to_dto(point) for point in history_facts]
        one_month_dates = set(recent_trade_dates[-EXPECTED_1M_POINTS:])
        history_1m = [point for point in history_3m if point.tradeDate in one_month_dates]

        status_result = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=source_state.observed_trade_date,
            metric_total_count=metrics.total_count,
            history_points_1m=len(history_1m),
            history_points_3m=len(history_3m),
            as_of_time=trading_day_context.as_of_time,
        )

        if status_result.module_status.status == "DELAYED" and source_state.observed_trade_date is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="breadth source date lagged",
                    expected_trade_date=trading_day_context.expected_trade_date.isoformat(),
                    observed_trade_date=source_state.observed_trade_date.isoformat(),
                )
            )
        if status_result.module_status.status == "EMPTY":
            exceptions.append(
                self._exception_builder.source_empty(
                    message="breadth source has no usable rows",
                    target_trade_date=trading_day_context.expected_trade_date.isoformat(),
                )
            )
        if status_result.history_incomplete:
            exceptions.append(
                self._exception_builder.history_incomplete(
                    message="breadth history points are incomplete",
                    actual_points_1m=len(history_1m),
                    expected_points_1m=EXPECTED_1M_POINTS,
                    actual_points_3m=len(history_3m),
                    expected_points_3m=EXPECTED_3M_POINTS,
                )
            )

        response = BreadthResponseDto(
            tradingDay=TradingDayDto(
                tradeDate=trading_day_context.expected_trade_date,
                prevTradeDate=trading_day_context.prev_trade_date,
                market="CN_A",
                isTradingDay=trading_day_context.is_trading_day,
                sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
                timezone="Asia/Shanghai",
            ),
            pageStatus=status_result.page_status,
            breadth=BreadthPayloadDto(
                tradeDate=trading_day_context.expected_trade_date,
                metrics=BreadthMetricsDto(
                    upCount=metrics.up_count,
                    downCount=metrics.down_count,
                    flatCount=metrics.flat_count,
                    totalCount=metrics.total_count,
                    redRate=metrics.red_rate,
                    distributionBuckets=_buckets_to_dto(metrics.distribution_buckets),
                ),
                historyByRange={
                    "1m": history_1m,
                    "3m": history_3m,
                },
            ),
            debugInfo=(
                BreadthDebugInfoDto(
                    modules=[status_result.module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )
        return response

    def _build_error_response(
        self,
        *,
        trading_day_context: BreadthTradingDayContext,
        source_state: BreadthSourceState,
        debug: bool,
        exceptions: list,
    ) -> BreadthResponseDto:
        lag_days = None
        if source_state.observed_trade_date is not None:
            lag_days = (trading_day_context.expected_trade_date - source_state.observed_trade_date).days
            if lag_days < 0:
                lag_days = 0
        module_status = ModuleStatusItemDto(
            moduleKey="breadth",
            expectedTradeDate=trading_day_context.expected_trade_date,
            observedTradeDate=source_state.observed_trade_date,
            lagDays=lag_days,
            status="ERROR",
            note="module failed to load",
        )
        return BreadthResponseDto(
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
            breadth=BreadthPayloadDto(
                tradeDate=trading_day_context.expected_trade_date,
                metrics=_metrics_to_dto(_empty_fact(trading_day_context.expected_trade_date)),
                historyByRange={"1m": [], "3m": []},
            ),
            debugInfo=(
                BreadthDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )


def _empty_fact(trade_date: date) -> BreadthFactRow:
    return BreadthFactRow(
        trade_date=trade_date,
        up_count=0,
        down_count=0,
        flat_count=0,
        total_count=0,
        red_rate=0.0,
        distribution_buckets=BreadthDistributionBuckets(
            down_gt_7_count=0,
            down_5_7_count=0,
            down_3_5_count=0,
            down_0_3_count=0,
            up_0_3_count=0,
            up_3_5_count=0,
            up_5_7_count=0,
            up_gt_7_count=0,
        ),
    )


def _buckets_to_dto(buckets: BreadthDistributionBuckets) -> BreadthDistributionBucketsDto:
    return BreadthDistributionBucketsDto(
        downGt7Count=buckets.down_gt_7_count,
        down5To7Count=buckets.down_5_7_count,
        down3To5Count=buckets.down_3_5_count,
        down0To3Count=buckets.down_0_3_count,
        up0To3Count=buckets.up_0_3_count,
        up3To5Count=buckets.up_3_5_count,
        up5To7Count=buckets.up_5_7_count,
        upGt7Count=buckets.up_gt_7_count,
    )


def _metrics_to_dto(fact: BreadthFactRow) -> BreadthMetricsDto:
    return BreadthMetricsDto(
        upCount=fact.up_count,
        downCount=fact.down_count,
        flatCount=fact.flat_count,
        totalCount=fact.total_count,
        redRate=fact.red_rate,
        distributionBuckets=_buckets_to_dto(fact.distribution_buckets),
    )


def _history_point_to_dto(fact: BreadthFactRow) -> BreadthHistoryPointDto:
    return BreadthHistoryPointDto(
        tradeDate=fact.trade_date,
        upCount=fact.up_count,
        downCount=fact.down_count,
        flatCount=fact.flat_count,
        totalCount=fact.total_count,
        redRate=fact.red_rate,
        distributionBuckets=_buckets_to_dto(fact.distribution_buckets),
    )
