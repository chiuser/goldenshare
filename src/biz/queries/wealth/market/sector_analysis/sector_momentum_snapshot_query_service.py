from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchyQuery,
    SectorHierarchySnapshot,
)
from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContext,
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_momentum_query import (
    SectorMomentumQuery,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    SectorMomentumFactVersionMismatchError,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_calculator import (
    SectorMomentumCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorMomentumPeriod,
    SectorMomentumScope,
    SectorRankFact,
    SectorReturnFact,
    SectorScopeInvalidError,
    SectorSelectionInvalidError,
    SectorTradingDateResolution,
    resolve_scope_pool,
)


@dataclass(frozen=True, slots=True)
class SectorMomentumSnapshotRow:
    node: SectorHierarchyNode
    return_fact: SectorReturnFact
    rank_fact: SectorRankFact


@dataclass(frozen=True, slots=True)
class SectorMomentumSnapshot:
    context: MarketPageContext
    hierarchy: SectorHierarchySnapshot
    resolution: SectorTradingDateResolution
    scope: SectorMomentumScope
    period: SectorMomentumPeriod
    level1_code: str | None
    level2_code: str | None
    rows: tuple[SectorMomentumSnapshotRow, ...]


@dataclass(frozen=True, slots=True)
class SectorMomentumSnapshotPreparation:
    context: MarketPageContext
    hierarchy: SectorHierarchySnapshot
    resolution: SectorTradingDateResolution
    scope: SectorMomentumScope
    period: SectorMomentumPeriod
    level1_code: str | None
    level2_code: str | None
    pool: tuple[SectorHierarchyNode, ...]


class SectorMomentumSnapshotQueryService:
    """Build one immutable, page-neutral momentum snapshot with bounded IO."""

    def __init__(
        self,
        *,
        context_query: MarketPageContextQuery | None = None,
        hierarchy_query: SectorHierarchyQuery | None = None,
        momentum_query: SectorMomentumQuery | None = None,
        calculator: SectorMomentumCalculator | None = None,
    ) -> None:
        self._context_query = context_query or MarketPageContextQuery()
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()
        self._query = momentum_query or SectorMomentumQuery()
        self._calculator = calculator or SectorMomentumCalculator()

    def build(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
        period: SectorMomentumPeriod,
        expected_hierarchy_version: str | None = None,
        date_errors_are_selection: bool = False,
    ) -> SectorMomentumSnapshot:
        context = self._context_query.resolve_context(
            session,
            market=market,
            requested_trade_date=None,
        )
        preparation = self.prepare_for_context(
            session,
            context=context,
            trade_date=trade_date,
            scope=scope,
            level1_code=level1_code,
            level2_code=level2_code,
            period=period,
            expected_hierarchy_version=expected_hierarchy_version,
            date_errors_are_selection=date_errors_are_selection,
        )
        return self.build_prepared(session, preparation=preparation)

    def prepare_for_context(
        self,
        session: Session,
        *,
        context: MarketPageContext,
        trade_date: date | None,
        scope: SectorMomentumScope,
        level1_code: str | None,
        level2_code: str | None,
        period: SectorMomentumPeriod,
        expected_hierarchy_version: str | None = None,
        date_errors_are_selection: bool = False,
    ) -> SectorMomentumSnapshotPreparation:
        hierarchy = self._hierarchy_query.load(session)
        if (
            expected_hierarchy_version is not None
            and hierarchy.baseline_version != expected_hierarchy_version
        ):
            raise SectorMomentumFactVersionMismatchError(
                "sector hierarchy version no longer matches the requested facts"
            )
        pool = resolve_scope_pool(
            hierarchy,
            scope=scope,
            level1_code=level1_code,
            level2_code=level2_code,
        )
        try:
            resolution = self._query.resolve_trading_date(
                session,
                expected_trade_date=trade_date or context.trade_date,
                coverage_end_date=context.trade_date,
                sector_codes=tuple(node.sector_code for node in hierarchy.nodes),
                is_explicit=trade_date is not None,
            )
        except SectorScopeInvalidError as exc:
            if date_errors_are_selection:
                raise SectorSelectionInvalidError(str(exc)) from exc
            raise
        return SectorMomentumSnapshotPreparation(
            context=context,
            hierarchy=hierarchy,
            resolution=resolution,
            scope=scope,
            period=period,
            level1_code=level1_code,
            level2_code=level2_code,
            pool=pool,
        )

    def build_prepared(
        self,
        session: Session,
        *,
        preparation: SectorMomentumSnapshotPreparation,
    ) -> SectorMomentumSnapshot:
        resolution = preparation.resolution
        if (
            resolution.observed is None
            or resolution.observed.availability == "MISSING"
        ):
            target_date = (
                resolution.observed.trade_date
                if resolution.observed is not None
                else resolution.expected.trade_date
            )
            returns = tuple(
                SectorReturnFact(
                    sector_code=node.sector_code,
                    trade_date=target_date,
                    return_pct=None,
                    missing_reason="DATE_MISSING",
                )
                for node in preparation.pool
            )
        else:
            open_dates = self._query.load_open_dates(
                session,
                end_date=resolution.observed.trade_date,
                count=1 if preparation.period == 1 else preparation.period + 1,
            )
            facts = self._query.load_facts(
                session,
                sector_codes=tuple(node.sector_code for node in preparation.pool),
                start_date=open_dates[0],
                end_date=open_dates[-1],
            )
            returns = self._calculator.calculate_for_date(
                sector_codes=(node.sector_code for node in preparation.pool),
                open_dates=open_dates,
                target_date=resolution.observed.trade_date,
                period=preparation.period,
                fact_index=self._calculator.index_facts(facts),
            )
        ranked = self._calculator.rank_strength(returns)
        rows = tuple(
            SectorMomentumSnapshotRow(
                node=node,
                return_fact=return_fact,
                rank_fact=rank_fact,
            )
            for node, return_fact, rank_fact in zip(
                preparation.pool,
                returns,
                ranked,
                strict=True,
            )
        )
        self._validate_rows(rows)
        return SectorMomentumSnapshot(
            context=preparation.context,
            hierarchy=preparation.hierarchy,
            resolution=preparation.resolution,
            scope=preparation.scope,
            period=preparation.period,
            level1_code=preparation.level1_code,
            level2_code=preparation.level2_code,
            rows=rows,
        )

    @staticmethod
    def _validate_rows(rows: tuple[SectorMomentumSnapshotRow, ...]) -> None:
        for row in rows:
            codes = {
                row.node.sector_code,
                row.return_fact.sector_code,
                row.rank_fact.sector_code,
            }
            if len(codes) != 1:
                raise ValueError("snapshot facts must align to the hierarchy node")
            values = (
                row.rank_fact.return_pct,
                row.rank_fact.strength_rank,
                row.rank_fact.percentile,
            )
            if any(value is None for value in values) and not all(
                value is None for value in values
            ):
                raise ValueError("snapshot rank values must be null together")
            if row.return_fact.return_pct != row.rank_fact.return_pct:
                raise ValueError("snapshot return and rank values must match")
