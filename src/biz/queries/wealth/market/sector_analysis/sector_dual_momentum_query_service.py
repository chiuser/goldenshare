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
    SectorPublishedDualMomentumRow,
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
from src.biz.schemas.wealth.market.sector_dual_momentum import (
    SectorDualMomentumAnalysisDto,
    SectorDualMomentumDefaultsDto,
    SectorDualMomentumFormulaDto,
    SectorDualMomentumMetaResponseDto,
    SectorDualMomentumResultsResponseDto,
    SectorDualMomentumRowDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_analysis_status_resolver import (
    SectorAnalysisStatusResolution,
    SectorAnalysisStatusResolver,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    ALLOWED_LEADING_THRESHOLDS,
    ALLOWED_PERIODS,
    BASIS_FORMULA_KEY,
    BASIS_FORMULA_VERSION,
    FORMULA_KEY,
    FORMULA_VERSION,
    MINIMUM_GROUP_SIZE,
    SectorDualMomentumLeadingThreshold,
    SectorDualMomentumPeriod,
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


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


class SectorDualMomentumQueryService:
    """Compose dual-momentum DTOs exclusively from the selected published batch."""

    def __init__(
        self,
        *,
        context_query: MarketPageContextQuery | None = None,
        hierarchy_query: SectorHierarchyQuery | None = None,
        fact_reader: SectorAnalysisFactReader | None = None,
        calculator: SectorMomentumCalculator | None = None,
        status_resolver: SectorAnalysisStatusResolver | None = None,
    ) -> None:
        self._context_query = context_query or MarketPageContextQuery()
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()
        self._facts = fact_reader or SectorAnalysisFactReader()
        self._calculator = calculator or SectorMomentumCalculator()
        self._status = status_resolver or SectorAnalysisStatusResolver()

    def build_meta(
        self,
        session: Session,
        *,
        market: str,
    ) -> SectorDualMomentumMetaResponseDto:
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
        status = self._status.resolve(
            trading_day=resolution,
            calculable_count=resolution.observed.valid_sector_count if resolution.observed else 0,
        )
        if status.status not in {"READY", "DELAYED"}:
            raise SectorDataQueryError("dual-momentum meta has no usable business date")
        return SectorDualMomentumMetaResponseDto(
            status=status.status,
            tradingDay=self._trading_day(resolution),
            pageStatus=self._page_status(status, context=context),
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=None,
            formula=SectorDualMomentumFormulaDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                basisFormulaKey=BASIS_FORMULA_KEY,
                basisFormulaVersion=BASIS_FORMULA_VERSION,
                periods=list(ALLOWED_PERIODS),
                leadingThresholds=list(ALLOWED_LEADING_THRESHOLDS),
                minimumGroupSize=MINIMUM_GROUP_SIZE,
                scopes=list(ALLOWED_SCOPES),
            ),
            defaults=SectorDualMomentumDefaultsDto(
                scope="LEVEL_1",
                period=20,
                leadingThreshold=80,
                resultView="QUALIFIED",
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
        period: SectorDualMomentumPeriod,
        leading_threshold: SectorDualMomentumLeadingThreshold,
        hierarchy_version: str,
        debug: bool,
    ) -> SectorDualMomentumResultsResponseDto:
        try:
            context = self._context_query.resolve_context(
                session, market=market, requested_trade_date=None,
            )
            hierarchy = self._hierarchy_query.load(session)
            if hierarchy.baseline_version != hierarchy_version:
                raise SectorMomentumFactVersionMismatchError("行业层级版本已更新，请刷新后重试")
            pool = resolve_scope_pool(
                hierarchy,
                scope=scope,
                level1_code=level1_code,
                level2_code=level2_code,
            )
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
            batch_id = coverage.batch_by_date.get(observed.trade_date) if observed else None
            if batch_id is None or observed is None or observed.availability == "MISSING":
                return self._empty_response(context=context, resolution=resolution, debug_info=debug_info)
            rows = self._facts.load_dual_momentum_rows(
                session, batch_id=batch_id, trade_date=observed.trade_date,
                scope=scope, level1_code=level1_code, level2_code=level2_code,
                period=period, leading_threshold=leading_threshold, hierarchy=hierarchy,
            )
            calculable_count = sum(row.return_pct is not None for row in rows)
            status = self._status.resolve(
                trading_day=resolution,
                calculable_count=calculable_count,
            )
            items = [
                self._row_dto(
                    classification=item,
                    node=hierarchy.nodes_by_code[item.sector_code],
                    hierarchy=hierarchy,
                )
                for item in sorted(rows, key=self._classification_sort_key)
            ]
            if status.status == "EMPTY":
                return self._empty_response(context=context, resolution=resolution, debug_info=debug_info)
            analysis = SectorDualMomentumAnalysisDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                basisFormulaKey=BASIS_FORMULA_KEY,
                basisFormulaVersion=BASIS_FORMULA_VERSION,
                hierarchyVersion=hierarchy.baseline_version,
                scope=scope,
                period=period,
                leadingThreshold=leading_threshold,
                minimumGroupSize=MINIMUM_GROUP_SIZE,
                parentSelection=self._parent_selection(hierarchy, level1_code=level1_code, level2_code=level2_code),
                totalCount=len(items),
                calculableCount=calculable_count,
                qualifiedCount=sum(
                    item.qualificationStatus == "QUALIFIED" for item in items
                ),
                insufficientCount=sum(
                    item.qualificationStatus == "NOT_EVALUATED" for item in items
                ),
                plottableCount=sum(
                    item.coordinateStatus == "PLOTTABLE" for item in items
                ),
                items=items,
            )
            return SectorDualMomentumResultsResponseDto(
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
    def _classification_sort_key(item: SectorPublishedDualMomentumRow):
        if item.return_pct is None:
            return (1, 0, 0, item.sector_code)
        assert item.percentile is not None
        return (0, -item.percentile, -item.return_pct, item.sector_code)

    def _row_dto(
        self,
        *,
        classification: SectorPublishedDualMomentumRow,
        node: SectorHierarchyNode,
        hierarchy: SectorHierarchySnapshot,
    ) -> SectorDualMomentumRowDto:
        missing_reason = classification.missing_reason
        return SectorDualMomentumRowDto(
            sectorCode=node.sector_code,
            sectorName=node.sector_name,
            industryLevel=node.industry_level,  # type: ignore[arg-type]
            parentSectorCode=node.parent_sector_code,
            parentSectorName=node.parent_sector_name,
            hierarchyPath=node.hierarchy_path,
            canDrillDown=bool(hierarchy.children_by_parent.get(node.sector_code)),
            returnPct=self._calculator.as_json_return(classification.return_pct),
            strengthRank=classification.strength_rank,
            percentile=self._calculator.as_json_percentile(
                classification.percentile
            ),
            absoluteStatus=classification.absolute_status,
            relativeStatus=classification.relative_status,
            qualificationStatus=classification.qualification_status,
            coordinateStatus=classification.coordinate_status,
            displayStatus=classification.display_status,
            missingReason=(
                None if missing_reason in {None, "NONE"} else missing_reason
            ),
        )

    @staticmethod
    def _parent_selection(
        hierarchy: SectorHierarchySnapshot,
        *,
        level1_code: str | None,
        level2_code: str | None,
    ) -> SectorParentSelectionDto:
        level1 = hierarchy.nodes_by_code.get(level1_code or "")
        level2 = hierarchy.nodes_by_code.get(level2_code or "")
        return SectorParentSelectionDto(
            level1Code=level1_code,
            level1Name=level1.sector_name if level1 is not None else None,
            level2Code=level2_code,
            level2Name=level2.sector_name if level2 is not None else None,
        )

    def _empty_response(
        self,
        *,
        context: MarketPageContext,
        resolution: SectorTradingDateResolution,
        debug_info: SectorAnalysisDebugInfoDto | None,
    ) -> SectorDualMomentumResultsResponseDto:
        status = self._status.empty()
        return SectorDualMomentumResultsResponseDto(
            status=status.status,
            tradingDay=self._trading_day(resolution),
            pageStatus=self._page_status(status, context=context),
            analysis=None,
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=debug_info,
        )

    def _error_response(
        self,
        *,
        scope: SectorMomentumScope,
        debug: bool,
        code: str,
    ) -> SectorDualMomentumResultsResponseDto:
        context = self._fallback_context()
        resolution = self._fallback_resolution(context.trade_date)
        status = (
            self._status.error("SA_HIERARCHY_UNAVAILABLE")
            if code == "SA_HIERARCHY_UNAVAILABLE"
            else self._status.error("SA_QUERY_FAILED")
        )
        return SectorDualMomentumResultsResponseDto(
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
