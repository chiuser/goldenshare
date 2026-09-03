from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.biz.schemas.wealth.market.sector_analysis import (
    SectorAvailabilityValue,
    SectorHierarchyDto,
    SectorMomentumScopeValue,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    SectorPriceVolumeMissingReason,
)


PriceVolumeStateValue = Literal["JOINT", "PRICE_ONLY", "AMOUNT_ONLY", "NEUTRAL"]
PriceVolumeStatusValue = Literal["READY", "EMPTY", "ERROR"]


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceVolumeTradeDateAvailabilityDto(_StrictDto):
    tradeDate: date
    availability: SectorAvailabilityValue
    expectedSectorCount: int = Field(gt=0)
    validSectorCount: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_availability(self) -> "PriceVolumeTradeDateAvailabilityDto":
        if self.validSectorCount > self.expectedSectorCount:
            raise ValueError("validSectorCount cannot exceed expectedSectorCount")
        if self.availability == "COMPLETE" and self.validSectorCount != self.expectedSectorCount:
            raise ValueError("COMPLETE requires full coverage")
        if self.availability == "PARTIAL" and not 0 < self.validSectorCount < self.expectedSectorCount:
            raise ValueError("PARTIAL requires incomplete non-zero coverage")
        if self.availability == "MISSING" and self.validSectorCount != 0:
            raise ValueError("MISSING requires zero coverage")
        return self


class PriceVolumeDateContextDto(_StrictDto):
    expectedTradeDate: date
    defaultTradeDate: date | None = None
    defaultStatus: Literal["READY", "DELAYED", "EMPTY"]
    displayText: str

    @model_validator(mode="after")
    def validate_default(self) -> "PriceVolumeDateContextDto":
        if self.defaultStatus == "EMPTY" and self.defaultTradeDate is not None:
            raise ValueError("EMPTY cannot carry a default trade date")
        if self.defaultStatus != "EMPTY" and self.defaultTradeDate is None:
            raise ValueError("READY and DELAYED require a default trade date")
        if self.defaultStatus == "READY" and self.defaultTradeDate != self.expectedTradeDate:
            raise ValueError("READY must use expectedTradeDate")
        if self.defaultStatus == "DELAYED" and not (
            self.defaultTradeDate is not None
            and self.defaultTradeDate < self.expectedTradeDate
        ):
            raise ValueError("DELAYED requires an earlier default trade date")
        return self


class SectorPriceVolumeDefaultsDto(_StrictDto):
    scope: Literal["LEVEL_1"]
    period: Literal[20]
    stateFilter: Literal["ALL"]
    sortBy: Literal["PRICE_MOMENTUM"]
    sortDirection: Literal["DESC"]
    historyRange: Literal[20]


class SectorPriceVolumeMetaResponseDto(_StrictDto):
    formulaKey: Literal["sector-price-volume-distribution"]
    formulaVersion: Literal[1]
    market: Literal["CN_A"]
    periods: list[Literal[1, 5, 10, 20, 30]]
    historyRanges: list[Literal[20, 30, 60]]
    scopes: list[SectorMomentumScopeValue]
    states: list[PriceVolumeStateValue]
    defaults: SectorPriceVolumeDefaultsDto
    dateCoverageBasis: Literal["INDUSTRY_DAILY"]
    dateContext: PriceVolumeDateContextDto
    hierarchy: SectorHierarchyDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[PriceVolumeTradeDateAvailabilityDto]

    @model_validator(mode="after")
    def validate_meta(self) -> "SectorPriceVolumeMetaResponseDto":
        if self.periods != [1, 5, 10, 20, 30]:
            raise ValueError("price-volume periods must follow the frozen order")
        if self.historyRanges != [20, 30, 60]:
            raise ValueError("price-volume history ranges must follow the frozen order")
        if self.scopes != [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ]:
            raise ValueError("price-volume scopes must follow the frozen order")
        if self.states != ["JOINT", "PRICE_ONLY", "AMOUNT_ONLY", "NEUTRAL"]:
            raise ValueError("price-volume states must follow the frozen order")
        dates = [item.tradeDate for item in self.tradeDates]
        if not dates or dates != sorted(set(dates)):
            raise ValueError("tradeDates must be unique and ascending")
        if dates[0] != self.coverageStartDate or dates[-1] != self.coverageEndDate:
            raise ValueError("tradeDates must span the declared coverage")
        if self.dateContext.expectedTradeDate != self.coverageEndDate:
            raise ValueError("expectedTradeDate must equal coverageEndDate")
        if self.dateContext.defaultTradeDate is not None:
            defaults = [
                item
                for item in self.tradeDates
                if item.tradeDate == self.dateContext.defaultTradeDate
            ]
            if len(defaults) != 1:
                raise ValueError("defaultTradeDate must be a covered date")
        return self


class SectorPriceVolumeSnapshotRowDto(_StrictDto):
    sectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    hierarchyPath: str
    parentSectorCode: str | None = None
    parentSectorName: str | None = None
    rootSectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")
    rootSectorName: str
    priceMomentumPct: float | None = None
    amountActivityPct: float | None = None
    priceRank: int | None = Field(default=None, ge=1)
    priceRankableCount: int = Field(ge=0)
    amountRank: int | None = Field(default=None, ge=1)
    amountRankableCount: int = Field(ge=0)
    state: PriceVolumeStateValue | None = None
    priceMissingReason: SectorPriceVolumeMissingReason | None = None
    amountMissingReason: SectorPriceVolumeMissingReason | None = None

    @field_validator("priceMomentumPct", "amountActivityPct")
    @classmethod
    def validate_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("price-volume values must be finite")
        return value

    @model_validator(mode="after")
    def validate_row(self) -> "SectorPriceVolumeSnapshotRowDto":
        _validate_metric_pair(
            value=self.priceMomentumPct,
            reason=self.priceMissingReason,
            rank=self.priceRank,
            rankable_count=self.priceRankableCount,
            field_name="price",
        )
        _validate_metric_pair(
            value=self.amountActivityPct,
            reason=self.amountMissingReason,
            rank=self.amountRank,
            rankable_count=self.amountRankableCount,
            field_name="amount",
        )
        both = self.priceMomentumPct is not None and self.amountActivityPct is not None
        if both != (self.state is not None):
            raise ValueError("state requires both coordinates")
        if self.state == "JOINT" and not (
            self.priceMomentumPct is not None
            and self.priceMomentumPct > 0
            and self.amountActivityPct is not None
            and self.amountActivityPct > 0
        ):
            raise ValueError("JOINT has inconsistent signs")
        if self.state == "PRICE_ONLY" and not (
            self.priceMomentumPct is not None
            and self.priceMomentumPct > 0
            and self.amountActivityPct is not None
            and self.amountActivityPct <= 0
        ):
            raise ValueError("PRICE_ONLY has inconsistent signs")
        if self.state == "AMOUNT_ONLY" and not (
            self.priceMomentumPct is not None
            and self.priceMomentumPct <= 0
            and self.amountActivityPct is not None
            and self.amountActivityPct > 0
        ):
            raise ValueError("AMOUNT_ONLY has inconsistent signs")
        if self.state == "NEUTRAL" and not (
            self.priceMomentumPct is not None
            and self.priceMomentumPct <= 0
            and self.amountActivityPct is not None
            and self.amountActivityPct <= 0
        ):
            raise ValueError("NEUTRAL has inconsistent signs")
        return self


class SectorPriceVolumeSnapshotDto(_StrictDto):
    formulaKey: Literal["sector-price-volume-distribution"]
    formulaVersion: Literal[1]
    hierarchyVersion: str = Field(min_length=1, max_length=128)
    observedTradeDate: date
    availability: SectorAvailabilityValue
    scope: SectorMomentumScopeValue
    level1Code: str | None = None
    level2Code: str | None = None
    period: Literal[1, 5, 10, 20, 30]
    totalCount: int = Field(ge=0)
    coordinateCount: int = Field(ge=0)
    missingCoordinateCount: int = Field(ge=0)
    rows: list[SectorPriceVolumeSnapshotRowDto]

    @model_validator(mode="after")
    def validate_snapshot(self) -> "SectorPriceVolumeSnapshotDto":
        if len(self.rows) != self.totalCount:
            raise ValueError("totalCount must match rows")
        if self.coordinateCount + self.missingCoordinateCount != self.totalCount:
            raise ValueError("coordinate counts must close")
        codes = [item.sectorCode for item in self.rows]
        if len(codes) != len(set(codes)):
            raise ValueError("snapshot sector codes must be unique")
        coordinates = sum(item.state is not None for item in self.rows)
        if coordinates != self.coordinateCount:
            raise ValueError("coordinateCount must match rows")
        if self.rows:
            price_counts = {item.priceRankableCount for item in self.rows}
            amount_counts = {item.amountRankableCount for item in self.rows}
            if len(price_counts) != 1 or len(amount_counts) != 1:
                raise ValueError("rankable counts must be uniform")
        if self.rows != sorted(self.rows, key=_snapshot_sort_key):
            raise ValueError("snapshot rows must follow canonical price order")
        return self


class SectorPriceVolumeDebugInfoDto(_StrictDto):
    expectedTradeDate: date
    observedTradeDate: date | None = None
    scope: SectorMomentumScopeValue | None = None
    poolSize: int = Field(ge=0)
    requestedOpenDateCount: int = Field(ge=0)
    loadedOpenDateCount: int = Field(ge=0)
    reasonCounts: dict[SectorPriceVolumeMissingReason, int]

    @field_validator("reasonCounts")
    @classmethod
    def validate_reason_counts(
        cls, value: dict[SectorPriceVolumeMissingReason, int]
    ) -> dict[SectorPriceVolumeMissingReason, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("reason counts cannot be negative")
        return value


class SectorPriceVolumeSnapshotResponseDto(_StrictDto):
    status: PriceVolumeStatusValue
    snapshot: SectorPriceVolumeSnapshotDto | None = None
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: SectorPriceVolumeDebugInfoDto | None = None

    @model_validator(mode="after")
    def validate_response(self) -> "SectorPriceVolumeSnapshotResponseDto":
        if self.status == "READY":
            if self.snapshot is None or self.snapshot.coordinateCount <= 0:
                raise ValueError("READY requires coordinates")
            if self.exceptionCode is not None:
                raise ValueError("READY cannot carry an exception")
        elif self.status == "EMPTY":
            if self.snapshot is None or self.snapshot.coordinateCount != 0:
                raise ValueError("EMPTY requires a zero-coordinate snapshot")
            if self.exceptionCode is not None:
                raise ValueError("EMPTY cannot carry a technical exception")
        elif self.snapshot is not None or self.exceptionCode not in {
            "SA_HIERARCHY_UNAVAILABLE",
            "SA_QUERY_FAILED",
        }:
            raise ValueError("ERROR requires a safe technical exception shell")
        return self


class SectorPriceVolumeHistoryPointDto(_StrictDto):
    tradeDate: date
    priceMomentumPct: float | None = None
    amountActivityPct: float | None = None
    priceMissingReason: SectorPriceVolumeMissingReason | None = None
    amountMissingReason: SectorPriceVolumeMissingReason | None = None

    @field_validator("priceMomentumPct", "amountActivityPct")
    @classmethod
    def validate_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("price-volume history values must be finite")
        return value

    @model_validator(mode="after")
    def validate_point(self) -> "SectorPriceVolumeHistoryPointDto":
        _validate_value_reason(
            value=self.priceMomentumPct,
            reason=self.priceMissingReason,
            field_name="price",
        )
        _validate_value_reason(
            value=self.amountActivityPct,
            reason=self.amountMissingReason,
            field_name="amount",
        )
        return self


class SectorPriceVolumeSelectedDto(_StrictDto):
    sectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    hierarchyPath: str
    parentSectorCode: str | None = None
    rootSectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")


class SectorPriceVolumeDetailsDto(_StrictDto):
    formulaKey: Literal["sector-price-volume-distribution"]
    formulaVersion: Literal[1]
    hierarchyVersion: str = Field(min_length=1, max_length=128)
    observedTradeDate: date
    availability: SectorAvailabilityValue
    scope: SectorMomentumScopeValue
    level1Code: str | None = None
    level2Code: str | None = None
    period: Literal[1, 5, 10, 20, 30]
    historyRange: Literal[20, 30, 60]
    selected: SectorPriceVolumeSelectedDto
    history: list[SectorPriceVolumeHistoryPointDto]

    @model_validator(mode="after")
    def validate_details(self) -> "SectorPriceVolumeDetailsDto":
        dates = [item.tradeDate for item in self.history]
        if dates != sorted(set(dates)):
            raise ValueError("history dates must be unique and ascending")
        if len(dates) > self.historyRange:
            raise ValueError("history exceeds requested range")
        if dates and dates[-1] != self.observedTradeDate:
            raise ValueError("history must end at observedTradeDate")
        return self


class SectorPriceVolumeDetailsResponseDto(_StrictDto):
    status: PriceVolumeStatusValue
    details: SectorPriceVolumeDetailsDto | None = None
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: SectorPriceVolumeDebugInfoDto | None = None

    @model_validator(mode="after")
    def validate_response(self) -> "SectorPriceVolumeDetailsResponseDto":
        has_value = self.details is not None and any(
            item.priceMomentumPct is not None or item.amountActivityPct is not None
            for item in self.details.history
        )
        if self.status == "READY":
            if self.details is None or not has_value or self.exceptionCode is not None:
                raise ValueError("READY requires at least one historical value")
        elif self.status == "EMPTY":
            if self.details is None or has_value or self.exceptionCode is not None:
                raise ValueError("EMPTY requires an all-missing details payload")
        elif self.details is not None or self.exceptionCode not in {
            "SA_HIERARCHY_UNAVAILABLE",
            "SA_QUERY_FAILED",
        }:
            raise ValueError("ERROR requires a safe technical exception shell")
        return self


def _validate_value_reason(
    *,
    value: float | None,
    reason: SectorPriceVolumeMissingReason | None,
    field_name: str,
) -> None:
    if (value is None) == (reason is None):
        raise ValueError(f"{field_name} value and missing reason must be complementary")


def _validate_metric_pair(
    *,
    value: float | None,
    reason: SectorPriceVolumeMissingReason | None,
    rank: int | None,
    rankable_count: int,
    field_name: str,
) -> None:
    _validate_value_reason(value=value, reason=reason, field_name=field_name)
    if value is None and rank is not None:
        raise ValueError(f"missing {field_name} cannot carry a rank")
    if value is not None and (rank is None or rank > rankable_count):
        raise ValueError(f"present {field_name} requires a valid rank")


def _snapshot_sort_key(row: SectorPriceVolumeSnapshotRowDto):
    if row.priceMomentumPct is None:
        return (1, 0.0, row.sectorCode)
    return (0, -row.priceMomentumPct, row.sectorCode)
