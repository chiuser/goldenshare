from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorMomentumDirection,
    SectorMomentumPeriod,
)


SectorMemberReturnMissingReason = Literal[
    "NONE",
    "DATE_MISSING",
    "PCT_CHANGE_MISSING",
    "HISTORY_INSUFFICIENT",
]


class SectorMemberFactMismatchError(RuntimeError):
    pass


class DuplicateSectorMemberFactError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SectorMemberSourceFact:
    stock_code: str
    stock_name: str | None


@dataclass(frozen=True, slots=True)
class SectorMemberDailyFact:
    stock_code: str
    trade_date: date
    close: Decimal | None
    pct_change: Decimal | None


@dataclass(frozen=True, slots=True)
class SectorMemberReturnFact:
    stock_code: str
    stock_name: str | None
    close: Decimal | None
    return_pct: Decimal | None
    return_missing_reason: SectorMemberReturnMissingReason


@dataclass(frozen=True, slots=True)
class SectorMemberDetailRequest:
    market: Literal["CN_A"]
    trade_date: date
    hierarchy_version: str
    sector_code: str
    period: SectorMomentumPeriod
    direction: SectorMomentumDirection
