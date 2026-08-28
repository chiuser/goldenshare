from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorRankFact,
    SectorReturnFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_calculator import (
    SectorRelativeRotationCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_contract import (
    SectorRelativeRotationRankSlice,
    make_rank_slice,
    parse_relative_rotation_period,
    parse_relative_rotation_trail_length,
)


OPEN_DATES = tuple(date(2026, 8, 1) + timedelta(days=index) for index in range(11))
COMPARISON_DATE = OPEN_DATES[0]
CURRENT_DATE = OPEN_DATES[5]
CODES = ("BK1001.DC", "BK1002.DC", "BK1003.DC", "BK1004.DC")


def _slice(
    trade_date: date,
    *,
    percentiles: tuple[str | None, ...],
    reasons: tuple[str, ...] | None = None,
) -> SectorRelativeRotationRankSlice:
    missing_reasons = reasons or tuple(
        "NONE" if value is not None else "DATE_MISSING" for value in percentiles
    )
    returns = tuple(
        SectorReturnFact(
            sector_code=code,
            trade_date=trade_date,
            return_pct=Decimal(str(index)) if percentile is not None else None,
            missing_reason=reason,  # type: ignore[arg-type]
        )
        for index, (code, percentile, reason) in enumerate(
            zip(CODES, percentiles, missing_reasons, strict=True),
            start=1,
        )
    )
    ranked = tuple(
        SectorRankFact(
            sector_code=return_fact.sector_code,
            return_pct=return_fact.return_pct,
            strength_rank=index if percentile is not None else None,
            percentile=Decimal(percentile) if percentile is not None else None,
        )
        for index, (return_fact, percentile) in enumerate(
            zip(returns, percentiles, strict=True),
            start=1,
        )
    )
    return make_rank_slice(trade_date, returns, ranked)


def test_calculator_covers_four_quadrants_and_frozen_boundaries() -> None:
    grid = SectorRelativeRotationCalculator.calculate_grid(
        sector_codes=CODES,
        open_dates=OPEN_DATES,
        display_dates=(CURRENT_DATE,),
        rank_slices={
            COMPARISON_DATE: _slice(
                COMPARISON_DATE,
                percentiles=("50", "30", "60", "50"),
            ),
            CURRENT_DATE: _slice(
                CURRENT_DATE,
                percentiles=("60", "40", "60", "40"),
            ),
        },
    )

    points = grid[CURRENT_DATE]
    assert [item.percentile_delta_5d for item in points] == [
        Decimal("10.0"),
        Decimal("10.0"),
        Decimal("0.0"),
        Decimal("-10.0"),
    ]
    assert [item.rotation_status for item in points] == [
        "LEADING_IMPROVING",
        "WEAK_IMPROVING",
        "STRONG_NOT_IMPROVING",
        "WEAK_NOT_IMPROVING",
    ]
    assert all(item.coordinate_status == "PLOTTABLE" for item in points)


def test_small_group_keeps_coordinates_but_never_assigns_a_quadrant() -> None:
    grid = SectorRelativeRotationCalculator.calculate_grid(
        sector_codes=CODES,
        open_dates=OPEN_DATES,
        display_dates=(CURRENT_DATE,),
        rank_slices={
            COMPARISON_DATE: _slice(
                COMPARISON_DATE,
                percentiles=("100", "0", None, None),
            ),
            CURRENT_DATE: _slice(
                CURRENT_DATE,
                percentiles=("100", "50", "0", None),
            ),
        },
    )

    points = grid[CURRENT_DATE]
    assert points[0].rotation_status == "SAMPLE_INSUFFICIENT"
    assert points[0].coordinate_status == "PLOTTABLE"
    assert points[1].rotation_status == "SAMPLE_INSUFFICIENT"
    assert points[2].rotation_status == "DATA_INSUFFICIENT"
    assert points[2].comparison_missing_reason == "DATE_MISSING"


def test_current_and_comparison_missing_reasons_are_preserved_without_coordinates() -> None:
    grid = SectorRelativeRotationCalculator.calculate_grid(
        sector_codes=CODES,
        open_dates=OPEN_DATES,
        display_dates=(CURRENT_DATE,),
        rank_slices={
            COMPARISON_DATE: _slice(
                COMPARISON_DATE,
                percentiles=("100", None, "50", "0"),
                reasons=("NONE", "CLOSE_NON_POSITIVE", "NONE", "NONE"),
            ),
            CURRENT_DATE: _slice(
                CURRENT_DATE,
                percentiles=(None, "100", "50", "0"),
                reasons=("CLOSE_MISSING", "NONE", "NONE", "NONE"),
            ),
        },
    )

    current_missing, comparison_missing = grid[CURRENT_DATE][:2]
    assert current_missing.current_missing_reason == "CLOSE_MISSING"
    assert current_missing.percentile is None
    assert current_missing.percentile_delta_5d is None
    assert current_missing.coordinate_status == "UNAVAILABLE"
    assert comparison_missing.current_missing_reason is None
    assert comparison_missing.comparison_missing_reason == "CLOSE_NON_POSITIVE"
    assert comparison_missing.percentile == Decimal("100")
    assert comparison_missing.percentile_delta_5d is None


def test_canonical_sort_keeps_plottable_then_x_only_then_missing() -> None:
    grid = SectorRelativeRotationCalculator.calculate_grid(
        sector_codes=CODES,
        open_dates=OPEN_DATES,
        display_dates=(CURRENT_DATE,),
        rank_slices={
            COMPARISON_DATE: _slice(
                COMPARISON_DATE,
                percentiles=("60", None, "70", "0"),
            ),
            CURRENT_DATE: _slice(
                CURRENT_DATE,
                percentiles=("80", "90", None, "80"),
            ),
        },
    )

    sorted_rows = SectorRelativeRotationCalculator.canonical_sort(grid[CURRENT_DATE])
    assert [item.sector_code for item in sorted_rows] == [
        "BK1004.DC",
        "BK1001.DC",
        "BK1002.DC",
        "BK1003.DC",
    ]


def test_future_slice_cannot_change_an_existing_coordinate() -> None:
    slices = {
        COMPARISON_DATE: _slice(
            COMPARISON_DATE,
            percentiles=("50", "30", "60", "50"),
        ),
        CURRENT_DATE: _slice(
            CURRENT_DATE,
            percentiles=("60", "40", "60", "40"),
        ),
    }
    baseline = SectorRelativeRotationCalculator.calculate_grid(
        sector_codes=CODES,
        open_dates=OPEN_DATES,
        display_dates=(CURRENT_DATE,),
        rank_slices=slices,
    )
    with_future = SectorRelativeRotationCalculator.calculate_grid(
        sector_codes=CODES,
        open_dates=OPEN_DATES,
        display_dates=(CURRENT_DATE,),
        rank_slices={
            **slices,
            OPEN_DATES[6]: _slice(
                OPEN_DATES[6],
                percentiles=("0", "100", "0", "100"),
            ),
        },
    )

    assert with_future == baseline


@pytest.mark.parametrize(
    "mutation",
    ("length", "duplicate", "order", "value", "reason", "date", "count"),
)
def test_rank_slice_rejects_every_return_rank_alignment_violation(mutation: str) -> None:
    valid = _slice(CURRENT_DATE, percentiles=("100", "66.7", "33.3", "0"))
    returns = list(valid.returns)
    ranked = list(valid.ranked)
    calculable_count = valid.calculable_count
    if mutation == "length":
        ranked.pop()
    elif mutation == "duplicate":
        returns[1] = SectorReturnFact(
            returns[0].sector_code,
            CURRENT_DATE,
            returns[1].return_pct,
            "NONE",
        )
    elif mutation == "order":
        ranked[0], ranked[1] = ranked[1], ranked[0]
    elif mutation == "value":
        ranked[0] = SectorRankFact(
            ranked[0].sector_code,
            Decimal("999"),
            ranked[0].strength_rank,
            ranked[0].percentile,
        )
    elif mutation == "reason":
        returns[0] = SectorReturnFact(
            returns[0].sector_code,
            CURRENT_DATE,
            returns[0].return_pct,
            "DATE_MISSING",
        )
    elif mutation == "date":
        returns[0] = SectorReturnFact(
            returns[0].sector_code,
            COMPARISON_DATE,
            returns[0].return_pct,
            "NONE",
        )
    else:
        calculable_count -= 1

    with pytest.raises(ValueError):
        SectorRelativeRotationRankSlice(
            trade_date=CURRENT_DATE,
            returns=tuple(returns),
            ranked=tuple(ranked),
            calculable_count=calculable_count,
        )


@pytest.mark.parametrize("value", (5, 10, 20, 30))
def test_period_parser_accepts_only_frozen_integer_values(value: int) -> None:
    assert parse_relative_rotation_period(value) == value


@pytest.mark.parametrize("value", (20, 30, 60))
def test_trail_parser_accepts_only_frozen_integer_values(value: int) -> None:
    assert parse_relative_rotation_trail_length(value) == value


@pytest.mark.parametrize("value", (True, 1, 90, 20.0, "20"))
def test_contract_rejects_bool_one_and_non_frozen_values(value) -> None:
    with pytest.raises(ValueError):
        parse_relative_rotation_period(value)
    with pytest.raises(ValueError):
        parse_relative_rotation_trail_length(value)
