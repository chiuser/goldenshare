from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchyQuery,
    SectorHierarchySnapshot,
    SectorHierarchyUnavailableError,
)
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_meta_query_service import (
    SectorAnalysisMetaQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_member_breadth_query import (
    SectorMemberBreadthQuery,
)
from src.biz.schemas.wealth.market.sector_analysis import (
    SectorHierarchyDto,
    SectorHierarchyNodeDto,
    SectorParentSelectionDto,
    SectorTradeDateAvailabilityDto,
)
from src.biz.schemas.wealth.market.sector_member_breadth import (
    SectorMemberBreadthAvailabilityDto,
    SectorMemberBreadthCompositionDto,
    SectorMemberBreadthDateContextDto,
    SectorMemberBreadthDefaultsDto,
    SectorMemberBreadthDetailsResponseDto,
    SectorMemberBreadthMemberRowDto,
    SectorMemberBreadthMetaResponseDto,
    SectorMemberBreadthRankingRowDto,
    SectorMemberBreadthRankingsResponseDto,
    SectorMemberBreadthTrendPointDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_analysis_exception_builder import (
    SectorAnalysisExceptionBuilder,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_calculator import (
    SectorMemberBreadthCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    ALLOWED_MEMBER_BREADTH_DIRECTIONS,
    ALLOWED_MEMBER_BREADTH_HISTORY_RANGES,
    ALLOWED_MEMBER_BREADTH_MA_PERIODS,
    ALLOWED_MEMBER_BREADTH_METRICS,
    MEMBER_BREADTH_FORMULA_KEY,
    MEMBER_BREADTH_FORMULA_VERSION,
    MEMBER_BREADTH_MINIMUM_CALCULABLE_COUNT,
    MEMBER_BREADTH_MINIMUM_COVERAGE_PCT,
    MemberBreadthCompositionFact,
    SectorMemberBreadthDetailsRequest,
    SectorMemberBreadthFactMismatchError,
    SectorMemberBreadthRankingsRequest,
    SectorMemberBreadthReason,
    ordered_member_breadth_reasons,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    ALLOWED_SCOPES,
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
    resolve_scope_pool,
)


class SectorMemberBreadthQueryService:
    """Compose the frozen member-breadth metadata and bounded fact responses."""

    def __init__(
        self,
        *,
        meta_service: SectorAnalysisMetaQueryService | None = None,
        hierarchy_query: SectorHierarchyQuery | None = None,
        context_query: MarketPageContextQuery | None = None,
        query: SectorMemberBreadthQuery | None = None,
        calculator: SectorMemberBreadthCalculator | None = None,
    ) -> None:
        self._meta_service = meta_service or SectorAnalysisMetaQueryService()
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()
        self._context_query = context_query or MarketPageContextQuery()
        self._query = query or SectorMemberBreadthQuery()
        self._calculator = calculator or SectorMemberBreadthCalculator()
        self._exceptions = SectorAnalysisExceptionBuilder()

    def build_meta(
        self,
        session: Session,
        *,
        market: str,
    ) -> SectorMemberBreadthMetaResponseDto:
        if market != "CN_A":
            raise SectorScopeInvalidError("只支持 CN_A 市场")
        facts = self._meta_service.load(session, market=market)
        expected = facts.context.trade_date
        expected_availability = next(
            (item for item in facts.trade_dates if item.trade_date == expected),
            None,
        )
        if expected_availability is None:
            raise ValueError("public coverage does not contain the expected trade date")
        complete_dates = tuple(
            item.trade_date
            for item in facts.trade_dates
            if item.availability == "COMPLETE" and item.trade_date <= expected
        )
        if expected_availability.availability == "COMPLETE":
            default_date = expected
            default_status = "READY"
        elif complete_dates:
            default_date = complete_dates[-1]
            default_status = "DELAYED"
        else:
            default_date = None
            default_status = "EMPTY"
        display_text = (
            f"当前展示 {default_date.isoformat()} 盘后数据"
            if default_date is not None
            else "暂无可用盘后数据"
        )
        return SectorMemberBreadthMetaResponseDto(
            formulaKey=MEMBER_BREADTH_FORMULA_KEY,
            formulaVersion=MEMBER_BREADTH_FORMULA_VERSION,
            dateCoverageBasis="INDUSTRY_DAILY",
            dateContext=SectorMemberBreadthDateContextDto(
                expectedTradeDate=expected,
                defaultTradeDate=default_date,
                defaultStatus=default_status,
                displayText=display_text,
            ),
            hierarchy=self._hierarchy_dto(facts.hierarchy),
            coverageStartDate=facts.coverage_start_date,
            coverageEndDate=facts.coverage_end_date,
            tradeDates=[
                SectorTradeDateAvailabilityDto(
                    tradeDate=item.trade_date,
                    availability=item.availability,
                    expectedSectorCount=item.expected_sector_count,
                    validSectorCount=item.valid_sector_count,
                )
                for item in facts.trade_dates
            ],
            scopes=list(ALLOWED_SCOPES),
            directions=list(ALLOWED_MEMBER_BREADTH_DIRECTIONS),
            metrics=list(ALLOWED_MEMBER_BREADTH_METRICS),
            maPeriods=list(ALLOWED_MEMBER_BREADTH_MA_PERIODS),
            historyRanges=list(ALLOWED_MEMBER_BREADTH_HISTORY_RANGES),
            minimumCalculableCount=MEMBER_BREADTH_MINIMUM_CALCULABLE_COUNT,
            minimumCoveragePct=int(MEMBER_BREADTH_MINIMUM_COVERAGE_PCT),
            defaults=SectorMemberBreadthDefaultsDto(
                scope="LEVEL_1",
                direction="UP",
                metric="MEMBER_COUNT",
                maPeriod=20,
                historyRange=20,
            ),
        )

    def build_rankings(
        self,
        session: Session,
        *,
        request: SectorMemberBreadthRankingsRequest,
    ) -> SectorMemberBreadthRankingsResponseDto:
        hierarchy: SectorHierarchySnapshot | None = None
        pool: tuple[SectorHierarchyNode, ...] = ()
        try:
            self._validate_market(request.market)
            hierarchy = self._hierarchy_query.load(session)
            self._assert_version(hierarchy, request.hierarchy_version)
            pool = resolve_scope_pool(
                hierarchy,
                scope=request.scope,
                level1_code=request.level1_code,
                level2_code=request.level2_code,
            )
            context = self._context_query.resolve_context(
                session,
                market=request.market,
                requested_trade_date=None,
            )
            open_date_count = (
                request.ma_period if request.metric == "MA_POSITION" else 1
            )
            window = self._query.load_window_relations(
                session,
                target_date=request.trade_date,
                coverage_end_date=context.trade_date,
                hierarchy_sector_codes=tuple(
                    node.sector_code for node in hierarchy.nodes
                ),
                relation_sector_codes=tuple(node.sector_code for node in pool),
                open_date_count=open_date_count,
                relation_date_count=1,
            )
            stock_codes = tuple(sorted({row.stock_code for row in window.relations}))
            market_facts = self._query.load_market_facts(
                session,
                stock_codes=stock_codes,
                start_date=window.open_dates[0],
                end_date=window.open_dates[-1],
                include_adj_factor=request.metric == "MA_POSITION",
            )
            ranked = self._calculator.rank_requested_metric(
                sector_codes=(node.sector_code for node in pool),
                target_date=request.trade_date,
                metric=request.metric,
                direction=request.direction,
                ma_period=request.ma_period,
                open_dates=window.open_dates,
                relations=window.relations,
                market_facts=market_facts,
            )
            nodes_by_code = {node.sector_code: node for node in pool}
            rows = [
                SectorMemberBreadthRankingRowDto(
                    listPosition=position,
                    rank=item.rank,
                    rankTotal=item.rank_total,
                    sectorCode=item.sector_code,
                    sectorName=nodes_by_code[item.sector_code].sector_name,
                    industryLevel=nodes_by_code[item.sector_code].industry_level,
                    hierarchyPath=nodes_by_code[item.sector_code].hierarchy_path,
                    sourceMemberCount=item.coverage.source_count,
                    calculableCount=item.coverage.calculable_count,
                    coveragePct=self._json_decimal(item.coverage.coverage_pct),
                    metricValuePct=self._json_decimal(item.metric_value_pct),
                    qualificationStatus=(
                        "ELIGIBLE" if item.rank is not None else "INELIGIBLE"
                    ),
                    reasonCodes=list(item.reason_codes),
                )
                for position, item in enumerate(ranked, start=1)
            ]
            eligible_count = sum(item.rank is not None for item in ranked)
            calculable_count = sum(item.metric_calculable for item in ranked)
            reasons: set[SectorMemberBreadthReason] = {
                reason for item in ranked for reason in item.reason_codes
            }
            availability_status = (
                "UNAVAILABLE"
                if calculable_count == 0
                else "AVAILABLE"
                if calculable_count == len(pool)
                else "PARTIAL"
            )
            status = "READY" if calculable_count > 0 else "EMPTY"
            exception = (
                None if status == "READY" else self._exceptions.build("SA_SOURCE_EMPTY")
            )
            return SectorMemberBreadthRankingsResponseDto(
                status=status,
                message=exception.message if exception else None,
                exceptionCode=exception.code if exception else None,
                tradeDate=request.trade_date,
                hierarchyVersion=hierarchy.baseline_version,
                formulaKey=MEMBER_BREADTH_FORMULA_KEY,
                formulaVersion=MEMBER_BREADTH_FORMULA_VERSION,
                scope=request.scope,
                parentSelection=self._parent_selection(
                    hierarchy,
                    level1_code=request.level1_code,
                    level2_code=request.level2_code,
                ),
                direction=request.direction,
                metric=request.metric,
                maPeriod=request.ma_period,
                totalSectorCount=len(pool),
                eligibleSectorCount=eligible_count,
                ineligibleSectorCount=len(pool) - eligible_count,
                availability=SectorMemberBreadthAvailabilityDto(
                    metric=request.metric,
                    calculableSectorCount=calculable_count,
                    eligibleSectorCount=eligible_count,
                    status=availability_status,
                    reasonCodes=list(ordered_member_breadth_reasons(reasons)),
                ),
                defaultSelectedSectorCode=(
                    next(
                        (item.sector_code for item in ranked if item.rank is not None),
                        None,
                    )
                ),
                rows=rows,
            )
        except (
            SectorMemberBreadthFactMismatchError,
            SectorScopeInvalidError,
            SectorSelectionInvalidError,
        ):
            raise
        except SectorHierarchyUnavailableError:
            return self._error_rankings(
                request=request,
                hierarchy=None,
                exception_code="SA_HIERARCHY_UNAVAILABLE",
            )
        except Exception:  # noqa: BLE001
            return self._error_rankings(request=request, hierarchy=hierarchy)

    def build_details(
        self,
        session: Session,
        *,
        request: SectorMemberBreadthDetailsRequest,
    ) -> SectorMemberBreadthDetailsResponseDto:
        hierarchy: SectorHierarchySnapshot | None = None
        node: SectorHierarchyNode | None = None
        try:
            self._validate_market(request.market)
            hierarchy = self._hierarchy_query.load(session)
            self._assert_version(hierarchy, request.hierarchy_version)
            node = hierarchy.nodes_by_code.get(request.sector_code)
            if node is None:
                raise SectorSelectionInvalidError("sectorCode 不属于当前行业层级")
            context = self._context_query.resolve_context(
                session,
                market=request.market,
                requested_trade_date=None,
            )
            open_date_count = request.history_range + request.ma_period - 1
            window = self._query.load_details_window(
                session,
                target_date=request.trade_date,
                coverage_end_date=context.trade_date,
                hierarchy_sector_codes=tuple(
                    item.sector_code for item in hierarchy.nodes
                ),
                sector_code=request.sector_code,
                open_date_count=open_date_count,
                relation_date_count=request.history_range,
            )
            if window.target_source_count == 0:
                exception = self._exceptions.build("SA_BREADTH_SOURCE_EMPTY")
                return self._empty_details(
                    request=request,
                    node=node,
                    exception_code=exception.code,
                    message=exception.message,
                )
            projection = self._query.load_details_projection(
                session,
                sector_code=request.sector_code,
                target_date=request.trade_date,
                open_dates=window.open_dates,
                relation_dates=window.relation_dates,
                ma_period=request.ma_period,
            )
            details = self._calculator.build_details(
                target_date=request.trade_date,
                direction=request.direction,
                ma_period=request.ma_period,
                window=window,
                projection=projection,
            )
            return SectorMemberBreadthDetailsResponseDto(
                status="READY",
                message=None,
                exceptionCode=None,
                tradeDate=request.trade_date,
                hierarchyVersion=hierarchy.baseline_version,
                formulaKey=MEMBER_BREADTH_FORMULA_KEY,
                formulaVersion=MEMBER_BREADTH_FORMULA_VERSION,
                sectorCode=node.sector_code,
                sectorName=node.sector_name,
                industryLevel=node.industry_level,
                hierarchyPath=node.hierarchy_path,
                direction=request.direction,
                maPeriod=request.ma_period,
                historyRange=request.history_range,
                compositions=[
                    self._composition_dto(item) for item in details.compositions
                ],
                trend=[
                    SectorMemberBreadthTrendPointDto(
                        tradeDate=item.trade_date,
                        memberPct=self._json_decimal(item.member_pct),
                        turnoverPct=self._json_decimal(item.turnover_pct),
                        maPositionPct=self._json_decimal(item.ma_position_pct),
                        memberReasonCodes=list(item.member_reason_codes),
                        turnoverReasonCodes=list(item.turnover_reason_codes),
                        maPositionReasonCodes=list(item.ma_position_reason_codes),
                    )
                    for item in details.trend
                ],
                members=[
                    SectorMemberBreadthMemberRowDto(
                        stockName=item.stock_name,
                        stockCode=item.stock_code,
                        dailyPctChg=self._json_decimal(item.daily_pct_change),
                        amountThousandYuan=self._json_decimal(
                            item.amount_thousand_yuan
                        ),
                        amountContributionPct=self._json_decimal(
                            item.amount_contribution_pct
                        ),
                        maRelation=item.ma_relation,
                        maDistancePct=self._json_decimal(item.ma_distance_pct),
                        reasonCodes=list(item.reason_codes),
                    )
                    for item in details.members
                ],
            )
        except (
            SectorMemberBreadthFactMismatchError,
            SectorScopeInvalidError,
            SectorSelectionInvalidError,
        ):
            raise
        except SectorHierarchyUnavailableError:
            fallback_node = self._fallback_node(request.sector_code)
            exception = self._exceptions.build("SA_HIERARCHY_UNAVAILABLE")
            return self._empty_details(
                request=request,
                node=fallback_node,
                exception_code=exception.code,
                message=exception.message,
                status="ERROR",
            )
        except Exception:  # noqa: BLE001
            fallback_node = node or self._fallback_node(request.sector_code)
            exception = self._exceptions.build("SA_BREADTH_QUERY_FAILED")
            return self._empty_details(
                request=request,
                node=fallback_node,
                exception_code=exception.code,
                message=exception.message,
                status="ERROR",
            )

    @staticmethod
    def _assert_version(
        hierarchy: SectorHierarchySnapshot,
        expected_version: str,
    ) -> None:
        if hierarchy.baseline_version != expected_version:
            raise SectorMemberBreadthFactMismatchError(
                "sector hierarchy version no longer matches member breadth facts"
            )

    @staticmethod
    def _validate_market(market: str) -> None:
        if market != "CN_A":
            raise SectorScopeInvalidError("只支持 CN_A 市场")

    @staticmethod
    def _hierarchy_dto(hierarchy: SectorHierarchySnapshot) -> SectorHierarchyDto:
        return SectorHierarchyDto(
            hierarchyVersion=hierarchy.baseline_version,
            publishedAt=hierarchy.published_at,
            nodes=[
                SectorHierarchyNodeDto(
                    sectorCode=node.sector_code,
                    sectorName=node.sector_name,
                    industryLevel=node.industry_level,
                    parentSectorCode=node.parent_sector_code,
                    parentSectorName=node.parent_sector_name,
                    rootSectorCode=node.root_sector_code,
                    rootSectorName=node.root_sector_name,
                    hierarchyPath=node.hierarchy_path,
                    displayOrder=node.display_order,
                    isLeaf=node.is_leaf,
                )
                for node in hierarchy.nodes
            ],
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
            level1Name=SectorMemberBreadthQueryService._node_name(
                hierarchy, level1_code
            ),
            level2Code=level2_code,
            level2Name=SectorMemberBreadthQueryService._node_name(
                hierarchy, level2_code
            ),
        )

    @staticmethod
    def _node_name(
        hierarchy: SectorHierarchySnapshot,
        code: str | None,
    ) -> str | None:
        node = hierarchy.nodes_by_code.get(code or "")
        return node.sector_name if node is not None else None

    @staticmethod
    def _composition_dto(
        item: MemberBreadthCompositionFact,
    ) -> SectorMemberBreadthCompositionDto:
        return SectorMemberBreadthCompositionDto(
            metric=item.metric,
            sourceCount=item.coverage.source_count,
            calculableCount=item.coverage.calculable_count,
            coveragePct=SectorMemberBreadthQueryService._json_decimal(
                item.coverage.coverage_pct
            ),
            eligible=item.coverage.eligible,
            positiveCount=item.up_count,
            neutralCount=item.flat_count,
            negativeCount=item.down_count,
            positivePct=SectorMemberBreadthQueryService._json_decimal(item.up_pct),
            neutralPct=SectorMemberBreadthQueryService._json_decimal(item.flat_pct),
            negativePct=SectorMemberBreadthQueryService._json_decimal(item.down_pct),
            reasonCodes=list(item.coverage.reason_codes),
        )

    def _error_rankings(
        self,
        *,
        request: SectorMemberBreadthRankingsRequest,
        hierarchy: SectorHierarchySnapshot | None,
        exception_code: str = "SA_BREADTH_QUERY_FAILED",
    ) -> SectorMemberBreadthRankingsResponseDto:
        exception = self._exceptions.build(exception_code)
        return SectorMemberBreadthRankingsResponseDto(
            status="ERROR",
            message=exception.message,
            exceptionCode=exception.code,
            tradeDate=request.trade_date,
            hierarchyVersion=(
                hierarchy.baseline_version
                if hierarchy is not None
                else request.hierarchy_version
            ),
            formulaKey=MEMBER_BREADTH_FORMULA_KEY,
            formulaVersion=MEMBER_BREADTH_FORMULA_VERSION,
            scope=request.scope,
            parentSelection=SectorParentSelectionDto(
                level1Code=request.level1_code,
                level2Code=request.level2_code,
            ),
            direction=request.direction,
            metric=request.metric,
            maPeriod=request.ma_period,
            totalSectorCount=0,
            eligibleSectorCount=0,
            ineligibleSectorCount=0,
            availability=SectorMemberBreadthAvailabilityDto(
                metric=request.metric,
                calculableSectorCount=0,
                eligibleSectorCount=0,
                status="UNAVAILABLE",
                reasonCodes=[],
            ),
            defaultSelectedSectorCode=None,
            rows=[],
        )

    @staticmethod
    def _empty_details(
        *,
        request: SectorMemberBreadthDetailsRequest,
        node: SectorHierarchyNode,
        exception_code: str,
        message: str,
        status: str = "EMPTY",
    ) -> SectorMemberBreadthDetailsResponseDto:
        return SectorMemberBreadthDetailsResponseDto(
            status=status,
            message=message,
            exceptionCode=exception_code,
            tradeDate=request.trade_date,
            hierarchyVersion=request.hierarchy_version,
            formulaKey=MEMBER_BREADTH_FORMULA_KEY,
            formulaVersion=MEMBER_BREADTH_FORMULA_VERSION,
            sectorCode=node.sector_code,
            sectorName=node.sector_name,
            industryLevel=node.industry_level,
            hierarchyPath=node.hierarchy_path,
            direction=request.direction,
            maPeriod=request.ma_period,
            historyRange=request.history_range,
            compositions=[],
            trend=[],
            members=[],
        )

    @staticmethod
    def _fallback_node(sector_code: str) -> SectorHierarchyNode:
        return SectorHierarchyNode(
            sector_code=sector_code,
            sector_name="当前行业",
            industry_level=1,
            parent_sector_code=None,
            parent_sector_name=None,
            root_sector_code=sector_code,
            root_sector_name="当前行业",
            hierarchy_path="当前行业",
            display_order=0,
            is_leaf=False,
            baseline_version="unavailable",
        )

    @staticmethod
    def _json_decimal(value: Decimal | None) -> float | None:
        return None if value is None else float(value)
