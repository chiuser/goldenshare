from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.leaderboards import (
    LeaderboardBoardDto,
    LeaderboardDebugInfoDto,
    LeaderboardDefinitionDto,
    LeaderboardMetricsDto,
    LeaderboardRowDto,
    LeaderboardsResponseDto,
    LeaderboardSubjectDto,
    PageStatusDto,
    TradingDayDto,
)
from src.biz.services.wealth.config import StrategyConfigNotFoundError, StrategyConfigValidationError
from src.biz.services.wealth.market.leaderboards.exception_builder import LeaderboardExceptionBuilder
from src.biz.services.wealth.market.leaderboards.status_resolver import (
    LeaderboardBoardStatusResult,
    LeaderboardStatusResolver,
)
from src.biz.services.wealth.market.leaderboards.strategy_config_resolver import (
    LeaderboardDefinition,
    LeaderboardStrategyConfig,
    LeaderboardStrategyConfigResolver,
)
from .dc_hot_rankings_query import DcHotRankingResult, LeaderboardDcHotRankingsQuery
from .equity_rankings_query import EquityBoardKey, EquityRankingRow, LeaderboardEquityRankingsQuery
from .leaderboards_state_query import LeaderboardsSourceState, LeaderboardsStateQuery, LeaderboardsTradingDayContext
from .stock_pool_query import LeaderboardStockPoolQuery


_DEFAULT_DEFINITIONS: tuple[LeaderboardDefinition, ...] = (
    LeaderboardDefinition(board_key="gainers", board_label="涨幅榜"),
    LeaderboardDefinition(board_key="losers", board_label="跌幅榜"),
    LeaderboardDefinition(board_key="amount", board_label="成交额榜"),
    LeaderboardDefinition(board_key="turnover", board_label="换手榜"),
    LeaderboardDefinition(board_key="volumeRatio", board_label="量比榜"),
    LeaderboardDefinition(board_key="popularity", board_label="人气榜"),
    LeaderboardDefinition(board_key="surge", board_label="飙升榜"),
)

_EQUITY_BOARD_KEYS: set[str] = {"gainers", "losers", "amount", "turnover", "volumeRatio"}
_HOT_BOARD_KEYS: set[str] = {"popularity", "surge"}


class MarketLeaderboardsQueryService:
    """Orchestrate leaderboards module response assembly."""

    def __init__(self) -> None:
        self._state_query = LeaderboardsStateQuery()
        self._stock_pool_query = LeaderboardStockPoolQuery()
        self._equity_rankings_query = LeaderboardEquityRankingsQuery()
        self._dc_hot_rankings_query = LeaderboardDcHotRankingsQuery()
        self._strategy_resolver = LeaderboardStrategyConfigResolver()
        self._status_resolver = LeaderboardStatusResolver()
        self._exception_builder = LeaderboardExceptionBuilder()

    def build_leaderboards(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        limit: int | None,
        debug: bool,
    ) -> LeaderboardsResponseDto:
        exceptions = []
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        source_state = self._state_query.load_source_state(session)

        try:
            strategy = self._strategy_resolver.resolve(market=market)
        except (StrategyConfigNotFoundError, StrategyConfigValidationError, ValueError) as exc:
            exceptions.append(self._exception_builder.query_failed(message=str(exc), board_key="definitions"))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=source_state,
                definitions=_DEFAULT_DEFINITIONS,
                debug=debug,
                exceptions=exceptions,
            )

        effective_limit = int(limit if limit is not None else strategy.default_limit)

        stock_pool_codes: set[str] | None = None
        stock_pool_error: str | None = None
        try:
            if any(item.board_key in _EQUITY_BOARD_KEYS for item in strategy.definitions):
                stock_pool_codes = self._stock_pool_query.load_codes(
                    session,
                    trade_date=trading_day_context.expected_trade_date,
                )
            else:
                stock_pool_codes = set()
        except Exception as exc:  # noqa: BLE001
            stock_pool_codes = None
            stock_pool_error = str(exc)

        board_dtos: list[LeaderboardBoardDto] = []
        board_statuses: list[str] = []
        observed_dates: list[date] = []

        for definition in strategy.definitions:
            if definition.board_key in _EQUITY_BOARD_KEYS:
                board_dto, board_exceptions = self._build_equity_board(
                    session,
                    trading_day_context=trading_day_context,
                    definition=definition,
                    source_state=source_state,
                    stock_pool_codes=stock_pool_codes,
                    stock_pool_error=stock_pool_error,
                    limit=effective_limit,
                )
            elif definition.board_key in _HOT_BOARD_KEYS:
                board_dto, board_exceptions = self._build_hot_board(
                    session,
                    trading_day_context=trading_day_context,
                    definition=definition,
                    source_state=source_state,
                    strategy=strategy,
                    limit=effective_limit,
                )
            else:
                board_dto = self._build_error_board(
                    definition=definition,
                    expected_trade_date=trading_day_context.expected_trade_date,
                    observed_trade_date=None,
                    note=f"unsupported board key: {definition.board_key}",
                )
                board_exceptions = [
                    self._exception_builder.query_failed(
                        message=f"unsupported board key: {definition.board_key}",
                        board_key=definition.board_key,
                    )
                ]

            board_dtos.append(board_dto)
            board_statuses.append(board_dto.status)
            if board_dto.observedTradeDate is not None:
                observed_dates.append(board_dto.observedTradeDate)
            exceptions.extend(board_exceptions)

        page_status = self._status_resolver.resolve_page_status(
            board_statuses=board_statuses,
            as_of_time=trading_day_context.as_of_time,
        )
        overall_observed_trade_date = max(observed_dates) if observed_dates else None
        module_status = self._status_resolver.build_module_status(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=overall_observed_trade_date,
            status=page_status.status,
            note=page_status.displayText,
        )

        return LeaderboardsResponseDto(
            tradingDay=self._build_trading_day(trading_day_context=trading_day_context),
            pageStatus=page_status,
            definitions=[
                LeaderboardDefinitionDto(boardKey=item.board_key, boardLabel=item.board_label)
                for item in strategy.definitions
            ],
            boards=board_dtos,
            debugInfo=(
                LeaderboardDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    def _build_equity_board(
        self,
        session: Session,
        *,
        trading_day_context: LeaderboardsTradingDayContext,
        definition: LeaderboardDefinition,
        source_state: LeaderboardsSourceState,
        stock_pool_codes: set[str] | None,
        stock_pool_error: str | None,
        limit: int,
    ) -> tuple[LeaderboardBoardDto, list]:
        exceptions = []
        expected_trade_date = trading_day_context.expected_trade_date

        if stock_pool_error is not None or stock_pool_codes is None:
            board_dto = self._build_error_board(
                definition=definition,
                expected_trade_date=expected_trade_date,
                observed_trade_date=source_state.daily_source_date,
                note="stock pool query failed",
            )
            exceptions.append(
                self._exception_builder.query_failed(
                    message=f"stock pool query failed: {stock_pool_error}",
                    board_key=definition.board_key,
                )
            )
            return board_dto, exceptions

        try:
            rows = self._equity_rankings_query.load_board_rows(
                session,
                trade_date=expected_trade_date,
                board_key=definition.board_key,  # type: ignore[arg-type]
                stock_pool_codes=stock_pool_codes,
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            board_dto = self._build_error_board(
                definition=definition,
                expected_trade_date=expected_trade_date,
                observed_trade_date=source_state.daily_source_date,
                note="equity ranking query failed",
            )
            exceptions.append(
                self._exception_builder.query_failed(
                    message=f"equity ranking query failed: {exc}",
                    board_key=definition.board_key,
                )
            )
            return board_dto, exceptions

        status_result = self._status_resolver.resolve_board_status(
            expected_trade_date=expected_trade_date,
            observed_trade_date=source_state.daily_source_date,
            row_count=len(rows),
            delayed_as_empty=False,
        )
        exceptions.extend(
            self._build_status_exceptions(
                board_key=definition.board_key,
                status_result=status_result,
            )
        )

        has_name_missing = False
        has_metric_missing = False
        first_missing_name_code: str | None = None
        first_missing_metric_code: str | None = None
        row_dtos: list[LeaderboardRowDto] = []
        for index, row in enumerate(rows):
            if row.subject_name is None or not row.subject_name.strip():
                has_name_missing = True
                if first_missing_name_code is None:
                    first_missing_name_code = row.ts_code
            if definition.board_key == "turnover" and row.turnover_rate is None:
                has_metric_missing = True
                if first_missing_metric_code is None:
                    first_missing_metric_code = row.ts_code
            if definition.board_key == "volumeRatio" and row.volume_ratio is None:
                has_metric_missing = True
                if first_missing_metric_code is None:
                    first_missing_metric_code = row.ts_code

            row_dtos.append(
                self._build_row_dto(
                    rank=index + 1,
                    ts_code=row.ts_code,
                    subject_name=row.subject_name,
                    latest_price=row.latest_price,
                    change_pct=row.change_pct,
                    turnover_rate=row.turnover_rate,
                    volume_ratio=row.volume_ratio,
                    volume=row.volume,
                    amount=row.amount,
                )
            )

        if has_name_missing and first_missing_name_code is not None:
            exceptions.append(
                self._exception_builder.subject_name_missing(
                    message="subject name missing, fallback to code",
                    board_key=definition.board_key,
                    subject_code=first_missing_name_code,
                )
            )
        if has_metric_missing and first_missing_metric_code is not None:
            exceptions.append(
                self._exception_builder.join_metric_missing(
                    message="metric join missing, fallback to '--'",
                    board_key=definition.board_key,
                    subject_code=first_missing_metric_code,
                )
            )

        board_dto = LeaderboardBoardDto(
            boardKey=definition.board_key,  # type: ignore[arg-type]
            boardLabel=definition.board_label,
            status=status_result.status,  # type: ignore[arg-type]
            expectedTradeDate=status_result.expected_trade_date,
            observedTradeDate=status_result.observed_trade_date,
            lagDays=status_result.lag_days,
            rows=row_dtos,
        )
        return board_dto, exceptions

    def _build_hot_board(
        self,
        session: Session,
        *,
        trading_day_context: LeaderboardsTradingDayContext,
        definition: LeaderboardDefinition,
        source_state: LeaderboardsSourceState,
        strategy: LeaderboardStrategyConfig,
        limit: int,
    ) -> tuple[LeaderboardBoardDto, list]:
        exceptions = []
        expected_trade_date = trading_day_context.expected_trade_date

        try:
            hot_result = self._dc_hot_rankings_query.load_board_rows(
                session,
                expected_trade_date=expected_trade_date,
                board_key=definition.board_key,  # type: ignore[arg-type]
                limit=limit,
                strict_hot_date=strategy.strict_hot_date,
            )
        except Exception as exc:  # noqa: BLE001
            board_dto = self._build_error_board(
                definition=definition,
                expected_trade_date=expected_trade_date,
                observed_trade_date=source_state.hot_source_date,
                note="dc_hot ranking query failed",
            )
            exceptions.append(
                self._exception_builder.query_failed(
                    message=f"dc_hot ranking query failed: {exc}",
                    board_key=definition.board_key,
                )
            )
            return board_dto, exceptions

        status_result = self._status_resolver.resolve_board_status(
            expected_trade_date=expected_trade_date,
            observed_trade_date=hot_result.observed_trade_date,
            row_count=len(hot_result.rows),
            delayed_as_empty=strategy.strict_hot_date,
        )
        exceptions.extend(
            self._build_status_exceptions(
                board_key=definition.board_key,
                status_result=status_result,
            )
        )
        if hot_result.used_fallback and hot_result.observed_trade_date is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="dc_hot fallback date applied",
                    board_key=definition.board_key,
                    expected_trade_date=expected_trade_date.isoformat(),
                    observed_trade_date=hot_result.observed_trade_date.isoformat(),
                )
            )

        row_dtos = [
            self._build_row_dto(
                rank=row.rank if row.rank is not None else index + 1,
                ts_code=row.ts_code,
                subject_name=row.subject_name,
                latest_price=row.latest_price,
                change_pct=row.change_pct,
                turnover_rate=None,
                volume_ratio=None,
                volume=None,
                amount=None,
            )
            for index, row in enumerate(hot_result.rows)
        ]
        board_dto = LeaderboardBoardDto(
            boardKey=definition.board_key,  # type: ignore[arg-type]
            boardLabel=definition.board_label,
            status=status_result.status,  # type: ignore[arg-type]
            expectedTradeDate=status_result.expected_trade_date,
            observedTradeDate=status_result.observed_trade_date,
            lagDays=status_result.lag_days,
            rows=row_dtos,
        )
        return board_dto, exceptions

    def _build_status_exceptions(
        self,
        *,
        board_key: str,
        status_result: LeaderboardBoardStatusResult,
    ) -> list:
        exceptions = []
        if status_result.status == "DELAYED":
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="board source delayed",
                    board_key=board_key,
                    expected_trade_date=status_result.expected_trade_date.isoformat(),
                    observed_trade_date=(
                        status_result.observed_trade_date.isoformat()
                        if status_result.observed_trade_date is not None
                        else None
                    ),
                )
            )
        if status_result.status == "EMPTY":
            exceptions.append(
                self._exception_builder.source_empty(
                    message="board source empty",
                    board_key=board_key,
                    trade_date=status_result.expected_trade_date.isoformat(),
                )
            )
        return exceptions

    def _build_error_board(
        self,
        *,
        definition: LeaderboardDefinition,
        expected_trade_date: date,
        observed_trade_date: date | None,
        note: str,
    ) -> LeaderboardBoardDto:
        lag_days = None
        if observed_trade_date is not None:
            lag_days = (expected_trade_date - observed_trade_date).days
            if lag_days < 0:
                lag_days = 0
        return LeaderboardBoardDto(
            boardKey=definition.board_key,  # type: ignore[arg-type]
            boardLabel=definition.board_label,
            status="ERROR",
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
            lagDays=lag_days,
            rows=[],
        )

    @staticmethod
    def _build_trading_day(
        *,
        trading_day_context: LeaderboardsTradingDayContext,
    ) -> TradingDayDto:
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
        trading_day_context: LeaderboardsTradingDayContext,
        source_state: LeaderboardsSourceState,
        definitions: tuple[LeaderboardDefinition, ...],
        debug: bool,
        exceptions: list,
    ) -> LeaderboardsResponseDto:
        expected_trade_date = trading_day_context.expected_trade_date
        observed_candidates = [item for item in (source_state.daily_source_date, source_state.hot_source_date) if item is not None]
        observed_trade_date = max(observed_candidates) if observed_candidates else None
        module_status = self._status_resolver.build_module_status(
            expected_trade_date=expected_trade_date,
            observed_trade_date=observed_trade_date,
            status="ERROR",
            note="module failed to load",
        )
        return LeaderboardsResponseDto(
            tradingDay=self._build_trading_day(trading_day_context=trading_day_context),
            pageStatus=PageStatusDto(status="ERROR", displayText="模块加载失败", asOfTime=trading_day_context.as_of_time),
            definitions=[
                LeaderboardDefinitionDto(boardKey=item.board_key, boardLabel=item.board_label)
                for item in definitions
            ],
            boards=[
                self._build_error_board(
                    definition=item,
                    expected_trade_date=expected_trade_date,
                    observed_trade_date=observed_trade_date,
                    note="module failed to load",
                )
                for item in definitions
            ],
            debugInfo=(
                LeaderboardDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    @staticmethod
    def _build_row_dto(
        *,
        rank: int,
        ts_code: str,
        subject_name: str | None,
        latest_price,
        change_pct,
        turnover_rate,
        volume_ratio,
        volume,
        amount,
    ) -> LeaderboardRowDto:
        change_pct_float = float(change_pct) if change_pct is not None else None
        if change_pct_float is None:
            direction = "UNKNOWN"
        elif change_pct_float > 0:
            direction = "UP"
        elif change_pct_float < 0:
            direction = "DOWN"
        else:
            direction = "FLAT"

        return LeaderboardRowDto(
            rank=rank,
            subject=LeaderboardSubjectDto(
                subjectType="stock",
                subjectCode=ts_code,
                subjectName=subject_name,
            ),
            metrics=LeaderboardMetricsDto(
                latestPrice=float(latest_price) if latest_price is not None else None,
                changePct=change_pct_float,
                turnoverRate=float(turnover_rate) if turnover_rate is not None else None,
                volumeRatio=float(volume_ratio) if volume_ratio is not None else None,
                volume=float(volume) if volume is not None else None,
                amount=float(amount) if amount is not None else None,
                direction=direction,  # type: ignore[arg-type]
            ),
        )

