from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MEMBER_BREADTH_MINIMUM_CALCULABLE_COUNT,
    MEMBER_BREADTH_MINIMUM_COVERAGE_PCT,
    MemberBreadthCompositionFact,
    MemberBreadthDetailsFact,
    MemberBreadthMemberFact,
    MemberBreadthRankFact,
    MemberBreadthTrendPointFact,
    MemberMarketFact,
    MemberRelationFact,
    MetricCoverageFact,
    SectorMemberBreadthDirection,
    SectorMemberBreadthMaPeriod,
    SectorMemberBreadthMetric,
    SectorMemberBreadthReason,
    SectorMemberMaRelation,
    ordered_member_breadth_reasons,
)


_HUNDRED = Decimal("100")


class SectorMemberBreadthCalculator:
    """Pure Decimal calculations for the three independent breadth facts."""

    def calculate_composition(
        self,
        *,
        metric: SectorMemberBreadthMetric,
        target_date: date,
        relations: Iterable[MemberRelationFact],
        market_facts: Iterable[MemberMarketFact],
        open_dates: tuple[date, ...],
        ma_period: SectorMemberBreadthMaPeriod,
    ) -> MemberBreadthCompositionFact:
        relation_rows = tuple(
            sorted(
                (row for row in relations if row.trade_date == target_date),
                key=lambda row: (row.stock_code, row.sector_code),
            )
        )
        market_index = self.index_market_facts(market_facts)
        if metric == "MEMBER_COUNT":
            return self._member_composition(
                relations=relation_rows,
                target_date=target_date,
                market_index=market_index,
            )
        if metric == "TURNOVER":
            return self._turnover_composition(
                relations=relation_rows,
                target_date=target_date,
                market_index=market_index,
            )
        return self._ma_composition(
            relations=relation_rows,
            target_date=target_date,
            market_index=market_index,
            open_dates=open_dates,
            ma_period=ma_period,
        )

    def rank_requested_metric(
        self,
        *,
        sector_codes: Iterable[str],
        target_date: date,
        metric: SectorMemberBreadthMetric,
        direction: SectorMemberBreadthDirection,
        ma_period: SectorMemberBreadthMaPeriod,
        open_dates: tuple[date, ...],
        relations: Iterable[MemberRelationFact],
        market_facts: Iterable[MemberMarketFact],
    ) -> tuple[MemberBreadthRankFact, ...]:
        relation_rows = tuple(relations)
        market_rows = tuple(market_facts)
        compositions: dict[str, MemberBreadthCompositionFact] = {}
        for sector_code in sector_codes:
            compositions[sector_code] = self.calculate_composition(
                metric=metric,
                target_date=target_date,
                relations=(
                    row for row in relation_rows if row.sector_code == sector_code
                ),
                market_facts=market_rows,
                open_dates=open_dates,
                ma_period=ma_period,
            )

        eligible: list[tuple[str, Decimal, MemberBreadthCompositionFact]] = []
        ineligible: list[tuple[str, MemberBreadthCompositionFact]] = []
        for sector_code, composition in compositions.items():
            value = self.selected_pct(composition, direction=direction)
            if composition.coverage.eligible and value is not None:
                eligible.append((sector_code, value, composition))
            else:
                ineligible.append((sector_code, composition))
        eligible.sort(key=lambda item: (-item[1], item[0]))
        ineligible.sort(key=lambda item: item[0])

        rank_total = len(eligible)
        ranked: list[MemberBreadthRankFact] = []
        previous_value: Decimal | None = None
        previous_rank = 0
        for position, (sector_code, value, composition) in enumerate(
            eligible,
            start=1,
        ):
            rank = previous_rank if previous_value == value else position
            ranked.append(
                MemberBreadthRankFact(
                    sector_code=sector_code,
                    metric_calculable=True,
                    metric_value_pct=value,
                    rank=rank,
                    rank_total=rank_total,
                    coverage=composition.coverage,
                    reason_codes=composition.coverage.reason_codes,
                )
            )
            previous_value = value
            previous_rank = rank
        ranked.extend(
            MemberBreadthRankFact(
                sector_code=sector_code,
                metric_calculable=(
                    self.selected_pct(composition, direction=direction) is not None
                ),
                metric_value_pct=None,
                rank=None,
                rank_total=None,
                coverage=composition.coverage,
                reason_codes=composition.coverage.reason_codes,
            )
            for sector_code, composition in ineligible
        )
        return tuple(ranked)

    def build_details(
        self,
        *,
        sector_code: str,
        target_date: date,
        direction: SectorMemberBreadthDirection,
        ma_period: SectorMemberBreadthMaPeriod,
        open_dates: tuple[date, ...],
        relation_dates: tuple[date, ...],
        relations: Iterable[MemberRelationFact],
        market_facts: Iterable[MemberMarketFact],
    ) -> MemberBreadthDetailsFact:
        relation_rows = tuple(
            row for row in relations if row.sector_code == sector_code
        )
        market_rows = tuple(market_facts)
        compositions = tuple(
            self.calculate_composition(
                metric=metric,
                target_date=target_date,
                relations=relation_rows,
                market_facts=market_rows,
                open_dates=open_dates,
                ma_period=ma_period,
            )
            for metric in ("MEMBER_COUNT", "TURNOVER", "MA_POSITION")
        )

        trend: list[MemberBreadthTrendPointFact] = []
        for trend_date in relation_dates:
            point_compositions = tuple(
                self.calculate_composition(
                    metric=metric,
                    target_date=trend_date,
                    relations=relation_rows,
                    market_facts=market_rows,
                    open_dates=tuple(item for item in open_dates if item <= trend_date),
                    ma_period=ma_period,
                )
                for metric in ("MEMBER_COUNT", "TURNOVER", "MA_POSITION")
            )
            trend.append(
                MemberBreadthTrendPointFact(
                    trade_date=trend_date,
                    member_pct=self.selected_pct(
                        point_compositions[0], direction=direction
                    ),
                    turnover_pct=self.selected_pct(
                        point_compositions[1], direction=direction
                    ),
                    ma_position_pct=self.selected_pct(
                        point_compositions[2], direction=direction
                    ),
                    member_reason_codes=point_compositions[0].coverage.reason_codes,
                    turnover_reason_codes=point_compositions[1].coverage.reason_codes,
                    ma_position_reason_codes=point_compositions[
                        2
                    ].coverage.reason_codes,
                )
            )

        members = self._build_members(
            target_date=target_date,
            direction=direction,
            ma_period=ma_period,
            open_dates=open_dates,
            relations=tuple(
                row for row in relation_rows if row.trade_date == target_date
            ),
            market_facts=market_rows,
        )
        return MemberBreadthDetailsFact(
            compositions=compositions,
            trend=tuple(trend),
            members=members,
        )

    @staticmethod
    def index_market_facts(
        facts: Iterable[MemberMarketFact],
    ) -> dict[tuple[str, date], MemberMarketFact]:
        index: dict[tuple[str, date], MemberMarketFact] = {}
        for fact in facts:
            key = (fact.stock_code, fact.trade_date)
            if key in index:
                raise ValueError("duplicate member market fact")
            index[key] = fact
        return index

    @staticmethod
    def selected_pct(
        composition: MemberBreadthCompositionFact,
        *,
        direction: SectorMemberBreadthDirection,
    ) -> Decimal | None:
        return composition.up_pct if direction == "UP" else composition.down_pct

    def _member_composition(
        self,
        *,
        relations: tuple[MemberRelationFact, ...],
        target_date: date,
        market_index: dict[tuple[str, date], MemberMarketFact],
    ) -> MemberBreadthCompositionFact:
        reasons: set[SectorMemberBreadthReason] = set()
        values: list[Decimal] = []
        for relation in relations:
            market = market_index.get((relation.stock_code, target_date))
            if market is None:
                reasons.add("MARKET_ROW_MISSING")
                continue
            if not _is_finite(market.pct_change):
                reasons.add("PCT_CHANGE_MISSING")
                continue
            values.append(market.pct_change)
        coverage = self._coverage(
            source_count=len(relations),
            calculable_count=len(values),
            reasons=reasons,
            metric_available=bool(values),
        )
        return self._count_composition(
            metric="MEMBER_COUNT",
            values=values,
            coverage=coverage,
        )

    def _turnover_composition(
        self,
        *,
        relations: tuple[MemberRelationFact, ...],
        target_date: date,
        market_index: dict[tuple[str, date], MemberMarketFact],
    ) -> MemberBreadthCompositionFact:
        reasons: set[SectorMemberBreadthReason] = set()
        values: list[tuple[Decimal, Decimal]] = []
        for relation in relations:
            market = market_index.get((relation.stock_code, target_date))
            if market is None:
                reasons.add("MARKET_ROW_MISSING")
                continue
            if not _is_finite(market.pct_change):
                reasons.add("PCT_CHANGE_MISSING")
                continue
            if not _is_finite(market.amount_thousand_yuan):
                reasons.add("AMOUNT_MISSING")
                continue
            if market.amount_thousand_yuan < 0:
                reasons.add("AMOUNT_NON_POSITIVE")
                continue
            values.append((market.pct_change, market.amount_thousand_yuan))
        total_amount = sum((amount for _, amount in values), Decimal(0))
        available = bool(values) and total_amount > 0
        if values and total_amount <= 0:
            reasons.add("AMOUNT_NON_POSITIVE")
        coverage = self._coverage(
            source_count=len(relations),
            calculable_count=len(values),
            reasons=reasons,
            metric_available=available,
        )
        counts = _direction_counts(value for value, _ in values)
        if not available:
            percentages = (None, None, None)
        else:
            percentages = tuple(
                amount / total_amount * _HUNDRED
                for amount in (
                    sum((amount for value, amount in values if value > 0), Decimal(0)),
                    sum((amount for value, amount in values if value == 0), Decimal(0)),
                    sum((amount for value, amount in values if value < 0), Decimal(0)),
                )
            )
        return MemberBreadthCompositionFact(
            metric="TURNOVER",
            up_count=counts[0],
            flat_count=counts[1],
            down_count=counts[2],
            up_pct=percentages[0],
            flat_pct=percentages[1],
            down_pct=percentages[2],
            coverage=coverage,
        )

    def _ma_composition(
        self,
        *,
        relations: tuple[MemberRelationFact, ...],
        target_date: date,
        market_index: dict[tuple[str, date], MemberMarketFact],
        open_dates: tuple[date, ...],
        ma_period: SectorMemberBreadthMaPeriod,
    ) -> MemberBreadthCompositionFact:
        reasons: set[SectorMemberBreadthReason] = set()
        relations_by_ma: list[SectorMemberMaRelation] = []
        for relation in relations:
            ma_relation, _, member_reasons = self._calculate_ma_member(
                stock_code=relation.stock_code,
                target_date=target_date,
                market_index=market_index,
                open_dates=open_dates,
                ma_period=ma_period,
            )
            reasons.update(member_reasons)
            if ma_relation is not None:
                relations_by_ma.append(ma_relation)
        coverage = self._coverage(
            source_count=len(relations),
            calculable_count=len(relations_by_ma),
            reasons=reasons,
            metric_available=bool(relations_by_ma),
        )
        values = tuple(
            Decimal(1)
            if relation == "ABOVE"
            else Decimal(-1)
            if relation == "BELOW"
            else Decimal(0)
            for relation in relations_by_ma
        )
        return self._count_composition(
            metric="MA_POSITION",
            values=values,
            coverage=coverage,
        )

    def _build_members(
        self,
        *,
        target_date: date,
        direction: SectorMemberBreadthDirection,
        ma_period: SectorMemberBreadthMaPeriod,
        open_dates: tuple[date, ...],
        relations: tuple[MemberRelationFact, ...],
        market_facts: tuple[MemberMarketFact, ...],
    ) -> tuple[MemberBreadthMemberFact, ...]:
        market_index = self.index_market_facts(market_facts)
        amount_rows: dict[str, Decimal] = {}
        for relation in relations:
            market = market_index.get((relation.stock_code, target_date))
            if (
                market is not None
                and _is_finite(market.pct_change)
                and _is_finite(market.amount_thousand_yuan)
                and market.amount_thousand_yuan >= 0
            ):
                amount_rows[relation.stock_code] = market.amount_thousand_yuan
        total_amount = sum(amount_rows.values(), Decimal(0))

        members: list[MemberBreadthMemberFact] = []
        for relation in relations:
            reasons: set[SectorMemberBreadthReason] = set()
            market = market_index.get((relation.stock_code, target_date))
            if market is None:
                reasons.add("MARKET_ROW_MISSING")
                daily_pct = None
                amount = None
            else:
                daily_pct = market.pct_change if _is_finite(market.pct_change) else None
                amount = (
                    market.amount_thousand_yuan
                    if _is_finite(market.amount_thousand_yuan)
                    and market.amount_thousand_yuan >= 0
                    else None
                )
                if daily_pct is None:
                    reasons.add("PCT_CHANGE_MISSING")
                if not _is_finite(market.amount_thousand_yuan):
                    reasons.add("AMOUNT_MISSING")
                elif market.amount_thousand_yuan < 0:
                    reasons.add("AMOUNT_NON_POSITIVE")
            contribution = (
                amount_rows[relation.stock_code] / total_amount * _HUNDRED
                if relation.stock_code in amount_rows and total_amount > 0
                else None
            )
            ma_relation, ma_distance, ma_reasons = self._calculate_ma_member(
                stock_code=relation.stock_code,
                target_date=target_date,
                market_index=market_index,
                open_dates=open_dates,
                ma_period=ma_period,
            )
            reasons.update(ma_reasons)
            members.append(
                MemberBreadthMemberFact(
                    stock_code=relation.stock_code,
                    stock_name=relation.stock_name,
                    daily_pct_change=daily_pct,
                    amount_thousand_yuan=amount,
                    amount_contribution_pct=contribution,
                    ma_relation=ma_relation,
                    ma_distance_pct=ma_distance,
                    reason_codes=ordered_member_breadth_reasons(reasons),
                )
            )
        members.sort(key=lambda row: _member_sort_key(row, direction=direction))
        return tuple(members)

    @staticmethod
    def _coverage(
        *,
        source_count: int,
        calculable_count: int,
        reasons: set[SectorMemberBreadthReason],
        metric_available: bool,
    ) -> MetricCoverageFact:
        if source_count == 0:
            reasons.add("SOURCE_MEMBER_EMPTY")
            coverage_pct = Decimal(0)
        else:
            coverage_pct = Decimal(calculable_count) / Decimal(source_count) * _HUNDRED
        if calculable_count < MEMBER_BREADTH_MINIMUM_CALCULABLE_COUNT:
            reasons.add("MINIMUM_COUNT_NOT_MET")
        if coverage_pct < MEMBER_BREADTH_MINIMUM_COVERAGE_PCT:
            reasons.add("COVERAGE_NOT_MET")
        eligible = (
            metric_available
            and calculable_count >= MEMBER_BREADTH_MINIMUM_CALCULABLE_COUNT
            and coverage_pct >= MEMBER_BREADTH_MINIMUM_COVERAGE_PCT
        )
        return MetricCoverageFact(
            source_count=source_count,
            calculable_count=calculable_count,
            coverage_pct=coverage_pct,
            eligible=eligible,
            reason_codes=ordered_member_breadth_reasons(reasons),
        )

    @staticmethod
    def _count_composition(
        *,
        metric: SectorMemberBreadthMetric,
        values: Iterable[Decimal],
        coverage: MetricCoverageFact,
    ) -> MemberBreadthCompositionFact:
        value_rows = tuple(values)
        up_count, flat_count, down_count = _direction_counts(value_rows)
        denominator = len(value_rows)
        percentages: tuple[Decimal | None, Decimal | None, Decimal | None]
        if denominator == 0:
            percentages = (None, None, None)
        else:
            percentages = (
                Decimal(up_count) / Decimal(denominator) * _HUNDRED,
                Decimal(flat_count) / Decimal(denominator) * _HUNDRED,
                Decimal(down_count) / Decimal(denominator) * _HUNDRED,
            )
        return MemberBreadthCompositionFact(
            metric=metric,
            up_count=up_count,
            flat_count=flat_count,
            down_count=down_count,
            up_pct=percentages[0],
            flat_pct=percentages[1],
            down_pct=percentages[2],
            coverage=coverage,
        )

    @staticmethod
    def _calculate_ma_member(
        *,
        stock_code: str,
        target_date: date,
        market_index: dict[tuple[str, date], MemberMarketFact],
        open_dates: tuple[date, ...],
        ma_period: SectorMemberBreadthMaPeriod,
    ) -> tuple[
        SectorMemberMaRelation | None,
        Decimal | None,
        set[SectorMemberBreadthReason],
    ]:
        reasons: set[SectorMemberBreadthReason] = set()
        window = tuple(item for item in open_dates if item <= target_date)[-ma_period:]
        if len(window) < ma_period or not window or window[-1] != target_date:
            reasons.add("MA_HISTORY_INSUFFICIENT")
            return None, None, reasons
        adjusted_values: list[Decimal] = []
        for item in window:
            market = market_index.get((stock_code, item))
            if market is None or not _is_finite(market.close) or market.close <= 0:
                reasons.update({"MARKET_ROW_MISSING", "MA_HISTORY_INSUFFICIENT"})
                continue
            if not _is_finite(market.adj_factor):
                reasons.update({"ADJ_FACTOR_MISSING", "MA_HISTORY_INSUFFICIENT"})
                continue
            if market.adj_factor <= 0:
                reasons.update({"ADJ_FACTOR_NON_POSITIVE", "MA_HISTORY_INSUFFICIENT"})
                continue
            adjusted_values.append(market.close * market.adj_factor)
        if len(adjusted_values) != ma_period:
            return None, None, reasons
        moving_average = sum(adjusted_values, Decimal(0)) / Decimal(ma_period)
        current = adjusted_values[-1]
        if current > moving_average:
            relation: SectorMemberMaRelation = "ABOVE"
        elif current < moving_average:
            relation = "BELOW"
        else:
            relation = "EQUAL"
        distance = (current / moving_average - Decimal(1)) * _HUNDRED
        return relation, distance, reasons


def _direction_counts(values: Iterable[Decimal]) -> tuple[int, int, int]:
    rows = tuple(values)
    return (
        sum(value > 0 for value in rows),
        sum(value == 0 for value in rows),
        sum(value < 0 for value in rows),
    )


def _is_finite(value: Decimal | None) -> bool:
    return value is not None and value.is_finite()


def _member_sort_key(
    row: MemberBreadthMemberFact,
    *,
    direction: SectorMemberBreadthDirection,
) -> tuple[bool, Decimal, bool, Decimal, str]:
    daily_sort = (
        Decimal(0)
        if row.daily_pct_change is None
        else -row.daily_pct_change
        if direction == "UP"
        else row.daily_pct_change
    )
    amount_sort = (
        Decimal(0) if row.amount_thousand_yuan is None else -row.amount_thousand_yuan
    )
    return (
        row.daily_pct_change is None,
        daily_sort,
        row.amount_thousand_yuan is None,
        amount_sort,
        row.stock_code,
    )
