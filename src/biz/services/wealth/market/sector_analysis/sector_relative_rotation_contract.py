from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    MissingReason,
    SectorRankFact,
    SectorReturnFact,
    SectorScopeInvalidError,
)


SectorRelativeRotationPeriod = Literal[5, 10, 20, 30]
SectorRelativeRotationTrailLength = Literal[20, 30, 60]
SectorRelativeRotationStatus = Literal[
    "LEADING_IMPROVING",
    "WEAK_IMPROVING",
    "STRONG_NOT_IMPROVING",
    "WEAK_NOT_IMPROVING",
    "SAMPLE_INSUFFICIENT",
    "DATA_INSUFFICIENT",
]
SectorRelativeCoordinateStatus = Literal["PLOTTABLE", "UNAVAILABLE"]
SectorRelativeGroupInterpretation = Literal["QUADRANT", "SAMPLE_INSUFFICIENT"]

FORMULA_KEY = "sector-relative-rotation"
FORMULA_VERSION = 1
BASIS_FORMULA_KEY = "sector-cross-sectional-momentum"
BASIS_FORMULA_VERSION = 1
IMPROVEMENT_LOOKBACK_DAYS = 5
MINIMUM_GROUP_SIZE = 3
X_DOMAIN = (Decimal("0.0"), Decimal("100.0"))
X_SPLIT = Decimal("50.0")
Y_SPLIT = Decimal("0.0")
ALLOWED_PERIODS: tuple[SectorRelativeRotationPeriod, ...] = (5, 10, 20, 30)
ALLOWED_TRAIL_LENGTHS: tuple[SectorRelativeRotationTrailLength, ...] = (20, 30, 60)


@dataclass(frozen=True, slots=True)
class SectorRelativeRotationRankSlice:
    trade_date: date
    returns: tuple[SectorReturnFact, ...]
    ranked: tuple[SectorRankFact, ...]
    calculable_count: int

    def __post_init__(self) -> None:
        if len(self.returns) != len(self.ranked):
            raise ValueError(
                "relative-rotation return and rank facts must have equal length"
            )
        return_codes = [item.sector_code for item in self.returns]
        rank_codes = [item.sector_code for item in self.ranked]
        if len(return_codes) != len(set(return_codes)):
            raise ValueError(
                "relative-rotation return facts must have unique sector codes"
            )
        if len(rank_codes) != len(set(rank_codes)):
            raise ValueError(
                "relative-rotation rank facts must have unique sector codes"
            )
        if return_codes != rank_codes:
            raise ValueError(
                "relative-rotation return and rank facts must share code order"
            )

        calculable_count = 0
        for return_fact, rank_fact in zip(self.returns, self.ranked, strict=True):
            calculable_count += int(
                _validate_rank_pair(
                    trade_date=self.trade_date,
                    return_fact=return_fact,
                    rank_fact=rank_fact,
                )
            )
        if self.calculable_count != calculable_count:
            raise ValueError(
                "relative-rotation calculable count must match its rank facts"
            )


@dataclass(frozen=True, slots=True)
class SectorRelativeRotationSelectedRankSlice:
    trade_date: date
    return_fact: SectorReturnFact
    rank_fact: SectorRankFact
    calculable_count: int

    def __post_init__(self) -> None:
        selected_is_calculable = _validate_rank_pair(
            trade_date=self.trade_date,
            return_fact=self.return_fact,
            rank_fact=self.rank_fact,
        )
        if self.calculable_count < 0:
            raise ValueError("relative-rotation calculable count cannot be negative")
        if selected_is_calculable and self.calculable_count < 1:
            raise ValueError(
                "calculable selected rank requires a positive comparison count"
            )


@dataclass(frozen=True, slots=True)
class SectorRelativeRotationPointFact:
    sector_code: str
    trade_date: date
    return_pct: Decimal | None
    strength_rank: int | None
    percentile: Decimal | None
    percentile_delta_5d: Decimal | None
    current_calculable_count: int
    comparison_calculable_count: int
    rotation_status: SectorRelativeRotationStatus
    coordinate_status: SectorRelativeCoordinateStatus
    current_missing_reason: MissingReason | None
    comparison_missing_reason: MissingReason | None


def parse_relative_rotation_period(value: int) -> SectorRelativeRotationPeriod:
    if type(value) is not int or value not in ALLOWED_PERIODS:
        raise SectorScopeInvalidError(f"period 不支持：{value}")
    return cast(SectorRelativeRotationPeriod, value)


def parse_relative_rotation_trail_length(
    value: int,
) -> SectorRelativeRotationTrailLength:
    if type(value) is not int or value not in ALLOWED_TRAIL_LENGTHS:
        raise SectorScopeInvalidError(f"trailLength 不支持：{value}")
    return cast(SectorRelativeRotationTrailLength, value)


def make_rank_slice(
    trade_date: date,
    returns: tuple[SectorReturnFact, ...],
    ranked: tuple[SectorRankFact, ...],
) -> SectorRelativeRotationRankSlice:
    return SectorRelativeRotationRankSlice(
        trade_date=trade_date,
        returns=returns,
        ranked=ranked,
        calculable_count=sum(item.percentile is not None for item in ranked),
    )


def make_selected_rank_slice(
    trade_date: date,
    return_fact: SectorReturnFact,
    rank_fact: SectorRankFact,
    calculable_count: int,
) -> SectorRelativeRotationSelectedRankSlice:
    return SectorRelativeRotationSelectedRankSlice(
        trade_date=trade_date,
        return_fact=return_fact,
        rank_fact=rank_fact,
        calculable_count=calculable_count,
    )


def _validate_rank_pair(
    *,
    trade_date: date,
    return_fact: SectorReturnFact,
    rank_fact: SectorRankFact,
) -> bool:
    if return_fact.trade_date != trade_date:
        raise ValueError("relative-rotation return fact date must match its slice")
    if return_fact.sector_code != rank_fact.sector_code:
        raise ValueError("relative-rotation return and rank codes must match")
    if return_fact.return_pct != rank_fact.return_pct:
        raise ValueError("relative-rotation return and rank values must match")
    rank_values = (
        rank_fact.return_pct,
        rank_fact.strength_rank,
        rank_fact.percentile,
    )
    if any(value is None for value in rank_values) and not all(
        value is None for value in rank_values
    ):
        raise ValueError("relative-rotation rank values must be null together")
    if return_fact.return_pct is None:
        if return_fact.missing_reason == "NONE":
            raise ValueError("missing relative-rotation return requires a reason")
        return False
    if not return_fact.return_pct.is_finite():
        raise ValueError("relative-rotation returns must be finite")
    if return_fact.missing_reason != "NONE":
        raise ValueError("calculable relative-rotation return cannot be missing")
    assert rank_fact.percentile is not None
    if (
        not rank_fact.percentile.is_finite()
        or rank_fact.percentile < X_DOMAIN[0]
        or rank_fact.percentile > X_DOMAIN[1]
    ):
        raise ValueError("relative-rotation percentile is outside 0..100")
    return True
