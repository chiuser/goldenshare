from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.limit_up import (
    LimitHistoryByRangeDto,
    LimitHistoryPointDto,
    LimitLeaderPerformanceItemDto,
    LimitSectorItemDto,
    LimitStructureBlockDto,
    LimitSummaryCardItemDto,
    LimitUpDebugInfoDto,
    LimitUpPayloadDto,
    LimitUpSummaryResponseDto,
    PageStatusDto,
    TradingDayDto,
)
from src.biz.services.wealth.config import (
    LimitUpStrategyPayload,
    StrategyConfigNotFoundError,
    StrategyConfigService,
    StrategyConfigValidationError,
)
from src.biz.services.wealth.market.limit_up.limit_up_exception_builder import LimitUpExceptionBuilder
from src.biz.services.wealth.market.limit_up.limit_up_status_resolver import (
    EXPECTED_1M_POINTS,
    EXPECTED_3M_POINTS,
    LimitUpStatusResolver,
)
from .limit_up_history_query import LimitHistoryPoint, LimitUpHistoryQuery
from .limit_up_state_query import LimitUpSourceState, LimitUpStateQuery, LimitUpTradingDayContext
from .limit_up_structure_query import LimitStructureResult, LimitUpStructureQuery
from .limit_up_summary_query import LimitUpSummaryFacts, LimitUpSummaryQuery


@dataclass(frozen=True, slots=True)
class LimitUpDefinition:
    version: str
    st_excluded_sector_codes: tuple[str, ...]
    recent_limit_window_days: int


class LimitUpQueryService:
    """Orchestrate limit-up module response assembly."""

    def __init__(self) -> None:
        self._config_service = StrategyConfigService()
        self._state_query = LimitUpStateQuery()
        self._summary_query = LimitUpSummaryQuery()
        self._history_query = LimitUpHistoryQuery()
        self._status_resolver = LimitUpStatusResolver()
        self._exception_builder = LimitUpExceptionBuilder()

    def build_limit_up(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> LimitUpSummaryResponseDto:
        exceptions = []
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        source_state = self._state_query.load_source_state(session)

        try:
            definition = self._load_definition(market=market)
        except (StrategyConfigNotFoundError, StrategyConfigValidationError, ValueError) as exc:
            exceptions.append(self._exception_builder.query_failed(message=str(exc)))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=source_state,
                debug=debug,
                exceptions=exceptions,
            )

        structure_query = LimitUpStructureQuery(
            st_excluded_sector_codes=definition.st_excluded_sector_codes,
            recent_limit_window_days=definition.recent_limit_window_days,
        )

        try:
            summary_facts = self._summary_query.load(
                session,
                trade_date=trading_day_context.expected_trade_date,
            )
            today_structure = structure_query.load(
                session,
                trade_date=trading_day_context.expected_trade_date,
            )
            yesterday_trade_date = trading_day_context.prev_trade_date or trading_day_context.expected_trade_date
            yesterday_structure = structure_query.load(
                session,
                trade_date=yesterday_trade_date,
            )
            recent_trade_dates = self._history_query.load_recent_trade_dates(
                session,
                end_trade_date=trading_day_context.expected_trade_date,
                limit_days=EXPECTED_3M_POINTS,
            )
            history_points_3m = self._history_query.load_history_points(
                session,
                trade_dates=recent_trade_dates,
            )
        except Exception as exc:  # noqa: BLE001
            exceptions.append(self._exception_builder.query_failed(message=f"limit-up query failed: {exc}"))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=source_state,
                debug=debug,
                exceptions=exceptions,
            )

        history_points_1m = history_points_3m[-EXPECTED_1M_POINTS:]
        has_today_structure = self._has_structure_content(today_structure)
        has_yesterday_structure = self._has_structure_content(yesterday_structure)

        status_result = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=source_state.observed_trade_date,
            has_summary_data=summary_facts.has_summary_data,
            history_points_1m=len(history_points_1m),
            history_points_3m=len(history_points_3m),
            has_today_structure=has_today_structure,
            has_yesterday_structure=has_yesterday_structure,
            as_of_time=trading_day_context.as_of_time,
        )

        if status_result.module_status.status == "DELAYED" and source_state.observed_trade_date is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="limit-up source date lagged",
                    expected_trade_date=trading_day_context.expected_trade_date.isoformat(),
                    observed_trade_date=source_state.observed_trade_date.isoformat(),
                )
            )
        if status_result.module_status.status == "EMPTY":
            exceptions.append(
                self._exception_builder.source_empty(
                    message="limit-up source has no usable rows",
                )
            )
        if status_result.structure_incomplete:
            if not has_today_structure:
                exceptions.append(
                    self._exception_builder.distribution_mapping_missing(
                        message="today distribution mapping unavailable",
                        trade_date=trading_day_context.expected_trade_date.isoformat(),
                        block="today",
                    )
                )
            if not has_yesterday_structure:
                exceptions.append(
                    self._exception_builder.distribution_mapping_missing(
                        message="yesterday distribution mapping unavailable",
                        trade_date=(trading_day_context.prev_trade_date or trading_day_context.expected_trade_date).isoformat(),
                        block="yesterday",
                    )
                )
        if status_result.history_incomplete:
            exceptions.append(
                self._exception_builder.history_incomplete(
                    message="limit-up history points are incomplete",
                    actual_points_1m=len(history_points_1m),
                    expected_points_1m=EXPECTED_1M_POINTS,
                    actual_points_3m=len(history_points_3m),
                    expected_points_3m=EXPECTED_3M_POINTS,
                )
            )
        if summary_facts.sealing_rate_non_st is None and summary_facts.has_summary_data:
            exceptions.append(
                self._exception_builder.seal_rate_denom_zero(
                    message="sealing rate denominator is zero",
                    non_st_limit_up=summary_facts.non_st_limit_up,
                    non_st_broken=summary_facts.non_st_broken,
                )
            )

        return LimitUpSummaryResponseDto(
            tradingDay=self._build_trading_day(trading_day_context=trading_day_context),
            pageStatus=status_result.page_status,
            limitUp=LimitUpPayloadDto(
                tradeDate=trading_day_context.expected_trade_date,
                summaryCards=self._build_summary_cards(summary_facts=summary_facts),
                todayStructure=self._to_structure_dto(today_structure),
                yesterdayStructure=self._to_structure_dto(yesterday_structure),
                historyPoints=LimitHistoryByRangeDto(
                    oneMonth=self._to_history_points(history_points_1m),
                    threeMonth=self._to_history_points(history_points_3m),
                ),
            ),
            debugInfo=(
                LimitUpDebugInfoDto(
                    modules=[status_result.module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    def _load_definition(self, *, market: str) -> LimitUpDefinition:
        payload = self._config_service.get_payload(module_key="limitUp", market=market)
        version = self._config_service.get_version(module_key="limitUp", market=market)
        if not isinstance(payload, LimitUpStrategyPayload):
            raise StrategyConfigValidationError("limitUp payload model mismatch")
        return LimitUpDefinition(
            version=version,
            st_excluded_sector_codes=tuple(payload.st_excluded_sector_codes),
            recent_limit_window_days=payload.recent_limit_window_days,
        )

    @staticmethod
    def _build_trading_day(*, trading_day_context: LimitUpTradingDayContext) -> TradingDayDto:
        return TradingDayDto(
            tradeDate=trading_day_context.expected_trade_date,
            prevTradeDate=trading_day_context.prev_trade_date,
            market="CN_A",
            isTradingDay=trading_day_context.is_trading_day,
            sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
            timezone="Asia/Shanghai",
        )

    @staticmethod
    def _build_summary_cards(*, summary_facts: LimitUpSummaryFacts) -> list[LimitSummaryCardItemDto]:
        sealing_rate_value = round(summary_facts.sealing_rate_non_st * 100, 1) if summary_facts.sealing_rate_non_st is not None else None
        return [
            LimitSummaryCardItemDto(
                key="limitUpCount",
                label="涨停家数",
                value=f"{summary_facts.limit_up_total}/{summary_facts.limit_up_st}",
                direction="UP",
                subText="总涨停家数/ST涨停家数",
            ),
            LimitSummaryCardItemDto(
                key="limitDownCount",
                label="跌停家数",
                value=f"{summary_facts.limit_down_total}/{summary_facts.limit_down_st}",
                direction="DOWN",
                subText="总跌停家数/ST跌停家数",
            ),
            LimitSummaryCardItemDto(
                key="brokenLimitCount",
                label="炸板家数",
                value=f"{summary_facts.broken_total}/{summary_facts.broken_st}",
                direction="FLAT",
                subText="总炸板家数/ST炸板家数",
            ),
            LimitSummaryCardItemDto(
                key="sealingRate",
                label="封板率",
                value=sealing_rate_value,
                unit="%",
                direction="UP" if sealing_rate_value is not None else "UNKNOWN",
                subText="非ST口径",
            ),
            LimitSummaryCardItemDto(
                key="streakCount",
                label="连板家数",
                value=summary_facts.streak_count,
                unit="只",
                direction="UP",
                subText="二板及以上",
            ),
            LimitSummaryCardItemDto(
                key="maxBoard",
                label="最高连板",
                value=summary_facts.max_board,
                unit="板",
                direction="UP",
                subText="五板及以上合并展示",
            ),
            LimitSummaryCardItemDto(
                key="skyToFloorCount",
                label="天地板",
                value=summary_facts.sky_to_floor_count,
                unit="只",
                direction="DOWN",
                subText="高风险结构",
            ),
            LimitSummaryCardItemDto(
                key="floorToSkyCount",
                label="地天板",
                value=summary_facts.floor_to_sky_count,
                unit="只",
                direction="UP",
                subText="反包结构",
            ),
        ]

    @staticmethod
    def _to_structure_dto(result: LimitStructureResult) -> LimitStructureBlockDto:
        return LimitStructureBlockDto(
            tradeDate=result.trade_date,
            selectedSectorCode=result.selected_sector_code,
            selectedStockCode=result.selected_stock_code,
            sectors=[
                LimitSectorItemDto(
                    sectorCode=item.sector_code,
                    sectorName=item.sector_name,
                    sectorType=item.sector_type,  # type: ignore[arg-type]
                    limitUpCount=item.limit_up_count,
                )
                for item in result.sectors
            ],
            leaderStocks={
                sector_code: [
                    LimitLeaderPerformanceItemDto(
                        stockCode=item.stock_code,
                        stockName=item.stock_name,
                        latestPrice=item.latest_price,
                        changePct=item.change_pct,
                        rank=item.rank,
                        streakLabel=item.streak_label,
                        recentLimitText=item.recent_limit_text,
                        firstLimitTime=item.first_limit_time,
                        openTimes=item.open_times,
                        sealedAmountDisplayText=item.sealed_amount_display_text,
                    )
                    for item in leaders
                ]
                for sector_code, leaders in result.leader_stocks.items()
            },
        )

    @staticmethod
    def _to_history_points(points: list[LimitHistoryPoint]) -> list[LimitHistoryPointDto]:
        return [
            LimitHistoryPointDto(
                tradeDate=item.trade_date,
                limitUpCount=item.limit_up_count,
                limitDownCount=item.limit_down_count,
            )
            for item in points
        ]

    @staticmethod
    def _has_structure_content(result: LimitStructureResult) -> bool:
        if not result.sectors:
            return False
        if not result.selected_sector_code:
            return False
        selected_rows = result.leader_stocks.get(result.selected_sector_code, [])
        return bool(selected_rows)

    def _build_error_response(
        self,
        *,
        trading_day_context: LimitUpTradingDayContext,
        source_state: LimitUpSourceState,
        debug: bool,
        exceptions: list,
    ) -> LimitUpSummaryResponseDto:
        lag_days = None
        if source_state.observed_trade_date is not None:
            lag_days = (trading_day_context.expected_trade_date - source_state.observed_trade_date).days
            if lag_days < 0:
                lag_days = 0
        module_status = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=source_state.observed_trade_date,
            has_summary_data=False,
            history_points_1m=0,
            history_points_3m=0,
            has_today_structure=False,
            has_yesterday_structure=False,
            as_of_time=trading_day_context.as_of_time,
        ).module_status
        module_status = module_status.model_copy(update={"status": "ERROR", "note": "module failed to load", "lagDays": lag_days})

        empty_structure = LimitStructureResult(
            trade_date=trading_day_context.expected_trade_date,
            selected_sector_code="",
            selected_stock_code="",
            sectors=[],
            leader_stocks={},
        )
        empty_summary = LimitUpSummaryFacts(
            limit_up_total=0,
            limit_up_st=0,
            limit_down_total=0,
            limit_down_st=0,
            broken_total=0,
            broken_st=0,
            non_st_limit_up=0,
            non_st_broken=0,
            sealing_rate_non_st=None,
            streak_count=0,
            max_board=0,
            sky_to_floor_count=0,
            floor_to_sky_count=0,
        )

        return LimitUpSummaryResponseDto(
            tradingDay=self._build_trading_day(trading_day_context=trading_day_context),
            pageStatus=PageStatusDto(
                status="ERROR",
                displayText="模块加载失败",
                asOfTime=trading_day_context.as_of_time,
            ),
            limitUp=LimitUpPayloadDto(
                tradeDate=trading_day_context.expected_trade_date,
                summaryCards=self._build_summary_cards(summary_facts=empty_summary),
                todayStructure=self._to_structure_dto(empty_structure),
                yesterdayStructure=self._to_structure_dto(empty_structure),
                historyPoints=LimitHistoryByRangeDto(oneMonth=[], threeMonth=[]),
            ),
            debugInfo=(
                LimitUpDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )
