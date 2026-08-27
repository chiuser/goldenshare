from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchyQuery,
    SectorHierarchySnapshot,
    SectorHierarchyUnavailableError,
)
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_meta_query import (
    SectorAnalysisMetaQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_query import (
    SectorMomentumQuery,
)
from src.biz.schemas.wealth.market.sector_analysis import (
    HistoricalRankPointDto,
    RollingReturnPointDto,
    SectorAnalysisDebugInfoDto,
    SectorAnalysisMetaResponseDto,
    SectorAnalysisPageStatusDto,
    SectorAnalysisTradingDayDto,
    SectorFormulaDto,
    SectorHierarchyDto,
    SectorHierarchyNodeDto,
    SectorMomentumDetailDto,
    SectorMomentumHistoryResponseDto,
    SectorMomentumRankingsResponseDto,
    SectorParentSelectionDto,
    SectorRankingDto,
    SectorRankingRowDto,
    SectorTradeDateAvailabilityDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_analysis_status_resolver import (
    SectorAnalysisStatusResolution,
    SectorAnalysisStatusResolver,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_calculator import (
    SectorMomentumCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    ALLOWED_DIRECTIONS,
    ALLOWED_HISTORY_RANGES,
    ALLOWED_PERIODS,
    ALLOWED_SCOPES,
    FORMULA_KEY,
    FORMULA_VERSION,
    SectorDailyFact,
    SectorHistoryRange,
    SectorMomentumDirection,
    SectorMomentumPeriod,
    SectorMomentumScope,
    SectorRankFact,
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
    SectorTradingDateResolution,
    global_level_pool,
    parent_pool,
    resolve_scope_pool,
    scope_title,
)


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


class SectorMomentumQueryService:
    """Compose the immutable hierarchy, date coverage and price-only facts."""

    def __init__(
        self,
        *,
        context_query: MarketPageContextQuery | None = None,
        hierarchy_query: SectorHierarchyQuery | None = None,
        meta_query: SectorAnalysisMetaQuery | None = None,
        momentum_query: SectorMomentumQuery | None = None,
        calculator: SectorMomentumCalculator | None = None,
        status_resolver: SectorAnalysisStatusResolver | None = None,
    ) -> None:
        self._context_query = context_query or MarketPageContextQuery()
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()
        self._meta_query = meta_query or SectorAnalysisMetaQuery()
        self._query = momentum_query or SectorMomentumQuery()
        self._calculator = calculator or SectorMomentumCalculator()
        self._status = status_resolver or SectorAnalysisStatusResolver()

    def build_meta(self, session: Session, *, market: str) -> SectorAnalysisMetaResponseDto:
        context = self._context_query.resolve_context(
            session,
            market=market,
            requested_trade_date=None,
        )
        hierarchy = self._hierarchy_query.load(session)
        all_codes = tuple(node.sector_code for node in hierarchy.nodes)
        coverage_start, coverage = self._meta_query.load_coverage(
            session,
            coverage_end_date=context.trade_date,
            sector_codes=all_codes,
        )
        return SectorAnalysisMetaResponseDto(
            formula=SectorFormulaDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                periods=list(ALLOWED_PERIODS),
                historyRanges=list(ALLOWED_HISTORY_RANGES),
                scopes=list(ALLOWED_SCOPES),
                directions=list(ALLOWED_DIRECTIONS),
            ),
            hierarchy=SectorHierarchyDto(
                hierarchyVersion=hierarchy.baseline_version,
                publishedAt=hierarchy.published_at,
                nodes=[self._hierarchy_node_dto(node) for node in hierarchy.nodes],
            ),
            coverageStartDate=coverage_start,
            coverageEndDate=context.trade_date,
            tradeDates=[
                SectorTradeDateAvailabilityDto(
                    tradeDate=item.trade_date,
                    availability=item.availability,
                    expectedSectorCount=item.expected_sector_count,
                    validSectorCount=item.valid_sector_count,
                )
                for item in coverage
            ],
        )

    def build_rankings(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
        period: SectorMomentumPeriod,
        direction: SectorMomentumDirection,
        debug: bool,
    ) -> SectorMomentumRankingsResponseDto:
        context: MarketPageContext | None = None
        resolution: SectorTradingDateResolution | None = None
        pool: tuple[SectorHierarchyNode, ...] = ()
        try:
            context = self._load_current_context(session, market=market)
            hierarchy = self._hierarchy_query.load(session)
            pool = resolve_scope_pool(
                hierarchy,
                scope=scope,
                level1_code=level1_code,
                level2_code=level2_code,
            )
            resolution = self._resolve_date(
                session,
                context=context,
                requested_trade_date=trade_date,
                hierarchy=hierarchy,
            )
            if (
                resolution.observed is None
                or resolution.observed.availability == "MISSING"
            ):
                return self._empty_rankings_response(
                    context=context,
                    resolution=resolution,
                    scope=scope,
                    pool=pool,
                    debug=debug,
                )

            open_dates = self._query.load_open_dates(
                session,
                end_date=resolution.observed.trade_date,
                count=1 if period == 1 else period + 1,
            )
            facts = self._load_indexed_facts(
                session,
                nodes=pool,
                open_dates=open_dates,
            )
            ranked = self._calculate_ranked(
                nodes=pool,
                open_dates=open_dates,
                target_date=resolution.observed.trade_date,
                period=period,
                fact_index=facts,
            )
            calculable_count = sum(row.return_pct is not None for row in ranked)
            status = self._status.resolve(
                trading_day=resolution,
                calculable_count=calculable_count,
            )
            if status.status == "EMPTY":
                return self._empty_rankings_response(
                    context=context,
                    resolution=resolution,
                    scope=scope,
                    pool=pool,
                    debug=debug,
                )

            sorted_rows = self._calculator.sort_ranking_rows(ranked, direction=direction)
            node_by_code = {node.sector_code: node for node in pool}
            ranking = SectorRankingDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                hierarchyVersion=hierarchy.baseline_version,
                scope=scope,
                period=period,
                direction=direction,
                parentSelection=self._parent_selection(
                    hierarchy,
                    level1_code=level1_code,
                    level2_code=level2_code,
                ),
                totalCount=len(pool),
                calculableCount=calculable_count,
                rows=[
                    self._ranking_row(
                        list_position=index,
                        node=node_by_code[row.sector_code],
                        rank=row,
                        hierarchy=hierarchy,
                    )
                    for index, row in enumerate(sorted_rows, start=1)
                ],
            )
            return SectorMomentumRankingsResponseDto(
                status=status.status,
                tradingDay=self._trading_day(resolution),
                pageStatus=self._page_status(status, context=context),
                ranking=ranking,
                message=status.message,
                exceptionCode=status.exception_code,
                debugInfo=self._debug_info(
                    debug=debug,
                    resolution=resolution,
                    scope=scope,
                    pool=pool,
                ),
            )
        except (SectorScopeInvalidError, SectorSelectionInvalidError):
            raise
        except SectorHierarchyUnavailableError:
            return self._error_rankings_response(
                context=context,
                resolution=resolution,
                scope=scope,
                pool=pool,
                debug=debug,
                code="SA_HIERARCHY_UNAVAILABLE",
            )
        except Exception:  # noqa: BLE001
            return self._error_rankings_response(
                context=context,
                resolution=resolution,
                scope=scope,
                pool=pool,
                debug=debug,
                code="SA_QUERY_FAILED",
            )

    def build_history(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
        period: SectorMomentumPeriod,
        history_range: SectorHistoryRange,
        sector_code: str,
        debug: bool,
    ) -> SectorMomentumHistoryResponseDto:
        context: MarketPageContext | None = None
        resolution: SectorTradingDateResolution | None = None
        pool: tuple[SectorHierarchyNode, ...] = ()
        try:
            context = self._load_current_context(session, market=market)
            hierarchy = self._hierarchy_query.load(session)
            pool = resolve_scope_pool(
                hierarchy,
                scope=scope,
                level1_code=level1_code,
                level2_code=level2_code,
            )
            selected = next((node for node in pool if node.sector_code == sector_code), None)
            if selected is None:
                raise SectorSelectionInvalidError("sectorCode 不在当前比较范围内")
            resolution = self._resolve_date(
                session,
                context=context,
                requested_trade_date=trade_date,
                hierarchy=hierarchy,
            )
            if (
                resolution.observed is None
                or resolution.observed.availability == "MISSING"
            ):
                return self._empty_history_response(
                    context=context,
                    resolution=resolution,
                    scope=scope,
                    pool=pool,
                    debug=debug,
                )

            open_dates = self._query.load_open_dates(
                session,
                end_date=resolution.observed.trade_date,
                count=history_range + period,
            )
            open_dates = tuple(
                item for item in open_dates if item >= resolution.coverage_start_date
            )
            display_dates = open_dates[-history_range:]
            global_pool = global_level_pool(
                hierarchy,
                industry_level=selected.industry_level,
            )
            selected_parent_pool = parent_pool(hierarchy, node=selected)
            fact_nodes = self._union_nodes(pool, global_pool, selected_parent_pool or ())
            facts = self._load_indexed_facts(
                session,
                nodes=fact_nodes,
                open_dates=open_dates,
            )

            current_by_date = self._rank_by_date(
                nodes=pool,
                open_dates=open_dates,
                display_dates=display_dates,
                period=period,
                fact_index=facts,
            )
            observed_rank = self._find_rank(
                current_by_date[resolution.observed.trade_date],
                sector_code=selected.sector_code,
            )
            observed_calculable = self._calculable_count(
                current_by_date[resolution.observed.trade_date]
            )
            status = self._status.resolve(
                trading_day=resolution,
                calculable_count=observed_calculable,
            )
            if status.status == "EMPTY" or not display_dates:
                return self._empty_history_response(
                    context=context,
                    resolution=resolution,
                    scope=scope,
                    pool=pool,
                    debug=debug,
                )

            current_observed_ranked = current_by_date[resolution.observed.trade_date]
            global_ranked = (
                current_observed_ranked
                if self._same_pool(pool, global_pool)
                else self._calculate_ranked(
                    nodes=global_pool,
                    open_dates=open_dates,
                    target_date=resolution.observed.trade_date,
                    period=period,
                    fact_index=facts,
                )
            )
            parent_ranked = (
                current_observed_ranked
                if selected_parent_pool is not None
                and self._same_pool(pool, selected_parent_pool)
                else (
                    self._calculate_ranked(
                        nodes=selected_parent_pool,
                        open_dates=open_dates,
                        target_date=resolution.observed.trade_date,
                        period=period,
                        fact_index=facts,
                    )
                    if selected_parent_pool is not None
                    else None
                )
            )
            global_selected = self._find_rank(global_ranked, sector_code=sector_code)
            parent_selected = (
                self._find_rank(parent_ranked, sector_code=sector_code)
                if parent_ranked is not None
                else None
            )

            rolling_returns: list[RollingReturnPointDto] = []
            historical_ranks: list[HistoricalRankPointDto] = []
            for item in display_dates:
                ranked = current_by_date[item]
                selected_rank = self._find_rank(ranked, sector_code=sector_code)
                rolling_returns.append(
                    RollingReturnPointDto(
                        tradeDate=item,
                        returnPct=self._calculator.as_json_return(selected_rank.return_pct),
                    )
                )
                historical_ranks.append(
                    HistoricalRankPointDto(
                        tradeDate=item,
                        strengthRank=selected_rank.strength_rank,
                        calculableCount=self._calculable_count(ranked),
                        totalCount=len(pool),
                        percentile=self._calculator.as_json_percentile(selected_rank.percentile),
                    )
                )

            detail = SectorMomentumDetailDto(
                sectorCode=selected.sector_code,
                sectorName=selected.sector_name,
                industryLevel=selected.industry_level,  # type: ignore[arg-type]
                hierarchyPath=selected.hierarchy_path,
                scopeTitle=scope_title(
                    scope=scope,
                    level1_name=self._node_name(hierarchy, level1_code),
                    level2_name=self._node_name(hierarchy, level2_code),
                ),
                returnPct=self._calculator.as_json_return(observed_rank.return_pct),
                percentile=self._calculator.as_json_percentile(observed_rank.percentile),
                currentScopeStrengthRank=observed_rank.strength_rank,
                currentScopeCalculableCount=observed_calculable,
                currentScopeTotalCount=len(pool),
                globalLevelStrengthRank=global_selected.strength_rank,
                globalLevelCalculableCount=self._calculable_count(global_ranked),
                globalLevelTotalCount=len(global_pool),
                parentStrengthRank=parent_selected.strength_rank if parent_selected else None,
                parentCalculableCount=(
                    self._calculable_count(parent_ranked) if parent_ranked is not None else None
                ),
                parentTotalCount=(len(selected_parent_pool) if selected_parent_pool is not None else None),
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                hierarchyVersion=hierarchy.baseline_version,
            )
            return SectorMomentumHistoryResponseDto(
                status=status.status,
                tradingDay=self._trading_day(resolution),
                pageStatus=self._page_status(status, context=context),
                detail=detail,
                rollingReturns=rolling_returns,
                historicalRanks=historical_ranks,
                message=status.message,
                exceptionCode=status.exception_code,
                debugInfo=self._debug_info(
                    debug=debug,
                    resolution=resolution,
                    scope=scope,
                    pool=pool,
                ),
            )
        except (SectorScopeInvalidError, SectorSelectionInvalidError):
            raise
        except SectorHierarchyUnavailableError:
            return self._error_history_response(
                context=context,
                resolution=resolution,
                scope=scope,
                pool=pool,
                debug=debug,
                code="SA_HIERARCHY_UNAVAILABLE",
            )
        except Exception:  # noqa: BLE001
            return self._error_history_response(
                context=context,
                resolution=resolution,
                scope=scope,
                pool=pool,
                debug=debug,
                code="SA_QUERY_FAILED",
            )

    def _resolve_date(
        self,
        session: Session,
        *,
        context: MarketPageContext,
        requested_trade_date: date | None,
        hierarchy: SectorHierarchySnapshot,
    ) -> SectorTradingDateResolution:
        return self._query.resolve_trading_date(
            session,
            expected_trade_date=requested_trade_date or context.trade_date,
            coverage_end_date=context.trade_date,
            sector_codes=tuple(node.sector_code for node in hierarchy.nodes),
            is_explicit=requested_trade_date is not None,
        )

    def _load_current_context(self, session: Session, *, market: str) -> MarketPageContext:
        return self._context_query.resolve_context(
            session,
            market=market,
            requested_trade_date=None,
        )

    def _load_indexed_facts(
        self,
        session: Session,
        *,
        nodes: tuple[SectorHierarchyNode, ...],
        open_dates: tuple[date, ...],
    ) -> dict[tuple[str, date], SectorDailyFact]:
        if not open_dates:
            return {}
        facts = self._query.load_facts(
            session,
            sector_codes=tuple(node.sector_code for node in nodes),
            start_date=open_dates[0],
            end_date=open_dates[-1],
        )
        return self._calculator.index_facts(facts)

    def _calculate_ranked(
        self,
        *,
        nodes: tuple[SectorHierarchyNode, ...],
        open_dates: tuple[date, ...],
        target_date: date,
        period: SectorMomentumPeriod,
        fact_index: dict[tuple[str, date], SectorDailyFact],
    ) -> tuple[SectorRankFact, ...]:
        returns = self._calculator.calculate_for_date(
            sector_codes=(node.sector_code for node in nodes),
            open_dates=open_dates,
            target_date=target_date,
            period=period,
            fact_index=fact_index,
        )
        return self._calculator.rank_strength(returns)

    def _rank_by_date(
        self,
        *,
        nodes: tuple[SectorHierarchyNode, ...],
        open_dates: tuple[date, ...],
        display_dates: tuple[date, ...],
        period: SectorMomentumPeriod,
        fact_index: dict[tuple[str, date], SectorDailyFact],
    ) -> dict[date, tuple[SectorRankFact, ...]]:
        returns_by_date = self._calculator.calculate_for_dates(
            sector_codes=(node.sector_code for node in nodes),
            open_dates=open_dates,
            target_dates=display_dates,
            period=period,
            fact_index=fact_index,
        )
        return {
            item: self._calculator.rank_strength(returns_by_date[item])
            for item in display_dates
        }

    @staticmethod
    def _find_rank(
        rows: tuple[SectorRankFact, ...],
        *,
        sector_code: str,
    ) -> SectorRankFact:
        return next(row for row in rows if row.sector_code == sector_code)

    @staticmethod
    def _calculable_count(rows: tuple[SectorRankFact, ...]) -> int:
        return sum(row.return_pct is not None for row in rows)

    @staticmethod
    def _union_nodes(*groups: tuple[SectorHierarchyNode, ...]) -> tuple[SectorHierarchyNode, ...]:
        by_code = {node.sector_code: node for group in groups for node in group}
        return tuple(sorted(by_code.values(), key=lambda node: node.sector_code))

    @staticmethod
    def _same_pool(
        left: tuple[SectorHierarchyNode, ...],
        right: tuple[SectorHierarchyNode, ...],
    ) -> bool:
        return tuple(node.sector_code for node in left) == tuple(
            node.sector_code for node in right
        )

    @staticmethod
    def _hierarchy_node_dto(node: SectorHierarchyNode) -> SectorHierarchyNodeDto:
        return SectorHierarchyNodeDto(
            sectorCode=node.sector_code,
            sectorName=node.sector_name,
            industryLevel=node.industry_level,  # type: ignore[arg-type]
            parentSectorCode=node.parent_sector_code,
            parentSectorName=node.parent_sector_name,
            rootSectorCode=node.root_sector_code,
            rootSectorName=node.root_sector_name,
            hierarchyPath=node.hierarchy_path,
            displayOrder=node.display_order,
            isLeaf=node.is_leaf,
        )

    def _ranking_row(
        self,
        *,
        list_position: int,
        node: SectorHierarchyNode,
        rank: SectorRankFact,
        hierarchy: SectorHierarchySnapshot,
    ) -> SectorRankingRowDto:
        return SectorRankingRowDto(
            listPosition=list_position,
            strengthRank=rank.strength_rank,
            sectorCode=node.sector_code,
            sectorName=node.sector_name,
            industryLevel=node.industry_level,  # type: ignore[arg-type]
            parentSectorCode=node.parent_sector_code,
            parentSectorName=node.parent_sector_name,
            hierarchyPath=node.hierarchy_path,
            returnPct=self._calculator.as_json_return(rank.return_pct),
            percentile=self._calculator.as_json_percentile(rank.percentile),
            canDrillDown=bool(hierarchy.children_by_parent.get(node.sector_code)),
        )

    @staticmethod
    def _parent_selection(
        hierarchy: SectorHierarchySnapshot,
        *,
        level1_code: str | None,
        level2_code: str | None,
    ) -> SectorParentSelectionDto:
        return SectorParentSelectionDto(
            level1Code=level1_code,
            level1Name=SectorMomentumQueryService._node_name(hierarchy, level1_code),
            level2Code=level2_code,
            level2Name=SectorMomentumQueryService._node_name(hierarchy, level2_code),
        )

    @staticmethod
    def _node_name(hierarchy: SectorHierarchySnapshot, code: str | None) -> str | None:
        node = hierarchy.nodes_by_code.get(code or "")
        return node.sector_name if node is not None else None

    @staticmethod
    def _trading_day(resolution: SectorTradingDateResolution) -> SectorAnalysisTradingDayDto:
        observed = resolution.observed
        return SectorAnalysisTradingDayDto(
            expectedTradeDate=resolution.expected.trade_date,
            observedTradeDate=observed.trade_date if observed else None,
            expectedAvailability=resolution.expected.availability,
            expectedSectorCount=resolution.expected.expected_sector_count,
            expectedValidSectorCount=resolution.expected.valid_sector_count,
            observedAvailability=observed.availability if observed else None,
            observedValidSectorCount=observed.valid_sector_count if observed else 0,
        )

    @staticmethod
    def _page_status(
        status: SectorAnalysisStatusResolution,
        *,
        context: MarketPageContext,
    ) -> SectorAnalysisPageStatusDto:
        return SectorAnalysisPageStatusDto(
            status=status.status,
            displayText=status.display_text,
            asOfTime=context.generated_at,
        )

    @staticmethod
    def _debug_info(
        *,
        debug: bool,
        resolution: SectorTradingDateResolution,
        scope: SectorMomentumScope,
        pool: tuple[SectorHierarchyNode, ...],
    ) -> SectorAnalysisDebugInfoDto | None:
        if not debug:
            return None
        return SectorAnalysisDebugInfoDto(
            expectedTradeDate=resolution.expected.trade_date,
            observedTradeDate=(
                resolution.observed.trade_date if resolution.observed is not None else None
            ),
            scope=scope,
            expectedSectorCount=resolution.expected.expected_sector_count,
            expectedValidSectorCount=resolution.expected.valid_sector_count,
            observedValidSectorCount=(
                resolution.observed.valid_sector_count if resolution.observed is not None else 0
            ),
            sampleSectorCodes=[node.sector_code for node in pool[:5]],
        )

    def _empty_rankings_response(
        self,
        *,
        context: MarketPageContext,
        resolution: SectorTradingDateResolution,
        scope: SectorMomentumScope,
        pool: tuple[SectorHierarchyNode, ...],
        debug: bool,
    ) -> SectorMomentumRankingsResponseDto:
        status = self._status.empty()
        return SectorMomentumRankingsResponseDto(
            status=status.status,
            tradingDay=self._trading_day(resolution),
            pageStatus=self._page_status(status, context=context),
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=self._debug_info(
                debug=debug,
                resolution=resolution,
                scope=scope,
                pool=pool,
            ),
        )

    def _empty_history_response(
        self,
        *,
        context: MarketPageContext,
        resolution: SectorTradingDateResolution,
        scope: SectorMomentumScope,
        pool: tuple[SectorHierarchyNode, ...],
        debug: bool,
    ) -> SectorMomentumHistoryResponseDto:
        status = self._status.empty()
        return SectorMomentumHistoryResponseDto(
            status=status.status,
            tradingDay=self._trading_day(resolution),
            pageStatus=self._page_status(status, context=context),
            rollingReturns=[],
            historicalRanks=[],
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=self._debug_info(
                debug=debug,
                resolution=resolution,
                scope=scope,
                pool=pool,
            ),
        )

    def _error_rankings_response(
        self,
        *,
        context: MarketPageContext | None,
        resolution: SectorTradingDateResolution | None,
        scope: SectorMomentumScope,
        pool: tuple[SectorHierarchyNode, ...],
        debug: bool,
        code: str,
    ) -> SectorMomentumRankingsResponseDto:
        status = self._error_status(code)
        context = context or self._fallback_context()
        trading_day = resolution or self._fallback_resolution(context.trade_date)
        return SectorMomentumRankingsResponseDto(
            status="ERROR",
            tradingDay=self._trading_day(trading_day),
            pageStatus=self._page_status(status, context=context),
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=self._debug_info(
                debug=debug,
                resolution=trading_day,
                scope=scope,
                pool=pool,
            ),
        )

    def _error_history_response(
        self,
        *,
        context: MarketPageContext | None,
        resolution: SectorTradingDateResolution | None,
        scope: SectorMomentumScope,
        pool: tuple[SectorHierarchyNode, ...],
        debug: bool,
        code: str,
    ) -> SectorMomentumHistoryResponseDto:
        status = self._error_status(code)
        context = context or self._fallback_context()
        trading_day = resolution or self._fallback_resolution(context.trade_date)
        return SectorMomentumHistoryResponseDto(
            status="ERROR",
            tradingDay=self._trading_day(trading_day),
            pageStatus=self._page_status(status, context=context),
            rollingReturns=[],
            historicalRanks=[],
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=self._debug_info(
                debug=debug,
                resolution=trading_day,
                scope=scope,
                pool=pool,
            ),
        )

    def _error_status(self, code: str) -> SectorAnalysisStatusResolution:
        if code == "SA_HIERARCHY_UNAVAILABLE":
            return self._status.error("SA_HIERARCHY_UNAVAILABLE")
        return self._status.error("SA_QUERY_FAILED")

    @staticmethod
    def _fallback_context() -> MarketPageContext:
        now = datetime.now(_CN_TIMEZONE)
        return MarketPageContext(
            market="CN_A",
            trade_date=now.date(),
            prev_trade_date=None,
            is_trading_day=False,
            session_status="CLOSED",
            generated_at=now,
            source="default",
        )

    @staticmethod
    def _fallback_resolution(target_date: date) -> SectorTradingDateResolution:
        from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
            SectorDateAvailabilityFact,
        )

        expected = SectorDateAvailabilityFact(
            trade_date=target_date,
            availability="MISSING",
            expected_sector_count=0,
            valid_sector_count=0,
        )
        return SectorTradingDateResolution(
            coverage_start_date=target_date,
            coverage_end_date=target_date,
            expected=expected,
            observed=None,
            is_explicit=False,
        )
