from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_calculator import (
    SectorMemberBreadthCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MemberMarketFact,
    MemberRelationFact,
    parse_member_breadth_direction,
    parse_member_breadth_history_range,
    parse_member_breadth_ma_period,
    parse_member_breadth_metric,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorScopeInvalidError,
)


TARGET_DATE = date(2026, 8, 28)


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

    details = calculator.build_details(
        sector_code="BK1001.DC",
        target_date=TARGET_DATE,
        direction="UP",
        ma_period=5,
        open_dates=dates,
        relation_dates=(TARGET_DATE,),
        relations=relations,
        market_facts=facts,
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
    baseline = calculator.build_details(
        sector_code="BK1001.DC",
        target_date=TARGET_DATE,
        direction="UP",
        ma_period=5,
        open_dates=dates,
        relation_dates=(TARGET_DATE,),
        relations=relations,
        market_facts=facts,
    )
    future_date = TARGET_DATE + timedelta(days=1)
    perturbed = calculator.build_details(
        sector_code="BK1001.DC",
        target_date=TARGET_DATE,
        direction="UP",
        ma_period=5,
        open_dates=dates,
        relation_dates=(TARGET_DATE,),
        relations=relations
        + (
            MemberRelationFact(
                sector_code="BK1001.DC",
                trade_date=future_date,
                stock_code="999999.SZ",
                stock_name="未来股票",
            ),
        ),
        market_facts=facts
        + (
            _market(
                stock_code="999999.SZ",
                trade_date=future_date,
                close="9999",
            ),
        ),
    )

    assert perturbed == baseline


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
