from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Literal

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.sector_overview import (
    ConceptHeatDto,
    ConceptHeatPointDto,
    ConceptSectorOverviewPayloadDto,
    ConceptWorkspaceDto,
    IndustryRankColumnDto,
    IndustrySelectionDto,
    IndustrySectorOverviewPayloadDto,
    IndustryWorkspaceDto,
    MetricValueDto,
    ModuleExceptionItemDto,
    RegionWorkspaceDto,
    RegionSectorOverviewPayloadDto,
    SectorDetailDto,
    SectorLeaderStockDto,
    SectorMemberStockDto,
    SectorMetricsDto,
    SectorOverviewDebugInfoDto,
    SectorOverviewResponseDto,
    SectorRankItemDto,
    TradingDayDto,
)
from src.biz.services.wealth.market.sector_overview.effective_a_stock_pool_query import (
    EffectiveAStockPoolQuery,
)
from src.biz.services.wealth.market.sector_overview.sector_overview_exception_builder import (
    SectorOverviewExceptionBuilder,
)
from src.biz.services.wealth.market.sector_overview.sector_overview_status_resolver import (
    SectorOverviewStatusResolver,
)
from src.biz.services.wealth.market.sector_overview.sector_selection_resolver import (
    SectorSelectionResolver,
)

from .sector_heat_query import SectorHeatQuery, SectorHeatRow
from .sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchyQuery,
    SectorHierarchyUnavailableError,
)
from .sector_member_query import SectorMemberQuery
from .sector_metrics_query import SectorMetricRow, SectorMetricsQuery, SectorView
from .sector_overview_state_query import (
    SectorOverviewStateQuery,
    SectorOverviewTradingDayContext,
)


IndustryRankMetric = Literal["CHANGE_PCT", "MAIN_NET_INFLOW", "UP_COUNT"]
ConceptRankMetric = Literal["HEAT_SCORE", "HEAT_DELTA_1D", "CHANGE_PCT", "MAIN_NET_INFLOW"]
RegionRankMetric = Literal["CHANGE_PCT", "MAIN_NET_INFLOW", "UP_COUNT"]


class MarketSectorOverviewQueryService:
    """Build one prod-backed V2 sector workspace per request."""

    def __init__(self) -> None:
        self._state_query = SectorOverviewStateQuery()
        self._hierarchy_query = SectorHierarchyQuery()
        self._metrics_query = SectorMetricsQuery()
        self._heat_query = SectorHeatQuery()
        self._pool_query = EffectiveAStockPoolQuery()
        self._member_query = SectorMemberQuery()
        self._selection_resolver = SectorSelectionResolver()
        self._status_resolver = SectorOverviewStatusResolver()
        self._exception_builder = SectorOverviewExceptionBuilder()

    def build_sector_overview(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        view: SectorView,
        rank_metric: IndustryRankMetric | ConceptRankMetric | RegionRankMetric,
        selected_code: str | None,
        debug: bool,
    ) -> SectorOverviewResponseDto:
        exceptions: list[ModuleExceptionItemDto] = []
        context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        source_state = self._state_query.load_source_state(
            session,
            expected_trade_date=context.expected_trade_date,
            view=view,
        )
        query_trade_date = trade_date or source_state.common_base_date or context.expected_trade_date

        try:
            if trade_date is not None and (
                not context.is_trading_day or source_state.common_base_date != trade_date
            ):
                workspace, has_rows, partial = self._empty_workspace(view=view, rank_metric=rank_metric), False, False
            else:
                workspace, has_rows, partial = self._build_workspace(
                    session,
                    trade_date=query_trade_date,
                    view=view,
                    rank_metric=rank_metric,
                    selected_code=selected_code,
                    exceptions=exceptions,
                )
            partial = partial or (has_rows and not source_state.all_sources_on(query_trade_date))
            if source_state.common_base_date is not None and source_state.common_base_date < context.expected_trade_date:
                exceptions.append(
                    self._exception_builder.source_delayed(
                        message="sector source bundle delayed",
                        expected_trade_date=context.expected_trade_date.isoformat(),
                        observed_trade_date=source_state.common_base_date.isoformat(),
                    )
                )
            if not has_rows:
                exceptions.append(self._exception_builder.source_empty(message="sector source bundle has no usable rows"))
            status = self._status_resolver.resolve(
                expected_trade_date=context.expected_trade_date,
                observed_trade_date=(query_trade_date if has_rows else source_state.common_base_date),
                has_display_rows=has_rows,
                has_error=False,
                has_partial_data=partial,
                as_of_time=context.as_of_time,
            )
        except SectorHierarchyUnavailableError as exc:
            exceptions.append(self._exception_builder.hierarchy_unavailable(message=str(exc)))
            workspace = self._empty_workspace(view=view, rank_metric=rank_metric)
            status = self._status_resolver.resolve(
                expected_trade_date=context.expected_trade_date,
                observed_trade_date=source_state.common_base_date,
                has_display_rows=False,
                has_error=True,
                has_partial_data=False,
                as_of_time=context.as_of_time,
                note="industry hierarchy serving unavailable",
            )
        except Exception as exc:  # noqa: BLE001
            exceptions.append(self._exception_builder.query_failed(message=f"sector-overview query failed: {exc}"))
            workspace = self._empty_workspace(view=view, rank_metric=rank_metric)
            status = self._status_resolver.resolve(
                expected_trade_date=context.expected_trade_date,
                observed_trade_date=source_state.common_base_date,
                has_display_rows=False,
                has_error=True,
                has_partial_data=False,
                as_of_time=context.as_of_time,
            )

        return SectorOverviewResponseDto(
            tradingDay=self._build_trading_day(context),
            pageStatus=status.page_status,
            sectorOverview=self._build_panel_payload(
                trade_date=query_trade_date,
                status=status.module_status.status,
                view=view,
                as_of=context.as_of_time,
                workspace=workspace,
            ),
            debugInfo=(
                SectorOverviewDebugInfoDto(modules=[status.module_status], exceptions=exceptions) if debug else None
            ),
        )

    def _build_workspace(
        self,
        session: Session,
        *,
        trade_date: date,
        view: SectorView,
        rank_metric: str,
        selected_code: str | None,
        exceptions: list[ModuleExceptionItemDto],
    ) -> tuple[dict[str, object], bool, bool]:
        if view == "INDUSTRY":
            return self._build_industry(
                session,
                trade_date=trade_date,
                rank_metric=rank_metric,
                selected_code=selected_code,
                exceptions=exceptions,
            )
        if view == "CONCEPT":
            return self._build_concept(
                session,
                trade_date=trade_date,
                rank_metric=rank_metric,
                selected_code=selected_code,
                exceptions=exceptions,
            )
        return self._build_region(
            session,
            trade_date=trade_date,
            rank_metric=rank_metric,
            selected_code=selected_code,
            exceptions=exceptions,
        )

    def _build_industry(
        self,
        session: Session,
        *,
        trade_date: date,
        rank_metric: str,
        selected_code: str | None,
        exceptions: list[ModuleExceptionItemDto],
    ) -> tuple[dict[str, object], bool, bool]:
        hierarchy = self._hierarchy_query.load(session)
        metrics = self._metrics_query.load(
            session,
            trade_date=trade_date,
            view="INDUSTRY",
            sector_codes=tuple(node.sector_code for node in hierarchy.nodes),
        )
        ranked_by_parent = {
            parent: self._rank_nodes(list(nodes), metrics=metrics, rank_metric=rank_metric)[:5]
            for parent, nodes in hierarchy.children_by_parent.items()
        }
        selection = self._selection_resolver.resolve_industry(
            nodes_by_code=hierarchy.nodes_by_code,
            ranked_by_parent=ranked_by_parent,
            requested_code=selected_code,
        )
        if selection.corrected and selected_code is not None:
            exceptions.append(
                self._exception_builder.selection_invalid(
                    message="requested industry selection is outside the ranked hierarchy path",
                    requested_code=selected_code,
                )
            )

        level1_rows = ranked_by_parent.get(None, [])
        level2_rows = ranked_by_parent.get(selection.level1_code, []) if selection.level1_code else []
        level3_rows = ranked_by_parent.get(selection.level2_code, []) if selection.level2_code else []
        columns = [
            IndustryRankColumnDto(
                level=1,
                parentSectorCode=None,
                rows=self._build_node_rank_items(
                    level1_rows,
                    selected_code=selection.level1_code,
                    metrics=metrics,
                    rank_metric=rank_metric,
                ),
            ),
            IndustryRankColumnDto(
                level=2,
                parentSectorCode=selection.level1_code,
                rows=self._build_node_rank_items(
                    level2_rows,
                    selected_code=selection.level2_code,
                    metrics=metrics,
                    rank_metric=rank_metric,
                ),
            ),
            IndustryRankColumnDto(
                level=3,
                parentSectorCode=selection.level2_code,
                rows=self._build_node_rank_items(
                    level3_rows,
                    selected_code=selection.level3_code,
                    metrics=metrics,
                    rank_metric=rank_metric,
                ),
            ),
        ]
        detail_code = selection.detail_sector_code
        detail_node = hierarchy.nodes_by_code.get(detail_code or "")
        detail = self._build_detail(
            session,
            trade_date=trade_date,
            sector_code=detail_code,
            sector_name=detail_node.sector_name if detail_node is not None else None,
            sector_type="INDUSTRY",
            hierarchy_path=detail_node.hierarchy_path if detail_node is not None else None,
            metric=metrics.get(detail_code or ""),
            heat=None,
            heat_history=None,
        )
        has_rows = bool(level1_rows) and bool(metrics)
        partial = has_rows and (len(level1_rows) < 5 or any(not row.has_index for row in metrics.values()))
        return (
            {
                "industry": IndustryWorkspaceDto(
                    rankMetric=rank_metric,  # type: ignore[arg-type]
                    selection=IndustrySelectionDto(
                        level1Code=selection.level1_code,
                        level2Code=selection.level2_code,
                        level3Code=selection.level3_code,
                        detailSectorCode=selection.detail_sector_code,
                    ),
                    columns=columns,
                    detail=detail,
                )
            },
            has_rows,
            partial,
        )

    def _build_concept(
        self,
        session: Session,
        *,
        trade_date: date,
        rank_metric: str,
        selected_code: str | None,
        exceptions: list[ModuleExceptionItemDto],
    ) -> tuple[dict[str, object], bool, bool]:
        metrics = self._metrics_query.load(session, trade_date=trade_date, view="CONCEPT")
        heats_raw = self._heat_query.load_for_date(
            session,
            trade_date=trade_date,
        )
        mismatched = {code for code, heat in heats_raw.items() if not heat.source_matches_trade_date()}
        heats = {code: heat for code, heat in heats_raw.items() if code not in mismatched}
        if mismatched:
            exceptions.append(
                self._exception_builder.heat_source_mismatch(
                    message="concept Heat source date does not match the response trade date",
                    trade_date=trade_date.isoformat(),
                )
            )

        if rank_metric in {"HEAT_SCORE", "HEAT_DELTA_1D"}:
            candidates = [
                code
                for code, heat in heats.items()
                if code in metrics
                and heat.heat_status == "VALID"
                and self._heat_metric(heat, rank_metric) is not None
            ]
            ranked_codes = self._rank_codes(
                candidates,
                value=lambda code: self._heat_metric(heats[code], rank_metric),
            )[:20]
        else:
            ranked_codes = self._rank_codes(
                list(metrics),
                value=lambda code: self._metric_value(metrics.get(code), rank_metric),
            )[:20]

        heat_not_ready = not heats
        if heat_not_ready:
            exceptions.append(
                self._exception_builder.heat_not_ready(
                    message="concept Heat is not published for the requested trade date",
                    trade_date=trade_date.isoformat(),
                )
            )
        selection_candidates = ranked_codes
        selection = self._selection_resolver.resolve_flat(
            candidate_codes=selection_candidates,
            requested_code=selected_code,
        )
        if selection.corrected and selected_code is not None:
            exceptions.append(
                self._exception_builder.selection_invalid(
                    message="requested concept selection is outside the current Top20",
                    requested_code=selected_code,
                )
            )
        selected_heat = heats.get(selection.selected_code or "")
        history = (
            self._heat_query.load_history(
                session,
                trade_date=trade_date,
                sector_code=selection.selected_code,
            )
            if selection.selected_code is not None and selected_heat is not None
            else []
        )
        detail = self._build_detail(
            session,
            trade_date=trade_date,
            sector_code=selection.selected_code,
            sector_name=self._sector_name(selection.selected_code, metrics=metrics, heats=heats),
            sector_type="CONCEPT",
            hierarchy_path=None,
            metric=metrics.get(selection.selected_code or ""),
            heat=selected_heat,
            heat_history=history,
        )
        rows = [
            self._build_rank_item(
                rank=index + 1,
                sector_code=code,
                sector_name=self._sector_name(code, metrics=metrics, heats=heats) or code,
                level=None,
                metric=self._primary_metric(
                    rank_metric,
                    metric=metrics.get(code),
                    heat=heats.get(code),
                ),
                leader=self._leader(metrics.get(code)),
                heat=self._heat_dto(heats.get(code)),
                selected=code == selection.selected_code,
            )
            for index, code in enumerate(ranked_codes)
        ]
        invalid_selected = selected_heat is not None and selected_heat.heat_status == "INVALID"
        if invalid_selected and selected_heat.invalid_reason in {
            "MEMBER_COUNT_LOW",
            "QUOTE_ELIGIBLE_COUNT_ZERO",
            "QUOTE_COVERAGE_LOW",
        }:
            exceptions.append(
                self._exception_builder.member_coverage_low(
                    message="selected concept member coverage is below the Heat contract",
                    sector_code=selected_heat.sector_code,
                )
            )
        has_rows = bool(metrics)
        partial = bool(mismatched) or heat_not_ready or invalid_selected or any(not row.has_index for row in metrics.values())
        return (
            {
                "concept": ConceptWorkspaceDto(
                    rankMetric=rank_metric,  # type: ignore[arg-type]
                    selectedConceptCode=selection.selected_code,
                    rows=rows,
                    detail=detail,
                )
            },
            has_rows,
            partial,
        )

    def _build_region(
        self,
        session: Session,
        *,
        trade_date: date,
        rank_metric: str,
        selected_code: str | None,
        exceptions: list[ModuleExceptionItemDto],
    ) -> tuple[dict[str, object], bool, bool]:
        metrics = self._metrics_query.load(session, trade_date=trade_date, view="REGION")
        ranked_codes = self._rank_codes(
            list(metrics),
            value=lambda code: self._metric_value(metrics.get(code), rank_metric),
        )
        selection = self._selection_resolver.resolve_flat(
            candidate_codes=ranked_codes,
            requested_code=selected_code,
        )
        if selection.corrected and selected_code is not None:
            exceptions.append(
                self._exception_builder.selection_invalid(
                    message="requested region selection is outside the production region enumeration",
                    requested_code=selected_code,
                )
            )
        rows = [
            self._build_rank_item(
                rank=index + 1,
                sector_code=code,
                sector_name=metrics[code].sector_name or code,
                level=None,
                metric=self._primary_metric(rank_metric, metric=metrics[code], heat=None),
                leader=self._leader(metrics[code]),
                heat=None,
                selected=code == selection.selected_code,
            )
            for index, code in enumerate(ranked_codes)
        ]
        detail = self._build_detail(
            session,
            trade_date=trade_date,
            sector_code=selection.selected_code,
            sector_name=(metrics[selection.selected_code].sector_name if selection.selected_code else None),
            sector_type="REGION",
            hierarchy_path=None,
            metric=metrics.get(selection.selected_code or ""),
            heat=None,
            heat_history=None,
        )
        has_rows = bool(rows)
        partial = has_rows and (len(rows) != 31 or any(not row.has_index for row in metrics.values()))
        return (
            {
                "region": RegionWorkspaceDto(
                    rankMetric=rank_metric,  # type: ignore[arg-type]
                    selectedRegionCode=selection.selected_code,
                    rows=rows,
                    detail=detail,
                )
            },
            has_rows,
            partial,
        )

    def _build_detail(
        self,
        session: Session,
        *,
        trade_date: date,
        sector_code: str | None,
        sector_name: str | None,
        sector_type: SectorView,
        hierarchy_path: str | None,
        metric: SectorMetricRow | None,
        heat: SectorHeatRow | None,
        heat_history: list[SectorHeatRow] | None,
    ) -> SectorDetailDto | None:
        if sector_code is None:
            return None
        pools = self._pool_query.load(
            session,
            ordered_trade_dates=(trade_date,),
            sector_codes_by_date={trade_date: (sector_code,)},
        )
        pool = pools[(trade_date, sector_code)]
        members = self._member_query.load_top(
            session,
            trade_date=trade_date,
            sector_code=sector_code,
            limit=5,
        )
        counts = pool.counts
        return SectorDetailDto(
            sectorCode=sector_code,
            sectorName=sector_name or sector_code,
            sectorType=sector_type,
            hierarchyPath=hierarchy_path,
            metrics=SectorMetricsDto(
                changePct=self._to_float(metric.change_pct if metric is not None else None),
                upCount=pool.up_count,
                downCount=pool.down_count,
                sourceMemberCount=counts.source_member_count,
                memberCount=counts.member_count,
                suspendedCount=counts.suspended_count,
                quoteEligibleCount=counts.quote_eligible_count,
                validQuoteCount=counts.valid_quote_count,
                missingQuoteCount=counts.missing_quote_count,
                mainNetInflow=self._to_float(metric.main_net_inflow if metric is not None else None),
                turnoverAmount=self._to_float(metric.turnover_amount if metric is not None else None),
                quoteCoverage=(counts.quote_coverage if counts.quote_eligible_count else None),
            ),
            heat=self._heat_dto(heat),
            heatHistory=(
                [
                    ConceptHeatPointDto(
                        tradeDate=item.trade_date,
                        heatScore=(self._to_float(item.heat_score) if item.source_matches_trade_date() else None),
                        heatRank=(item.heat_rank if item.source_matches_trade_date() else None),
                        heatLevel=(item.heat_level if item.source_matches_trade_date() else "NONE"),  # type: ignore[arg-type]
                    )
                    for item in heat_history
                ]
                if heat_history is not None
                else None
            ),
            leader=self._leader(metric),
            members=[
                SectorMemberStockDto(
                    stockCode=item.stock_code,
                    stockName=item.stock_name,
                    changePct=self._to_float(item.change_pct),
                    direction=self._direction(item.change_pct),
                )
                for item in members
            ],
        )

    def _rank_nodes(
        self,
        nodes: list[SectorHierarchyNode],
        *,
        metrics: dict[str, SectorMetricRow],
        rank_metric: str,
    ) -> list[SectorHierarchyNode]:
        return sorted(
            nodes,
            key=lambda node: self._descending_key(
                self._metric_value(metrics.get(node.sector_code), rank_metric),
                node.sector_code,
            ),
        )

    def _build_node_rank_items(
        self,
        nodes: list[SectorHierarchyNode],
        *,
        selected_code: str | None,
        metrics: dict[str, SectorMetricRow],
        rank_metric: str,
    ) -> list[SectorRankItemDto]:
        return [
            self._build_rank_item(
                rank=index + 1,
                sector_code=node.sector_code,
                sector_name=node.sector_name,
                level=node.industry_level,
                metric=self._primary_metric(rank_metric, metric=metrics.get(node.sector_code), heat=None),
                leader=self._leader(metrics.get(node.sector_code)),
                heat=None,
                selected=node.sector_code == selected_code,
            )
            for index, node in enumerate(nodes)
        ]

    @staticmethod
    def _build_rank_item(
        *,
        rank: int,
        sector_code: str,
        sector_name: str,
        level: int | None,
        metric: MetricValueDto,
        leader: SectorLeaderStockDto | None,
        heat: ConceptHeatDto | None,
        selected: bool,
    ) -> SectorRankItemDto:
        return SectorRankItemDto(
            rank=rank,
            sectorCode=sector_code,
            sectorName=sector_name,
            level=level,  # type: ignore[arg-type]
            primaryMetric=metric,
            leader=leader,
            heat=heat,
            selected=selected,
        )

    def _primary_metric(
        self,
        rank_metric: str,
        *,
        metric: SectorMetricRow | None,
        heat: SectorHeatRow | None,
    ) -> MetricValueDto:
        value = self._heat_metric(heat, rank_metric) if rank_metric.startswith("HEAT_") else self._metric_value(metric, rank_metric)
        if rank_metric == "CHANGE_PCT":
            display = self._format_percent(value)
        elif rank_metric == "MAIN_NET_INFLOW":
            display = self._format_amount_yi(value)
        elif rank_metric == "UP_COUNT":
            display = "--" if value is None else str(int(value))
        elif rank_metric == "HEAT_DELTA_1D":
            display = "--" if value is None else f"{float(value):+.2f}"
        else:
            display = "--" if value is None else f"{float(value):.2f}"
        return MetricValueDto(
            value=(int(value) if rank_metric == "UP_COUNT" and value is not None else self._to_float(value)),
            displayText=display,
            direction=self._direction(value),
        )

    @staticmethod
    def _metric_value(metric: SectorMetricRow | None, rank_metric: str) -> Decimal | int | None:
        if metric is None:
            return None
        if rank_metric == "CHANGE_PCT":
            return metric.change_pct
        if rank_metric == "MAIN_NET_INFLOW":
            return metric.main_net_inflow
        if rank_metric == "UP_COUNT":
            return metric.up_count
        return None

    @staticmethod
    def _heat_metric(heat: SectorHeatRow | None, rank_metric: str) -> Decimal | None:
        if heat is None:
            return None
        if rank_metric == "HEAT_SCORE":
            return heat.heat_score
        if rank_metric == "HEAT_DELTA_1D":
            return heat.heat_delta_1d
        return None

    def _rank_codes(
        self,
        codes: list[str],
        *,
        value: Callable[[str], Decimal | int | None],
    ) -> list[str]:
        return sorted(codes, key=lambda code: self._descending_key(value(code), code))

    @staticmethod
    def _descending_key(value: Decimal | int | None, code: str) -> tuple[bool, float, str]:
        return value is None, -(float(value) if value is not None else 0.0), code

    def _heat_dto(self, heat: SectorHeatRow | None) -> ConceptHeatDto | None:
        if heat is None:
            return None
        return ConceptHeatDto(
            heatStatus=heat.heat_status,  # type: ignore[arg-type]
            invalidReason=heat.invalid_reason,  # type: ignore[arg-type]
            heatScore=self._to_float(heat.heat_score),
            heatLevel=heat.heat_level,  # type: ignore[arg-type]
            heatDelta1d=self._to_float(heat.heat_delta_1d),
            heatTrend=heat.heat_trend,  # type: ignore[arg-type]
            heatRank=heat.heat_rank,
            scoreVersion=heat.score_version,
            tradeDate=heat.trade_date,
            calculatedAt=heat.calculated_at,
        )

    def _leader(self, metric: SectorMetricRow | None) -> SectorLeaderStockDto | None:
        if metric is None or not any((metric.leading_code, metric.leading_name, metric.leading_pct is not None)):
            return None
        return SectorLeaderStockDto(
            stockCode=metric.leading_code,
            stockName=metric.leading_name,
            changePct=self._to_float(metric.leading_pct),
        )

    @staticmethod
    def _sector_name(
        sector_code: str | None,
        *,
        metrics: dict[str, SectorMetricRow],
        heats: dict[str, SectorHeatRow],
    ) -> str | None:
        if sector_code is None:
            return None
        metric = metrics.get(sector_code)
        if metric is not None and metric.sector_name:
            return metric.sector_name
        heat = heats.get(sector_code)
        return heat.sector_name if heat is not None else sector_code

    @staticmethod
    def _empty_workspace(*, view: SectorView, rank_metric: str) -> dict[str, object]:
        if view == "INDUSTRY":
            return {
                "industry": IndustryWorkspaceDto(
                    rankMetric=rank_metric,  # type: ignore[arg-type]
                    selection=IndustrySelectionDto(),
                    columns=[
                        IndustryRankColumnDto(level=1, parentSectorCode=None, rows=[]),
                        IndustryRankColumnDto(level=2, parentSectorCode=None, rows=[]),
                        IndustryRankColumnDto(level=3, parentSectorCode=None, rows=[]),
                    ],
                    detail=None,
                )
            }
        if view == "CONCEPT":
            return {"concept": ConceptWorkspaceDto(rankMetric=rank_metric, rows=[], detail=None)}  # type: ignore[arg-type]
        return {"region": RegionWorkspaceDto(rankMetric=rank_metric, rows=[], detail=None)}  # type: ignore[arg-type]

    @staticmethod
    def _build_panel_payload(
        *,
        trade_date: date,
        status: str,
        view: SectorView,
        as_of: datetime,
        workspace: dict[str, object],
    ) -> IndustrySectorOverviewPayloadDto | ConceptSectorOverviewPayloadDto | RegionSectorOverviewPayloadDto:
        common = {"tradeDate": trade_date, "status": status, "asOf": as_of}
        if view == "INDUSTRY":
            return IndustrySectorOverviewPayloadDto(
                view="INDUSTRY",
                industry=workspace["industry"],  # type: ignore[arg-type]
                **common,
            )
        if view == "CONCEPT":
            return ConceptSectorOverviewPayloadDto(
                view="CONCEPT",
                concept=workspace["concept"],  # type: ignore[arg-type]
                **common,
            )
        return RegionSectorOverviewPayloadDto(
            view="REGION",
            region=workspace["region"],  # type: ignore[arg-type]
            **common,
        )

    @staticmethod
    def _build_trading_day(context: SectorOverviewTradingDayContext) -> TradingDayDto:
        return TradingDayDto(
            tradeDate=context.expected_trade_date,
            prevTradeDate=context.prev_trade_date,
            market="CN_A",
            isTradingDay=context.is_trading_day,
            sessionStatus=context.session_status,  # type: ignore[arg-type]
            timezone="Asia/Shanghai",
        )

    @staticmethod
    def _direction(value: Decimal | int | float | None) -> str:
        if value is None:
            return "UNKNOWN"
        number = float(value)
        if number > 0:
            return "UP"
        if number < 0:
            return "DOWN"
        return "FLAT"

    @staticmethod
    def _to_float(value: Decimal | int | float | None) -> float | None:
        return None if value is None else float(value)

    @staticmethod
    def _format_percent(value: Decimal | int | None) -> str:
        return "--" if value is None else f"{float(value):+.2f}%"

    @staticmethod
    def _format_amount_yi(value: Decimal | int | None) -> str:
        return "--" if value is None else f"{float(value) / 100_000_000:+.1f}亿"
