from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_classifier import (
    SectorDualMomentumClassifier,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorRankFact,
    SectorReturnFact,
)


def _classify(
    value: str | None,
    *,
    percentile: str | None,
    calculable_count: int = 4,
    threshold: int = 80,
    reason: str = "NONE",
):
    decimal_value = Decimal(value) if value is not None else None
    decimal_percentile = Decimal(percentile) if percentile is not None else None
    return SectorDualMomentumClassifier.classify(
        return_fact=SectorReturnFact(
            sector_code="BK1001.DC",
            trade_date=date(2026, 8, 27),
            return_pct=decimal_value,
            missing_reason=reason,  # type: ignore[arg-type]
        ),
        rank_fact=SectorRankFact(
            sector_code="BK1001.DC",
            return_pct=decimal_value,
            strength_rank=1 if decimal_value is not None else None,
            percentile=decimal_percentile,
        ),
        calculable_count=calculable_count,
        leading_threshold=threshold,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("value", "percentile", "absolute", "relative", "qualification", "display"),
    (
        ("1", "80", "POSITIVE", "LEADING", "QUALIFIED", "QUALIFIED"),
        ("1", "79.9", "POSITIVE", "NOT_LEADING", "NOT_QUALIFIED", "UP_NOT_LEADING"),
        ("0", "80", "NOT_POSITIVE", "LEADING", "NOT_QUALIFIED", "NOT_UP_LEADING"),
        (
            "-1",
            "79.9",
            "NOT_POSITIVE",
            "NOT_LEADING",
            "NOT_QUALIFIED",
            "NOT_UP_NOT_LEADING",
        ),
    ),
)
def test_classifier_covers_four_complete_combinations_and_threshold_equality(
    value,
    percentile,
    absolute,
    relative,
    qualification,
    display,
) -> None:
    result = _classify(value, percentile=percentile)

    assert result.absolute_status == absolute
    assert result.relative_status == relative
    assert result.qualification_status == qualification
    assert result.coordinate_status == "PLOTTABLE"
    assert result.display_status == display
    assert result.missing_reason is None


@pytest.mark.parametrize("calculable_count", (1, 2))
def test_classifier_keeps_small_group_facts_but_never_qualifies(
    calculable_count: int,
) -> None:
    result = _classify(
        "5",
        percentile="100",
        calculable_count=calculable_count,
    )

    assert result.return_pct == Decimal("5")
    assert result.relative_status == "SAMPLE_INSUFFICIENT"
    assert result.qualification_status == "NOT_EVALUATED"
    assert result.coordinate_status == "PLOTTABLE"
    assert result.display_status == "SAMPLE_INSUFFICIENT"


def test_classifier_qualifies_at_minimum_group_size_three() -> None:
    result = _classify("5", percentile="100", calculable_count=3)
    assert result.qualification_status == "QUALIFIED"


def test_classifier_preserves_missing_reason_without_fabricating_coordinates() -> None:
    result = _classify(
        None,
        percentile=None,
        reason="HISTORY_INSUFFICIENT",
    )

    assert result.absolute_status == "UNAVAILABLE"
    assert result.relative_status == "UNAVAILABLE"
    assert result.qualification_status == "NOT_EVALUATED"
    assert result.coordinate_status == "UNAVAILABLE"
    assert result.display_status == "DATA_INSUFFICIENT"
    assert result.missing_reason == "HISTORY_INSUFFICIENT"


@pytest.mark.parametrize(
    ("return_fact", "rank_fact"),
    (
        (
            SectorReturnFact(
                "BK1001.DC",
                date(2026, 8, 27),
                Decimal("1"),
                "NONE",
            ),
            SectorRankFact("BK1002.DC", Decimal("1"), 1, Decimal("100")),
        ),
        (
            SectorReturnFact(
                "BK1001.DC",
                date(2026, 8, 27),
                Decimal("1"),
                "NONE",
            ),
            SectorRankFact("BK1001.DC", Decimal("2"), 1, Decimal("100")),
        ),
        (
            SectorReturnFact(
                "BK1001.DC",
                date(2026, 8, 27),
                None,
                "NONE",
            ),
            SectorRankFact("BK1001.DC", None, None, None),
        ),
    ),
)
def test_classifier_rejects_misaligned_or_internally_invalid_facts(
    return_fact: SectorReturnFact,
    rank_fact: SectorRankFact,
) -> None:
    with pytest.raises(ValueError):
        SectorDualMomentumClassifier.classify(
            return_fact=return_fact,
            rank_fact=rank_fact,
            calculable_count=3,
            leading_threshold=80,
        )
