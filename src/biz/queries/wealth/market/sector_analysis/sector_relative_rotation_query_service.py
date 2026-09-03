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
    SectorPublishedRelativeRotationRow,
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
    resolve_scope_pool,
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
    SectorRelativeRotationTrailLength,
    parse_relative_rotation_period,
    parse_relative_rotation_trail_length,
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
        self, *, context_query: MarketPageContextQuery | None = None,
        hierarchy_query: SectorHierarchyQuery | None = None,
        fact_reader: SectorAnalysisFactReader | None = None,
        momentum_calculator: SectorMomentumCalculator | None = None,
        status_resolver: SectorAnalysisStatusResolver | None = None,
    ) -> None:
        self._context_query = context_query or MarketPageContextQuery()
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()
        self._facts = fact_reader or SectorAnalysisFactReader()
        # Formatting only; online requests never execute the formula kernel.
        self._momentum_calculator = momentum_calculator or SectorMomentumCalculator()
        self._status = status_resolver or SectorAnalysisStatusResolver()

    def build_meta(
        self,
        session: Session,
        *,
        market: str,
    ) -> SectorRelativeRotationMetaResponseDto:
        context = self._context_query.resolve_context(
            session, market=market, requested_trade_date=None,
        )
        hierarchy = self._hierarchy_query.load(session)
        coverage = self._facts.load_momentum_coverage(
            session, coverage_end_date=context.trade_date, hierarchy=hierarchy,
        )
        resolution = self._facts.resolve_trading_date(
            coverage, expected_trade_date=context.trade_date, is_explicit=False,
        )
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
            pageStatus=self._page_status(status, context=context),
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
            hierarchy=self._hierarchy_dto(hierarchy),
            coverageStartDate=coverage.coverage_start_date,
            coverageEndDate=coverage.coverage_end_date,
            tradeDates=[
                SectorTradeDateAvailabilityDto(
                    tradeDate=item.trade_date,
                    availability=item.availability,
                    expectedSectorCount=item.expected_sector_count,
                    validSectorCount=item.valid_sector_count,
                )
                for item in (entry.availability for entry in coverage.calendar_dates)
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
            parse_relative_rotation_period(period)
            parse_relative_rotation_trail_length(trail_length)
            context = self._context_query.resolve_context(
                session, market=market, requested_trade_date=None,
            )
            hierarchy = self._hierarchy_query.load(session)
            if hierarchy.baseline_version != hierarchy_version:
                raise SectorMomentumFactVersionMismatchError("行业层级版本已更新，请刷新后重试")
            pool = resolve_scope_pool(
                hierarchy, scope=scope, level1_code=level1_code, level2_code=level2_code,
            )
            if sector_code is not None and sector_code not in {node.sector_code for node in pool}:
                raise SectorSelectionInvalidError("所选行业不属于当前比较范围")
            coverage = self._facts.load_momentum_coverage(
                session, coverage_end_date=context.trade_date, hierarchy=hierarchy,
            )
            try:
                resolution = self._facts.resolve_trading_date(
                    coverage, expected_trade_date=trade_date or context.trade_date,
                    is_explicit=trade_date is not None,
                )
            except SectorScopeInvalidError as exc:
                raise SectorSelectionInvalidError(str(exc)) from exc
            debug_info = self._debug_info(
                resolution=resolution, scope=scope, pool=pool, debug=debug,
            )
            observed = resolution.observed
            batch_by_date = coverage.batch_by_date
            batch_id = batch_by_date.get(observed.trade_date) if observed else None
            if batch_id is None or observed is None or observed.availability == "MISSING":
                return self._empty_response(
                    context=context, resolution=resolution, debug_info=debug_info,
                )
            current_points = self._facts.load_relative_rotation_rows(
                session, batch_id=batch_id, trade_date=observed.trade_date,
                scope=scope, level1_code=level1_code, level2_code=level2_code,
                period=period, hierarchy=hierarchy,
            )
            current_calculable_count = sum(point.percentile is not None for point in current_points)
            status = self._status.resolve(
                trading_day=resolution, calculable_count=current_calculable_count,
            )
            if status.status == "EMPTY":
                return self._empty_response(
                    context=context, resolution=resolution, debug_info=debug_info,
                )
            sorted_points = tuple(sorted(current_points, key=self._canonical_sort_key))
            selected_code = sector_code or self._default_selection(sorted_points)
            display_dates = tuple(
                entry.availability.trade_date for entry in coverage.calendar_dates
                if entry.availability.trade_date <= observed.trade_date
            )[-trail_length:]
            history = self._facts.load_relative_rotation_history(
                session,
                batch_by_date={
                    day: batch_by_date[day] for day in display_dates[:-1]
                    if day in batch_by_date
                },
                scope=scope, level1_code=level1_code, level2_code=level2_code,
                period=period, hierarchy=hierarchy, selected_sector_code=selected_code,
            )
            selected_by_date = {point.trade_date: point for point in history}
            selected_by_date[observed.trade_date] = next(
                point for point in current_points if point.sector_code == selected_code
            )
            selected_points = [
                self._trail_point_dto(selected_by_date[day]) if day in selected_by_date
                else self._unpublished_trail_point(day)
                for day in display_dates
            ]
            group_interpretation = self._group_interpretation(current_points)
            quadrant_counts = self._quadrant_counts(
                current_points,
                group_interpretation=group_interpretation,
            )
            node_by_code = {node.sector_code: node for node in pool}
            items = [
                self._row_dto(
                    point=point,
                    node=node_by_code[point.sector_code],
                    hierarchy=hierarchy,
                )
                for point in sorted_points
            ]
            selected_trail = SectorRelativeRotationTrailDto(
                sectorCode=selected_code,
                requestedLength=trail_length,
                dateSlotCount=len(selected_points),
                points=selected_points,
            )
            analysis = SectorRelativeRotationAnalysisDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                basisFormulaKey=BASIS_FORMULA_KEY,
                basisFormulaVersion=BASIS_FORMULA_VERSION,
                hierarchyVersion=hierarchy.baseline_version,
                scope=scope,
                period=period,
                improvementLookbackDays=IMPROVEMENT_LOOKBACK_DAYS,
                trailLength=trail_length,
                minimumGroupSize=MINIMUM_GROUP_SIZE,
                parentSelection=self._parent_selection(hierarchy, level1_code=level1_code, level2_code=level2_code),
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
                debugInfo=debug_info,
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
    def _canonical_sort_key(point: SectorPublishedRelativeRotationRow):
        if point.percentile is None:
            return (2, 0, 0, point.sector_code)
        if point.percentile_delta_5d is None:
            return (1, -point.percentile, 0, point.sector_code)
        return (0, -point.percentile, -point.percentile_delta_5d, point.sector_code)

    @staticmethod
    def _unpublished_trail_point(day: date) -> SectorRelativeRotationTrailPointDto:
        return SectorRelativeRotationTrailPointDto(
            tradeDate=day, returnPct=None, percentile=None, percentileDelta5d=None,
            rotationStatus="DATA_INSUFFICIENT", coordinateStatus="UNAVAILABLE",
            currentMissingReason="DATE_MISSING", comparisonMissingReason="DATE_MISSING",
        )

    @staticmethod
    def _default_selection(
        rows: tuple[SectorPublishedRelativeRotationRow, ...],
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
        rows: tuple[SectorPublishedRelativeRotationRow, ...],
    ) -> SectorRelativeGroupInterpretation:
        if not rows:
            raise SectorDataQueryError("relative-rotation current snapshot is empty")
        interpretations = {row.group_interpretation for row in rows}
        if len(interpretations) != 1:
            raise SectorDataQueryError("published rotation group interpretations disagree")
        return rows[0].group_interpretation

    @staticmethod
    def _quadrant_counts(
        rows: tuple[SectorPublishedRelativeRotationRow, ...],
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
        point: SectorPublishedRelativeRotationRow,
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
        point: SectorPublishedRelativeRotationRow,
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
        hierarchy: SectorHierarchySnapshot, *, level1_code: str | None, level2_code: str | None,
    ) -> SectorParentSelectionDto:
        level1 = hierarchy.nodes_by_code.get(level1_code or "")
        level2 = hierarchy.nodes_by_code.get(level2_code or "")
        return SectorParentSelectionDto(
            level1Code=level1_code, level1Name=level1.sector_name if level1 else None,
            level2Code=level2_code, level2Name=level2.sector_name if level2 else None,
        )

    def _empty_response(
        self, *, context: MarketPageContext, resolution: SectorTradingDateResolution,
        debug_info: SectorAnalysisDebugInfoDto | None,
    ) -> SectorRelativeRotationResultsResponseDto:
        status = self._status.empty()
        return SectorRelativeRotationResultsResponseDto(
            status=status.status, tradingDay=self._trading_day(resolution),
            pageStatus=self._page_status(status, context=context), analysis=None,
            message=status.message, exceptionCode=status.exception_code, debugInfo=debug_info,
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
        resolution: SectorTradingDateResolution,
        scope: SectorMomentumScope,
        pool: tuple[SectorHierarchyNode, ...],
        debug: bool,
    ) -> SectorAnalysisDebugInfoDto | None:
        if not debug:
            return None
        observed = resolution.observed
        return SectorAnalysisDebugInfoDto(
            expectedTradeDate=resolution.expected.trade_date,
            observedTradeDate=observed.trade_date if observed else None,
            scope=scope,
            expectedSectorCount=resolution.expected.expected_sector_count,
            expectedValidSectorCount=resolution.expected.valid_sector_count,
            observedValidSectorCount=observed.valid_sector_count if observed else 0,
            sampleSectorCodes=[node.sector_code for node in pool[:5]],
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
