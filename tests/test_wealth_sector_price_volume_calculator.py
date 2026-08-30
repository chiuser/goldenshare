from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import pytest

from src.biz.services.wealth.market.sector_analysis.sector_price_volume_calculator import (
    SectorPriceVolumeCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    SectorPriceVolumeDailyFact,
    SectorPriceVolumeMissingReason,
)


def _dates(count: int) -> tuple[date, ...]:
    start = date(2026, 7, 1)
    return tuple(start + timedelta(days=index) for index in range(count))


def test_snapshot_reuses_price_semantics_and_calculates_equal_amount_windows() -> None:
    open_dates = _dates(11)
    codes = ("BK1001.DC", "BK1002.DC", "BK1003.DC")
    facts = []
    for code in codes:
        for index, trade_date in enumerate(open_dates):
            close_step = Decimal(2 if code == "BK1003.DC" else 1)
            if index == 0:
                amount = Decimal(90)
            elif index <= 5:
                amount = Decimal(100)
            elif code == "BK1003.DC":
                amount = Decimal(50)
            else:
                amount = Decimal(200)
            facts.append(
                SectorPriceVolumeDailyFact(
                    sector_code=code,
                    trade_date=trade_date,
                    close=Decimal(100) + close_step * index,
                    pct_change=close_step,
                    amount=amount,
                )
            )

    rows = SectorPriceVolumeCalculator().calculate_snapshot(
        sector_codes=codes,
        open_dates=open_dates,
        facts=facts,
        period=5,
    )
    by_code = {item.metric.sector_code: item for item in rows}

    assert by_code["BK1001.DC"].metric.price_momentum_pct == Decimal("4.7619")
    assert by_code["BK1001.DC"].metric.amount_activity_pct == Decimal("100.0000")
    assert by_code["BK1002.DC"].price_rank == 2
    assert by_code["BK1001.DC"].price_rank == 2
    assert by_code["BK1003.DC"].price_rank == 1
    assert by_code["BK1001.DC"].amount_rank == 1
    assert by_code["BK1002.DC"].amount_rank == 1
    assert by_code["BK1003.DC"].amount_rank == 3
    assert by_code["BK1001.DC"].state == "JOINT"
    assert by_code["BK1003.DC"].state == "PRICE_ONLY"
    assert [item.metric.sector_code for item in rows] == [
        "BK1003.DC",
        "BK1001.DC",
        "BK1002.DC",
    ]


def test_period_one_keeps_price_when_amount_is_missing_and_does_not_create_state() -> None:
    open_dates = _dates(2)
    rows = SectorPriceVolumeCalculator().calculate_snapshot(
        sector_codes=("BK1001.DC",),
        open_dates=open_dates,
        facts=(
            SectorPriceVolumeDailyFact(
                "BK1001.DC",
                open_dates[0],
                Decimal("100"),
                Decimal("1"),
                Decimal("100"),
            ),
            SectorPriceVolumeDailyFact(
                "BK1001.DC",
                open_dates[1],
                Decimal("101"),
                Decimal("1.23456"),
                None,
            ),
        ),
        period=1,
    )
    row = rows[0]
    assert row.metric.price_momentum_pct == Decimal("1.2346")
    assert row.metric.price_missing_reason is None
    assert row.metric.amount_activity_pct is None
    assert row.metric.amount_missing_reason == SectorPriceVolumeMissingReason.AMOUNT_MISSING
    assert row.price_rank == 1
    assert row.amount_rank is None
    assert row.state is None


def test_amount_missing_reason_priority_and_zero_prior_sum_are_deterministic() -> None:
    open_dates = _dates(4)
    calculator = SectorPriceVolumeCalculator()
    facts = (
        SectorPriceVolumeDailyFact(
            "BK1001.DC", open_dates[0], Decimal("100"), Decimal("1"), None
        ),
        SectorPriceVolumeDailyFact(
            "BK1001.DC", open_dates[2], Decimal("102"), Decimal("1"), Decimal("1")
        ),
        SectorPriceVolumeDailyFact(
            "BK1001.DC", open_dates[3], Decimal("103"), Decimal("1"), Decimal("1")
        ),
    )
    row = calculator.calculate_snapshot(
        sector_codes=("BK1001.DC",),
        open_dates=open_dates,
        facts=facts,
        period=2,
    )[0]
    assert row.metric.amount_missing_reason == SectorPriceVolumeMissingReason.DATE_MISSING

    zero_prior_facts = tuple(
        SectorPriceVolumeDailyFact(
            "BK1001.DC",
            item,
            Decimal(100 + index),
            Decimal("1"),
            Decimal(0 if index < 2 else 1),
        )
        for index, item in enumerate(open_dates)
    )
    zero_prior = calculator.calculate_snapshot(
        sector_codes=("BK1001.DC",),
        open_dates=open_dates,
        facts=zero_prior_facts,
        period=2,
    )[0]
    assert (
        zero_prior.metric.amount_missing_reason
        == SectorPriceVolumeMissingReason.PRIOR_AMOUNT_AVERAGE_NON_POSITIVE
    )

    non_finite_facts = tuple(
        SectorPriceVolumeDailyFact(
            "BK1001.DC",
            item,
            Decimal(100 + index),
            Decimal("1"),
            Decimal("Infinity") if index == 1 else Decimal("1"),
        )
        for index, item in enumerate(open_dates)
    )
    non_finite = calculator.calculate_snapshot(
        sector_codes=("BK1001.DC",),
        open_dates=open_dates,
        facts=non_finite_facts,
        period=2,
    )[0]
    assert (
        non_finite.metric.amount_missing_reason
        == SectorPriceVolumeMissingReason.AMOUNT_NON_FINITE
    )


def test_history_keeps_twenty_slots_and_future_fact_cannot_change_past_output() -> None:
    open_dates = _dates(29)
    facts = tuple(
        SectorPriceVolumeDailyFact(
            "BK1001.DC",
            trade_date,
            Decimal(100 + index),
            Decimal("1"),
            Decimal(100 + index),
        )
        for index, trade_date in enumerate(open_dates)
    )
    calculator = SectorPriceVolumeCalculator()
    baseline = calculator.calculate_history(
        sector_code="BK1001.DC",
        open_dates=open_dates,
        facts=facts,
        period=5,
        history_range=20,
    )
    future_fact = SectorPriceVolumeDailyFact(
        "BK1001.DC",
        open_dates[-1] + timedelta(days=1),
        Decimal("999999"),
        Decimal("999"),
        Decimal("999999"),
    )
    repeated = calculator.calculate_history(
        sector_code="BK1001.DC",
        open_dates=open_dates,
        facts=facts + (future_fact,),
        period=5,
        history_range=20,
    )
    assert len(baseline) == 20
    assert baseline[0].trade_date == open_dates[-20]
    assert baseline[-1].trade_date == open_dates[-1]
    assert repeated == baseline


@pytest.mark.parametrize("period", (1, 5, 10, 20, 30))
def test_amount_prefix_calculation_equals_naive_two_window_oracle(period: int) -> None:
    open_dates = _dates(119)
    amounts = tuple(
        Decimal(100 + (index % 11) * 7 + index)
        for index in range(len(open_dates))
    )
    facts = tuple(
        SectorPriceVolumeDailyFact(
            "BK1001.DC",
            trade_date,
            Decimal(100 + index),
            Decimal("1"),
            amounts[index],
        )
        for index, trade_date in enumerate(open_dates)
    )

    history = SectorPriceVolumeCalculator().calculate_history(
        sector_code="BK1001.DC",
        open_dates=open_dates,
        facts=facts,
        period=period,
        history_range=60,
    )

    for point in history:
        target_index = open_dates.index(point.trade_date)
        recent = amounts[target_index - period + 1 : target_index + 1]
        prior = amounts[target_index - 2 * period + 1 : target_index - period + 1]
        expected = ((sum(recent) / sum(prior)) - Decimal(1)) * Decimal(100)
        assert point.amount_activity_pct == expected.quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
