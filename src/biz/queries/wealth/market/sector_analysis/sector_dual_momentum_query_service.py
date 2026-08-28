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
)
from src.biz.queries.wealth.market.sector_analysis.sector_analysis_meta_query_service import (
    SectorAnalysisMetaFacts,
    SectorAnalysisMetaQueryService,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_snapshot_query_service import (
    SectorMomentumSnapshot,
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
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_classifier import (
    SectorDualMomentumClassifier,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    ALLOWED_LEADING_THRESHOLDS,
    ALLOWED_PERIODS,
    BASIS_FORMULA_KEY,
    BASIS_FORMULA_VERSION,
    FORMULA_KEY,
    FORMULA_VERSION,
    MINIMUM_GROUP_SIZE,
    SectorDualMomentumClassification,
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
)


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")


class SectorDualMomentumQueryService:
    """Compose dual-momentum DTOs from the shared immutable fact snapshot."""

    def __init__(
        self,
        *,
        meta_service: SectorAnalysisMetaQueryService | None = None,
        snapshot_service: SectorMomentumSnapshotQueryService | None = None,
        classifier: SectorDualMomentumClassifier | None = None,
        calculator: SectorMomentumCalculator | None = None,
        status_resolver: SectorAnalysisStatusResolver | None = None,
    ) -> None:
        self._meta_service = meta_service or SectorAnalysisMetaQueryService()
        self._snapshot_service = snapshot_service or SectorMomentumSnapshotQueryService()
        self._classifier = classifier or SectorDualMomentumClassifier()
        self._calculator = calculator or SectorMomentumCalculator()
        self._status = status_resolver or SectorAnalysisStatusResolver()

    def build_meta(
        self,
        session: Session,
        *,
        market: str,
    ) -> SectorDualMomentumMetaResponseDto:
        facts = self._meta_service.load(session, market=market)
        resolution = self._meta_resolution(facts)
        assert resolution.observed is not None
        status = self._status.resolve(
            trading_day=resolution,
            calculable_count=resolution.observed.valid_sector_count,
        )
        if status.status not in {"READY", "DELAYED"}:
            raise SectorDataQueryError("dual-momentum meta has no usable business date")
        return SectorDualMomentumMetaResponseDto(
            status=status.status,
            tradingDay=self._trading_day(resolution),
            pageStatus=self._page_status(status, context=facts.context),
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
        period: SectorDualMomentumPeriod,
        leading_threshold: SectorDualMomentumLeadingThreshold,
        hierarchy_version: str,
        debug: bool,
    ) -> SectorDualMomentumResultsResponseDto:
        try:
            snapshot = self._snapshot_service.build(
                session,
                market=market,
                trade_date=trade_date,
                scope=scope,
                level1_code=level1_code,
                level2_code=level2_code,
                period=period,
                expected_hierarchy_version=hierarchy_version,
                date_errors_are_selection=True,
            )
            calculable_count = sum(
                row.rank_fact.return_pct is not None for row in snapshot.rows
            )
            status = self._status.resolve(
                trading_day=snapshot.resolution,
                calculable_count=calculable_count,
            )
            if status.status == "EMPTY":
                return self._empty_response(snapshot=snapshot, debug=debug)

            classifications = tuple(
                self._classifier.classify(
                    return_fact=row.return_fact,
                    rank_fact=row.rank_fact,
                    calculable_count=calculable_count,
                    leading_threshold=leading_threshold,
                )
                for row in snapshot.rows
            )
            sorted_classifications = tuple(
                sorted(classifications, key=self._classification_sort_key)
            )
            node_by_code = {
                row.node.sector_code: row.node for row in snapshot.rows
            }
            items = [
                self._row_dto(
                    classification=item,
                    node=node_by_code[item.sector_code],
                    hierarchy=snapshot.hierarchy,
                )
                for item in sorted_classifications
            ]
            analysis = SectorDualMomentumAnalysisDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                basisFormulaKey=BASIS_FORMULA_KEY,
                basisFormulaVersion=BASIS_FORMULA_VERSION,
                hierarchyVersion=snapshot.hierarchy.baseline_version,
                scope=scope,
                period=period,
                leadingThreshold=leading_threshold,
                minimumGroupSize=MINIMUM_GROUP_SIZE,
                parentSelection=self._parent_selection(snapshot),
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
                tradingDay=self._trading_day(snapshot.resolution),
                pageStatus=self._page_status(status, context=snapshot.context),
                analysis=analysis,
                message=status.message,
                exceptionCode=status.exception_code,
                debugInfo=self._debug_info(snapshot=snapshot, debug=debug),
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
    def _classification_sort_key(item: SectorDualMomentumClassification):
        if item.return_pct is None:
            return (1, 0, 0, item.sector_code)
        assert item.percentile is not None
        return (0, -item.percentile, -item.return_pct, item.sector_code)

    def _row_dto(
        self,
        *,
        classification: SectorDualMomentumClassification,
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
        snapshot: SectorMomentumSnapshot,
    ) -> SectorParentSelectionDto:
        level1 = snapshot.hierarchy.nodes_by_code.get(snapshot.level1_code or "")
        level2 = snapshot.hierarchy.nodes_by_code.get(snapshot.level2_code or "")
        return SectorParentSelectionDto(
            level1Code=snapshot.level1_code,
            level1Name=level1.sector_name if level1 is not None else None,
            level2Code=snapshot.level2_code,
            level2Name=level2.sector_name if level2 is not None else None,
        )

    def _empty_response(
        self,
        *,
        snapshot: SectorMomentumSnapshot,
        debug: bool,
    ) -> SectorDualMomentumResultsResponseDto:
        status = self._status.empty()
        return SectorDualMomentumResultsResponseDto(
            status=status.status,
            tradingDay=self._trading_day(snapshot.resolution),
            pageStatus=self._page_status(status, context=snapshot.context),
            analysis=None,
            message=status.message,
            exceptionCode=status.exception_code,
            debugInfo=self._debug_info(snapshot=snapshot, debug=debug),
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
        snapshot: SectorMomentumSnapshot,
        debug: bool,
    ) -> SectorAnalysisDebugInfoDto | None:
        if not debug:
            return None
        resolution = snapshot.resolution
        observed = resolution.observed
        return SectorAnalysisDebugInfoDto(
            expectedTradeDate=resolution.expected.trade_date,
            observedTradeDate=observed.trade_date if observed else None,
            scope=snapshot.scope,
            expectedSectorCount=resolution.expected.expected_sector_count,
            expectedValidSectorCount=resolution.expected.valid_sector_count,
            observedValidSectorCount=observed.valid_sector_count if observed else 0,
            sampleSectorCodes=[row.node.sector_code for row in snapshot.rows[:5]],
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
