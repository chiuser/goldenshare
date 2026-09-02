from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
    MarketPageContextQuery,
)
from src.biz.schemas.wealth.market.index_turnover_insight import (
    IndexTurnoverInsightDebugInfoDto,
    IndexTurnoverInsightExceptionDto,
    IndexTurnoverInsightPanelDto,
    IndexTurnoverInsightResponseDto,
    IndexTurnoverInsightTradingDayDto,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_exception_builder import (
    IndexTurnoverInsightExceptionBuilder,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_status_resolver import (
    IndexTurnoverInsightStatusResolver,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_universe import (
    INDEX_TURNOVER_INSIGHT_UNIVERSE,
    IndexTurnoverInsightIdentity,
)
from src.foundation.clients.local_lake.major_index_turnover_reader import (
    MajorIndexTurnoverLakeReader,
    MajorIndexTurnoverMinuteRow,
    MajorIndexTurnoverReadIssue,
    MajorIndexTurnoverReadRequest,
    MajorIndexTurnoverReadResult,
    MajorIndexTurnoverReaderError,
)

from .index_turnover_insight_calculator import IndexTurnoverInsightCalculator
from .index_turnover_insight_calendar_query import (
    IndexTurnoverInsightCalendarContractError,
    IndexTurnoverInsightCalendarDay,
    IndexTurnoverInsightCalendarQuery,
)


class IndexTurnoverInsightQueryService:
    def __init__(
        self,
        *,
        context_query: MarketPageContextQuery,
        calendar_query: IndexTurnoverInsightCalendarQuery,
        reader: MajorIndexTurnoverLakeReader,
        calculator: IndexTurnoverInsightCalculator,
        status_resolver: IndexTurnoverInsightStatusResolver,
        exception_builder: IndexTurnoverInsightExceptionBuilder,
    ) -> None:
        self._context_query = context_query
        self._calendar_query = calendar_query
        self._reader = reader
        self._calculator = calculator
        self._status = status_resolver
        self._exceptions = exception_builder

    def build_index_turnover_insight(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> IndexTurnoverInsightResponseDto:
        context = self._context_query.resolve_context(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        candidates: tuple[IndexTurnoverInsightCalendarDay, ...] = ()
        try:
            candidates = self._calendar_query.load_candidates(
                session,
                expected_trade_date=context.trade_date,
                limit=24,
            )
            read_result = self._reader.read(
                MajorIndexTurnoverReadRequest(
                    trade_dates=tuple(day.trade_date for day in candidates)
                )
            )
        except (MajorIndexTurnoverReaderError, IndexTurnoverInsightCalendarContractError) as exc:
            return self._global_error(
                context=context,
                code=exc.code,
                debug=debug,
                candidate_count=len(candidates),
            )
        except Exception:  # noqa: BLE001
            return self._global_error(
                context=context,
                code="ITI_QUERY_FAILED",
                debug=debug,
                candidate_count=len(candidates),
            )

        try:
            return self._build_from_read_result(
                context=context,
                candidates=candidates,
                read_result=read_result,
                debug=debug,
            )
        except Exception:  # noqa: BLE001
            return self._global_error(
                context=context,
                code="ITI_QUERY_FAILED",
                debug=debug,
                candidate_count=len(candidates),
            )

    def _build_from_read_result(
        self,
        *,
        context: MarketPageContext,
        candidates: tuple[IndexTurnoverInsightCalendarDay, ...],
        read_result: MajorIndexTurnoverReadResult,
        debug: bool,
    ) -> IndexTurnoverInsightResponseDto:
        pair, delayed = self._select_date_pair(
            context=context,
            candidates=candidates,
            result=read_result,
        )
        exceptions = self._build_read_exceptions(read_result.issues)
        if pair is None:
            exceptions.append(
                self._exceptions.build(
                    code="ITI_SOURCE_NOT_READY",
                    message="没有可展示的指数成交额日期对。",
                    details={"expectedTradeDate": context.trade_date.isoformat()},
                )
            )
            panels = self._unavailable_panels(
                result=read_result,
                current_date=context.trade_date,
            )
            resolution = self._status.resolve_group(
                delayed=False,
                item_statuses=tuple(panel.status for panel in panels),
            )
            return self._response(
                context=context,
                observed_trade_date=None,
                previous_observed_trade_date=None,
                resolution=resolution,
                panels=panels,
                debug=debug,
                candidates=candidates,
                result=read_result,
                exceptions=exceptions,
            )

        observed_trade_date, previous_observed_trade_date = pair
        rows_by_code: dict[str, list[MajorIndexTurnoverMinuteRow]] = defaultdict(list)
        for row in read_result.rows:
            rows_by_code[row.ts_code].append(row)
        panels = tuple(
            self._build_panel(
                identity=identity,
                result=read_result,
                rows=tuple(rows_by_code.get(identity.ts_code, ())),
                observed_trade_date=observed_trade_date,
                previous_observed_trade_date=previous_observed_trade_date,
            )
            for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE
        )
        if delayed:
            exceptions.append(
                self._exceptions.build(
                    code="ITI_SOURCE_DELAYED",
                    message="正在展示较早的完整指数成交额日期对。",
                    details={
                        "expectedTradeDate": context.trade_date.isoformat(),
                        "observedTradeDate": observed_trade_date.isoformat(),
                    },
                )
            )
        resolution = self._status.resolve_group(
            delayed=delayed,
            item_statuses=tuple(panel.status for panel in panels),
        )
        return self._response(
            context=context,
            observed_trade_date=observed_trade_date,
            previous_observed_trade_date=previous_observed_trade_date,
            resolution=resolution,
            panels=panels,
            debug=debug,
            candidates=candidates,
            result=read_result,
            exceptions=exceptions,
        )

    def _select_date_pair(
        self,
        *,
        context: MarketPageContext,
        candidates: tuple[IndexTurnoverInsightCalendarDay, ...],
        result: MajorIndexTurnoverReadResult,
    ) -> tuple[tuple[date, date] | None, bool]:
        expected_previous = context.prev_trade_date
        if expected_previous is not None:
            expected_pair = (context.trade_date, expected_previous)
            available = set(result.available_trade_dates)
            if set(expected_pair).issubset(available) and self._displayable_code_count(
                result, current_date=context.trade_date
            ):
                return expected_pair, False

        candidate_by_date = {day.trade_date: day for day in candidates[:4]}
        for newer in candidates[:4]:
            older_date = newer.previous_trade_date
            if older_date is None or older_date not in candidate_by_date:
                continue
            if self._pair_is_complete(
                result,
                current_date=newer.trade_date,
                previous_date=older_date,
            ):
                return (newer.trade_date, older_date), newer.trade_date != context.trade_date
        return None, False

    @staticmethod
    def _displayable_code_count(
        result: MajorIndexTurnoverReadResult, *, current_date: date
    ) -> int:
        codes = {
            row.ts_code for row in result.rows if row.trade_date == current_date
        }
        return len(codes)

    @staticmethod
    def _pair_is_complete(
        result: MajorIndexTurnoverReadResult,
        *,
        current_date: date,
        previous_date: date,
    ) -> bool:
        current_codes = {
            row.ts_code for row in result.rows if row.trade_date == current_date
        }
        previous_codes = {
            row.ts_code for row in result.rows if row.trade_date == previous_date
        }
        required = {identity.ts_code for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE}
        return current_codes == required and previous_codes == required

    def _build_panel(
        self,
        *,
        identity: IndexTurnoverInsightIdentity,
        result: MajorIndexTurnoverReadResult,
        rows: tuple[MajorIndexTurnoverMinuteRow, ...],
        observed_trade_date: date,
        previous_observed_trade_date: date,
    ) -> IndexTurnoverInsightPanelDto:
        calculation = self._calculator.calculate(
            ts_code=identity.ts_code,
            rows=rows,
            observed_trade_date=observed_trade_date,
            previous_observed_trade_date=previous_observed_trade_date,
        )
        current_issue = self._primary_issue(
            result.issues,
            ts_code=identity.ts_code,
            trade_date=observed_trade_date,
        )
        previous_issue = self._primary_issue(
            result.issues,
            ts_code=identity.ts_code,
            trade_date=previous_observed_trade_date,
        )
        if not calculation.current_available:
            resolution = (
                self._status.item_empty()
                if current_issue in {None, "ITI_SOURCE_NOT_READY"}
                else self._status.item_error(current_issue)
            )
        elif not calculation.previous_available:
            resolution = self._status.item_current_only(
                previous_issue or "ITI_SOURCE_NOT_READY"
            )
        elif not calculation.averages_complete:
            resolution = self._status.item_average_partial()
        else:
            resolution = self._status.item_ready()
        return self._calculator.build_panel_dto(
            identity=identity,
            calculation=calculation,
            status=resolution.status,
            message=resolution.message,
            exception_code=resolution.exception_code,
        )

    def _unavailable_panels(
        self,
        *,
        result: MajorIndexTurnoverReadResult,
        current_date: date,
    ) -> tuple[IndexTurnoverInsightPanelDto, ...]:
        panels: list[IndexTurnoverInsightPanelDto] = []
        for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE:
            issue = self._primary_issue(
                result.issues,
                ts_code=identity.ts_code,
                trade_date=current_date,
            )
            resolution = (
                self._status.item_empty()
                if issue in {None, "ITI_SOURCE_NOT_READY"}
                else self._status.item_error(issue)
            )
            panels.append(
                self._calculator.build_panel_dto(
                    identity=identity,
                    calculation=None,
                    status=resolution.status,
                    message=resolution.message,
                    exception_code=resolution.exception_code,
                )
            )
        return tuple(panels)

    @staticmethod
    def _primary_issue(
        issues: tuple[MajorIndexTurnoverReadIssue, ...],
        *,
        ts_code: str,
        trade_date: date,
    ) -> str | None:
        codes = [
            issue.code
            for issue in issues
            if issue.ts_code == ts_code and issue.trade_date == trade_date
        ]
        return IndexTurnoverInsightExceptionBuilder.select_primary(codes)

    def _build_read_exceptions(
        self, issues: tuple[MajorIndexTurnoverReadIssue, ...]
    ) -> list[IndexTurnoverInsightExceptionDto]:
        return [
            self._exceptions.build(
                code=issue.code,
                message="指数分钟数据未通过完整性校验。",
                details={
                    "tsCode": issue.ts_code,
                    "tradeDate": (
                        issue.trade_date.isoformat() if issue.trade_date else None
                    ),
                    "reasonCode": issue.code,
                },
            )
            for issue in issues
        ]

    def _global_error(
        self,
        *,
        context: MarketPageContext,
        code: str,
        debug: bool,
        candidate_count: int | None,
    ) -> IndexTurnoverInsightResponseDto:
        resolution = self._status.global_error(code)
        panels = tuple(
            self._calculator.build_panel_dto(
                identity=identity,
                calculation=None,
                status="ERROR",
                message="指数成交额数据读取失败，请稍后重试。",
                exception_code=code,
            )
            for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE
        )
        exception = self._exceptions.build(
            code=code,
            message="指数成交额批量查询失败。",
        )
        return IndexTurnoverInsightResponseDto(
            status=resolution.status,
            tradingDay=self._trading_day(context, None, None),
            indices=list(panels),
            message=resolution.message,
            exceptionCode=resolution.exception_code,
            debugInfo=(
                IndexTurnoverInsightDebugInfoDto(
                    candidateTradeDateCount=candidate_count or 0,
                    scannedFileCount=0,
                    scannedRowCount=0,
                    exceptions=[exception],
                )
                if debug
                else None
            ),
        )

    def _response(
        self,
        *,
        context: MarketPageContext,
        observed_trade_date: date | None,
        previous_observed_trade_date: date | None,
        resolution,
        panels: tuple[IndexTurnoverInsightPanelDto, ...],
        debug: bool,
        candidates: tuple[IndexTurnoverInsightCalendarDay, ...],
        result: MajorIndexTurnoverReadResult,
        exceptions: list[IndexTurnoverInsightExceptionDto],
    ) -> IndexTurnoverInsightResponseDto:
        expected_identities = tuple(
            (identity.ts_code, identity.index_name)
            for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE
        )
        actual_identities = tuple(
            (panel.tsCode, panel.indexName) for panel in panels
        )
        if actual_identities != expected_identities:
            raise RuntimeError("index turnover insight response order drifted")
        return IndexTurnoverInsightResponseDto(
            status=resolution.status,
            tradingDay=self._trading_day(
                context,
                observed_trade_date,
                previous_observed_trade_date,
            ),
            asOf=(
                f"盘后数据 · {observed_trade_date.isoformat()}"
                if observed_trade_date is not None
                else None
            ),
            indices=list(panels),
            message=resolution.message,
            exceptionCode=resolution.exception_code,
            debugInfo=(
                IndexTurnoverInsightDebugInfoDto(
                    candidateTradeDateCount=len(candidates),
                    scannedFileCount=result.scanned_file_count,
                    scannedRowCount=result.scanned_row_count,
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    @staticmethod
    def _trading_day(
        context: MarketPageContext,
        observed_trade_date: date | None,
        previous_observed_trade_date: date | None,
    ) -> IndexTurnoverInsightTradingDayDto:
        return IndexTurnoverInsightTradingDayDto(
            market="CN_A",
            expectedTradeDate=context.trade_date,
            observedTradeDate=observed_trade_date,
            previousObservedTradeDate=previous_observed_trade_date,
            isTradingDay=context.is_trading_day,
            sessionStatus=context.session_status,  # type: ignore[arg-type]
            generatedAt=context.generated_at,
        )
