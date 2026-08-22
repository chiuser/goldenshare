from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.turnover_common.turnover_daily_average_query import (
    TurnoverDailyAverageQuery,
)
from src.biz.schemas.wealth.market.turnover_insight import (
    TurnoverInsightAmountDto,
    TurnoverInsightAverageAmountDto,
    TurnoverInsightDebugInfoDto,
    TurnoverInsightResponseDto,
    TurnoverInsightSummaryDto,
    TurnoverInsightTradingDayDto,
)
from src.biz.services.wealth.market.turnover_insight.turnover_insight_exception_builder import (
    TurnoverInsightExceptionBuilder,
)
from src.biz.services.wealth.market.turnover_insight.turnover_insight_status_resolver import (
    TurnoverInsightStatusResolution,
    TurnoverInsightStatusResolver,
)

from .turnover_insight_calculator import (
    TurnoverInsightCalculation,
    TurnoverInsightCalculator,
    TurnoverInsightPointQualityError,
    TurnoverInsightTimeGridError,
)
from .turnover_insight_query import (
    TurnoverInsightCandidateSet,
    TurnoverInsightQuery,
    TurnoverInsightSnapshotRow,
)


class TurnoverInsightQueryService:
    """Build the standalone turnover insight response from minute snapshots."""

    def __init__(self) -> None:
        self._context_query = MarketPageContextQuery()
        self._query = TurnoverInsightQuery()
        self._daily_average_query = TurnoverDailyAverageQuery()
        self._calculator = TurnoverInsightCalculator()
        self._status = TurnoverInsightStatusResolver()
        self._exceptions = TurnoverInsightExceptionBuilder()

    def build_turnover_insight(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> TurnoverInsightResponseDto:
        context = self._context_query.resolve_context(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        try:
            candidates = self._query.load_candidates(
                session,
                expected_trade_date=context.trade_date,
                expected_prev_trade_date=context.prev_trade_date,
            )
        except Exception:  # noqa: BLE001
            exception = self._exceptions.build(
                code="TI_QUERY_FAILED",
                severity="error",
                message="turnover insight candidate query failed",
            )
            return self._empty_response(
                context=context,
                resolution=self._status.error(),
                debug=debug,
                candidate_count=0,
                exceptions=[exception],
            )

        current = self._find_row(candidates.rows, context.trade_date)
        if current is not None:
            return self._build_expected_response(
                session=session,
                context=context,
                candidates=candidates,
                current=current,
                debug=debug,
            )
        return self._build_fallback_response(
            session=session,
            context=context,
            candidates=candidates,
            debug=debug,
        )

    def _build_expected_response(
        self,
        *,
        session: Session,
        context: MarketPageContext,
        candidates: TurnoverInsightCandidateSet,
        current: TurnoverInsightSnapshotRow,
        debug: bool,
    ) -> TurnoverInsightResponseDto:
        previous = self._find_row(candidates.rows, context.prev_trade_date)
        try:
            if previous is None:
                calculation = self._calculator.calculate_pair(
                    current_snapshot=current,
                    previous_snapshot=None,
                )
                exception = self._exceptions.build(
                    code="TI_PREVIOUS_SNAPSHOT_MISSING",
                    severity="warn",
                    message="expected previous turnover snapshot is missing",
                    details={"expectedTradeDate": context.trade_date.isoformat()},
                )
                return self._calculated_response(
                    session=session,
                    context=context,
                    resolution=self._status.partial(),
                    current=current,
                    previous=None,
                    calculation=calculation,
                    debug=debug,
                    candidate_count=len(candidates.rows),
                    exceptions=[exception],
                )
            calculation = self._calculator.calculate_pair(
                current_snapshot=current,
                previous_snapshot=previous,
            )
        except TurnoverInsightTimeGridError:
            if previous is not None:
                return self._partial_from_valid_current(
                    session=session,
                    context=context,
                    candidates=candidates,
                    current=current,
                    debug=debug,
                    code="TI_TIME_GRID_MISMATCH",
                    message="previous turnover snapshot time grid is invalid",
                )
            return self._invalid_current_response(
                context=context,
                candidates=candidates,
                debug=debug,
                code="TI_TIME_GRID_MISMATCH",
                message="current turnover snapshot time grid is invalid",
            )
        except TurnoverInsightPointQualityError:
            if previous is not None:
                try:
                    self._calculator.calculate_pair(current_snapshot=current, previous_snapshot=None)
                except TurnoverInsightPointQualityError:
                    return self._invalid_current_response(
                        context=context,
                        candidates=candidates,
                        debug=debug,
                        code="TI_POINT_QUALITY_INVALID",
                        message="current turnover snapshot point quality is invalid",
                    )
                return self._partial_from_valid_current(
                    session=session,
                    context=context,
                    candidates=candidates,
                    current=current,
                    debug=debug,
                    code="TI_POINT_QUALITY_INVALID",
                    message="previous turnover snapshot point quality is invalid",
                )
            return self._invalid_current_response(
                context=context,
                candidates=candidates,
                debug=debug,
                code="TI_POINT_QUALITY_INVALID",
                message="current turnover snapshot point quality is invalid",
            )

        return self._calculated_response(
            session=session,
            context=context,
            resolution=self._status.ready(),
            current=current,
            previous=previous,
            calculation=calculation,
            debug=debug,
            candidate_count=len(candidates.rows),
            exceptions=[],
        )

    def _build_fallback_response(
        self,
        *,
        session: Session,
        context: MarketPageContext,
        candidates: TurnoverInsightCandidateSet,
        debug: bool,
    ) -> TurnoverInsightResponseDto:
        rows_by_date = {row.trade_date: row for row in candidates.rows}
        for newer in candidates.rows:
            if newer.pretrade_date is None:
                continue
            older = rows_by_date.get(newer.pretrade_date)
            if older is None:
                continue
            try:
                calculation = self._calculator.calculate_pair(
                    current_snapshot=newer,
                    previous_snapshot=older,
                )
            except TurnoverInsightPointQualityError:
                continue
            exception = self._exceptions.build(
                code="TI_SOURCE_DELAYED",
                severity="warn",
                message="using the latest complete adjacent turnover snapshot pair",
                details={
                    "expectedTradeDate": context.trade_date.isoformat(),
                    "observedTradeDate": newer.trade_date.isoformat(),
                },
            )
            return self._calculated_response(
                session=session,
                context=context,
                resolution=self._status.delayed(),
                current=newer,
                previous=older,
                calculation=calculation,
                debug=debug,
                candidate_count=len(candidates.rows),
                exceptions=[exception],
            )

        exception = self._exceptions.build(
            code="TI_CURRENT_SNAPSHOT_MISSING",
            severity="warn",
            message="no complete current turnover snapshot is available",
            details={"expectedTradeDate": context.trade_date.isoformat()},
        )
        return self._empty_response(
            context=context,
            resolution=self._status.empty(),
            debug=debug,
            candidate_count=len(candidates.rows),
            exceptions=[exception],
        )

    def _partial_from_valid_current(
        self,
        *,
        session: Session,
        context: MarketPageContext,
        candidates: TurnoverInsightCandidateSet,
        current: TurnoverInsightSnapshotRow,
        debug: bool,
        code: str,
        message: str,
    ) -> TurnoverInsightResponseDto:
        try:
            calculation = self._calculator.calculate_pair(
                current_snapshot=current,
                previous_snapshot=None,
            )
        except TurnoverInsightPointQualityError:
            return self._invalid_current_response(
                context=context,
                candidates=candidates,
                debug=debug,
                code="TI_POINT_QUALITY_INVALID",
                message="current turnover snapshot point quality is invalid",
            )
        exception = self._exceptions.build(code=code, severity="warn", message=message)
        resolution = TurnoverInsightStatusResolution(
            status="PARTIAL",
            message="上一交易日数据暂不完整，仅展示当日累计成交额。",
            exception_code=code,
        )
        return self._calculated_response(
            session=session,
            context=context,
            resolution=resolution,
            current=current,
            previous=None,
            calculation=calculation,
            debug=debug,
            candidate_count=len(candidates.rows),
            exceptions=[exception],
        )

    def _invalid_current_response(
        self,
        *,
        context: MarketPageContext,
        candidates: TurnoverInsightCandidateSet,
        debug: bool,
        code: str,
        message: str,
    ) -> TurnoverInsightResponseDto:
        exception = self._exceptions.build(code=code, severity="error", message=message)
        resolution = TurnoverInsightStatusResolution(
            status="ERROR",
            message="成交额快照质量校验失败，请稍后重试。",
            exception_code=code,
        )
        return self._empty_response(
            context=context,
            resolution=resolution,
            debug=debug,
            candidate_count=len(candidates.rows),
            exceptions=[exception],
        )

    def _calculated_response(
        self,
        *,
        session: Session,
        context: MarketPageContext,
        resolution: TurnoverInsightStatusResolution,
        current: TurnoverInsightSnapshotRow,
        previous: TurnoverInsightSnapshotRow | None,
        calculation: TurnoverInsightCalculation,
        debug: bool,
        candidate_count: int,
        exceptions: list,
    ) -> TurnoverInsightResponseDto:
        response_exceptions = list(exceptions)
        try:
            daily_averages = self._daily_average_query.load(
                session,
                end_trade_date=current.trade_date,
            )
        except Exception:  # noqa: BLE001
            daily_averages = None
            response_exceptions.append(
                self._exceptions.build(
                    code="TI_DAILY_AVERAGE_UNAVAILABLE",
                    severity="warn",
                    message="turnover daily averages are unavailable",
                    details={"observedTradeDate": current.trade_date.isoformat()},
                )
            )
        calculation = self._calculator.with_daily_averages(calculation, daily_averages)
        return TurnoverInsightResponseDto(
            status=resolution.status,
            tradingDay=self._trading_day(
                context=context,
                observed_trade_date=current.trade_date,
                previous_observed_trade_date=previous.trade_date if previous is not None else None,
            ),
            asOf=current.built_at,
            summary=calculation.summary,
            upperAxis=calculation.upper_axis,
            deltaAxis=calculation.delta_axis,
            series=list(calculation.series),
            message=resolution.message,
            exceptionCode=resolution.exception_code,
            debugInfo=self._debug_info(
                debug,
                candidate_count=candidate_count,
                exceptions=response_exceptions,
            ),
        )

    def _empty_response(
        self,
        *,
        context: MarketPageContext,
        resolution: TurnoverInsightStatusResolution,
        debug: bool,
        candidate_count: int,
        exceptions: list,
    ) -> TurnoverInsightResponseDto:
        return TurnoverInsightResponseDto(
            status=resolution.status,
            tradingDay=self._trading_day(
                context=context,
                observed_trade_date=None,
                previous_observed_trade_date=None,
            ),
            summary=self._empty_summary(),
            series=[],
            message=resolution.message,
            exceptionCode=resolution.exception_code,
            debugInfo=self._debug_info(debug, candidate_count=candidate_count, exceptions=exceptions),
        )

    @staticmethod
    def _find_row(
        rows: tuple[TurnoverInsightSnapshotRow, ...],
        trade_date: date | None,
    ) -> TurnoverInsightSnapshotRow | None:
        if trade_date is None:
            return None
        return next((row for row in rows if row.trade_date == trade_date), None)

    @staticmethod
    def _trading_day(
        *,
        context: MarketPageContext,
        observed_trade_date: date | None,
        previous_observed_trade_date: date | None,
    ) -> TurnoverInsightTradingDayDto:
        return TurnoverInsightTradingDayDto(
            market="CN_A",
            expectedTradeDate=context.trade_date,
            observedTradeDate=observed_trade_date,
            previousObservedTradeDate=previous_observed_trade_date,
            isTradingDay=context.is_trading_day,
            sessionStatus=context.session_status,  # type: ignore[arg-type]
            generatedAt=context.generated_at,
        )

    @staticmethod
    def _empty_summary() -> TurnoverInsightSummaryDto:
        return TurnoverInsightSummaryDto(
            current=TurnoverInsightAmountDto(amountYi=None, displayText="--", direction="neutral"),
            previous=TurnoverInsightAmountDto(amountYi=None, displayText="--", direction="neutral"),
            delta=TurnoverInsightAmountDto(amountYi=None, displayText="--", direction="neutral"),
            avg5d=TurnoverInsightAverageAmountDto(
                amountYi=None,
                displayText="--",
                direction="neutral",
                referenceLabel="5日均值 --",
            ),
            avg20d=TurnoverInsightAverageAmountDto(
                amountYi=None,
                displayText="--",
                direction="neutral",
                referenceLabel="20日均值 --",
            ),
        )

    @staticmethod
    def _debug_info(debug: bool, *, candidate_count: int, exceptions: list):
        if not debug:
            return None
        return TurnoverInsightDebugInfoDto(
            candidateCount=candidate_count,
            exceptions=exceptions,
        )
