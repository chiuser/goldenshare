from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
    SectorHierarchyUnavailableError,
)
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_meta_query_service import (
    SectorAnalysisMetaFacts,
    SectorAnalysisMetaQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_query import (
    SectorMomentumQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_snapshot_query_service import (
    SectorMomentumSnapshotPreparation,
    SectorMomentumSnapshotQueryService,
)
from src.biz.schemas.wealth.market.sector_analysis import (
    SectorAnalysisDebugInfoDto,
    SectorAnalysisPageStatusDto,
    SectorAnalysisTradingDayDto,
    SectorHierarchyDto,
    SectorHierarchyNodeDto,
    SectorParentSelectionDto,
    SectorTradeDateAvailabilityDto,
)
from src.biz.schemas.wealth.market.sector_relative_rotation import (
    SectorRelativeRotationAnalysisDto,
    SectorRelativeRotationDefaultsDto,
    SectorRelativeRotationFormulaDto,
    SectorRelativeRotationMetaResponseDto,
    SectorRelativeRotationQuadrantCountsDto,
    SectorRelativeRotationResultsResponseDto,
    SectorRelativeRotationRowDto,
    SectorRelativeRotationTrailDto,
    SectorRelativeRotationTrailPointDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_analysis_status_resolver import (
    SectorAnalysisStatusResolution,
    SectorAnalysisStatusResolver,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    SectorMomentumFactVersionMismatchError,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_calculator import (
    SectorMomentumCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    ALLOWED_SCOPES,
    SectorDataQueryError,
    SectorMomentumScope,
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
    SectorTradingDateResolution,
)
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_calculator import (
    SectorRelativeRotationCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_contract import (
    ALLOWED_PERIODS,
    ALLOWED_TRAIL_LENGTHS,
    BASIS_FORMULA_KEY,
    BASIS_FORMULA_VERSION,
    FORMULA_KEY,
    FORMULA_VERSION,
    IMPROVEMENT_LOOKBACK_DAYS,
    MINIMUM_GROUP_SIZE,
    X_DOMAIN,
    X_SPLIT,
    Y_SPLIT,
    SectorRelativeGroupInterpretation,
    SectorRelativeRotationPeriod,
    SectorRelativeRotationPointFact,
    SectorRelativeRotationTrailLength,
    make_rank_slice,
    make_selected_rank_slice,
)


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
_QUADRANT_STATUSES = (
    "LEADING_IMPROVING",
    "WEAK_IMPROVING",
    "STRONG_NOT_IMPROVING",
    "WEAK_NOT_IMPROVING",
)


class SectorRelativeRotationQueryService:
    """Compose one relative-rotation snapshot and selected trail with bounded IO."""

    def __init__(
        self,
        *,
        context_query: MarketPageContextQuery | None = None,
        meta_service: SectorAnalysisMetaQueryService | None = None,
        snapshot_service: SectorMomentumSnapshotQueryService | None = None,
        momentum_query: SectorMomentumQuery | None = None,
        momentum_calculator: SectorMomentumCalculator | None = None,
        relative_calculator: SectorRelativeRotationCalculator | None = None,
        status_resolver: SectorAnalysisStatusResolver | None = None,
    ) -> None:
        self._context_query = context_query or MarketPageContextQuery()
        self._meta_service = meta_service or SectorAnalysisMetaQueryService()
        self._snapshot_service = (
            snapshot_service or SectorMomentumSnapshotQueryService()
        )
        self._query = momentum_query or SectorMomentumQuery()
        self._momentum_calculator = momentum_calculator or SectorMomentumCalculator()
        self._relative_calculator = (
            relative_calculator or SectorRelativeRotationCalculator()
        )
        self._status = status_resolver or SectorAnalysisStatusResolver()

    def build_meta(
        self,
        session: Session,
        *,
        market: str,
    ) -> SectorRelativeRotationMetaResponseDto:
        facts = self._meta_service.load(session, market=market)
        resolution = self._meta_resolution(facts)
        assert resolution.observed is not None
        status = self._status.resolve(
            trading_day=resolution,
            calculable_count=resolution.observed.valid_sector_count,
        )
        if status.status not in {"READY", "DELAYED"}:
            raise SectorDataQueryError(
                "relative-rotation meta has no usable business date"
            )
        return SectorRelativeRotationMetaResponseDto(
            status=status.status,
            tradingDay=self._trading_day(resolution),
            pageStatus=self._page_status(status, context=facts.context),
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=None,
            formula=SectorRelativeRotationFormulaDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                basisFormulaKey=BASIS_FORMULA_KEY,
                basisFormulaVersion=BASIS_FORMULA_VERSION,
                periods=list(ALLOWED_PERIODS),
                improvementLookbackDays=IMPROVEMENT_LOOKBACK_DAYS,
                trailLengths=list(ALLOWED_TRAIL_LENGTHS),
                minimumGroupSize=MINIMUM_GROUP_SIZE,
                scopes=list(ALLOWED_SCOPES),
                xDomain=(int(X_DOMAIN[0]), int(X_DOMAIN[1])),
                xSplit=int(X_SPLIT),
                ySplit=int(Y_SPLIT),
            ),
            defaults=SectorRelativeRotationDefaultsDto(
                scope="LEVEL_1",
                period=20,
                trailLength=20,
                quadrantFilter="ALL",
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
        )

    def build_results(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
        period: SectorRelativeRotationPeriod,
        trail_length: SectorRelativeRotationTrailLength,
        sector_code: str | None,
        hierarchy_version: str,
        debug: bool,
    ) -> SectorRelativeRotationResultsResponseDto:
        try:
            context = self._context_query.resolve_context(
                session,
                market=market,
                requested_trade_date=None,
            )
            preparation = self._snapshot_service.prepare_for_context(
                session,
                context=context,
                trade_date=trade_date,
                scope=scope,
                level1_code=level1_code,
                level2_code=level2_code,
                period=period,
                expected_hierarchy_version=hierarchy_version,
                date_errors_are_selection=True,
            )
            pool_codes = tuple(node.sector_code for node in preparation.pool)
            if sector_code is not None and sector_code not in pool_codes:
                raise SectorSelectionInvalidError("sectorCode 不属于当前比较范围")
            resolution = preparation.resolution
            if (
                resolution.observed is None
                or resolution.observed.availability == "MISSING"
            ):
                return self._empty_response(preparation=preparation, debug=debug)

            required_count = period + IMPROVEMENT_LOOKBACK_DAYS + trail_length
            open_dates = self._query.load_open_dates(
                session,
                end_date=resolution.observed.trade_date,
                count=required_count,
            )
            if not open_dates:
                return self._empty_response(preparation=preparation, debug=debug)
            facts = self._query.load_facts(
                session,
                sector_codes=pool_codes,
                start_date=open_dates[0],
                end_date=open_dates[-1],
            )
            fact_index = self._momentum_calculator.index_facts(facts)
            date_indexes = {item: index for index, item in enumerate(open_dates)}
            display_dates = tuple(
                item
                for item in open_dates[-trail_length:]
                if item >= resolution.coverage_start_date
                and date_indexes[item] >= IMPROVEMENT_LOOKBACK_DAYS
            )
            if not display_dates:
                return self._empty_response(preparation=preparation, debug=debug)
            comparison_dates = tuple(
                open_dates[date_indexes[item] - IMPROVEMENT_LOOKBACK_DAYS]
                for item in display_dates
            )
            calculation_date_set = set(display_dates + comparison_dates)
            calculation_dates = tuple(
                item for item in open_dates if item in calculation_date_set
            )
            returns_by_date = self._momentum_calculator.calculate_for_dates(
                sector_codes=pool_codes,
                open_dates=open_dates,
                target_dates=calculation_dates,
                period=period,
                fact_index=fact_index,
            )
            current_date = display_dates[-1]
            current_position = date_indexes[current_date]
            current_comparison_date = open_dates[
                current_position - IMPROVEMENT_LOOKBACK_DAYS
            ]
            full_rank_slices = {
                item: make_rank_slice(
                    item,
                    returns_by_date[item],
                    self._momentum_calculator.rank_strength(returns_by_date[item]),
                )
                for item in (current_comparison_date, current_date)
            }
            current_points = self._relative_calculator.calculate_current_snapshot(
                sector_codes=pool_codes,
                open_dates=open_dates,
                current_date=current_date,
                current_slice=full_rank_slices[current_date],
                comparison_slice=full_rank_slices[current_comparison_date],
            )

            current_calculable_count = sum(
                item.percentile is not None for item in current_points
            )
            status = self._status.resolve(
                trading_day=resolution,
                calculable_count=current_calculable_count,
            )
            if status.status == "EMPTY":
                return self._empty_response(preparation=preparation, debug=debug)

            sorted_points = self._relative_calculator.canonical_sort(current_points)
            selected_code = sector_code or self._default_selection(sorted_points)
            selected_rank_slices = {}
            for item in calculation_dates:
                if item in full_rank_slices:
                    rank_slice = full_rank_slices[item]
                    selected_index = next(
                        index
                        for index, rank_fact in enumerate(rank_slice.ranked)
                        if rank_fact.sector_code == selected_code
                    )
                    selected_rank_slices[item] = make_selected_rank_slice(
                        item,
                        rank_slice.returns[selected_index],
                        rank_slice.ranked[selected_index],
                        rank_slice.calculable_count,
                    )
                    continue
                selected_rank, calculable_count = (
                    self._momentum_calculator.rank_selected(
                        returns_by_date[item],
                        sector_code=selected_code,
                    )
                )
                selected_return = next(
                    return_fact
                    for return_fact in returns_by_date[item]
                    if return_fact.sector_code == selected_code
                )
                selected_rank_slices[item] = make_selected_rank_slice(
                    item,
                    selected_return,
                    selected_rank,
                    calculable_count,
                )
            selected_points = self._relative_calculator.calculate_selected_trail(
                selected_sector_code=selected_code,
                open_dates=open_dates,
                display_dates=display_dates,
                rank_slices=selected_rank_slices,
            )
            group_interpretation = self._group_interpretation(current_points)
            quadrant_counts = self._quadrant_counts(
                current_points,
                group_interpretation=group_interpretation,
            )
            node_by_code = {node.sector_code: node for node in preparation.pool}
            items = [
                self._row_dto(
                    point=point,
                    node=node_by_code[point.sector_code],
                    hierarchy=preparation.hierarchy,
                )
                for point in sorted_points
            ]
            selected_trail = SectorRelativeRotationTrailDto(
                sectorCode=selected_code,
                requestedLength=trail_length,
                dateSlotCount=len(selected_points),
                points=[self._trail_point_dto(item) for item in selected_points],
            )
            analysis = SectorRelativeRotationAnalysisDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                basisFormulaKey=BASIS_FORMULA_KEY,
                basisFormulaVersion=BASIS_FORMULA_VERSION,
                hierarchyVersion=preparation.hierarchy.baseline_version,
                scope=scope,
                period=period,
                improvementLookbackDays=IMPROVEMENT_LOOKBACK_DAYS,
                trailLength=trail_length,
                minimumGroupSize=MINIMUM_GROUP_SIZE,
                parentSelection=self._parent_selection(preparation),
                selectedSectorCode=selected_code,
                groupInterpretation=group_interpretation,
                totalCount=len(items),
                currentCalculableCount=current_calculable_count,
                plottableCount=sum(
                    item.coordinateStatus == "PLOTTABLE" for item in items
                ),
                missingCoordinateCount=sum(
                    item.coordinateStatus == "UNAVAILABLE" for item in items
                ),
                quadrantCounts=quadrant_counts,
                items=items,
                selectedTrail=selected_trail,
            )
            return SectorRelativeRotationResultsResponseDto(
                status=status.status,
                tradingDay=self._trading_day(resolution),
                pageStatus=self._page_status(status, context=context),
                analysis=analysis,
                message=status.message,
                exceptionCode=status.exception_code,
                debugInfo=self._debug_info(
                    preparation=preparation,
                    debug=debug,
                ),
            )
        except (SectorScopeInvalidError, SectorSelectionInvalidError):
            raise
        except SectorMomentumFactVersionMismatchError:
            raise
        except SectorHierarchyUnavailableError:
            return self._error_response(
                scope=scope,
                debug=debug,
                code="SA_HIERARCHY_UNAVAILABLE",
            )
        except Exception:  # noqa: BLE001
            return self._error_response(
                scope=scope,
                debug=debug,
                code="SA_QUERY_FAILED",
            )

    @staticmethod
    def _meta_resolution(facts: SectorAnalysisMetaFacts) -> SectorTradingDateResolution:
        expected = next(
            (
                item
                for item in facts.trade_dates
                if item.trade_date == facts.context.trade_date
            ),
            None,
        )
        if expected is None:
            raise SectorDataQueryError("public business date is absent from coverage")
        if expected.availability == "COMPLETE":
            observed = expected
        else:
            observed = next(
                (
                    item
                    for item in reversed(facts.trade_dates)
                    if item.trade_date < expected.trade_date
                    and item.availability == "COMPLETE"
                ),
                None,
            )
        if observed is None:
            raise SectorDataQueryError("coverage has no complete business date")
        return SectorTradingDateResolution(
            coverage_start_date=facts.coverage_start_date,
            coverage_end_date=facts.coverage_end_date,
            expected=expected,
            observed=observed,
            is_explicit=False,
        )

    @staticmethod
    def _default_selection(
        rows: tuple[SectorRelativeRotationPointFact, ...],
    ) -> str:
        selected = next(
            (item for item in rows if item.coordinate_status == "PLOTTABLE"),
            None,
        ) or next((item for item in rows if item.percentile is not None), None)
        if selected is None:
            raise SectorDataQueryError(
                "relative-rotation has no selectable current fact"
            )
        return selected.sector_code

    @staticmethod
    def _group_interpretation(
        rows: tuple[SectorRelativeRotationPointFact, ...],
    ) -> SectorRelativeGroupInterpretation:
        if not rows:
            raise SectorDataQueryError("relative-rotation current snapshot is empty")
        first = rows[0]
        if (
            first.current_calculable_count >= MINIMUM_GROUP_SIZE
            and first.comparison_calculable_count >= MINIMUM_GROUP_SIZE
        ):
            return "QUADRANT"
        return "SAMPLE_INSUFFICIENT"

    @staticmethod
    def _quadrant_counts(
        rows: tuple[SectorRelativeRotationPointFact, ...],
        *,
        group_interpretation: SectorRelativeGroupInterpretation,
    ) -> SectorRelativeRotationQuadrantCountsDto:
        if group_interpretation == "SAMPLE_INSUFFICIENT":
            return SectorRelativeRotationQuadrantCountsDto(
                leadingImproving=0,
                weakImproving=0,
                strongNotImproving=0,
                weakNotImproving=0,
            )
        counts = {
            status: sum(item.rotation_status == status for item in rows)
            for status in _QUADRANT_STATUSES
        }
        return SectorRelativeRotationQuadrantCountsDto(
            leadingImproving=counts["LEADING_IMPROVING"],
            weakImproving=counts["WEAK_IMPROVING"],
            strongNotImproving=counts["STRONG_NOT_IMPROVING"],
            weakNotImproving=counts["WEAK_NOT_IMPROVING"],
        )

    def _row_dto(
        self,
        *,
        point: SectorRelativeRotationPointFact,
        node: SectorHierarchyNode,
        hierarchy: SectorHierarchySnapshot,
    ) -> SectorRelativeRotationRowDto:
        return SectorRelativeRotationRowDto(
            sectorCode=node.sector_code,
            sectorName=node.sector_name,
            industryLevel=node.industry_level,  # type: ignore[arg-type]
            parentSectorCode=node.parent_sector_code,
            parentSectorName=node.parent_sector_name,
            hierarchyPath=node.hierarchy_path,
            canDrillDown=bool(hierarchy.children_by_parent.get(node.sector_code)),
            returnPct=self._momentum_calculator.as_json_return(point.return_pct),
            strengthRank=point.strength_rank,
            percentile=self._momentum_calculator.as_json_percentile(point.percentile),
            percentileDelta5d=self._momentum_calculator.as_json_percentile(
                point.percentile_delta_5d
            ),
            rotationStatus=point.rotation_status,
            coordinateStatus=point.coordinate_status,
            currentMissingReason=point.current_missing_reason,  # type: ignore[arg-type]
            comparisonMissingReason=point.comparison_missing_reason,  # type: ignore[arg-type]
        )

    def _trail_point_dto(
        self,
        point: SectorRelativeRotationPointFact,
    ) -> SectorRelativeRotationTrailPointDto:
        return SectorRelativeRotationTrailPointDto(
            tradeDate=point.trade_date,
            returnPct=self._momentum_calculator.as_json_return(point.return_pct),
            percentile=self._momentum_calculator.as_json_percentile(point.percentile),
            percentileDelta5d=self._momentum_calculator.as_json_percentile(
                point.percentile_delta_5d
            ),
            rotationStatus=point.rotation_status,
            coordinateStatus=point.coordinate_status,
            currentMissingReason=point.current_missing_reason,  # type: ignore[arg-type]
            comparisonMissingReason=point.comparison_missing_reason,  # type: ignore[arg-type]
        )

    @staticmethod
    def _parent_selection(
        preparation: SectorMomentumSnapshotPreparation,
    ) -> SectorParentSelectionDto:
        level1 = preparation.hierarchy.nodes_by_code.get(preparation.level1_code or "")
        level2 = preparation.hierarchy.nodes_by_code.get(preparation.level2_code or "")
        return SectorParentSelectionDto(
            level1Code=preparation.level1_code,
            level1Name=level1.sector_name if level1 is not None else None,
            level2Code=preparation.level2_code,
            level2Name=level2.sector_name if level2 is not None else None,
        )

    def _empty_response(
        self,
        *,
        preparation: SectorMomentumSnapshotPreparation,
        debug: bool,
    ) -> SectorRelativeRotationResultsResponseDto:
        status = self._status.empty()
        return SectorRelativeRotationResultsResponseDto(
            status=status.status,
            tradingDay=self._trading_day(preparation.resolution),
            pageStatus=self._page_status(status, context=preparation.context),
            analysis=None,
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=self._debug_info(preparation=preparation, debug=debug),
        )

    def _error_response(
        self,
        *,
        scope: SectorMomentumScope,
        debug: bool,
        code: str,
    ) -> SectorRelativeRotationResultsResponseDto:
        context = self._fallback_context()
        resolution = self._fallback_resolution(context.trade_date)
        status = (
            self._status.error("SA_HIERARCHY_UNAVAILABLE")
            if code == "SA_HIERARCHY_UNAVAILABLE"
            else self._status.error("SA_QUERY_FAILED")
        )
        return SectorRelativeRotationResultsResponseDto(
            status="ERROR",
            tradingDay=self._trading_day(resolution),
            pageStatus=self._page_status(status, context=context),
            analysis=None,
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=(
                SectorAnalysisDebugInfoDto(
                    expectedTradeDate=resolution.expected.trade_date,
                    observedTradeDate=None,
                    scope=scope,
                    expectedSectorCount=0,
                    expectedValidSectorCount=0,
                    observedValidSectorCount=0,
                    sampleSectorCodes=[],
                )
                if debug
                else None
            ),
        )

    @staticmethod
    def _hierarchy_dto(hierarchy: SectorHierarchySnapshot) -> SectorHierarchyDto:
        return SectorHierarchyDto(
            hierarchyVersion=hierarchy.baseline_version,
            publishedAt=hierarchy.published_at,
            nodes=[
                SectorHierarchyNodeDto(
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
                for node in hierarchy.nodes
            ],
        )

    @staticmethod
    def _trading_day(
        resolution: SectorTradingDateResolution,
    ) -> SectorAnalysisTradingDayDto:
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
        preparation: SectorMomentumSnapshotPreparation,
        debug: bool,
    ) -> SectorAnalysisDebugInfoDto | None:
        if not debug:
            return None
        resolution = preparation.resolution
        observed = resolution.observed
        return SectorAnalysisDebugInfoDto(
            expectedTradeDate=resolution.expected.trade_date,
            observedTradeDate=observed.trade_date if observed else None,
            scope=preparation.scope,
            expectedSectorCount=resolution.expected.expected_sector_count,
            expectedValidSectorCount=resolution.expected.valid_sector_count,
            observedValidSectorCount=observed.valid_sector_count if observed else 0,
            sampleSectorCodes=[node.sector_code for node in preparation.pool[:5]],
        )

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
