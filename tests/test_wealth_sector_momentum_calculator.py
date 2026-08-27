from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.biz.services.wealth.market.sector_analysis.sector_momentum_calculator import (
    SectorMomentumCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    DuplicateSectorFactError,
    SectorDailyFact,
    SectorReturnFact,
)


START_DATE = date(2026, 8, 1)


def _dates(count: int) -> tuple[date, ...]:
    return tuple(START_DATE + timedelta(days=index) for index in range(count))


def _fact(code: str, item: date, *, close: str | None, pct: str | None) -> SectorDailyFact:
    return SectorDailyFact(
        sector_code=code,
        trade_date=item,
        close=Decimal(close) if close is not None else None,
        pct_change=Decimal(pct) if pct is not None else None,
    )


def test_one_day_uses_pct_change_and_quantizes_half_up() -> None:
    dates = _dates(1)
    facts = SectorMomentumCalculator.index_facts(
        [_fact("BK1001.DC", dates[0], close="10", pct="1.23455")]
    )

    result = SectorMomentumCalculator().calculate_for_date(
        sector_codes=("BK1001.DC",),
        open_dates=dates,
        target_date=dates[0],
        period=1,
        fact_index=facts,
    )

    assert result[0].return_pct == Decimal("1.2346")


@pytest.mark.parametrize("period", [5, 10, 20, 30])
def test_multi_day_formula_requires_n_plus_one_complete_dates(period: int) -> None:
    dates = _dates(period + 1)
    facts = SectorMomentumCalculator.index_facts(
        [
            _fact(
                "BK1001.DC",
                item,
                close="100" if index == 0 else ("121" if index == period else "110"),
                pct="1",
            )
            for index, item in enumerate(dates)
        ]
    )

    result = SectorMomentumCalculator().calculate_for_date(
        sector_codes=("BK1001.DC",),
        open_dates=dates,
        target_date=dates[-1],
        period=period,
        fact_index=facts,
    )

    assert result[0].return_pct == Decimal("21.0000")


def test_multi_day_missing_intermediate_date_is_null_without_fill() -> None:
    dates = _dates(6)
    facts = SectorMomentumCalculator.index_facts(
        [
            _fact("BK1001.DC", item, close="100", pct="1")
            for item in dates
            if item != dates[3]
        ]
    )

    result = SectorMomentumCalculator().calculate_for_date(
        sector_codes=("BK1001.DC",),
        open_dates=dates,
        target_date=dates[-1],
        period=5,
        fact_index=facts,
    )

    assert result[0].return_pct is None
    assert result[0].missing_reason == "DATE_MISSING"


def test_non_positive_close_and_missing_pct_change_are_rejected() -> None:
    dates = _dates(2)
    fact_index = SectorMomentumCalculator.index_facts(
        [
            _fact("BK1001.DC", dates[0], close="0", pct="1"),
            _fact("BK1001.DC", dates[1], close="10", pct=None),
        ]
    )
    calculator = SectorMomentumCalculator()

    multi = calculator.calculate_for_date(
        sector_codes=("BK1001.DC",),
        open_dates=dates,
        target_date=dates[1],
        period=1,
        fact_index=fact_index,
    )
    assert multi[0].missing_reason == "PCT_CHANGE_MISSING"

    five_dates = _dates(6)
    negative_index = SectorMomentumCalculator.index_facts(
        [
            _fact(
                "BK1001.DC",
                item,
                close="0" if index == 2 else "10",
                pct="1",
            )
            for index, item in enumerate(five_dates)
        ]
    )
    result = calculator.calculate_for_date(
        sector_codes=("BK1001.DC",),
        open_dates=five_dates,
        target_date=five_dates[-1],
        period=5,
        fact_index=negative_index,
    )
    assert result[0].missing_reason == "CLOSE_NON_POSITIVE"


def test_duplicate_business_key_fails_closed() -> None:
    item = _dates(1)[0]
    fact = _fact("BK1001.DC", item, close="10", pct="1")
    with pytest.raises(DuplicateSectorFactError):
        SectorMomentumCalculator.index_facts([fact, fact])


def test_competition_rank_average_percentile_and_direction_sort_are_separate() -> None:
    item = _dates(1)[0]
    returns = (
        SectorReturnFact("BK1001.DC", item, Decimal("5"), "NONE"),
        SectorReturnFact("BK1002.DC", item, Decimal("3"), "NONE"),
        SectorReturnFact("BK1003.DC", item, Decimal("3"), "NONE"),
        SectorReturnFact("BK1004.DC", item, Decimal("1"), "NONE"),
        SectorReturnFact("BK1005.DC", item, None, "DATE_MISSING"),
    )

    ranked = SectorMomentumCalculator.rank_strength(returns)
    by_code = {row.sector_code: row for row in ranked}
    assert by_code["BK1001.DC"].strength_rank == 1
    assert by_code["BK1001.DC"].percentile == Decimal("100.0")
    assert by_code["BK1002.DC"].strength_rank == 2
    assert by_code["BK1002.DC"].percentile == Decimal("50.0")
    assert by_code["BK1003.DC"].strength_rank == 2
    assert by_code["BK1004.DC"].strength_rank == 4
    assert by_code["BK1004.DC"].percentile == Decimal("0.0")
    assert by_code["BK1005.DC"].strength_rank is None

    gainers = SectorMomentumCalculator.sort_ranking_rows(ranked, direction="GAINERS")
    losers = SectorMomentumCalculator.sort_ranking_rows(ranked, direction="LOSERS")
    assert [row.sector_code for row in gainers] == [
        "BK1001.DC",
        "BK1002.DC",
        "BK1003.DC",
        "BK1004.DC",
        "BK1005.DC",
    ]
    assert [row.sector_code for row in losers] == [
        "BK1004.DC",
        "BK1002.DC",
        "BK1003.DC",
        "BK1001.DC",
        "BK1005.DC",
    ]
    assert by_code["BK1001.DC"].strength_rank == 1


def test_single_calculable_row_has_percentile_one_hundred() -> None:
    item = _dates(1)[0]
    ranked = SectorMomentumCalculator.rank_strength(
        (SectorReturnFact("BK1001.DC", item, Decimal("1"), "NONE"),)
    )
    assert ranked[0].strength_rank == 1
    assert ranked[0].percentile == Decimal("100.0")


@pytest.mark.parametrize("period", [1, 5, 10, 20, 30])
def test_historical_grid_matches_individual_date_calculations(period: int) -> None:
    dates = _dates(40)
    codes = ("BK1001.DC", "BK1002.DC")
    facts = SectorMomentumCalculator.index_facts(
        [
            _fact(
                code,
                item,
                close=str(100 + code_index * 10 + date_index),
                pct=str(code_index + date_index / 10),
            )
            for code_index, code in enumerate(codes)
            for date_index, item in enumerate(dates)
            if not (code == "BK1002.DC" and item == dates[25])
        ]
    )
    target_dates = dates[-8:]
    calculator = SectorMomentumCalculator()

    grid = calculator.calculate_for_dates(
        sector_codes=codes,
        open_dates=dates,
        target_dates=target_dates,
        period=period,
        fact_index=facts,
    )

    assert grid == {
        item: calculator.calculate_for_date(
            sector_codes=codes,
            open_dates=dates,
            target_date=item,
            period=period,
            fact_index=facts,
        )
        for item in target_dates
    }
