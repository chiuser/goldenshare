from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, cast

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    MissingReason,
    SectorScopeInvalidError,
)


SectorDualMomentumPeriod = Literal[5, 10, 20, 30]
SectorDualMomentumLeadingThreshold = Literal[70, 80, 90]
SectorDualMomentumAbsoluteStatus = Literal[
    "POSITIVE",
    "NOT_POSITIVE",
    "UNAVAILABLE",
]
SectorDualMomentumRelativeStatus = Literal[
    "LEADING",
    "NOT_LEADING",
    "SAMPLE_INSUFFICIENT",
    "UNAVAILABLE",
]
SectorDualMomentumQualificationStatus = Literal[
    "QUALIFIED",
    "NOT_QUALIFIED",
    "NOT_EVALUATED",
]
SectorDualMomentumCoordinateStatus = Literal["PLOTTABLE", "UNAVAILABLE"]
SectorDualMomentumDisplayStatus = Literal[
    "QUALIFIED",
    "UP_NOT_LEADING",
    "NOT_UP_LEADING",
    "NOT_UP_NOT_LEADING",
    "SAMPLE_INSUFFICIENT",
    "DATA_INSUFFICIENT",
]

FORMULA_KEY = "sector-dual-momentum"
FORMULA_VERSION = 1
BASIS_FORMULA_KEY = "sector-cross-sectional-momentum"
BASIS_FORMULA_VERSION = 1
MINIMUM_GROUP_SIZE = 3
ALLOWED_PERIODS: tuple[SectorDualMomentumPeriod, ...] = (5, 10, 20, 30)
ALLOWED_LEADING_THRESHOLDS: tuple[SectorDualMomentumLeadingThreshold, ...] = (
    70,
    80,
    90,
)


class SectorMomentumFactVersionMismatchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SectorDualMomentumClassification:
    sector_code: str
    return_pct: Decimal | None
    strength_rank: int | None
    percentile: Decimal | None
    absolute_status: SectorDualMomentumAbsoluteStatus
    relative_status: SectorDualMomentumRelativeStatus
    qualification_status: SectorDualMomentumQualificationStatus
    coordinate_status: SectorDualMomentumCoordinateStatus
    display_status: SectorDualMomentumDisplayStatus
    missing_reason: MissingReason | None


def parse_dual_momentum_period(value: int) -> SectorDualMomentumPeriod:
    if value not in ALLOWED_PERIODS:
        raise SectorScopeInvalidError(f"period 不支持：{value}")
    return cast(SectorDualMomentumPeriod, value)


def parse_dual_momentum_leading_threshold(
    value: int,
) -> SectorDualMomentumLeadingThreshold:
    if value not in ALLOWED_LEADING_THRESHOLDS:
        raise SectorScopeInvalidError(f"leadingThreshold 不支持：{value}")
    return cast(SectorDualMomentumLeadingThreshold, value)
