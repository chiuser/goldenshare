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
    SectorRelativeRotationSelectedRankSlice,
    make_rank_slice,
    make_selected_rank_slice,
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


def _snapshot(
    *,
    comparison: SectorRelativeRotationRankSlice,
    current: SectorRelativeRotationRankSlice,
):
    return SectorRelativeRotationCalculator.calculate_current_snapshot(
        sector_codes=CODES,
        open_dates=OPEN_DATES,
        current_date=CURRENT_DATE,
        current_slice=current,
        comparison_slice=comparison,
    )


def _selected_slice(
    rank_slice: SectorRelativeRotationRankSlice,
    *,
    sector_code: str = CODES[0],
) -> SectorRelativeRotationSelectedRankSlice:
    index = next(
        index
        for index, item in enumerate(rank_slice.ranked)
        if item.sector_code == sector_code
    )
    return make_selected_rank_slice(
        rank_slice.trade_date,
        rank_slice.returns[index],
        rank_slice.ranked[index],
        rank_slice.calculable_count,
    )


def _legacy_grid(
    *,
    display_dates: tuple[date, ...],
    rank_slices: dict[date, SectorRelativeRotationRankSlice],
):
    """Test-only oracle matching the removed full historical grid orchestration."""
    date_indexes = {item: index for index, item in enumerate(OPEN_DATES)}
    return {
        display_date: tuple(
            SectorRelativeRotationCalculator._calculate_point(  # noqa: SLF001
                sector_code=sector_code,
                trade_date=display_date,
                current=(
                    rank_slices[display_date].returns[index],
                    rank_slices[display_date].ranked[index],
                ),
                comparison=(
                    rank_slices[OPEN_DATES[date_indexes[display_date] - 5]].returns[
                        index
                    ],
                    rank_slices[OPEN_DATES[date_indexes[display_date] - 5]].ranked[
                        index
                    ],
                ),
                current_count=rank_slices[display_date].calculable_count,
                comparison_count=rank_slices[
                    OPEN_DATES[date_indexes[display_date] - 5]
                ].calculable_count,
            )
            for index, sector_code in enumerate(CODES)
        )
        for display_date in display_dates
    }


def test_calculator_covers_four_quadrants_and_frozen_boundaries() -> None:
    points = _snapshot(
        comparison=_slice(
            COMPARISON_DATE,
            percentiles=("50", "30", "60", "50"),
        ),
        current=_slice(
            CURRENT_DATE,
            percentiles=("60", "40", "60", "40"),
        ),
    )

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
    points = _snapshot(
        comparison=_slice(
            COMPARISON_DATE,
            percentiles=("100", "0", None, None),
        ),
        current=_slice(
            CURRENT_DATE,
            percentiles=("100", "50", "0", None),
        ),
    )

    assert points[0].rotation_status == "SAMPLE_INSUFFICIENT"
    assert points[0].coordinate_status == "PLOTTABLE"
    assert points[1].rotation_status == "SAMPLE_INSUFFICIENT"
    assert points[2].rotation_status == "DATA_INSUFFICIENT"
    assert points[2].comparison_missing_reason == "DATE_MISSING"


def test_current_and_comparison_missing_reasons_are_preserved_without_coordinates() -> (
    None
):
    points = _snapshot(
        comparison=_slice(
            COMPARISON_DATE,
            percentiles=("100", None, "50", "0"),
            reasons=("NONE", "CLOSE_NON_POSITIVE", "NONE", "NONE"),
        ),
        current=_slice(
            CURRENT_DATE,
            percentiles=(None, "100", "50", "0"),
            reasons=("CLOSE_MISSING", "NONE", "NONE", "NONE"),
        ),
    )

    current_missing, comparison_missing = points[:2]
    assert current_missing.current_missing_reason == "CLOSE_MISSING"
    assert current_missing.percentile is None
    assert current_missing.percentile_delta_5d is None
    assert current_missing.coordinate_status == "UNAVAILABLE"
    assert comparison_missing.current_missing_reason is None
    assert comparison_missing.comparison_missing_reason == "CLOSE_NON_POSITIVE"
    assert comparison_missing.percentile == Decimal("100")
    assert comparison_missing.percentile_delta_5d is None


def test_canonical_sort_keeps_plottable_then_x_only_then_missing() -> None:
    points = _snapshot(
        comparison=_slice(
            COMPARISON_DATE,
            percentiles=("60", None, "70", "0"),
        ),
        current=_slice(
            CURRENT_DATE,
            percentiles=("80", "90", None, "80"),
        ),
    )

    sorted_rows = SectorRelativeRotationCalculator.canonical_sort(points)
    assert [item.sector_code for item in sorted_rows] == [
        "BK1004.DC",
        "BK1001.DC",
        "BK1002.DC",
        "BK1003.DC",
    ]


def test_future_slice_cannot_change_an_existing_coordinate() -> None:
    slices = {
        COMPARISON_DATE: _selected_slice(
            _slice(
                COMPARISON_DATE,
                percentiles=("50", "30", "60", "50"),
            )
        ),
        CURRENT_DATE: _selected_slice(
            _slice(
                CURRENT_DATE,
                percentiles=("60", "40", "60", "40"),
            )
        ),
    }
    baseline = SectorRelativeRotationCalculator.calculate_selected_trail(
        selected_sector_code=CODES[0],
        open_dates=OPEN_DATES,
        display_dates=(CURRENT_DATE,),
        rank_slices=slices,
    )
    with_future = SectorRelativeRotationCalculator.calculate_selected_trail(
        selected_sector_code=CODES[0],
        open_dates=OPEN_DATES,
        display_dates=(CURRENT_DATE,),
        rank_slices={
            **slices,
            OPEN_DATES[6]: _selected_slice(
                _slice(
                    OPEN_DATES[6],
                    percentiles=("0", "100", "0", "100"),
                )
            ),
        },
    )

    assert with_future == baseline


def test_selected_trail_preserves_date_slots_and_uses_one_sector_only() -> None:
    final_date = OPEN_DATES[10]
    slices = {
        COMPARISON_DATE: _selected_slice(
            _slice(COMPARISON_DATE, percentiles=("50", "30", "60", "50"))
        ),
        CURRENT_DATE: _selected_slice(
            _slice(CURRENT_DATE, percentiles=("60", "40", "60", "40"))
        ),
        final_date: _selected_slice(
            _slice(final_date, percentiles=("90", "30", "60", "50"))
        ),
    }

    points = SectorRelativeRotationCalculator.calculate_selected_trail(
        selected_sector_code=CODES[0],
        open_dates=OPEN_DATES,
        display_dates=(CURRENT_DATE, final_date),
        rank_slices=slices,
    )

    assert [item.trade_date for item in points] == [CURRENT_DATE, final_date]
    assert [item.sector_code for item in points] == [CODES[0], CODES[0]]
    assert [item.percentile_delta_5d for item in points] == [
        Decimal("10.0"),
        Decimal("30.0"),
    ]


@pytest.mark.parametrize("selected_sector_code", CODES)
def test_sparse_snapshot_and_trail_exactly_match_removed_full_grid_oracle(
    selected_sector_code: str,
) -> None:
    final_date = OPEN_DATES[10]
    display_dates = (CURRENT_DATE, final_date)
    full_slices = {
        COMPARISON_DATE: _slice(
            COMPARISON_DATE,
            percentiles=("50", "30", "60", None),
        ),
        CURRENT_DATE: _slice(
            CURRENT_DATE,
            percentiles=("60", "40", "60", "40"),
        ),
        final_date: _slice(
            final_date,
            percentiles=("90", "40", None, "40"),
        ),
    }
    legacy = _legacy_grid(
        display_dates=display_dates,
        rank_slices=full_slices,
    )

    current = SectorRelativeRotationCalculator.calculate_current_snapshot(
        sector_codes=CODES,
        open_dates=OPEN_DATES,
        current_date=final_date,
        current_slice=full_slices[final_date],
        comparison_slice=full_slices[CURRENT_DATE],
    )
    selected_slices = {
        item: _selected_slice(rank_slice, sector_code=selected_sector_code)
        for item, rank_slice in full_slices.items()
    }
    trail = SectorRelativeRotationCalculator.calculate_selected_trail(
        selected_sector_code=selected_sector_code,
        open_dates=OPEN_DATES,
        display_dates=display_dates,
        rank_slices=selected_slices,
    )

    assert current == legacy[final_date]
    assert trail == tuple(
        next(
            point
            for point in legacy[display_date]
            if point.sector_code == selected_sector_code
        )
        for display_date in display_dates
    )


@pytest.mark.parametrize(
    "mutation",
    ("length", "duplicate", "order", "value", "reason", "date", "count"),
)
def test_rank_slice_rejects_every_return_rank_alignment_violation(
    mutation: str,
) -> None:
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


@pytest.mark.parametrize(
    "mutation",
    ("code", "value", "reason", "date", "count"),
)
def test_selected_rank_slice_rejects_alignment_violations(mutation: str) -> None:
    full = _slice(CURRENT_DATE, percentiles=("100", "66.7", "33.3", "0"))
    return_fact = full.returns[0]
    rank_fact = full.ranked[0]
    calculable_count = full.calculable_count
    if mutation == "code":
        rank_fact = SectorRankFact(
            CODES[1],
            rank_fact.return_pct,
            rank_fact.strength_rank,
            rank_fact.percentile,
        )
    elif mutation == "value":
        rank_fact = SectorRankFact(
            rank_fact.sector_code,
            Decimal("999"),
            rank_fact.strength_rank,
            rank_fact.percentile,
        )
    elif mutation == "reason":
        return_fact = SectorReturnFact(
            return_fact.sector_code,
            return_fact.trade_date,
            return_fact.return_pct,
            "DATE_MISSING",
        )
    elif mutation == "date":
        return_fact = SectorReturnFact(
            return_fact.sector_code,
            COMPARISON_DATE,
            return_fact.return_pct,
            "NONE",
        )
    else:
        calculable_count = 0

    with pytest.raises(ValueError):
        SectorRelativeRotationSelectedRankSlice(
            trade_date=CURRENT_DATE,
            return_fact=return_fact,
            rank_fact=rank_fact,
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
