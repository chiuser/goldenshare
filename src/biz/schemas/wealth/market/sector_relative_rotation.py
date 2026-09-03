from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.biz.schemas.wealth.market.sector_analysis import (
    SectorAnalysisDebugInfoDto,
    SectorAnalysisPageStatusDto,
    SectorAnalysisStatusValue,
    SectorAnalysisTradingDayDto,
    SectorHierarchyDto,
    SectorMomentumScopeValue,
    SectorParentSelectionDto,
    SectorTradeDateAvailabilityDto,
    _validate_response_status as _validate_non_delayed_status,
)


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_response_status(*, status, trading_day, exception_code) -> None:
    if status != "DELAYED":
        _validate_non_delayed_status(
            status=status, trading_day=trading_day, exception_code=exception_code,
        )
        return
    # Published partial facts remain usable; publication, not completeness, selects the date.
    if (
        trading_day.observedTradeDate is None
        or trading_day.observedTradeDate >= trading_day.expectedTradeDate
        or trading_day.expectedAvailability not in {"PARTIAL", "MISSING"}
        or trading_day.observedAvailability not in {"COMPLETE", "PARTIAL"}
        or exception_code != "SA_SOURCE_DELAYED"
    ):
        raise ValueError("DELAYED response has an invalid trading-day contract")


RelativeRotationStatusValue = Literal[
    "LEADING_IMPROVING",
    "WEAK_IMPROVING",
    "STRONG_NOT_IMPROVING",
    "WEAK_NOT_IMPROVING",
    "SAMPLE_INSUFFICIENT",
    "DATA_INSUFFICIENT",
]
RelativeCoordinateStatusValue = Literal["PLOTTABLE", "UNAVAILABLE"]
RelativeMissingReasonValue = Literal[
    "HISTORY_INSUFFICIENT",
    "DATE_MISSING",
    "CLOSE_MISSING",
    "CLOSE_NON_POSITIVE",
    "PCT_CHANGE_MISSING",
]
RelativeQuadrantStatusValue = Literal[
    "LEADING_IMPROVING",
    "WEAK_IMPROVING",
    "STRONG_NOT_IMPROVING",
    "WEAK_NOT_IMPROVING",
]


class SectorRelativeRotationFormulaDto(_StrictDto):
    formulaKey: Literal["sector-relative-rotation"]
    formulaVersion: Literal[1]
    basisFormulaKey: Literal["sector-cross-sectional-momentum"]
    basisFormulaVersion: Literal[1]
    periods: list[Literal[5, 10, 20, 30]]
    improvementLookbackDays: Literal[5]
    trailLengths: list[Literal[20, 30, 60]]
    minimumGroupSize: Literal[3]
    scopes: list[SectorMomentumScopeValue]
    xDomain: tuple[Literal[0], Literal[100]]
    xSplit: Literal[50]
    ySplit: Literal[0]

    @model_validator(mode="after")
    def validate_frozen_values(self) -> "SectorRelativeRotationFormulaDto":
        if self.periods != [5, 10, 20, 30]:
            raise ValueError("relative-rotation periods must match the frozen order")
        if self.trailLengths != [20, 30, 60]:
            raise ValueError("relative-rotation trail lengths must match the frozen order")
        if self.scopes != [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ]:
            raise ValueError("relative-rotation scopes must match the frozen order")
        if self.xDomain != (0, 100):
            raise ValueError("relative-rotation x domain must remain 0..100")
        return self


class SectorRelativeRotationDefaultsDto(_StrictDto):
    scope: Literal["LEVEL_1"]
    period: Literal[20]
    trailLength: Literal[20]
    quadrantFilter: Literal["ALL"]


class SectorRelativeRotationMetaResponseDto(_StrictDto):
    status: Literal["READY", "DELAYED"]
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: SectorAnalysisDebugInfoDto | None = None
    formula: SectorRelativeRotationFormulaDto
    defaults: SectorRelativeRotationDefaultsDto
    hierarchy: SectorHierarchyDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[SectorTradeDateAvailabilityDto]

    @model_validator(mode="after")
    def validate_meta(self) -> "SectorRelativeRotationMetaResponseDto":
        if self.pageStatus.status != self.status:
            raise ValueError("pageStatus must match response status")
        _validate_response_status(
            status=self.status,
            trading_day=self.tradingDay,
            exception_code=self.exceptionCode,
        )
        dates = [item.tradeDate for item in self.tradeDates]
        if not dates or dates != sorted(set(dates)):
            raise ValueError("tradeDates must be unique and strictly ascending")
        if dates[0] != self.coverageStartDate or dates[-1] != self.coverageEndDate:
            raise ValueError("tradeDates must span the complete coverage range")
        return self


class SectorRelativeRotationRowDto(_StrictDto):
    sectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    parentSectorCode: str | None = None
    parentSectorName: str | None = None
    hierarchyPath: str
    canDrillDown: bool
    returnPct: float | None = None
    strengthRank: int | None = Field(default=None, ge=1)
    percentile: float | None = Field(default=None, ge=0, le=100)
    percentileDelta5d: float | None = None
    rotationStatus: RelativeRotationStatusValue
    coordinateStatus: RelativeCoordinateStatusValue
    currentMissingReason: RelativeMissingReasonValue | None = None
    comparisonMissingReason: RelativeMissingReasonValue | None = None

    @field_validator("returnPct", "percentile", "percentileDelta5d")
    @classmethod
    def validate_finite_number(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("relative-rotation numeric values must be finite")
        return value

    @model_validator(mode="after")
    def validate_fact_shape(self) -> "SectorRelativeRotationRowDto":
        _validate_coordinate_shape(self)
        return self


class SectorRelativeRotationTrailPointDto(_StrictDto):
    tradeDate: date
    returnPct: float | None = None
    percentile: float | None = Field(default=None, ge=0, le=100)
    percentileDelta5d: float | None = None
    rotationStatus: RelativeRotationStatusValue
    coordinateStatus: RelativeCoordinateStatusValue
    currentMissingReason: RelativeMissingReasonValue | None = None
    comparisonMissingReason: RelativeMissingReasonValue | None = None

    @field_validator("returnPct", "percentile", "percentileDelta5d")
    @classmethod
    def validate_finite_number(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("relative-rotation trail values must be finite")
        return value

    @model_validator(mode="after")
    def validate_fact_shape(self) -> "SectorRelativeRotationTrailPointDto":
        _validate_coordinate_shape(self)
        return self


class SectorRelativeRotationTrailDto(_StrictDto):
    sectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")
    requestedLength: Literal[20, 30, 60]
    dateSlotCount: int = Field(ge=0)
    points: list[SectorRelativeRotationTrailPointDto]

    @model_validator(mode="after")
    def validate_trail(self) -> "SectorRelativeRotationTrailDto":
        dates = [item.tradeDate for item in self.points]
        if dates != sorted(set(dates)):
            raise ValueError("relative-rotation trail dates must be unique and ascending")
        if self.dateSlotCount != len(self.points):
            raise ValueError("relative-rotation dateSlotCount must match points")
        if self.dateSlotCount > self.requestedLength:
            raise ValueError("relative-rotation trail exceeds its requested length")
        return self


class SectorRelativeRotationQuadrantCountsDto(_StrictDto):
    leadingImproving: int = Field(ge=0)
    weakImproving: int = Field(ge=0)
    strongNotImproving: int = Field(ge=0)
    weakNotImproving: int = Field(ge=0)

    def total(self) -> int:
        return (
            self.leadingImproving
            + self.weakImproving
            + self.strongNotImproving
            + self.weakNotImproving
        )


class SectorRelativeRotationAnalysisDto(_StrictDto):
    formulaKey: Literal["sector-relative-rotation"]
    formulaVersion: Literal[1]
    basisFormulaKey: Literal["sector-cross-sectional-momentum"]
    basisFormulaVersion: Literal[1]
    hierarchyVersion: str = Field(min_length=1, max_length=128)
    scope: SectorMomentumScopeValue
    period: Literal[5, 10, 20, 30]
    improvementLookbackDays: Literal[5]
    trailLength: Literal[20, 30, 60]
    minimumGroupSize: Literal[3]
    parentSelection: SectorParentSelectionDto
    selectedSectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")
    groupInterpretation: Literal["QUADRANT", "SAMPLE_INSUFFICIENT"]
    totalCount: int = Field(ge=0)
    currentCalculableCount: int = Field(ge=0)
    plottableCount: int = Field(ge=0)
    missingCoordinateCount: int = Field(ge=0)
    quadrantCounts: SectorRelativeRotationQuadrantCountsDto
    items: list[SectorRelativeRotationRowDto]
    selectedTrail: SectorRelativeRotationTrailDto

    @model_validator(mode="after")
    def validate_analysis(self) -> "SectorRelativeRotationAnalysisDto":
        if len(self.items) != self.totalCount:
            raise ValueError("relative-rotation totalCount must match items")
        codes = [item.sectorCode for item in self.items]
        if len(codes) != len(set(codes)):
            raise ValueError("relative-rotation sector codes must be unique")
        if self.selectedSectorCode not in codes:
            raise ValueError("selected relative-rotation sector must exist in items")
        if self.selectedTrail.sectorCode != self.selectedSectorCode:
            raise ValueError("selected relative-rotation trail must match selection")
        if self.selectedTrail.requestedLength != self.trailLength:
            raise ValueError("selected trail length must match the analysis")
        current_calculable = sum(item.percentile is not None for item in self.items)
        plottable = sum(item.coordinateStatus == "PLOTTABLE" for item in self.items)
        if self.currentCalculableCount != current_calculable:
            raise ValueError("currentCalculableCount must match items")
        if self.plottableCount != plottable:
            raise ValueError("plottableCount must match items")
        if self.missingCoordinateCount != self.totalCount - self.plottableCount:
            raise ValueError("missingCoordinateCount must complement plottableCount")
        if not (
            0 < self.currentCalculableCount <= self.totalCount
            and 0 <= self.plottableCount <= self.currentCalculableCount
        ):
            raise ValueError("relative-rotation counts are outside valid bounds")
        if self.items != sorted(self.items, key=_canonical_sort_key):
            raise ValueError("relative-rotation items do not follow canonical order")

        quadrant_statuses: tuple[RelativeQuadrantStatusValue, ...] = (
            "LEADING_IMPROVING",
            "WEAK_IMPROVING",
            "STRONG_NOT_IMPROVING",
            "WEAK_NOT_IMPROVING",
        )
        if self.groupInterpretation == "QUADRANT":
            if self.quadrantCounts.total() != self.plottableCount:
                raise ValueError("quadrant counts must partition plottable items")
            if any(
                item.coordinateStatus == "PLOTTABLE"
                and item.rotationStatus not in quadrant_statuses
                for item in self.items
            ):
                raise ValueError("plottable items must carry a quadrant status")
            expected_counts = {
                status: sum(item.rotationStatus == status for item in self.items)
                for status in quadrant_statuses
            }
            if (
                self.quadrantCounts.leadingImproving
                != expected_counts["LEADING_IMPROVING"]
                or self.quadrantCounts.weakImproving
                != expected_counts["WEAK_IMPROVING"]
                or self.quadrantCounts.strongNotImproving
                != expected_counts["STRONG_NOT_IMPROVING"]
                or self.quadrantCounts.weakNotImproving
                != expected_counts["WEAK_NOT_IMPROVING"]
            ):
                raise ValueError("quadrant counts must match item statuses")
        else:
            if self.quadrantCounts.total() != 0:
                raise ValueError("small groups cannot produce quadrant counts")
            if any(
                item.coordinateStatus == "PLOTTABLE"
                and item.rotationStatus != "SAMPLE_INSUFFICIENT"
                for item in self.items
            ):
                raise ValueError("small-group coordinates must remain uninterpreted")
        return self


class SectorRelativeRotationResultsResponseDto(_StrictDto):
    status: SectorAnalysisStatusValue
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    analysis: SectorRelativeRotationAnalysisDto | None = None
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: SectorAnalysisDebugInfoDto | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "SectorRelativeRotationResultsResponseDto":
        if self.pageStatus.status != self.status:
            raise ValueError("pageStatus must match response status")
        if self.status in {"READY", "DELAYED"}:
            if self.analysis is None or self.analysis.currentCalculableCount <= 0:
                raise ValueError("READY and DELAYED require calculable analysis")
            points = self.analysis.selectedTrail.points
            if not points or points[-1].tradeDate != self.tradingDay.observedTradeDate:
                raise ValueError("selected trail must end at observedTradeDate")
        elif self.analysis is not None:
            raise ValueError("EMPTY and ERROR cannot carry relative-rotation analysis")
        _validate_response_status(
            status=self.status,
            trading_day=self.tradingDay,
            exception_code=self.exceptionCode,
        )
        return self


def _validate_coordinate_shape(value) -> None:
    current_values = (value.returnPct, getattr(value, "strengthRank", None), value.percentile)
    if hasattr(value, "strengthRank"):
        if any(item is None for item in current_values) and not all(
            item is None for item in current_values
        ):
            raise ValueError("returnPct, strengthRank and percentile must be null together")
    elif (value.returnPct is None) != (value.percentile is None):
        raise ValueError("trail returnPct and percentile must be null together")

    if value.percentile is None:
        if (
            value.percentileDelta5d is not None
            or value.coordinateStatus != "UNAVAILABLE"
            or value.rotationStatus != "DATA_INSUFFICIENT"
            or value.currentMissingReason is None
        ):
            raise ValueError("missing current facts must use the unavailable state")
        return
    if value.currentMissingReason is not None:
        raise ValueError("calculable current facts cannot carry a missing reason")
    if value.percentileDelta5d is None:
        if (
            value.coordinateStatus != "UNAVAILABLE"
            or value.rotationStatus != "DATA_INSUFFICIENT"
            or value.comparisonMissingReason is None
        ):
            raise ValueError("missing comparison facts must use the unavailable state")
        return
    if (
        value.coordinateStatus != "PLOTTABLE"
        or value.rotationStatus == "DATA_INSUFFICIENT"
        or value.comparisonMissingReason is not None
    ):
        raise ValueError("complete coordinates must be plottable without missing reasons")
    if value.rotationStatus != "SAMPLE_INSUFFICIENT":
        expected = _expected_quadrant(value.percentile, value.percentileDelta5d)
        if value.rotationStatus != expected:
            raise ValueError("relative-rotation status does not match its coordinates")


def _canonical_sort_key(row: SectorRelativeRotationRowDto):
    if row.percentile is None:
        return (2, 0.0, 0.0, row.sectorCode)
    if row.percentileDelta5d is None:
        return (1, -row.percentile, 0.0, row.sectorCode)
    return (0, -row.percentile, -row.percentileDelta5d, row.sectorCode)


def _expected_quadrant(percentile: float, delta: float) -> str:
    if percentile >= 50 and delta > 0:
        return "LEADING_IMPROVING"
    if percentile < 50 and delta > 0:
        return "WEAK_IMPROVING"
    if percentile >= 50 and delta <= 0:
        return "STRONG_NOT_IMPROVING"
    return "WEAK_NOT_IMPROVING"
