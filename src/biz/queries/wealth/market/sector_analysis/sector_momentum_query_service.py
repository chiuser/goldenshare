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
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_fact_reader import (
    SectorAnalysisFactReader,
    SectorMomentumFactSelection,
    SectorMomentumHistorySelection,
    SectorPublishedMomentumHistorySlice,
    SectorPublishedMomentumRow,
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
    SectorHistoryRange,
    SectorDataQueryError,
    SectorMomentumDirection,
    SectorMomentumPeriod,
    SectorMomentumScope,
    SectorRankFact,
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
    SectorTradingDateResolution,
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
        calculator: SectorMomentumCalculator | None = None,
        status_resolver: SectorAnalysisStatusResolver | None = None,
        fact_reader: SectorAnalysisFactReader | None = None,
    ) -> None:
        self._context_query = context_query or MarketPageContextQuery()
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()
        self._calculator = calculator or SectorMomentumCalculator()
        self._status = status_resolver or SectorAnalysisStatusResolver()
        self._facts = fact_reader or SectorAnalysisFactReader()

    def build_meta(
        self, session: Session, *, market: str
    ) -> SectorAnalysisMetaResponseDto:
        context = self._load_current_context(session, market=market)
        hierarchy = self._hierarchy_query.load(session)
        coverage = self._facts.load_momentum_coverage(
            session,
            coverage_end_date=context.trade_date,
            hierarchy=hierarchy,
        )
        published_dates = coverage.published_dates
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
            coverageStartDate=published_dates[0].trade_date,
            coverageEndDate=published_dates[-1].trade_date,
            tradeDates=[
                SectorTradeDateAvailabilityDto(
                    tradeDate=item.trade_date,
                    availability=item.availability,
                    expectedSectorCount=item.expected_sector_count,
                    validSectorCount=item.valid_sector_count,
                )
                for item in published_dates
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
            coverage = self._facts.load_momentum_coverage(
                session,
                coverage_end_date=context.trade_date,
                hierarchy=hierarchy,
            )
            resolution = self._facts.resolve_trading_date(
                coverage,
                expected_trade_date=trade_date or context.trade_date,
                is_explicit=trade_date is not None,
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

            comparison_key = self._comparison_key(
                scope=scope,
                level1_code=level1_code,
                level2_code=level2_code,
            )
            rows = self._facts.load_momentum_rows(
                session,
                selections=(
                    SectorMomentumFactSelection(
                        trade_dates=(resolution.observed.trade_date,),
                        comparison_scope=scope,
                        comparison_key=comparison_key,
                    ),
                ),
                period=period,
                hierarchy=hierarchy,
                sector_codes=tuple(node.sector_code for node in pool),
            )
            ranked, calculable_count = self._ranked_from_published_rows(
                rows,
                pool=pool,
                trade_date=resolution.observed.trade_date,
                comparison_key=comparison_key,
            )
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

            sorted_rows = self._calculator.sort_ranking_rows(
                ranked, direction=direction
            )
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
            selected = next(
                (node for node in pool if node.sector_code == sector_code), None
            )
            if selected is None:
                raise SectorSelectionInvalidError("sectorCode 不在当前比较范围内")
            coverage = self._facts.load_momentum_coverage(
                session,
                hierarchy=hierarchy,
                coverage_end_date=context.trade_date,
            )
            resolution = self._facts.resolve_trading_date(
                coverage,
                expected_trade_date=trade_date or context.trade_date,
                is_explicit=trade_date is not None,
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

            display_dates = self._facts.load_open_dates(
                session,
                end_date=resolution.observed.trade_date,
                count=history_range,
            )
            display_dates = tuple(
                item for item in display_dates if item >= resolution.coverage_start_date
            )
            current_key = self._comparison_key(
                scope=scope,
                level1_code=level1_code,
                level2_code=level2_code,
            )
            global_scope, global_key, global_pool = self._global_identity(
                hierarchy,
                node=selected,
            )
            parent_identity = self._parent_identity(hierarchy, node=selected)
            selections = [
                SectorMomentumHistorySelection(
                    trade_dates=display_dates,
                    comparison_scope=scope,
                    comparison_key=current_key,
                    selected_sector_code=selected.sector_code,
                    expected_sector_codes=tuple(node.sector_code for node in pool),
                )
            ]
            if global_key != current_key:
                selections.append(
                    SectorMomentumHistorySelection(
                        trade_dates=(resolution.observed.trade_date,),
                        comparison_scope=global_scope,
                        comparison_key=global_key,
                        selected_sector_code=selected.sector_code,
                        expected_sector_codes=tuple(
                            node.sector_code for node in global_pool
                        ),
                    )
                )
            if parent_identity is not None and parent_identity[1] not in {
                current_key,
                global_key,
            }:
                parent_pool_for_selection = parent_identity[2]
                selections.append(
                    SectorMomentumHistorySelection(
                        trade_dates=(resolution.observed.trade_date,),
                        comparison_scope=parent_identity[0],
                        comparison_key=parent_identity[1],
                        selected_sector_code=selected.sector_code,
                        expected_sector_codes=tuple(
                            node.sector_code for node in parent_pool_for_selection
                        ),
                    )
                )
            slices = self._facts.load_momentum_history_slices(
                session,
                selections=tuple(selections),
                period=period,
                hierarchy=hierarchy,
            )
            slices_by_identity: dict[
                tuple[date, str], SectorPublishedMomentumHistorySlice
            ] = {}
            for history_slice in slices:
                identity = (
                    history_slice.trade_date,
                    history_slice.comparison_key,
                )
                if identity in slices_by_identity:
                    raise SectorDataQueryError(
                        "published momentum history contains a duplicate slice"
                    )
                slices_by_identity[identity] = history_slice

            def resolve_published_slice(
                *, trade_date: date, comparison_key: str
            ) -> SectorPublishedMomentumHistorySlice | None:
                history_slice = slices_by_identity.get((trade_date, comparison_key))
                published_batch_id = coverage.batch_by_date.get(trade_date)
                if published_batch_id is None:
                    if history_slice is not None:
                        raise SectorDataQueryError(
                            "unpublished date cannot carry momentum facts"
                        )
                    return None
                if (
                    history_slice is None
                    or history_slice.batch_id != published_batch_id
                ):
                    raise SectorDataQueryError(
                        "published momentum history slice is missing or stale"
                    )
                return history_slice

            current_by_date = {
                item: resolve_published_slice(
                    trade_date=item,
                    comparison_key=current_key,
                )
                for item in display_dates
            }
            observed_slice = current_by_date[resolution.observed.trade_date]
            if observed_slice is None:
                raise SectorDataQueryError(
                    "observed momentum history slice is unpublished"
                )
            observed_calculable = observed_slice.calculable_count
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

            global_slice = (
                observed_slice
                if global_key == current_key
                else resolve_published_slice(
                    trade_date=resolution.observed.trade_date,
                    comparison_key=global_key,
                )
            )
            if global_slice is None:
                raise SectorDataQueryError(
                    "global momentum history slice is unpublished"
                )
            global_calculable = global_slice.calculable_count
            parent_slice: SectorPublishedMomentumHistorySlice | None = None
            parent_pool_nodes: tuple[SectorHierarchyNode, ...] | None = None
            if parent_identity is not None:
                _parent_scope, parent_key, parent_pool_nodes = parent_identity
                if parent_key == current_key:
                    parent_slice = observed_slice
                elif parent_key == global_key:
                    parent_slice = global_slice
                else:
                    parent_slice = resolve_published_slice(
                        trade_date=resolution.observed.trade_date,
                        comparison_key=parent_key,
                    )
                    if parent_slice is None:
                        raise SectorDataQueryError(
                            "parent momentum history slice is unpublished"
                        )

            rolling_returns: list[RollingReturnPointDto] = []
            historical_ranks: list[HistoricalRankPointDto] = []
            for item in display_dates:
                history_slice = current_by_date[item]
                rolling_returns.append(
                    RollingReturnPointDto(
                        tradeDate=item,
                        returnPct=self._calculator.as_json_return(
                            history_slice.selected_return_pct
                            if history_slice is not None
                            else None
                        ),
                    )
                )
                historical_ranks.append(
                    HistoricalRankPointDto(
                        tradeDate=item,
                        strengthRank=(
                            history_slice.selected_strength_rank
                            if history_slice is not None
                            else None
                        ),
                        calculableCount=(
                            history_slice.calculable_count
                            if history_slice is not None
                            else 0
                        ),
                        totalCount=len(pool),
                        percentile=self._calculator.as_json_percentile(
                            history_slice.selected_percentile
                            if history_slice is not None
                            else None
                        ),
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
                returnPct=self._calculator.as_json_return(
                    observed_slice.selected_return_pct
                ),
                percentile=self._calculator.as_json_percentile(
                    observed_slice.selected_percentile
                ),
                currentScopeStrengthRank=observed_slice.selected_strength_rank,
                currentScopeCalculableCount=observed_calculable,
                currentScopeTotalCount=len(pool),
                globalLevelStrengthRank=global_slice.selected_strength_rank,
                globalLevelCalculableCount=global_calculable,
                globalLevelTotalCount=len(global_pool),
                parentStrengthRank=(
                    parent_slice.selected_strength_rank
                    if parent_slice is not None
                    else None
                ),
                parentCalculableCount=(
                    parent_slice.calculable_count if parent_slice is not None else None
                ),
                parentTotalCount=(
                    len(parent_pool_nodes) if parent_pool_nodes is not None else None
                ),
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

    def _load_current_context(self, session: Session, *, market: str) -> MarketPageContext:
        return self._context_query.resolve_context(
            session,
            market=market,
            requested_trade_date=None,
        )

    @staticmethod
    def _comparison_key(
        *,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
    ) -> str:
        if scope == "LEVEL_1":
            return "GLOBAL:L1"
        if scope == "LEVEL_2":
            return "GLOBAL:L2"
        if scope == "LEVEL_3":
            return "GLOBAL:L3"
        if scope == "LEVEL_1_CHILDREN":
            assert level1_code is not None
            return f"PARENT:L1:{level1_code}"
        assert level2_code is not None
        return f"PARENT:L2:{level2_code}"

    @staticmethod
    def _global_identity(
        hierarchy: SectorHierarchySnapshot,
        *,
        node: SectorHierarchyNode,
    ) -> tuple[SectorMomentumScope, str, tuple[SectorHierarchyNode, ...]]:
        scopes: dict[int, SectorMomentumScope] = {
            1: "LEVEL_1",
            2: "LEVEL_2",
            3: "LEVEL_3",
        }
        scope = scopes[node.industry_level]
        pool = tuple(
            sorted(
                (
                    item
                    for item in hierarchy.nodes
                    if item.industry_level == node.industry_level
                ),
                key=lambda item: (item.display_order, item.sector_code),
            )
        )
        return scope, f"GLOBAL:L{node.industry_level}", pool

    @staticmethod
    def _parent_identity(
        hierarchy: SectorHierarchySnapshot,
        *,
        node: SectorHierarchyNode,
    ) -> (
        tuple[SectorMomentumScope, str, tuple[SectorHierarchyNode, ...]] | None
    ):
        if node.industry_level == 1:
            return None
        assert node.parent_sector_code is not None
        parent_level = node.industry_level - 1
        scope: SectorMomentumScope = (
            "LEVEL_1_CHILDREN" if parent_level == 1 else "LEVEL_2_CHILDREN"
        )
        pool = tuple(
            sorted(
                (
                    item
                    for item in hierarchy.children_by_parent.get(
                        node.parent_sector_code,
                        (),
                    )
                    if item.industry_level == node.industry_level
                ),
                key=lambda item: (item.display_order, item.sector_code),
            )
        )
        return (
            scope,
            f"PARENT:L{parent_level}:{node.parent_sector_code}",
            pool,
        )

    @staticmethod
    def _ranked_from_published_rows(
        rows: tuple[SectorPublishedMomentumRow, ...],
        *,
        pool: tuple[SectorHierarchyNode, ...],
        trade_date: date,
        comparison_key: str,
    ) -> tuple[tuple[SectorRankFact, ...], int]:
        by_code = {
            row.sector_code: row
            for row in rows
            if row.trade_date == trade_date and row.comparison_key == comparison_key
        }
        expected_codes = {node.sector_code for node in pool}
        if set(by_code) != expected_codes or len(by_code) != len(rows):
            raise SectorDataQueryError(
                "published momentum slice does not match the comparison pool"
            )
        calculable_count = sum(row.return_pct is not None for row in by_code.values())
        if any(
            row.rankable_count != calculable_count
            for row in by_code.values()
            if row.return_pct is not None
        ):
            raise SectorDataQueryError(
                "published momentum rank denominator is inconsistent"
            )
        return (
            tuple(
                SectorRankFact(
                    sector_code=node.sector_code,
                    return_pct=by_code[node.sector_code].return_pct,
                    strength_rank=by_code[node.sector_code].strength_rank,
                    percentile=by_code[node.sector_code].percentile,
                )
                for node in pool
            ),
            calculable_count,
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
