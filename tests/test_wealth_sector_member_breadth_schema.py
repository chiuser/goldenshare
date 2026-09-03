from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.biz.schemas.wealth.market.sector_member_breadth import (
    SectorMemberBreadthCompositionDto,
)


def _composition(**changes):
    values = {
        "metric": "MEMBER_COUNT",
        "sourceCount": 6,
        "calculableCount": 6,
        "coveragePct": 100,
        "eligible": True,
        "positiveCount": 2,
        "neutralCount": 2,
        "negativeCount": 2,
        "positivePct": 33.3333,
        "neutralPct": 33.3333,
        "negativePct": 33.3333,
        "reasonCodes": [],
    }
    values.update(changes)
    return SectorMemberBreadthCompositionDto(**values)


@pytest.mark.parametrize("metric", ["MEMBER_COUNT", "TURNOVER", "MA_POSITION"])
@pytest.mark.parametrize(
    ("counts", "percentages"),
    [
        ((2, 2, 2), (33.3333, 33.3333, 33.3333)),
        ((1, 1, 4), (16.6667, 16.6667, 66.6667)),
        ((2, 2, 2), (100 / 3, 100 / 3, 100 / 3)),
        ((6, 0, 0), (100.0, 0.0, 0.0)),
    ],
)
def test_composition_accepts_normal_rounding_without_rewriting(metric, counts, percentages):
    result = _composition(
        metric=metric,
        positiveCount=counts[0],
        neutralCount=counts[1],
        negativeCount=counts[2],
        positivePct=percentages[0],
        neutralPct=percentages[1],
        negativePct=percentages[2],
    )
    assert (result.positivePct, result.neutralPct, result.negativePct) == percentages
    assert SectorMemberBreadthCompositionDto.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    "percentages",
    [(33.3332, 33.3333, 33.3333), (33.3334, 33.3334, 33.3334)],
)
def test_composition_rejects_sum_beyond_normal_rounding(percentages):
    with pytest.raises(ValidationError, match="percentages must sum to 100"):
        _composition(
            positivePct=percentages[0],
            neutralPct=percentages[1],
            negativePct=percentages[2],
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"positivePct": float("nan")},
        {"positivePct": float("inf")},
        {"positivePct": -0.00001},
        {"positivePct": 100.00001},
        {"positivePct": None},
        {"positiveCount": 3},
        {"sourceCount": 5},
    ],
)
def test_rounding_tolerance_does_not_relax_other_invariants(changes):
    with pytest.raises(ValidationError):
        _composition(**changes)


def test_unavailable_composition_stays_null():
    result = _composition(
        calculableCount=0,
        coveragePct=0,
        eligible=False,
        positiveCount=0,
        neutralCount=0,
        negativeCount=0,
        positivePct=None,
        neutralPct=None,
        negativePct=None,
        reasonCodes=["MARKET_ROW_MISSING"],
    )
    assert (result.positivePct, result.neutralPct, result.negativePct) == (None, None, None)
