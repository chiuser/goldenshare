from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, cast

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorScopeInvalidError,
)


SectorPriceVolumePeriod = Literal[1, 5, 10, 20, 30]
SectorPriceVolumeHistoryRange = Literal[20, 30, 60]
SectorPriceVolumeState = Literal["JOINT", "PRICE_ONLY", "AMOUNT_ONLY", "NEUTRAL"]
SectorPriceVolumeSortField = Literal["PRICE_MOMENTUM", "AMOUNT_ACTIVITY"]
SectorPriceVolumeDefaultStatus = Literal["READY", "DELAYED", "EMPTY"]

FORMULA_KEY = "sector-price-volume-distribution"
FORMULA_VERSION = 1
DATE_COVERAGE_BASIS = "INDUSTRY_DAILY"
ALLOWED_PERIODS: tuple[SectorPriceVolumePeriod, ...] = (1, 5, 10, 20, 30)
ALLOWED_HISTORY_RANGES: tuple[SectorPriceVolumeHistoryRange, ...] = (20, 30, 60)
ALLOWED_STATES: tuple[SectorPriceVolumeState, ...] = (
    "JOINT",
    "PRICE_ONLY",
    "AMOUNT_ONLY",
    "NEUTRAL",
)


class SectorPriceVolumeMissingReason(StrEnum):
    HISTORY_INSUFFICIENT = "HISTORY_INSUFFICIENT"
    DATE_MISSING = "DATE_MISSING"
    PCT_CHANGE_MISSING = "PCT_CHANGE_MISSING"
    CLOSE_MISSING = "CLOSE_MISSING"
    CLOSE_NON_POSITIVE = "CLOSE_NON_POSITIVE"
    AMOUNT_MISSING = "AMOUNT_MISSING"
    AMOUNT_NON_FINITE = "AMOUNT_NON_FINITE"
    AMOUNT_NEGATIVE = "AMOUNT_NEGATIVE"
    PRIOR_AMOUNT_AVERAGE_NON_POSITIVE = "PRIOR_AMOUNT_AVERAGE_NON_POSITIVE"


class SectorPriceVolumeFactMismatchError(RuntimeError):
    pass


def _validate_decimal(value: Decimal | None, *, field_name: str) -> None:
    if value is not None and not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal or None")


@dataclass(frozen=True, slots=True)
class SectorPriceVolumeDailyFact:
    sector_code: str
    trade_date: date
    close: Decimal | None
    pct_change: Decimal | None
    amount: Decimal | None

    def __post_init__(self) -> None:
        if not self.sector_code:
            raise ValueError("sector_code must be non-empty")
        if not isinstance(self.trade_date, date):
            raise TypeError("trade_date must be a date")
        _validate_decimal(self.close, field_name="close")
        _validate_decimal(self.pct_change, field_name="pct_change")
        _validate_decimal(self.amount, field_name="amount")


@dataclass(frozen=True, slots=True)
class SectorPriceVolumeMetricFact:
    sector_code: str
    trade_date: date
    price_momentum_pct: Decimal | None
    amount_activity_pct: Decimal | None
    price_missing_reason: SectorPriceVolumeMissingReason | None
    amount_missing_reason: SectorPriceVolumeMissingReason | None

    def __post_init__(self) -> None:
        _validate_decimal(self.price_momentum_pct, field_name="price_momentum_pct")
        _validate_decimal(self.amount_activity_pct, field_name="amount_activity_pct")
        if (self.price_momentum_pct is None) == (self.price_missing_reason is None):
            raise ValueError("price value and missing reason must be complementary")
        if (self.amount_activity_pct is None) == (self.amount_missing_reason is None):
            raise ValueError("amount value and missing reason must be complementary")
        if self.price_momentum_pct is not None and not self.price_momentum_pct.is_finite():
            raise ValueError("price_momentum_pct must be finite")
        if self.amount_activity_pct is not None and not self.amount_activity_pct.is_finite():
            raise ValueError("amount_activity_pct must be finite")


@dataclass(frozen=True, slots=True)
class SectorPriceVolumeRankedFact:
    metric: SectorPriceVolumeMetricFact
    price_rank: int | None
    price_rankable_count: int
    amount_rank: int | None
    amount_rankable_count: int
    state: SectorPriceVolumeState | None

    def __post_init__(self) -> None:
        if self.price_rankable_count < 0 or self.amount_rankable_count < 0:
            raise ValueError("rankable counts cannot be negative")
        if self.metric.price_momentum_pct is None:
            if self.price_rank is not None:
                raise ValueError("missing price cannot carry a rank")
        elif self.price_rank is None or not 1 <= self.price_rank <= self.price_rankable_count:
            raise ValueError("price rank is inconsistent with its value")
        if self.metric.amount_activity_pct is None:
            if self.amount_rank is not None:
                raise ValueError("missing amount cannot carry a rank")
        elif self.amount_rank is None or not 1 <= self.amount_rank <= self.amount_rankable_count:
            raise ValueError("amount rank is inconsistent with its value")
        both_present = (
            self.metric.price_momentum_pct is not None
            and self.metric.amount_activity_pct is not None
        )
        if both_present != (self.state is not None):
            raise ValueError("state requires both coordinates and only both coordinates")


def parse_price_volume_period(value: int) -> SectorPriceVolumePeriod:
    if value not in ALLOWED_PERIODS:
        raise SectorScopeInvalidError(f"period 不支持：{value}")
    return cast(SectorPriceVolumePeriod, value)


def parse_price_volume_history_range(value: int) -> SectorPriceVolumeHistoryRange:
    if value not in ALLOWED_HISTORY_RANGES:
        raise SectorScopeInvalidError(f"historyRange 不支持：{value}")
    return cast(SectorPriceVolumeHistoryRange, value)


def assert_price_volume_hierarchy_version(
    *, requested: str, current: str
) -> None:
    if requested != current:
        raise SectorPriceVolumeFactMismatchError(
            "price-volume hierarchy version is stale"
        )
