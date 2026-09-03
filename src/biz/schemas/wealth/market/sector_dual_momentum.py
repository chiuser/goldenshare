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
)


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SectorDualMomentumFormulaDto(_StrictDto):
    formulaKey: Literal["sector-dual-momentum"]
    formulaVersion: Literal[1]
    basisFormulaKey: Literal["sector-cross-sectional-momentum"]
    basisFormulaVersion: Literal[1]
    periods: list[Literal[5, 10, 20, 30]]
    leadingThresholds: list[Literal[70, 80, 90]]
    minimumGroupSize: Literal[3]
    scopes: list[SectorMomentumScopeValue]

    @model_validator(mode="after")
    def validate_frozen_values(self) -> "SectorDualMomentumFormulaDto":
        if self.periods != [5, 10, 20, 30]:
            raise ValueError("dual-momentum periods must match the frozen order")
        if self.leadingThresholds != [70, 80, 90]:
            raise ValueError("leading thresholds must match the frozen order")
        if self.scopes != [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ]:
            raise ValueError("dual-momentum scopes must match the frozen order")
        return self


class SectorDualMomentumDefaultsDto(_StrictDto):
    scope: Literal["LEVEL_1"]
    period: Literal[20]
    leadingThreshold: Literal[80]
    resultView: Literal["QUALIFIED"]


class SectorDualMomentumMetaResponseDto(_StrictDto):
    status: Literal["READY", "DELAYED"]
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: SectorAnalysisDebugInfoDto | None = None
    formula: SectorDualMomentumFormulaDto
    defaults: SectorDualMomentumDefaultsDto
    hierarchy: SectorHierarchyDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[SectorTradeDateAvailabilityDto]

    @model_validator(mode="after")
    def validate_meta(self) -> "SectorDualMomentumMetaResponseDto":
        _validate_status(
            status=self.status,
            trading_day=self.tradingDay,
            exception_code=self.exceptionCode,
        )
        if self.pageStatus.status != self.status:
            raise ValueError("pageStatus must match response status")
        dates = [item.tradeDate for item in self.tradeDates]
        if not dates or dates != sorted(set(dates)):
            raise ValueError("tradeDates must be unique and strictly ascending")
        if dates[0] != self.coverageStartDate or dates[-1] != self.coverageEndDate:
            raise ValueError("tradeDates must span the complete coverage range")
        return self


AbsoluteStatus = Literal["POSITIVE", "NOT_POSITIVE", "UNAVAILABLE"]
RelativeStatus = Literal[
    "LEADING",
    "NOT_LEADING",
    "SAMPLE_INSUFFICIENT",
    "UNAVAILABLE",
]
QualificationStatus = Literal["QUALIFIED", "NOT_QUALIFIED", "NOT_EVALUATED"]
CoordinateStatus = Literal["PLOTTABLE", "UNAVAILABLE"]
DisplayStatus = Literal[
    "QUALIFIED",
    "UP_NOT_LEADING",
    "NOT_UP_LEADING",
    "NOT_UP_NOT_LEADING",
    "SAMPLE_INSUFFICIENT",
    "DATA_INSUFFICIENT",
]
MissingReason = Literal[
    "HISTORY_INSUFFICIENT",
    "DATE_MISSING",
    "CLOSE_MISSING",
    "CLOSE_NON_POSITIVE",
    "PCT_CHANGE_MISSING",
]


class SectorDualMomentumRowDto(_StrictDto):
    sectorCode: str
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    parentSectorCode: str | None = None
    parentSectorName: str | None = None
    hierarchyPath: str
    canDrillDown: bool
    returnPct: float | None = None
    strengthRank: int | None = Field(default=None, ge=1)
    percentile: float | None = Field(default=None, ge=0, le=100)
    absoluteStatus: AbsoluteStatus
    relativeStatus: RelativeStatus
    qualificationStatus: QualificationStatus
    coordinateStatus: CoordinateStatus
    displayStatus: DisplayStatus
    missingReason: MissingReason | None = None

    @field_validator("returnPct", "percentile")
    @classmethod
    def validate_finite_number(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("dual-momentum numeric values must be finite")
        return value

    @model_validator(mode="after")
    def validate_fact_shape(self) -> "SectorDualMomentumRowDto":
        values = (self.returnPct, self.strengthRank, self.percentile)
        if any(value is None for value in values) and not all(
            value is None for value in values
        ):
            raise ValueError("returnPct, strengthRank and percentile must be null together")
        if self.returnPct is None:
            if (
                self.coordinateStatus != "UNAVAILABLE"
                or self.absoluteStatus != "UNAVAILABLE"
                or self.relativeStatus != "UNAVAILABLE"
                or self.qualificationStatus != "NOT_EVALUATED"
                or self.displayStatus != "DATA_INSUFFICIENT"
                or self.missingReason is None
            ):
                raise ValueError("missing facts must use the unavailable state set")
        elif self.coordinateStatus != "PLOTTABLE" or self.missingReason is not None:
            raise ValueError("calculable facts must be plottable and have no missing reason")
        return self


class SectorDualMomentumAnalysisDto(_StrictDto):
    formulaKey: Literal["sector-dual-momentum"]
    formulaVersion: Literal[1]
    basisFormulaKey: Literal["sector-cross-sectional-momentum"]
    basisFormulaVersion: Literal[1]
    hierarchyVersion: str = Field(min_length=1, max_length=128)
    scope: SectorMomentumScopeValue
    period: Literal[5, 10, 20, 30]
    leadingThreshold: Literal[70, 80, 90]
    minimumGroupSize: Literal[3]
    parentSelection: SectorParentSelectionDto
    totalCount: int = Field(ge=0)
    calculableCount: int = Field(ge=0)
    qualifiedCount: int = Field(ge=0)
    insufficientCount: int = Field(ge=0)
    plottableCount: int = Field(ge=0)
    items: list[SectorDualMomentumRowDto]

    @model_validator(mode="after")
    def validate_analysis(self) -> "SectorDualMomentumAnalysisDto":
        if len(self.items) != self.totalCount:
            raise ValueError("totalCount must match items")
        codes = [item.sectorCode for item in self.items]
        if len(codes) != len(set(codes)):
            raise ValueError("dual-momentum sector codes must be unique")
        calculable = sum(item.returnPct is not None for item in self.items)
        qualified = sum(
            item.qualificationStatus == "QUALIFIED" for item in self.items
        )
        insufficient = sum(
            item.qualificationStatus == "NOT_EVALUATED" for item in self.items
        )
        plottable = sum(item.coordinateStatus == "PLOTTABLE" for item in self.items)
        if (
            self.calculableCount != calculable
            or self.qualifiedCount != qualified
            or self.insufficientCount != insufficient
            or self.plottableCount != plottable
        ):
            raise ValueError("dual-momentum counts must match items")
        not_qualified = sum(
            item.qualificationStatus == "NOT_QUALIFIED" for item in self.items
        )
        if qualified + not_qualified + insufficient != self.totalCount:
            raise ValueError("qualification states must partition all items")
        if not (
            0 <= qualified <= calculable <= self.totalCount
            and 0 <= plottable <= calculable
        ):
            raise ValueError("dual-momentum counts are outside their valid bounds")
        expected_order = sorted(self.items, key=_canonical_sort_key)
        if self.items != expected_order:
            raise ValueError("dual-momentum items do not follow canonical order")
        for item in self.items:
            self._validate_classification(item)
        return self

    def _validate_classification(self, item: SectorDualMomentumRowDto) -> None:
        if item.returnPct is None:
            return
        expected_absolute = "POSITIVE" if item.returnPct > 0 else "NOT_POSITIVE"
        if item.absoluteStatus != expected_absolute:
            raise ValueError("absoluteStatus does not match returnPct")
        if self.calculableCount < self.minimumGroupSize:
            if (
                item.relativeStatus != "SAMPLE_INSUFFICIENT"
                or item.qualificationStatus != "NOT_EVALUATED"
                or item.displayStatus != "SAMPLE_INSUFFICIENT"
            ):
                raise ValueError("small groups cannot produce qualifications")
            return
        expected_relative = (
            "LEADING"
            if item.percentile is not None
            and item.percentile >= self.leadingThreshold
            else "NOT_LEADING"
        )
        expected_qualification = (
            "QUALIFIED"
            if expected_absolute == "POSITIVE" and expected_relative == "LEADING"
            else "NOT_QUALIFIED"
        )
        expected_display = {
            ("POSITIVE", "LEADING"): "QUALIFIED",
            ("POSITIVE", "NOT_LEADING"): "UP_NOT_LEADING",
            ("NOT_POSITIVE", "LEADING"): "NOT_UP_LEADING",
            ("NOT_POSITIVE", "NOT_LEADING"): "NOT_UP_NOT_LEADING",
        }[(expected_absolute, expected_relative)]
        if (
            item.relativeStatus != expected_relative
            or item.qualificationStatus != expected_qualification
            or item.displayStatus != expected_display
        ):
            raise ValueError("dual-momentum classification does not match its facts")


class SectorDualMomentumResultsResponseDto(_StrictDto):
    status: SectorAnalysisStatusValue
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    analysis: SectorDualMomentumAnalysisDto | None = None
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: SectorAnalysisDebugInfoDto | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "SectorDualMomentumResultsResponseDto":
        if self.pageStatus.status != self.status:
            raise ValueError("pageStatus must match response status")
        if self.status in {"READY", "DELAYED"}:
            if self.analysis is None or self.analysis.calculableCount <= 0:
                raise ValueError("READY and DELAYED require calculable analysis")
        elif self.analysis is not None:
            raise ValueError("EMPTY and ERROR cannot carry analysis")
        _validate_status(
            status=self.status,
            trading_day=self.tradingDay,
            exception_code=self.exceptionCode,
        )
        return self


def _canonical_sort_key(row: SectorDualMomentumRowDto):
    if row.returnPct is None:
        return (1, 0.0, 0.0, row.sectorCode)
    assert row.percentile is not None
    return (0, -row.percentile, -row.returnPct, row.sectorCode)


def _validate_status(
    *,
    status: SectorAnalysisStatusValue,
    trading_day: SectorAnalysisTradingDayDto,
    exception_code: str | None,
) -> None:
    if status == "READY":
        if (
            trading_day.observedTradeDate != trading_day.expectedTradeDate
            or trading_day.expectedAvailability == "MISSING"
            or exception_code is not None
        ):
            raise ValueError("READY response has an invalid trading-day contract")
    elif status == "DELAYED":
        if (
            trading_day.observedTradeDate is None
            or trading_day.observedTradeDate >= trading_day.expectedTradeDate
            or trading_day.expectedAvailability not in {"PARTIAL", "MISSING"}
            or trading_day.observedAvailability not in {"COMPLETE", "PARTIAL"}
            or exception_code != "SA_SOURCE_DELAYED"
        ):
            raise ValueError("DELAYED response has an invalid trading-day contract")
    elif status == "EMPTY":
        if exception_code != "SA_SOURCE_EMPTY":
            raise ValueError("EMPTY requires SA_SOURCE_EMPTY")
    elif status == "ERROR" and exception_code not in {
        "SA_HIERARCHY_UNAVAILABLE",
        "SA_QUERY_FAILED",
    }:
        raise ValueError("ERROR requires a registered error exceptionCode")
