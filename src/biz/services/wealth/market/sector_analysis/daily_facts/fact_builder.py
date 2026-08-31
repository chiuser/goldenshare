from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    BuiltMethodFacts,
    DualMomentumFactRow,
    FactIdentity,
    MemberBreadthFactRow,
    MemberMaBreadthFactRow,
    MomentumFactRow,
    PriceVolumeFactRow,
    RelativeRotationFactRow,
    SectorAnalysisSourceBundle,
    SectorComparisonPool,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_classifier import (
    SectorDualMomentumClassifier,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    MINIMUM_GROUP_SIZE as DUAL_MINIMUM_GROUP_SIZE,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_calculator import (
    SectorMemberBreadthCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MemberBreadthCompositionFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_calculator import (
    SectorMomentumCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorRankFact,
    SectorReturnFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_calculator import (
    SectorPriceVolumeCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_calculator import (
    SectorRelativeRotationCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_contract import (
    MINIMUM_GROUP_SIZE as ROTATION_MINIMUM_GROUP_SIZE,
    make_rank_slice,
)


class SectorAnalysisDailyFactBuilder:
    def __init__(
        self,
        *,
        momentum: SectorMomentumCalculator | None = None,
        dual: SectorDualMomentumClassifier | None = None,
        rotation: SectorRelativeRotationCalculator | None = None,
        breadth: SectorMemberBreadthCalculator | None = None,
        price_volume: SectorPriceVolumeCalculator | None = None,
    ) -> None:
        self._momentum = momentum or SectorMomentumCalculator()
        self._dual = dual or SectorDualMomentumClassifier()
        self._rotation = rotation or SectorRelativeRotationCalculator()
        self._breadth = breadth or SectorMemberBreadthCalculator()
        self._price_volume = price_volume or SectorPriceVolumeCalculator()

    def build(self, bundle: SectorAnalysisSourceBundle) -> BuiltMethodFacts:
        fact_index = self._momentum.index_facts(bundle.sector_facts)
        momentum_cache: dict[tuple[str, int, date], tuple[tuple[SectorReturnFact, ...], tuple[SectorRankFact, ...], int]] = {}
        for pool in bundle.comparison_pools:
            for period in (1, 5, 10, 20, 30):
                dates = (bundle.trade_date,)
                if period != 1:
                    dates += (bundle.open_dates[-6],)
                for target_date in dict.fromkeys(dates):
                    returns = self._momentum.calculate_for_date(
                        sector_codes=pool.sector_codes,
                        open_dates=bundle.open_dates,
                        target_date=target_date,
                        period=period,  # type: ignore[arg-type]
                        fact_index=fact_index,
                    )
                    ranks = self._momentum.rank_strength(returns)
                    momentum_cache[(pool.comparison_key, period, target_date)] = (
                        returns,
                        ranks,
                        sum(row.percentile is not None for row in ranks),
                    )

        momentum_rows = self._build_momentum(bundle, momentum_cache)
        dual_rows = self._build_dual(bundle, momentum_cache)
        rotation_rows = self._build_rotation(bundle, momentum_cache)
        member_rows, member_ma_rows = self._build_breadth(bundle)
        price_volume_rows = self._build_price_volume(bundle)
        return BuiltMethodFacts(
            momentum=momentum_rows,
            dual_momentum=dual_rows,
            relative_rotation=rotation_rows,
            member_breadth=member_rows,
            member_ma_breadth=member_ma_rows,
            price_volume=price_volume_rows,
        )

    def _build_momentum(self, bundle, cache) -> tuple[MomentumFactRow, ...]:  # type: ignore[no-untyped-def]
        rows: list[MomentumFactRow] = []
        for pool in bundle.comparison_pools:
            for period in (1, 5, 10, 20, 30):
                returns, ranks, count = cache[(pool.comparison_key, period, bundle.trade_date)]
                for return_fact, rank in zip(returns, ranks, strict=True):
                    rows.append(
                        MomentumFactRow(
                            identity=self._identity(bundle, pool, return_fact.sector_code),
                            period=period,
                            return_pct=return_fact.return_pct,
                            strength_rank=rank.strength_rank,
                            rankable_count=count if rank.strength_rank is not None else None,
                            percentile=rank.percentile,
                            calculation_status="CALCULABLE" if return_fact.return_pct is not None else "UNAVAILABLE",
                            missing_reason=return_fact.missing_reason,
                        )
                    )
        return tuple(rows)

    def _build_dual(self, bundle, cache) -> tuple[DualMomentumFactRow, ...]:  # type: ignore[no-untyped-def]
        rows: list[DualMomentumFactRow] = []
        for pool in bundle.comparison_pools:
            for period in (5, 10, 20, 30):
                returns, ranks, count = cache[(pool.comparison_key, period, bundle.trade_date)]
                for return_fact, rank in zip(returns, ranks, strict=True):
                    classified = {
                        threshold: self._dual.classify(
                            return_fact=return_fact,
                            rank_fact=rank,
                            calculable_count=count,
                            leading_threshold=threshold,  # type: ignore[arg-type]
                        )
                        for threshold in (70, 80, 90)
                    }
                    basis = classified[80]
                    rows.append(
                        DualMomentumFactRow(
                            identity=self._identity(bundle, pool, return_fact.sector_code),
                            period=period,
                            return_pct=basis.return_pct,
                            strength_rank=basis.strength_rank,
                            rankable_count=count if basis.strength_rank is not None else None,
                            percentile=basis.percentile,
                            absolute_status=basis.absolute_status,
                            coordinate_status=basis.coordinate_status,
                            relative_status_70=classified[70].relative_status,
                            qualification_status_70=classified[70].qualification_status,
                            display_status_70=classified[70].display_status,
                            relative_status_80=classified[80].relative_status,
                            qualification_status_80=classified[80].qualification_status,
                            display_status_80=classified[80].display_status,
                            relative_status_90=classified[90].relative_status,
                            qualification_status_90=classified[90].qualification_status,
                            display_status_90=classified[90].display_status,
                            minimum_group_size=DUAL_MINIMUM_GROUP_SIZE,
                            calculation_status="CALCULABLE" if basis.return_pct is not None else "UNAVAILABLE",
                            missing_reason=basis.missing_reason or "NONE",
                        )
                    )
        return tuple(rows)

    def _build_rotation(self, bundle, cache) -> tuple[RelativeRotationFactRow, ...]:  # type: ignore[no-untyped-def]
        rows: list[RelativeRotationFactRow] = []
        comparison_date = bundle.open_dates[-6]
        for pool in bundle.comparison_pools:
            for period in (5, 10, 20, 30):
                current_returns, current_ranks, current_count = cache[(pool.comparison_key, period, bundle.trade_date)]
                previous_returns, previous_ranks, previous_count = cache[(pool.comparison_key, period, comparison_date)]
                points = self._rotation.calculate_current_snapshot(
                    sector_codes=pool.sector_codes,
                    open_dates=bundle.open_dates,
                    current_date=bundle.trade_date,
                    current_slice=make_rank_slice(bundle.trade_date, current_returns, current_ranks),
                    comparison_slice=make_rank_slice(comparison_date, previous_returns, previous_ranks),
                )
                previous_by_code = {row.sector_code: row for row in previous_ranks}
                for point in points:
                    previous = previous_by_code[point.sector_code]
                    reason = point.current_missing_reason or point.comparison_missing_reason or "NONE"
                    rows.append(
                        RelativeRotationFactRow(
                            identity=self._identity(bundle, pool, point.sector_code),
                            period=period,
                            comparison_trade_date=comparison_date,
                            return_pct=point.return_pct,
                            strength_rank=point.strength_rank,
                            rankable_count=current_count if point.strength_rank is not None else None,
                            percentile=point.percentile,
                            comparison_return_pct=previous.return_pct,
                            comparison_strength_rank=previous.strength_rank,
                            comparison_rankable_count=previous_count if previous.strength_rank is not None else None,
                            comparison_percentile=previous.percentile,
                            percentile_delta_5d=point.percentile_delta_5d,
                            rotation_status=point.rotation_status,
                            coordinate_status=point.coordinate_status,
                            group_interpretation=(
                                "QUADRANT"
                                if current_count >= ROTATION_MINIMUM_GROUP_SIZE and previous_count >= ROTATION_MINIMUM_GROUP_SIZE
                                else "SAMPLE_INSUFFICIENT"
                            ),
                            current_missing_reason=point.current_missing_reason,
                            comparison_missing_reason=point.comparison_missing_reason,
                            minimum_group_size=ROTATION_MINIMUM_GROUP_SIZE,
                            calculation_status="CALCULABLE" if point.coordinate_status == "PLOTTABLE" else "UNAVAILABLE",
                            missing_reason=reason,
                        )
                    )
        return tuple(rows)

    def _build_breadth(self, bundle) -> tuple[tuple[MemberBreadthFactRow, ...], tuple[MemberMaBreadthFactRow, ...]]:  # type: ignore[no-untyped-def]
        sector_codes = tuple(node.sector_code for node in bundle.hierarchy.nodes)
        grid = self._breadth.calculate_composition_grid(
            sector_codes=sector_codes,
            target_date=bundle.trade_date,
            relations=bundle.member_relations,
            market_facts=bundle.member_market_facts,
            open_dates=bundle.open_dates,
        )
        target_relations: dict[str, list] = {code: [] for code in sector_codes}
        for relation in bundle.member_relations:
            if relation.trade_date == bundle.trade_date and relation.sector_code in target_relations:
                target_relations[relation.sector_code].append(relation)
        market_index = self._breadth.index_market_facts(bundle.member_market_facts)
        breadth_rows: list[MemberBreadthFactRow] = []
        ma_rows: list[MemberMaBreadthFactRow] = []
        for pool in bundle.comparison_pools:
            member = {code: grid[(code, "MEMBER_COUNT", 20)] for code in pool.sector_codes}
            turnover = {code: grid[(code, "TURNOVER", 20)] for code in pool.sector_codes}
            member_up = self._rank_compositions(member, direction="UP")
            member_down = self._rank_compositions(member, direction="DOWN")
            turnover_up = self._rank_compositions(turnover, direction="UP")
            turnover_down = self._rank_compositions(turnover, direction="DOWN")
            for code in pool.sector_codes:
                member_comp = member[code]
                turnover_comp = turnover[code]
                amounts = self._breadth.turnover_amount_totals(
                    relations=target_relations[code],
                    target_date=bundle.trade_date,
                    market_index=market_index,
                )
                values = {
                    "source_member_count": member_comp.coverage.source_count,
                    "member_calculable_count": member_comp.coverage.calculable_count,
                    "member_coverage_pct": member_comp.coverage.coverage_pct,
                    "member_qualification": "ELIGIBLE" if member_comp.coverage.eligible else "INELIGIBLE",
                    "member_reason_codes": tuple(member_comp.coverage.reason_codes),
                    "member_up_count": member_comp.up_count, "member_flat_count": member_comp.flat_count, "member_down_count": member_comp.down_count,
                    "member_up_pct": member_comp.up_pct, "member_flat_pct": member_comp.flat_pct, "member_down_pct": member_comp.down_pct,
                    **self._rank_values("member_up", member_up[code]),
                    **self._rank_values("member_down", member_down[code]),
                    "turnover_calculable_count": turnover_comp.coverage.calculable_count,
                    "turnover_coverage_pct": turnover_comp.coverage.coverage_pct,
                    "turnover_qualification": "ELIGIBLE" if turnover_comp.coverage.eligible else "INELIGIBLE",
                    "turnover_reason_codes": tuple(turnover_comp.coverage.reason_codes),
                    "turnover_up_count": turnover_comp.up_count, "turnover_flat_count": turnover_comp.flat_count, "turnover_down_count": turnover_comp.down_count,
                    "turnover_up_amount": amounts[0], "turnover_flat_amount": amounts[1], "turnover_down_amount": amounts[2],
                    "turnover_up_pct": turnover_comp.up_pct, "turnover_flat_pct": turnover_comp.flat_pct, "turnover_down_pct": turnover_comp.down_pct,
                    **self._rank_values("turnover_up", turnover_up[code]),
                    **self._rank_values("turnover_down", turnover_down[code]),
                }
                reasons = tuple(dict.fromkeys((*member_comp.coverage.reason_codes, *turnover_comp.coverage.reason_codes)))
                breadth_rows.append(
                    MemberBreadthFactRow(
                        identity=self._identity(bundle, pool, code),
                        values=values,
                        calculation_status="CALCULABLE" if member_comp.coverage.eligible or turnover_comp.coverage.eligible else "UNAVAILABLE",
                        missing_reason=reasons[0] if reasons else "NONE",
                    )
                )
            for ma_period in (5, 10, 15, 20, 30, 60):
                compositions = {code: grid[(code, "MA_POSITION", ma_period)] for code in pool.sector_codes}
                up = self._rank_compositions(compositions, direction="UP")
                down = self._rank_compositions(compositions, direction="DOWN")
                for code in pool.sector_codes:
                    comp = compositions[code]
                    values = {
                        "source_member_count": comp.coverage.source_count,
                        "calculable_count": comp.coverage.calculable_count,
                        "coverage_pct": comp.coverage.coverage_pct,
                        "qualification": "ELIGIBLE" if comp.coverage.eligible else "INELIGIBLE",
                        "reason_codes": tuple(comp.coverage.reason_codes),
                        "above_count": comp.up_count, "equal_count": comp.flat_count, "below_count": comp.down_count,
                        "above_pct": comp.up_pct, "equal_pct": comp.flat_pct, "below_pct": comp.down_pct,
                        **self._rank_values("up", up[code]),
                        **self._rank_values("down", down[code]),
                    }
                    ma_rows.append(
                        MemberMaBreadthFactRow(
                            identity=self._identity(bundle, pool, code),
                            ma_period=ma_period,
                            values=values,
                            calculation_status="CALCULABLE" if comp.coverage.eligible else "UNAVAILABLE",
                            missing_reason=comp.coverage.reason_codes[0] if comp.coverage.reason_codes else "NONE",
                        )
                    )
        return tuple(breadth_rows), tuple(ma_rows)

    def _build_price_volume(self, bundle) -> tuple[PriceVolumeFactRow, ...]:  # type: ignore[no-untyped-def]
        rows: list[PriceVolumeFactRow] = []
        for pool in bundle.comparison_pools:
            pool_facts = tuple(row for row in bundle.price_volume_facts if row.sector_code in set(pool.sector_codes))
            for period in (1, 5, 10, 20, 30):
                ranked = self._price_volume.calculate_snapshot(
                    sector_codes=pool.sector_codes,
                    open_dates=bundle.open_dates,
                    facts=pool_facts,
                    period=period,  # type: ignore[arg-type]
                )
                by_code = {row.metric.sector_code: row for row in ranked}
                price_pct = self._rank_values_by_metric(by_code, attribute="price_momentum_pct")
                amount_pct = self._rank_values_by_metric(by_code, attribute="amount_activity_pct")
                for code in pool.sector_codes:
                    row = by_code[code]
                    metric = row.metric
                    price_reason = metric.price_missing_reason.value if metric.price_missing_reason else None
                    amount_reason = metric.amount_missing_reason.value if metric.amount_missing_reason else None
                    values = {
                        "price_momentum_pct": metric.price_momentum_pct,
                        "price_missing_reason": price_reason,
                        "price_rank": row.price_rank,
                        "price_rankable_count": row.price_rankable_count if row.price_rank is not None else None,
                        "price_percentile": price_pct[code][2],
                        "amount_activity_pct": metric.amount_activity_pct,
                        "amount_missing_reason": amount_reason,
                        "amount_rank": row.amount_rank,
                        "amount_rankable_count": row.amount_rankable_count if row.amount_rank is not None else None,
                        "amount_percentile": amount_pct[code][2],
                        "distribution_state": row.state,
                    }
                    reason = price_reason or amount_reason or "NONE"
                    rows.append(
                        PriceVolumeFactRow(
                            identity=self._identity(bundle, pool, code),
                            period=period,
                            values=values,
                            calculation_status="CALCULABLE" if row.state is not None else "UNAVAILABLE",
                            missing_reason=reason,
                        )
                    )
        return tuple(rows)

    def _rank_compositions(self, compositions: Mapping[str, MemberBreadthCompositionFact], *, direction: str):  # type: ignore[no-untyped-def]
        returns = tuple(
            SectorReturnFact(
                code,
                date.min,
                self._breadth.selected_pct(comp, direction=direction) if comp.coverage.eligible else None,  # type: ignore[arg-type]
                "NONE" if comp.coverage.eligible else "DATE_MISSING",
            )
            for code, comp in compositions.items()
        )
        ranks = self._momentum.rank_strength(returns)
        count = sum(row.strength_rank is not None for row in ranks)
        return {
            row.sector_code: (
                row.strength_rank,
                count if row.strength_rank is not None else None,
                row.percentile,
            )
            for row in ranks
        }

    def _rank_values_by_metric(self, rows, *, attribute: str):  # type: ignore[no-untyped-def]
        returns = tuple(
            SectorReturnFact(
                code,
                row.metric.trade_date,
                getattr(row.metric, attribute),
                "NONE" if getattr(row.metric, attribute) is not None else "DATE_MISSING",
            )
            for code, row in rows.items()
        )
        ranks = self._momentum.rank_strength(returns)
        count = sum(row.strength_rank is not None for row in ranks)
        return {row.sector_code: (row.strength_rank, count if row.strength_rank is not None else None, row.percentile) for row in ranks}

    @staticmethod
    def _rank_values(prefix: str, value) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return {
            f"{prefix}_rank": value[0],
            f"{prefix}_rankable_count": value[1],
            f"{prefix}_percentile": value[2],
        }

    @staticmethod
    def _identity(bundle: SectorAnalysisSourceBundle, pool: SectorComparisonPool, sector_code: str) -> FactIdentity:
        node = bundle.hierarchy.nodes_by_code[sector_code]
        return FactIdentity(
            trade_date=bundle.trade_date,
            comparison_scope=pool.scope,
            comparison_key=pool.comparison_key,
            parent_sector_code=pool.parent_sector_code,
            sector_code=node.sector_code,
            sector_name=node.sector_name,
            industry_level=node.industry_level,
            hierarchy_path=node.hierarchy_path,
        )
