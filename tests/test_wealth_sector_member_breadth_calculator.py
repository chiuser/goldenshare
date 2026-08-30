from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from time import perf_counter

import pytest

from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_calculator import (
    SectorMemberBreadthCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MemberBreadthDetailsFact,
    MemberBreadthDailyProjectionFact,
    MemberBreadthDetailsProjectionFact,
    MemberBreadthDetailsWindowFact,
    MemberBreadthMemberFact,
    MemberBreadthMemberProjectionFact,
    MemberBreadthRankFact,
    MemberBreadthTrendPointFact,
    MemberMarketFact,
    MemberRelationFact,
    SectorMemberBreadthDirection,
    SectorMemberBreadthMaPeriod,
    SectorMemberBreadthMetric,
    parse_member_breadth_direction,
    parse_member_breadth_history_range,
    parse_member_breadth_ma_period,
    parse_member_breadth_metric,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorScopeInvalidError,
)


TARGET_DATE = date(2026, 8, 28)


class _IndexCountingCalculator(SectorMemberBreadthCalculator):
    def __init__(self) -> None:
        self.market_index_build_count = 0

    def index_market_facts(
        self,
        facts: Iterable[MemberMarketFact],
    ) -> dict[tuple[str, date], MemberMarketFact]:
        self.market_index_build_count += 1
        return SectorMemberBreadthCalculator.index_market_facts(facts)


def _open_dates(count: int) -> tuple[date, ...]:
    return tuple(
        TARGET_DATE - timedelta(days=count - index - 1) for index in range(count)
    )


def _relations(
    *,
    sector_code: str = "BK1001.DC",
    trade_date: date = TARGET_DATE,
    count: int = 5,
) -> tuple[MemberRelationFact, ...]:
    return tuple(
        MemberRelationFact(
            sector_code=sector_code,
            trade_date=trade_date,
            stock_code=f"{index:06d}.SZ",
            stock_name=f"股票{index}",
        )
        for index in range(1, count + 1)
    )


def _market(
    *,
    stock_code: str,
    trade_date: date = TARGET_DATE,
    close: str | None = "10",
    pct_change: str | None = "1",
    amount: str | None = "100",
    adj_factor: str | None = "1",
) -> MemberMarketFact:
    return MemberMarketFact(
        stock_code=stock_code,
        trade_date=trade_date,
        close=None if close is None else Decimal(close),
        pct_change=None if pct_change is None else Decimal(pct_change),
        amount_thousand_yuan=None if amount is None else Decimal(amount),
        adj_factor=None if adj_factor is None else Decimal(adj_factor),
    )


def _legacy_rank_requested_metric(
    calculator: SectorMemberBreadthCalculator,
    *,
    sector_codes: tuple[str, ...],
    target_date: date,
    metric: SectorMemberBreadthMetric,
    direction: SectorMemberBreadthDirection,
    ma_period: SectorMemberBreadthMaPeriod,
    open_dates: tuple[date, ...],
    relations: tuple[MemberRelationFact, ...],
    market_facts: tuple[MemberMarketFact, ...],
) -> tuple[MemberBreadthRankFact, ...]:
    compositions = {
        sector_code: calculator.calculate_composition(
            metric=metric,
            target_date=target_date,
            relations=(row for row in relations if row.sector_code == sector_code),
            market_facts=market_facts,
            open_dates=open_dates,
            ma_period=ma_period,
        )
        for sector_code in sector_codes
    }
    eligible = []
    ineligible = []
    for sector_code, composition in compositions.items():
        value = calculator.selected_pct(composition, direction=direction)
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
    for position, (sector_code, value, composition) in enumerate(eligible, start=1):
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
                calculator.selected_pct(composition, direction=direction) is not None
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


def _legacy_build_details(
    calculator: SectorMemberBreadthCalculator,
    *,
    sector_code: str,
    target_date: date,
    direction: SectorMemberBreadthDirection,
    ma_period: SectorMemberBreadthMaPeriod,
    open_dates: tuple[date, ...],
    relation_dates: tuple[date, ...],
    relations: tuple[MemberRelationFact, ...],
    market_facts: tuple[MemberMarketFact, ...],
) -> MemberBreadthDetailsFact:
    relation_rows = tuple(row for row in relations if row.sector_code == sector_code)
    compositions = tuple(
        calculator.calculate_composition(
            metric=metric,
            target_date=target_date,
            relations=relation_rows,
            market_facts=market_facts,
            open_dates=open_dates,
            ma_period=ma_period,
        )
        for metric in ("MEMBER_COUNT", "TURNOVER", "MA_POSITION")
    )
    trend = []
    for trend_date in relation_dates:
        point_compositions = tuple(
            calculator.calculate_composition(
                metric=metric,
                target_date=trend_date,
                relations=relation_rows,
                market_facts=market_facts,
                open_dates=tuple(item for item in open_dates if item <= trend_date),
                ma_period=ma_period,
            )
            for metric in ("MEMBER_COUNT", "TURNOVER", "MA_POSITION")
        )
        trend.append(
            MemberBreadthTrendPointFact(
                trade_date=trend_date,
                member_pct=calculator.selected_pct(
                    point_compositions[0], direction=direction
                ),
                turnover_pct=calculator.selected_pct(
                    point_compositions[1], direction=direction
                ),
                ma_position_pct=calculator.selected_pct(
                    point_compositions[2], direction=direction
                ),
                member_reason_codes=point_compositions[0].coverage.reason_codes,
                turnover_reason_codes=point_compositions[1].coverage.reason_codes,
                ma_position_reason_codes=point_compositions[2].coverage.reason_codes,
            )
        )
    target_relations = tuple(
        row for row in relation_rows if row.trade_date == target_date
    )
    members = _legacy_build_members(
        calculator,
        target_date=target_date,
        direction=direction,
        ma_period=ma_period,
        open_dates=open_dates,
        relations=target_relations,
        market_index=calculator.index_market_facts(market_facts),
    )
    return MemberBreadthDetailsFact(
        compositions=compositions,
        trend=tuple(trend),
        members=members,
    )


def _legacy_build_members(
    calculator: SectorMemberBreadthCalculator,
    *,
    target_date: date,
    direction: SectorMemberBreadthDirection,
    ma_period: SectorMemberBreadthMaPeriod,
    open_dates: tuple[date, ...],
    relations: tuple[MemberRelationFact, ...],
    market_index: dict[tuple[str, date], MemberMarketFact],
) -> tuple[MemberBreadthMemberFact, ...]:
    amount_rows = {
        relation.stock_code: market.amount_thousand_yuan
        for relation in relations
        if (market := market_index.get((relation.stock_code, target_date))) is not None
        and _finite(market.pct_change)
        and _finite(market.amount_thousand_yuan)
        and market.amount_thousand_yuan >= 0
    }
    total_amount = sum(amount_rows.values(), Decimal(0))
    members: list[MemberBreadthMemberFact] = []
    for relation in relations:
        market = market_index.get((relation.stock_code, target_date))
        reasons = set()
        if market is None:
            reasons.add("MARKET_ROW_MISSING")
            daily_pct = None
            amount = None
        else:
            daily_pct = market.pct_change if _finite(market.pct_change) else None
            amount = (
                market.amount_thousand_yuan
                if _finite(market.amount_thousand_yuan)
                and market.amount_thousand_yuan >= 0
                else None
            )
            if daily_pct is None:
                reasons.add("PCT_CHANGE_MISSING")
            if not _finite(market.amount_thousand_yuan):
                reasons.add("AMOUNT_MISSING")
            elif market.amount_thousand_yuan < 0:
                reasons.add("AMOUNT_NON_POSITIVE")
        contribution = (
            amount_rows[relation.stock_code] / total_amount * Decimal(100)
            if relation.stock_code in amount_rows and total_amount > 0
            else None
        )
        ma_relation, ma_distance, ma_reasons = calculator._calculate_ma_member(
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
                reason_codes=tuple(
                    reason
                    for reason in (
                        "SOURCE_MEMBER_EMPTY",
                        "MARKET_ROW_MISSING",
                        "PCT_CHANGE_MISSING",
                        "AMOUNT_MISSING",
                        "AMOUNT_NON_POSITIVE",
                        "ADJ_FACTOR_MISSING",
                        "ADJ_FACTOR_NON_POSITIVE",
                        "MA_HISTORY_INSUFFICIENT",
                        "MINIMUM_COUNT_NOT_MET",
                        "COVERAGE_NOT_MET",
                    )
                    if reason in reasons
                ),
            )
        )
    members.sort(
        key=lambda row: (
            row.daily_pct_change is None,
            Decimal(0)
            if row.daily_pct_change is None
            else -row.daily_pct_change
            if direction == "UP"
            else row.daily_pct_change,
            row.amount_thousand_yuan is None,
            Decimal(0)
            if row.amount_thousand_yuan is None
            else -row.amount_thousand_yuan,
            row.stock_code,
        )
    )
    return tuple(members)


def _project_details_inputs(
    calculator: SectorMemberBreadthCalculator,
    *,
    target_date: date,
    ma_period: SectorMemberBreadthMaPeriod,
    open_dates: tuple[date, ...],
    relation_dates: tuple[date, ...],
    relations: tuple[MemberRelationFact, ...],
    market_facts: tuple[MemberMarketFact, ...],
    expected: MemberBreadthDetailsFact,
) -> tuple[MemberBreadthDetailsWindowFact, MemberBreadthDetailsProjectionFact]:
    market_index = calculator.index_market_facts(market_facts)
    relations_by_date = {
        item: tuple(row for row in relations if row.trade_date == item)
        for item in relation_dates
    }
    daily: list[MemberBreadthDailyProjectionFact] = []
    for item, trend_point in zip(relation_dates, expected.trend, strict=True):
        compositions = tuple(
            calculator.calculate_composition(
                metric=metric,
                target_date=item,
                relations=relations_by_date[item],
                market_facts=market_facts,
                open_dates=tuple(day for day in open_dates if day <= item),
                ma_period=ma_period,
            )
            for metric in ("MEMBER_COUNT", "TURNOVER", "MA_POSITION")
        )
        amount_sums = [Decimal(0), Decimal(0), Decimal(0)]
        for relation in relations_by_date[item]:
            market = market_index.get((relation.stock_code, item))
            if (
                market is None
                or not _finite(market.pct_change)
                or not _finite(market.amount_thousand_yuan)
                or market.amount_thousand_yuan < 0
            ):
                continue
            bucket = 0 if market.pct_change > 0 else 2 if market.pct_change < 0 else 1
            amount_sums[bucket] += market.amount_thousand_yuan
        daily.append(
            MemberBreadthDailyProjectionFact(
                trade_date=item,
                source_count=compositions[0].coverage.source_count,
                member_calculable_count=compositions[0].coverage.calculable_count,
                member_up_count=compositions[0].up_count,
                member_flat_count=compositions[0].flat_count,
                member_down_count=compositions[0].down_count,
                turnover_calculable_count=compositions[1].coverage.calculable_count,
                turnover_up_count=compositions[1].up_count,
                turnover_flat_count=compositions[1].flat_count,
                turnover_down_count=compositions[1].down_count,
                turnover_up_amount=amount_sums[0],
                turnover_flat_amount=amount_sums[1],
                turnover_down_amount=amount_sums[2],
                ma_calculable_count=compositions[2].coverage.calculable_count,
                ma_above_count=compositions[2].up_count,
                ma_equal_count=compositions[2].flat_count,
                ma_below_count=compositions[2].down_count,
                member_source_reasons=trend_point.member_reason_codes,
                turnover_source_reasons=trend_point.turnover_reason_codes,
                ma_source_reasons=trend_point.ma_position_reason_codes,
            )
        )
    expected_members = {item.stock_code: item for item in expected.members}
    members: list[MemberBreadthMemberProjectionFact] = []
    target_relations = relations_by_date[target_date]
    for relation in target_relations:
        market = market_index.get((relation.stock_code, target_date))
        window_dates = tuple(item for item in open_dates if item <= target_date)[
            -ma_period:
        ]
        adjusted_values = []
        for item in window_dates:
            row = market_index.get((relation.stock_code, item))
            if (
                row is not None
                and _finite(row.close)
                and row.close > 0
                and _finite(row.adj_factor)
                and row.adj_factor > 0
            ):
                adjusted_values.append(row.close * row.adj_factor)
        members.append(
            MemberBreadthMemberProjectionFact(
                trade_date=target_date,
                stock_code=relation.stock_code,
                stock_name=relation.stock_name,
                daily_pct_change=(
                    market.pct_change
                    if market is not None and _finite(market.pct_change)
                    else None
                ),
                amount_thousand_yuan=(
                    market.amount_thousand_yuan
                    if market is not None
                    and _finite(market.amount_thousand_yuan)
                    and market.amount_thousand_yuan >= 0
                    else None
                ),
                current_adjusted_basis=(
                    adjusted_values[-1]
                    if len(adjusted_values) == ma_period
                    else None
                ),
                rolling_adjusted_sum=(
                    sum(adjusted_values, Decimal(0)) if adjusted_values else None
                ),
                rolling_slot_count=len(window_dates),
                rolling_valid_count=len(adjusted_values),
                source_reasons=expected_members[relation.stock_code].reason_codes,
            )
        )
    window = MemberBreadthDetailsWindowFact(
        coverage_start_date=open_dates[0],
        coverage_end_date=target_date,
        open_dates=open_dates,
        relation_dates=relation_dates,
        target_source_count=len(target_relations),
    )
    return window, MemberBreadthDetailsProjectionFact(
        daily=tuple(daily),
        members=tuple(members),
    )


def _finite(value: Decimal | None) -> bool:
    return value is not None and value.is_finite()


def _equivalence_facts() -> tuple[
    tuple[str, ...],
    tuple[date, ...],
    tuple[MemberRelationFact, ...],
    tuple[MemberMarketFact, ...],
]:
    open_dates = _open_dates(119)
    sector_codes = tuple(f"BK2{index:03d}.DC" for index in range(1, 5))
    relations = tuple(
        MemberRelationFact(
            sector_code=sector_code,
            trade_date=trade_date,
            stock_code=f"{sector_index:02d}{member_index:04d}.SZ",
            stock_name=f"股票{sector_index}-{member_index}",
        )
        for sector_index, sector_code in enumerate(sector_codes, start=1)
        for trade_date in open_dates[-60:]
        for member_index in range(1, 7)
    )
    market_facts = tuple(
        _market(
            stock_code=f"{sector_index:02d}{member_index:04d}.SZ",
            trade_date=trade_date,
            close=str(10 + day_index + member_index),
            pct_change=str(((sector_index + member_index + day_index) % 3) - 1),
            amount=str(100 + sector_index * 10 + member_index * 5 + day_index),
        )
        for sector_index in range(1, 5)
        for member_index in range(1, 7)
        for day_index, trade_date in enumerate(open_dates)
    )
    return sector_codes, open_dates, relations, market_facts


def test_member_and_turnover_use_independent_denominators_and_ignore_factor_gaps() -> (
    None
):
    calculator = SectorMemberBreadthCalculator()
    relations = _relations(count=6)
    facts = tuple(
        _market(
            stock_code=row.stock_code,
            pct_change=("1", "1", "0", "-1", "-1", None)[index],
            amount=("100", "200", "100", "50", None, "500")[index],
            adj_factor=None,
        )
        for index, row in enumerate(relations)
    )

    member = calculator.calculate_composition(
        metric="MEMBER_COUNT",
        target_date=TARGET_DATE,
        relations=relations,
        market_facts=facts,
        open_dates=(TARGET_DATE,),
        ma_period=20,
    )
    turnover = calculator.calculate_composition(
        metric="TURNOVER",
        target_date=TARGET_DATE,
        relations=relations,
        market_facts=facts,
        open_dates=(TARGET_DATE,),
        ma_period=20,
    )

    assert (member.up_count, member.flat_count, member.down_count) == (2, 1, 2)
    assert member.coverage.calculable_count == 5
    assert member.coverage.eligible is True
    assert "ADJ_FACTOR_MISSING" not in member.coverage.reason_codes
    assert turnover.coverage.calculable_count == 4
    assert turnover.coverage.eligible is False
    assert turnover.up_pct == Decimal(300) / Decimal(450) * Decimal(100)
    assert "AMOUNT_MISSING" in turnover.coverage.reason_codes
    assert "ADJ_FACTOR_MISSING" not in turnover.coverage.reason_codes


def test_zero_total_turnover_is_unavailable_not_zero_percent() -> None:
    calculator = SectorMemberBreadthCalculator()
    relations = _relations()
    facts = tuple(_market(stock_code=row.stock_code, amount="0") for row in relations)

    composition = calculator.calculate_composition(
        metric="TURNOVER",
        target_date=TARGET_DATE,
        relations=relations,
        market_facts=facts,
        open_dates=(TARGET_DATE,),
        ma_period=20,
    )

    assert composition.coverage.calculable_count == 5
    assert composition.coverage.eligible is False
    assert composition.up_pct is composition.flat_pct is composition.down_pct is None
    assert "AMOUNT_NON_POSITIVE" in composition.coverage.reason_codes


@pytest.mark.parametrize("ma_period", [5, 10, 15, 20, 30, 60])
def test_all_six_ma_periods_use_close_times_adjustment_factor(
    ma_period: int,
) -> None:
    calculator = SectorMemberBreadthCalculator()
    dates = _open_dates(ma_period)
    relations = _relations()
    facts = tuple(
        _market(
            stock_code=relation.stock_code,
            trade_date=item,
            close=str(index + 1),
            adj_factor="2",
        )
        for relation in relations
        for index, item in enumerate(dates)
    )

    composition = calculator.calculate_composition(
        metric="MA_POSITION",
        target_date=TARGET_DATE,
        relations=relations,
        market_facts=facts,
        open_dates=dates,
        ma_period=ma_period,  # type: ignore[arg-type]
    )

    assert composition.coverage.eligible is True
    assert composition.up_count == 5
    assert composition.up_pct == Decimal(100)


def test_equal_to_ma_is_neutral_and_missing_factor_only_changes_ma() -> None:
    calculator = SectorMemberBreadthCalculator()
    dates = _open_dates(5)
    relations = _relations()
    facts = [
        _market(stock_code=relation.stock_code, trade_date=item)
        for relation in relations
        for item in dates
    ]
    facts = [
        MemberMarketFact(
            stock_code=fact.stock_code,
            trade_date=fact.trade_date,
            close=fact.close,
            pct_change=fact.pct_change,
            amount_thousand_yuan=fact.amount_thousand_yuan,
            adj_factor=(
                None
                if fact.stock_code == relations[0].stock_code
                and fact.trade_date == dates[2]
                else fact.adj_factor
            ),
        )
        for fact in facts
    ]

    ma = calculator.calculate_composition(
        metric="MA_POSITION",
        target_date=TARGET_DATE,
        relations=relations,
        market_facts=facts,
        open_dates=dates,
        ma_period=5,
    )
    member = calculator.calculate_composition(
        metric="MEMBER_COUNT",
        target_date=TARGET_DATE,
        relations=relations,
        market_facts=facts,
        open_dates=dates,
        ma_period=5,
    )

    assert (ma.up_count, ma.flat_count, ma.down_count) == (0, 4, 0)
    assert ma.coverage.calculable_count == 4
    assert "ADJ_FACTOR_MISSING" in ma.coverage.reason_codes
    assert member.coverage.calculable_count == 5
    assert member.coverage.eligible is True


def test_ma_rejects_short_history_and_non_positive_factor() -> None:
    calculator = SectorMemberBreadthCalculator()
    dates = _open_dates(4)
    relations = _relations()
    facts = tuple(
        _market(
            stock_code=relation.stock_code,
            trade_date=item,
            adj_factor="0" if relation == relations[0] else "1",
        )
        for relation in relations
        for item in dates
    )

    composition = calculator.calculate_composition(
        metric="MA_POSITION",
        target_date=TARGET_DATE,
        relations=relations,
        market_facts=facts,
        open_dates=dates,
        ma_period=5,
    )

    assert composition.up_pct is None
    assert "MA_HISTORY_INSUFFICIENT" in composition.coverage.reason_codes


def test_competition_ranking_keeps_full_list_and_uses_1_2_2_4() -> None:
    calculator = SectorMemberBreadthCalculator()
    sector_codes = tuple(f"BK100{index}.DC" for index in range(1, 5))
    positive_counts = (5, 4, 4, 3)
    relations: list[MemberRelationFact] = []
    facts: list[MemberMarketFact] = []
    for sector_code, positive_count in zip(sector_codes, positive_counts, strict=True):
        sector_relations = _relations(sector_code=sector_code)
        relations.extend(sector_relations)
        facts.extend(
            _market(
                stock_code=f"{sector_code[2:6]}{index:02d}.SZ",
                pct_change="1" if index <= positive_count else "-1",
            )
            for index in range(1, 6)
        )
        relations[-5:] = [
            MemberRelationFact(
                sector_code=sector_code,
                trade_date=TARGET_DATE,
                stock_code=facts[-5 + offset].stock_code,
                stock_name=None,
            )
            for offset in range(5)
        ]

    ranked = calculator.rank_requested_metric(
        sector_codes=sector_codes,
        target_date=TARGET_DATE,
        metric="MEMBER_COUNT",
        direction="UP",
        ma_period=20,
        open_dates=(TARGET_DATE,),
        relations=relations,
        market_facts=facts,
    )

    assert [item.rank for item in ranked] == [1, 2, 2, 4]
    assert [item.rank_total for item in ranked] == [4, 4, 4, 4]
    assert [item.metric_value_pct for item in ranked] == [
        Decimal(100),
        Decimal(80),
        Decimal(80),
        Decimal(60),
    ]


def test_small_sector_remains_in_list_but_is_not_ranked() -> None:
    calculator = SectorMemberBreadthCalculator()
    relations = _relations(count=4)
    facts = tuple(_market(stock_code=row.stock_code) for row in relations)

    ranked = calculator.rank_requested_metric(
        sector_codes=("BK1001.DC",),
        target_date=TARGET_DATE,
        metric="MEMBER_COUNT",
        direction="UP",
        ma_period=20,
        open_dates=(TARGET_DATE,),
        relations=relations,
        market_facts=facts,
    )

    assert len(ranked) == 1
    assert ranked[0].metric_calculable is True
    assert ranked[0].metric_value_pct is None
    assert ranked[0].rank is None
    assert "MINIMUM_COUNT_NOT_MET" in ranked[0].reason_codes


def test_details_sort_members_and_use_one_turnover_denominator() -> None:
    calculator = SectorMemberBreadthCalculator()
    dates = _open_dates(5)
    relations = _relations(count=5)
    pcts = ("1", "1", "-1", None, "0")
    amounts = ("100", "200", "300", "400", None)
    facts = tuple(
        _market(
            stock_code=relation.stock_code,
            trade_date=item,
            pct_change=pcts[index] if item == TARGET_DATE else "0",
            amount=amounts[index],
        )
        for index, relation in enumerate(relations)
        for item in dates
    )

    expected = _legacy_build_details(
        calculator,
        sector_code="BK1001.DC",
        target_date=TARGET_DATE,
        direction="UP",
        ma_period=5,
        open_dates=dates,
        relation_dates=(TARGET_DATE,),
        relations=relations,
        market_facts=facts,
    )
    window, projection = _project_details_inputs(
        calculator,
        target_date=TARGET_DATE,
        ma_period=5,
        open_dates=dates,
        relation_dates=(TARGET_DATE,),
        relations=relations,
        market_facts=facts,
        expected=expected,
    )
    details = calculator.build_details(
        target_date=TARGET_DATE,
        direction="UP",
        ma_period=5,
        window=window,
        projection=projection,
    )

    assert [row.stock_code for row in details.members] == [
        "000002.SZ",
        "000001.SZ",
        "000005.SZ",
        "000003.SZ",
        "000004.SZ",
    ]
    contributions = {
        row.stock_code: row.amount_contribution_pct for row in details.members
    }
    assert contributions["000001.SZ"] == Decimal(100) / Decimal(600) * Decimal(100)
    assert contributions["000002.SZ"] == Decimal(200) / Decimal(600) * Decimal(100)
    assert contributions["000003.SZ"] == Decimal(300) / Decimal(600) * Decimal(100)
    assert contributions["000004.SZ"] is None
    assert contributions["000005.SZ"] is None


def test_future_market_and_members_do_not_change_past_details() -> None:
    calculator = SectorMemberBreadthCalculator()
    dates = _open_dates(5)
    relations = _relations()
    facts = tuple(
        _market(stock_code=relation.stock_code, trade_date=item, close=str(index + 1))
        for relation in relations
        for index, item in enumerate(dates)
    )
    baseline_expected = _legacy_build_details(
        calculator,
        sector_code="BK1001.DC",
        target_date=TARGET_DATE,
        direction="UP",
        ma_period=5,
        open_dates=dates,
        relation_dates=(TARGET_DATE,),
        relations=relations,
        market_facts=facts,
    )
    baseline_window, baseline_projection = _project_details_inputs(
        calculator,
        target_date=TARGET_DATE,
        ma_period=5,
        open_dates=dates,
        relation_dates=(TARGET_DATE,),
        relations=relations,
        market_facts=facts,
        expected=baseline_expected,
    )
    baseline = calculator.build_details(
        target_date=TARGET_DATE,
        direction="UP",
        ma_period=5,
        window=baseline_window,
        projection=baseline_projection,
    )
    future_date = TARGET_DATE + timedelta(days=1)
    perturbed_relations = relations + (
        MemberRelationFact(
            sector_code="BK1001.DC",
            trade_date=future_date,
            stock_code="999999.SZ",
            stock_name="未来股票",
        ),
    )
    perturbed_facts = facts + (
        _market(
            stock_code="999999.SZ",
            trade_date=future_date,
            close="9999",
        ),
    )
    perturbed_expected = _legacy_build_details(
        calculator,
        sector_code="BK1001.DC",
        target_date=TARGET_DATE,
        direction="UP",
        ma_period=5,
        open_dates=dates,
        relation_dates=(TARGET_DATE,),
        relations=perturbed_relations,
        market_facts=perturbed_facts,
    )
    perturbed_window, perturbed_projection = _project_details_inputs(
        calculator,
        target_date=TARGET_DATE,
        ma_period=5,
        open_dates=dates,
        relation_dates=(TARGET_DATE,),
        relations=perturbed_relations,
        market_facts=perturbed_facts,
        expected=perturbed_expected,
    )
    perturbed = calculator.build_details(
        target_date=TARGET_DATE,
        direction="UP",
        ma_period=5,
        window=perturbed_window,
        projection=perturbed_projection,
    )

    assert perturbed == baseline


@pytest.mark.parametrize(
    ("metric", "direction", "ma_period"),
    [
        (metric, direction, ma_period)
        for metric in ("MEMBER_COUNT", "TURNOVER", "MA_POSITION")
        for direction in ("UP", "DOWN")
        for ma_period in ((5, 10, 15, 20, 30, 60) if metric == "MA_POSITION" else (20,))
    ],
)
def test_rankings_match_legacy_oracle_for_the_full_metric_matrix(
    metric: SectorMemberBreadthMetric,
    direction: SectorMemberBreadthDirection,
    ma_period: SectorMemberBreadthMaPeriod,
) -> None:
    sector_codes, open_dates, relations, market_facts = _equivalence_facts()
    calculator = SectorMemberBreadthCalculator()

    expected = _legacy_rank_requested_metric(
        calculator,
        sector_codes=sector_codes,
        target_date=TARGET_DATE,
        metric=metric,
        direction=direction,
        ma_period=ma_period,
        open_dates=open_dates,
        relations=relations,
        market_facts=market_facts,
    )
    actual = calculator.rank_requested_metric(
        sector_codes=sector_codes,
        target_date=TARGET_DATE,
        metric=metric,
        direction=direction,
        ma_period=ma_period,
        open_dates=open_dates,
        relations=relations,
        market_facts=market_facts,
    )

    assert actual == expected


@pytest.mark.parametrize("direction", ["UP", "DOWN"])
@pytest.mark.parametrize("ma_period", [5, 10, 15, 20, 30, 60])
@pytest.mark.parametrize("history_range", [20, 30, 60])
def test_details_match_legacy_oracle_for_every_direction_and_ma_period(
    direction: SectorMemberBreadthDirection,
    ma_period: SectorMemberBreadthMaPeriod,
    history_range: int,
) -> None:
    sector_codes, open_dates, relations, market_facts = _equivalence_facts()
    calculator = SectorMemberBreadthCalculator()
    relation_dates = open_dates[-history_range:]

    expected = _legacy_build_details(
        calculator,
        sector_code=sector_codes[0],
        target_date=TARGET_DATE,
        direction=direction,
        ma_period=ma_period,
        open_dates=open_dates,
        relation_dates=relation_dates,
        relations=relations,
        market_facts=market_facts,
    )
    window, projection = _project_details_inputs(
        calculator,
        target_date=TARGET_DATE,
        ma_period=ma_period,
        open_dates=open_dates,
        relation_dates=relation_dates,
        relations=tuple(
            row for row in relations if row.sector_code == sector_codes[0]
        ),
        market_facts=market_facts,
        expected=expected,
    )
    actual = calculator.build_details(
        target_date=TARGET_DATE,
        direction=direction,
        ma_period=ma_period,
        window=window,
        projection=projection,
    )

    assert actual == expected


def test_realistic_level3_ma60_rankings_build_one_market_index() -> None:
    calculator = _IndexCountingCalculator()
    open_dates = _open_dates(60)
    sector_codes = tuple(f"BK{index:04d}.DC" for index in range(1, 338))
    stock_codes = tuple(f"S{index:06d}.SZ" for index in range(5_523))
    relations: list[MemberRelationFact] = []
    relation_index = 0
    for sector_index, sector_code in enumerate(sector_codes):
        sector_size = 51 if sector_index < 73 else 50
        for _ in range(sector_size):
            stock_code = stock_codes[relation_index % len(stock_codes)]
            relations.append(
                MemberRelationFact(
                    sector_code=sector_code,
                    trade_date=TARGET_DATE,
                    stock_code=stock_code,
                    stock_name=None,
                )
            )
            relation_index += 1
    market_facts = tuple(
        _market(
            stock_code=stock_code,
            trade_date=trade_date,
            close=str(10 + day_index),
        )
        for stock_code in stock_codes
        for day_index, trade_date in enumerate(open_dates)
    )

    started_at = perf_counter()
    ranked = calculator.rank_requested_metric(
        sector_codes=sector_codes,
        target_date=TARGET_DATE,
        metric="MA_POSITION",
        direction="UP",
        ma_period=60,
        open_dates=open_dates,
        relations=relations,
        market_facts=market_facts,
    )
    elapsed_seconds = perf_counter() - started_at

    assert len(relations) == 16_923
    assert len(ranked) == 337
    assert all(item.rank is not None for item in ranked)
    assert calculator.market_index_build_count == 1
    assert elapsed_seconds < 2


def test_realistic_largest_details_projection_stays_under_internal_budget() -> None:
    calculator = SectorMemberBreadthCalculator()
    open_dates = _open_dates(119)
    relation_dates = open_dates[-60:]
    stock_codes = tuple(f"L{index:06d}.SZ" for index in range(625))
    daily = tuple(
        MemberBreadthDailyProjectionFact(
            trade_date=trade_date,
            source_count=625,
            member_calculable_count=625,
            member_up_count=625,
            member_flat_count=0,
            member_down_count=0,
            turnover_calculable_count=625,
            turnover_up_count=625,
            turnover_flat_count=0,
            turnover_down_count=0,
            turnover_up_amount=Decimal("62500"),
            turnover_flat_amount=Decimal(0),
            turnover_down_amount=Decimal(0),
            ma_calculable_count=625,
            ma_above_count=0,
            ma_equal_count=625,
            ma_below_count=0,
            member_source_reasons=(),
            turnover_source_reasons=(),
            ma_source_reasons=(),
        )
        for trade_date in relation_dates
    )
    members = tuple(
        MemberBreadthMemberProjectionFact(
            trade_date=TARGET_DATE,
            stock_code=stock_code,
            stock_name=None,
            daily_pct_change=Decimal(1),
            amount_thousand_yuan=Decimal(100),
            current_adjusted_basis=Decimal(10),
            rolling_adjusted_sum=Decimal(600),
            rolling_slot_count=60,
            rolling_valid_count=60,
            source_reasons=(),
        )
        for stock_code in stock_codes
    )
    window = MemberBreadthDetailsWindowFact(
        coverage_start_date=open_dates[0],
        coverage_end_date=TARGET_DATE,
        open_dates=open_dates,
        relation_dates=relation_dates,
        target_source_count=625,
    )
    projection = MemberBreadthDetailsProjectionFact(daily=daily, members=members)

    elapsed_samples = []
    details = None
    for _ in range(20):
        started_at = perf_counter()
        details = calculator.build_details(
            target_date=TARGET_DATE,
            direction="UP",
            ma_period=60,
            window=window,
            projection=projection,
        )
        elapsed_samples.append(perf_counter() - started_at)
    p95_seconds = sorted(elapsed_samples)[18]

    assert details is not None
    assert len(details.members) == 625
    assert len(details.trend) == 60
    assert len(projection.daily) + len(projection.members) == 685
    assert p95_seconds < 0.2


def test_member_breadth_parsers_reject_unapproved_values() -> None:
    assert parse_member_breadth_metric("MEMBER_COUNT") == "MEMBER_COUNT"
    assert parse_member_breadth_direction("DOWN") == "DOWN"
    assert parse_member_breadth_ma_period(60) == 60
    assert parse_member_breadth_history_range(30) == 30
    for callback in (
        lambda: parse_member_breadth_metric("COMPOSITE"),
        lambda: parse_member_breadth_direction("GAINERS"),
        lambda: parse_member_breadth_ma_period(120),
        lambda: parse_member_breadth_history_range(90),
    ):
        with pytest.raises(SectorScopeInvalidError):
            callback()
