from __future__ import annotations

from collections import Counter
from datetime import date

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
from src.biz.queries.wealth.market.sector_analysis.sector_price_volume_query import (
    SectorPriceVolumeQuery,
)
from src.biz.schemas.wealth.market.sector_analysis import (
    SectorHierarchyDto,
    SectorHierarchyNodeDto,
)
from src.biz.schemas.wealth.market.sector_price_volume import (
    PriceVolumeDateContextDto,
    PriceVolumeTradeDateAvailabilityDto,
    SectorPriceVolumeDebugInfoDto,
    SectorPriceVolumeDefaultsDto,
    SectorPriceVolumeDetailsDto,
    SectorPriceVolumeDetailsResponseDto,
    SectorPriceVolumeHistoryPointDto,
    SectorPriceVolumeMetaResponseDto,
    SectorPriceVolumeSelectedDto,
    SectorPriceVolumeSnapshotDto,
    SectorPriceVolumeSnapshotResponseDto,
    SectorPriceVolumeSnapshotRowDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    ALLOWED_SCOPES,
    SectorDataQueryError,
    SectorMomentumScope,
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
    resolve_scope_pool,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_calculator import (
    SectorPriceVolumeCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    ALLOWED_HISTORY_RANGES,
    ALLOWED_PERIODS,
    ALLOWED_STATES,
    DATE_COVERAGE_BASIS,
    FORMULA_KEY,
    FORMULA_VERSION,
    SectorPriceVolumeDateAvailabilityFact,
    SectorPriceVolumeFactMismatchError,
    SectorPriceVolumeHistoryRange,
    SectorPriceVolumeMetricFact,
    SectorPriceVolumeMissingReason,
    SectorPriceVolumePeriod,
    SectorPriceVolumeRankedFact,
    assert_price_volume_hierarchy_version,
)


class SectorPriceVolumeQueryService:
    """Compose price-volume metadata, snapshot, and selected history."""

    def __init__(
        self,
        *,
        context_query: MarketPageContextQuery | None = None,
        hierarchy_query: SectorHierarchyQuery | None = None,
        price_volume_query: SectorPriceVolumeQuery | None = None,
        calculator: SectorPriceVolumeCalculator | None = None,
    ) -> None:
        self._context_query = context_query or MarketPageContextQuery()
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()
        self._query = price_volume_query or SectorPriceVolumeQuery()
        self._calculator = calculator or SectorPriceVolumeCalculator()

    def build_meta(
        self,
        session: Session,
        *,
        market: str,
    ) -> SectorPriceVolumeMetaResponseDto:
        context = self._context_query.resolve_context(
            session,
            market=market,
            requested_trade_date=None,
        )
        hierarchy = self._hierarchy_query.load(session)
        coverage = self._query.load_trade_date_coverage(
            session,
            hierarchy_codes=self._hierarchy_codes(hierarchy),
            expected_trade_date=context.trade_date,
        )
        expected = next(
            (
                item
                for item in coverage.trade_dates
                if item.trade_date == context.trade_date
            ),
            None,
        )
        if expected is None:
            raise SectorDataQueryError("public business date is absent from coverage")
        default = expected if expected.availability == "COMPLETE" else next(
            (
                item
                for item in reversed(coverage.trade_dates)
                if item.trade_date < context.trade_date
                and item.availability == "COMPLETE"
            ),
            None,
        )
        if default is None:
            default_status = "EMPTY"
            display_text = "暂无可用量价数据"
        elif default.trade_date == context.trade_date:
            default_status = "READY"
            display_text = f"{default.trade_date.isoformat()} 盘后数据"
        else:
            default_status = "DELAYED"
            display_text = f"当前展示 {default.trade_date.isoformat()} 盘后数据"
        return SectorPriceVolumeMetaResponseDto(
            formulaKey=FORMULA_KEY,
            formulaVersion=FORMULA_VERSION,
            market="CN_A",
            periods=list(ALLOWED_PERIODS),
            historyRanges=list(ALLOWED_HISTORY_RANGES),
            scopes=list(ALLOWED_SCOPES),
            states=list(ALLOWED_STATES),
            defaults=SectorPriceVolumeDefaultsDto(
                scope="LEVEL_1",
                period=20,
                stateFilter="ALL",
                sortBy="PRICE_MOMENTUM",
                sortDirection="DESC",
                historyRange=20,
            ),
            dateCoverageBasis=DATE_COVERAGE_BASIS,
            dateContext=PriceVolumeDateContextDto(
                expectedTradeDate=context.trade_date,
                defaultTradeDate=default.trade_date if default is not None else None,
                defaultStatus=default_status,
                displayText=display_text,
            ),
            hierarchy=self._hierarchy_dto(hierarchy),
            coverageStartDate=coverage.coverage_start_date,
            coverageEndDate=coverage.coverage_end_date,
            tradeDates=[self._availability_dto(item) for item in coverage.trade_dates],
        )

    def build_snapshot(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
        period: SectorPriceVolumePeriod,
        hierarchy_version: str,
        debug: bool,
    ) -> SectorPriceVolumeSnapshotResponseDto:
        context: MarketPageContext | None = None
        pool_size = 0
        requested_count = 2 * period
        loaded_count = 0
        try:
            context = self._context_query.resolve_context(
                session,
                market=market,
                requested_trade_date=None,
            )
            hierarchy = self._hierarchy_query.load(session)
            assert_price_volume_hierarchy_version(
                requested=hierarchy_version,
                current=hierarchy.baseline_version,
            )
            pool = resolve_scope_pool(
                hierarchy,
                scope=scope,
                level1_code=level1_code,
                level2_code=level2_code,
            )
            pool_size = len(pool)
            self._validate_trade_date(trade_date=trade_date, context=context)
            availability = self._query.load_exact_trade_date_status(
                session,
                hierarchy_codes=self._hierarchy_codes(hierarchy),
                trade_date=trade_date,
            )
            open_dates = self._query.load_open_dates(
                session,
                end_date=trade_date,
                count=requested_count,
            )
            loaded_count = len(open_dates)
            if not open_dates or open_dates[-1] != trade_date:
                raise SectorSelectionInvalidError("tradeDate 必须是 SSE 开市日")
            facts = self._query.load_facts(
                session,
                sector_codes=tuple(node.sector_code for node in pool),
                start_date=open_dates[0],
                end_date=open_dates[-1],
            )
            ranked = self._calculator.calculate_snapshot(
                sector_codes=tuple(node.sector_code for node in pool),
                open_dates=open_dates,
                facts=facts,
                period=period,
            )
            node_by_code = {node.sector_code: node for node in pool}
            rows = [
                self._snapshot_row_dto(item, node=node_by_code[item.metric.sector_code])
                for item in ranked
            ]
            coordinate_count = sum(item.state is not None for item in rows)
            snapshot = SectorPriceVolumeSnapshotDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                hierarchyVersion=hierarchy.baseline_version,
                observedTradeDate=trade_date,
                availability=availability.availability,
                scope=scope,
                level1Code=level1_code,
                level2Code=level2_code,
                period=period,
                totalCount=len(rows),
                coordinateCount=coordinate_count,
                missingCoordinateCount=len(rows) - coordinate_count,
                rows=rows,
            )
            return SectorPriceVolumeSnapshotResponseDto(
                status="READY" if coordinate_count > 0 else "EMPTY",
                snapshot=snapshot,
                message=None if coordinate_count > 0 else "当前范围暂无可绘制量价坐标。",
                exceptionCode=None,
                debugInfo=self._debug_info(
                    enabled=debug,
                    context=context,
                    observed_trade_date=trade_date,
                    scope=scope,
                    pool_size=pool_size,
                    requested_count=requested_count,
                    loaded_count=loaded_count,
                    metrics=tuple(item.metric for item in ranked),
                ),
            )
        except (
            SectorPriceVolumeFactMismatchError,
            SectorScopeInvalidError,
            SectorSelectionInvalidError,
        ):
            raise
        except SectorHierarchyUnavailableError:
            return self._snapshot_error(
                code="SA_HIERARCHY_UNAVAILABLE",
                message="行业分类暂不可用，请稍后重试。",
                context=context,
                scope=scope,
                pool_size=pool_size,
                requested_count=requested_count,
                loaded_count=loaded_count,
                debug=debug,
            )
        except SectorDataQueryError:
            return self._snapshot_error(
                code="SA_QUERY_FAILED",
                message="量价分布数据读取失败，请稍后重试。",
                context=context,
                scope=scope,
                pool_size=pool_size,
                requested_count=requested_count,
                loaded_count=loaded_count,
                debug=debug,
            )
        except Exception:
            return self._snapshot_error(
                code="SA_QUERY_FAILED",
                message="量价分布数据读取失败，请稍后重试。",
                context=context,
                scope=scope,
                pool_size=pool_size,
                requested_count=requested_count,
                loaded_count=loaded_count,
                debug=debug,
            )

    def build_details(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
        period: SectorPriceVolumePeriod,
        history_range: SectorPriceVolumeHistoryRange,
        sector_code: str,
        hierarchy_version: str,
        debug: bool,
    ) -> SectorPriceVolumeDetailsResponseDto:
        context: MarketPageContext | None = None
        pool_size = 0
        requested_count = history_range + 2 * period - 1
        loaded_count = 0
        try:
            context = self._context_query.resolve_context(
                session,
                market=market,
                requested_trade_date=None,
            )
            hierarchy = self._hierarchy_query.load(session)
            assert_price_volume_hierarchy_version(
                requested=hierarchy_version,
                current=hierarchy.baseline_version,
            )
            pool = resolve_scope_pool(
                hierarchy,
                scope=scope,
                level1_code=level1_code,
                level2_code=level2_code,
            )
            pool_size = len(pool)
            selected = next(
                (item for item in pool if item.sector_code == sector_code),
                None,
            )
            if selected is None:
                raise SectorSelectionInvalidError("sectorCode 不属于当前比较范围")
            self._validate_trade_date(trade_date=trade_date, context=context)
            availability = self._query.load_exact_trade_date_status(
                session,
                hierarchy_codes=self._hierarchy_codes(hierarchy),
                trade_date=trade_date,
            )
            open_dates = self._query.load_open_dates(
                session,
                end_date=trade_date,
                count=requested_count,
            )
            loaded_count = len(open_dates)
            if not open_dates or open_dates[-1] != trade_date:
                raise SectorSelectionInvalidError("tradeDate 必须是 SSE 开市日")
            facts = self._query.load_facts(
                session,
                sector_codes=(selected.sector_code,),
                start_date=open_dates[0],
                end_date=open_dates[-1],
            )
            metrics = self._calculator.calculate_history(
                sector_code=selected.sector_code,
                open_dates=open_dates,
                facts=facts,
                period=period,
                history_range=history_range,
            )
            if availability.availability == "MISSING":
                metrics = (
                    SectorPriceVolumeMetricFact(
                        sector_code=selected.sector_code,
                        trade_date=trade_date,
                        price_momentum_pct=None,
                        amount_activity_pct=None,
                        price_missing_reason=SectorPriceVolumeMissingReason.DATE_MISSING,
                        amount_missing_reason=SectorPriceVolumeMissingReason.DATE_MISSING,
                    ),
                )
            details = SectorPriceVolumeDetailsDto(
                formulaKey=FORMULA_KEY,
                formulaVersion=FORMULA_VERSION,
                hierarchyVersion=hierarchy.baseline_version,
                observedTradeDate=trade_date,
                availability=availability.availability,
                scope=scope,
                level1Code=level1_code,
                level2Code=level2_code,
                period=period,
                historyRange=history_range,
                selected=self._selected_dto(selected),
                history=[self._history_point_dto(item) for item in metrics],
            )
            has_value = any(
                item.price_momentum_pct is not None
                or item.amount_activity_pct is not None
                for item in metrics
            )
            return SectorPriceVolumeDetailsResponseDto(
                status="READY" if has_value else "EMPTY",
                details=details,
                message=None if has_value else "当前行业暂无可展示的量价历史。",
                exceptionCode=None,
                debugInfo=self._debug_info(
                    enabled=debug,
                    context=context,
                    observed_trade_date=trade_date,
                    scope=scope,
                    pool_size=pool_size,
                    requested_count=requested_count,
                    loaded_count=loaded_count,
                    metrics=metrics,
                ),
            )
        except (
            SectorPriceVolumeFactMismatchError,
            SectorScopeInvalidError,
            SectorSelectionInvalidError,
        ):
            raise
        except SectorHierarchyUnavailableError:
            return self._details_error(
                code="SA_HIERARCHY_UNAVAILABLE",
                message="行业分类暂不可用，请稍后重试。",
                context=context,
                scope=scope,
                pool_size=pool_size,
                requested_count=requested_count,
                loaded_count=loaded_count,
                debug=debug,
            )
        except SectorDataQueryError:
            return self._details_error(
                code="SA_QUERY_FAILED",
                message="量价分布数据读取失败，请稍后重试。",
                context=context,
                scope=scope,
                pool_size=pool_size,
                requested_count=requested_count,
                loaded_count=loaded_count,
                debug=debug,
            )
        except Exception:
            return self._details_error(
                code="SA_QUERY_FAILED",
                message="量价分布数据读取失败，请稍后重试。",
                context=context,
                scope=scope,
                pool_size=pool_size,
                requested_count=requested_count,
                loaded_count=loaded_count,
                debug=debug,
            )

    @staticmethod
    def _validate_trade_date(
        *, trade_date: date, context: MarketPageContext
    ) -> None:
        if trade_date > context.trade_date:
            raise SectorSelectionInvalidError("tradeDate 超出公共业务日期范围")

    @staticmethod
    def _hierarchy_codes(hierarchy: SectorHierarchySnapshot) -> tuple[str, ...]:
        return tuple(node.sector_code for node in hierarchy.nodes)

    @staticmethod
    def _availability_dto(
        item: SectorPriceVolumeDateAvailabilityFact,
    ) -> PriceVolumeTradeDateAvailabilityDto:
        return PriceVolumeTradeDateAvailabilityDto(
            tradeDate=item.trade_date,
            availability=item.availability,
            expectedSectorCount=item.expected_sector_count,
            validSectorCount=item.valid_sector_count,
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

    def _snapshot_row_dto(
        self,
        item: SectorPriceVolumeRankedFact,
        *,
        node: SectorHierarchyNode,
    ) -> SectorPriceVolumeSnapshotRowDto:
        return SectorPriceVolumeSnapshotRowDto(
            sectorCode=node.sector_code,
            sectorName=node.sector_name,
            industryLevel=node.industry_level,
            hierarchyPath=node.hierarchy_path,
            parentSectorCode=node.parent_sector_code,
            parentSectorName=node.parent_sector_name,
            rootSectorCode=node.root_sector_code,
            rootSectorName=node.root_sector_name,
            priceMomentumPct=self._calculator.as_json_percent(
                item.metric.price_momentum_pct
            ),
            amountActivityPct=self._calculator.as_json_percent(
                item.metric.amount_activity_pct
            ),
            priceRank=item.price_rank,
            priceRankableCount=item.price_rankable_count,
            amountRank=item.amount_rank,
            amountRankableCount=item.amount_rankable_count,
            state=item.state,
            priceMissingReason=item.metric.price_missing_reason,
            amountMissingReason=item.metric.amount_missing_reason,
        )

    @staticmethod
    def _selected_dto(node: SectorHierarchyNode) -> SectorPriceVolumeSelectedDto:
        return SectorPriceVolumeSelectedDto(
            sectorCode=node.sector_code,
            sectorName=node.sector_name,
            industryLevel=node.industry_level,
            hierarchyPath=node.hierarchy_path,
            parentSectorCode=node.parent_sector_code,
            rootSectorCode=node.root_sector_code,
        )

    def _history_point_dto(
        self, item: SectorPriceVolumeMetricFact
    ) -> SectorPriceVolumeHistoryPointDto:
        return SectorPriceVolumeHistoryPointDto(
            tradeDate=item.trade_date,
            priceMomentumPct=self._calculator.as_json_percent(
                item.price_momentum_pct
            ),
            amountActivityPct=self._calculator.as_json_percent(
                item.amount_activity_pct
            ),
            priceMissingReason=item.price_missing_reason,
            amountMissingReason=item.amount_missing_reason,
        )

    @staticmethod
    def _reason_counts(
        metrics: tuple[SectorPriceVolumeMetricFact, ...],
    ) -> dict[SectorPriceVolumeMissingReason, int]:
        counts: Counter[SectorPriceVolumeMissingReason] = Counter()
        for item in metrics:
            if item.price_missing_reason is not None:
                counts[item.price_missing_reason] += 1
            if item.amount_missing_reason is not None:
                counts[item.amount_missing_reason] += 1
        return dict(sorted(counts.items(), key=lambda item: item[0].value))

    def _debug_info(
        self,
        *,
        enabled: bool,
        context: MarketPageContext,
        observed_trade_date: date,
        scope: SectorMomentumScope,
        pool_size: int,
        requested_count: int,
        loaded_count: int,
        metrics: tuple[SectorPriceVolumeMetricFact, ...],
    ) -> SectorPriceVolumeDebugInfoDto | None:
        if not enabled:
            return None
        return SectorPriceVolumeDebugInfoDto(
            expectedTradeDate=context.trade_date,
            observedTradeDate=observed_trade_date,
            scope=scope,
            poolSize=pool_size,
            requestedOpenDateCount=requested_count,
            loadedOpenDateCount=loaded_count,
            reasonCounts=self._reason_counts(metrics),
        )

    @staticmethod
    def _error_debug(
        *,
        enabled: bool,
        context: MarketPageContext | None,
        scope: SectorMomentumScope,
        pool_size: int,
        requested_count: int,
        loaded_count: int,
    ) -> SectorPriceVolumeDebugInfoDto | None:
        if not enabled or context is None:
            return None
        return SectorPriceVolumeDebugInfoDto(
            expectedTradeDate=context.trade_date,
            observedTradeDate=None,
            scope=scope,
            poolSize=pool_size,
            requestedOpenDateCount=requested_count,
            loadedOpenDateCount=loaded_count,
            reasonCounts={},
        )

    def _snapshot_error(self, **kwargs) -> SectorPriceVolumeSnapshotResponseDto:
        code = kwargs.pop("code")
        message = kwargs.pop("message")
        return SectorPriceVolumeSnapshotResponseDto(
            status="ERROR",
            snapshot=None,
            message=message,
            exceptionCode=code,
            debugInfo=self._error_debug(enabled=kwargs.pop("debug"), **kwargs),
        )

    def _details_error(self, **kwargs) -> SectorPriceVolumeDetailsResponseDto:
        code = kwargs.pop("code")
        message = kwargs.pop("message")
        return SectorPriceVolumeDetailsResponseDto(
            status="ERROR",
            details=None,
            message=message,
            exceptionCode=code,
            debugInfo=self._error_debug(enabled=kwargs.pop("debug"), **kwargs),
        )
