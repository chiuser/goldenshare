from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MEMBER_BREADTH_MINIMUM_CALCULABLE_COUNT,
    MEMBER_BREADTH_MINIMUM_COVERAGE_PCT,
    MemberBreadthCompositionFact,
    MemberBreadthDailyProjectionFact,
    MemberBreadthDetailsFact,
    MemberBreadthDetailsProjectionFact,
    MemberBreadthDetailsWindowFact,
    MemberBreadthMemberFact,
    MemberBreadthMemberProjectionFact,
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
        return self._calculate_composition_from_index(
            metric=metric,
            target_date=target_date,
            relations=relation_rows,
            market_index=market_index,
            open_dates=open_dates,
            ma_period=ma_period,
        )

    def calculate_composition_grid(
        self,
        *,
        sector_codes: Iterable[str],
        target_date: date,
        relations: Iterable[MemberRelationFact],
        market_facts: Iterable[MemberMarketFact],
        open_dates: tuple[date, ...],
    ) -> dict[tuple[str, SectorMemberBreadthMetric, int], MemberBreadthCompositionFact]:
        """Build every frozen breadth composition while indexing the source only once."""
        codes = tuple(dict.fromkeys(sector_codes))
        relations_by_sector: dict[str, list[MemberRelationFact]] = {
            code: [] for code in codes
        }
        for relation in relations:
            if relation.trade_date == target_date and relation.sector_code in relations_by_sector:
                relations_by_sector[relation.sector_code].append(relation)
        market_index = self.index_market_facts(market_facts)
        grid: dict[tuple[str, SectorMemberBreadthMetric, int], MemberBreadthCompositionFact] = {}
        for code in codes:
            rows = tuple(sorted(relations_by_sector[code], key=lambda item: item.stock_code))
            for metric, ma_periods in (
                ("MEMBER_COUNT", (20,)),
                ("TURNOVER", (20,)),
                ("MA_POSITION", (5, 10, 15, 20, 30, 60)),
            ):
                for ma_period in ma_periods:
                    grid[(code, metric, ma_period)] = self._calculate_composition_from_index(
                        metric=metric,
                        target_date=target_date,
                        relations=rows,
                        market_index=market_index,
                        open_dates=open_dates,
                        ma_period=ma_period,
                    )
        return grid

    @staticmethod
    def turnover_amount_totals(
        *,
        relations: Iterable[MemberRelationFact],
        target_date: date,
        market_index: dict[tuple[str, date], MemberMarketFact],
    ) -> tuple[Decimal, Decimal, Decimal]:
        totals = [Decimal(0), Decimal(0), Decimal(0)]
        for relation in relations:
            market = market_index.get((relation.stock_code, target_date))
            if (
                market is None
                or not _is_finite(market.pct_change)
                or not _is_finite(market.amount_thousand_yuan)
                or market.amount_thousand_yuan < 0
            ):
                continue
            position = 0 if market.pct_change > 0 else 1 if market.pct_change == 0 else 2
            totals[position] += market.amount_thousand_yuan
        return totals[0], totals[1], totals[2]

    def _calculate_composition_from_index(
        self,
        *,
        metric: SectorMemberBreadthMetric,
        target_date: date,
        relations: tuple[MemberRelationFact, ...],
        market_index: dict[tuple[str, date], MemberMarketFact],
        open_dates: tuple[date, ...],
        ma_period: SectorMemberBreadthMaPeriod,
    ) -> MemberBreadthCompositionFact:
        if metric == "MEMBER_COUNT":
            return self._member_composition(
                relations=relations,
                target_date=target_date,
                market_index=market_index,
            )
        if metric == "TURNOVER":
            return self._turnover_composition(
                relations=relations,
                target_date=target_date,
                market_index=market_index,
            )
        return self._ma_composition(
            relations=relations,
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
        requested_sector_codes = tuple(dict.fromkeys(sector_codes))
        if not requested_sector_codes:
            return ()
        relations_by_sector: dict[str, list[MemberRelationFact]] = {
            sector_code: [] for sector_code in requested_sector_codes
        }
        for relation in relations:
            if relation.trade_date != target_date:
                continue
            bucket = relations_by_sector.get(relation.sector_code)
            if bucket is not None:
                bucket.append(relation)
        sorted_relations_by_sector = {
            sector_code: tuple(
                sorted(rows, key=lambda row: (row.stock_code, row.sector_code))
            )
            for sector_code, rows in relations_by_sector.items()
        }
        market_index = self.index_market_facts(market_facts)
        compositions: dict[str, MemberBreadthCompositionFact] = {}
        for sector_code in requested_sector_codes:
            compositions[sector_code] = self._calculate_composition_from_index(
                metric=metric,
                target_date=target_date,
                relations=sorted_relations_by_sector[sector_code],
                market_index=market_index,
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
        target_date: date,
        direction: SectorMemberBreadthDirection,
        ma_period: SectorMemberBreadthMaPeriod,
        window: MemberBreadthDetailsWindowFact,
        projection: MemberBreadthDetailsProjectionFact,
    ) -> MemberBreadthDetailsFact:
        if not window.relation_dates or window.relation_dates[-1] != target_date:
            raise ValueError("member breadth target date mismatch")
        if tuple(item.trade_date for item in projection.daily) != window.relation_dates:
            raise ValueError("member breadth daily projection dates mismatch")
        if any(item.trade_date != target_date for item in projection.members):
            raise ValueError("member breadth target projection date mismatch")
        member_codes = tuple(item.stock_code for item in projection.members)
        if len(set(member_codes)) != len(member_codes):
            raise ValueError("duplicate member breadth target projection")
        target_projection = projection.daily[-1]
        if (
            target_projection.source_count != window.target_source_count
            or window.target_source_count != len(projection.members)
        ):
            raise ValueError("member breadth target source count mismatch")

        compositions_by_date = {
            item.trade_date: self._projected_compositions(item)
            for item in projection.daily
        }
        compositions = compositions_by_date[target_date]
        trend = tuple(
            MemberBreadthTrendPointFact(
                trade_date=item.trade_date,
                member_pct=self.selected_pct(
                    compositions_by_date[item.trade_date][0], direction=direction
                ),
                turnover_pct=self.selected_pct(
                    compositions_by_date[item.trade_date][1], direction=direction
                ),
                ma_position_pct=self.selected_pct(
                    compositions_by_date[item.trade_date][2], direction=direction
                ),
                member_reason_codes=compositions_by_date[item.trade_date][
                    0
                ].coverage.reason_codes,
                turnover_reason_codes=compositions_by_date[item.trade_date][
                    1
                ].coverage.reason_codes,
                ma_position_reason_codes=compositions_by_date[item.trade_date][
                    2
                ].coverage.reason_codes,
            )
            for item in projection.daily
        )
        members = self._project_members(
            rows=projection.members,
            direction=direction,
            ma_period=ma_period,
        )
        return MemberBreadthDetailsFact(
            compositions=compositions,
            trend=trend,
            members=members,
        )

    def _projected_compositions(
        self,
        row: MemberBreadthDailyProjectionFact,
    ) -> tuple[
        MemberBreadthCompositionFact,
        MemberBreadthCompositionFact,
        MemberBreadthCompositionFact,
    ]:
        member_coverage = self._coverage(
            source_count=row.source_count,
            calculable_count=row.member_calculable_count,
            reasons=set(row.member_source_reasons),
            metric_available=row.member_calculable_count > 0,
        )
        member = self._count_composition_from_counts(
            metric="MEMBER_COUNT",
            counts=(row.member_up_count, row.member_flat_count, row.member_down_count),
            coverage=member_coverage,
        )

        turnover_reasons = set(row.turnover_source_reasons)
        turnover_total = (
            row.turnover_up_amount
            + row.turnover_flat_amount
            + row.turnover_down_amount
        )
        turnover_available = (
            row.turnover_calculable_count > 0 and turnover_total > 0
        )
        if row.turnover_calculable_count > 0 and turnover_total <= 0:
            turnover_reasons.add("AMOUNT_NON_POSITIVE")
        turnover_coverage = self._coverage(
            source_count=row.source_count,
            calculable_count=row.turnover_calculable_count,
            reasons=turnover_reasons,
            metric_available=turnover_available,
        )
        turnover_percentages: tuple[
            Decimal | None,
            Decimal | None,
            Decimal | None,
        ]
        if turnover_available:
            turnover_percentages = (
                row.turnover_up_amount / turnover_total * _HUNDRED,
                row.turnover_flat_amount / turnover_total * _HUNDRED,
                row.turnover_down_amount / turnover_total * _HUNDRED,
            )
        else:
            turnover_percentages = (None, None, None)
        turnover = MemberBreadthCompositionFact(
            metric="TURNOVER",
            up_count=row.turnover_up_count,
            flat_count=row.turnover_flat_count,
            down_count=row.turnover_down_count,
            up_pct=turnover_percentages[0],
            flat_pct=turnover_percentages[1],
            down_pct=turnover_percentages[2],
            coverage=turnover_coverage,
        )

        ma_coverage = self._coverage(
            source_count=row.source_count,
            calculable_count=row.ma_calculable_count,
            reasons=set(row.ma_source_reasons),
            metric_available=row.ma_calculable_count > 0,
        )
        ma = self._count_composition_from_counts(
            metric="MA_POSITION",
            counts=(row.ma_above_count, row.ma_equal_count, row.ma_below_count),
            coverage=ma_coverage,
        )
        return member, turnover, ma

    def _project_members(
        self,
        *,
        rows: tuple[MemberBreadthMemberProjectionFact, ...],
        direction: SectorMemberBreadthDirection,
        ma_period: SectorMemberBreadthMaPeriod,
    ) -> tuple[MemberBreadthMemberFact, ...]:
        contribution_amounts = {
            row.stock_code: row.amount_thousand_yuan
            for row in rows
            if row.daily_pct_change is not None
            and row.amount_thousand_yuan is not None
        }
        total_amount = sum(contribution_amounts.values(), Decimal(0))
        members: list[MemberBreadthMemberFact] = []
        for row in rows:
            reasons = set(row.source_reasons)
            ma_relation: SectorMemberMaRelation | None = None
            ma_distance: Decimal | None = None
            if (
                row.rolling_slot_count == ma_period
                and row.rolling_valid_count == ma_period
                and row.current_adjusted_basis is not None
                and row.rolling_adjusted_sum is not None
            ):
                comparison_basis = row.current_adjusted_basis * Decimal(ma_period)
                if comparison_basis > row.rolling_adjusted_sum:
                    ma_relation = "ABOVE"
                elif comparison_basis < row.rolling_adjusted_sum:
                    ma_relation = "BELOW"
                else:
                    ma_relation = "EQUAL"
                moving_average = row.rolling_adjusted_sum / Decimal(ma_period)
                ma_distance = (
                    row.current_adjusted_basis / moving_average - Decimal(1)
                ) * _HUNDRED
            else:
                reasons.add("MA_HISTORY_INSUFFICIENT")
            contribution = (
                contribution_amounts[row.stock_code] / total_amount * _HUNDRED
                if row.stock_code in contribution_amounts and total_amount > 0
                else None
            )
            members.append(
                MemberBreadthMemberFact(
                    stock_code=row.stock_code,
                    stock_name=row.stock_name,
                    daily_pct_change=row.daily_pct_change,
                    amount_thousand_yuan=row.amount_thousand_yuan,
                    amount_contribution_pct=contribution,
                    ma_relation=ma_relation,
                    ma_distance_pct=ma_distance,
                    reason_codes=ordered_member_breadth_reasons(reasons),
                )
            )
        members.sort(key=lambda item: _member_sort_key(item, direction=direction))
        return tuple(members)

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
        amount_totals = self.turnover_amount_totals(
            relations=relations,
            target_date=target_date,
            market_index=market_index,
        )
        total_amount = sum(amount_totals, Decimal(0))
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
            percentages = tuple(amount / total_amount * _HUNDRED for amount in amount_totals)
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
        return SectorMemberBreadthCalculator._count_composition_from_counts(
            metric=metric,
            counts=_direction_counts(value_rows),
            coverage=coverage,
        )

    @staticmethod
    def _count_composition_from_counts(
        *,
        metric: SectorMemberBreadthMetric,
        counts: tuple[int, int, int],
        coverage: MetricCoverageFact,
    ) -> MemberBreadthCompositionFact:
        up_count, flat_count, down_count = counts
        denominator = up_count + flat_count + down_count
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
