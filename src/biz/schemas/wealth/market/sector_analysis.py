from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SectorMomentumScopeValue = Literal[
    "LEVEL_1",
    "LEVEL_2",
    "LEVEL_3",
    "LEVEL_1_CHILDREN",
    "LEVEL_2_CHILDREN",
]
SectorMomentumDirectionValue = Literal["GAINERS", "LOSERS"]
SectorMomentumPeriodValue = Literal[1, 5, 10, 20, 30]
SectorHistoryRangeValue = Literal[20, 30, 60]
SectorAnalysisStatusValue = Literal["READY", "DELAYED", "EMPTY", "ERROR"]
SectorAvailabilityValue = Literal["COMPLETE", "PARTIAL", "MISSING"]


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SectorFormulaDto(_StrictDto):
    formulaKey: Literal["sector-cross-sectional-momentum"]
    formulaVersion: Literal[1]
    periods: list[SectorMomentumPeriodValue]
    historyRanges: list[SectorHistoryRangeValue]
    scopes: list[SectorMomentumScopeValue]
    directions: list[SectorMomentumDirectionValue]


class SectorHierarchyNodeDto(_StrictDto):
    sectorCode: str
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    parentSectorCode: str | None = None
    parentSectorName: str | None = None
    rootSectorCode: str
    rootSectorName: str
    hierarchyPath: str
    displayOrder: int = Field(ge=0)
    isLeaf: bool


class SectorHierarchyDto(_StrictDto):
    hierarchyVersion: str
    publishedAt: datetime
    nodes: list[SectorHierarchyNodeDto]


class SectorTradeDateAvailabilityDto(_StrictDto):
    tradeDate: date
    availability: SectorAvailabilityValue
    expectedSectorCount: int = Field(gt=0)
    validSectorCount: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_availability(self) -> "SectorTradeDateAvailabilityDto":
        if self.validSectorCount > self.expectedSectorCount:
            raise ValueError("validSectorCount cannot exceed expectedSectorCount")
        if self.availability == "COMPLETE" and self.validSectorCount != self.expectedSectorCount:
            raise ValueError("COMPLETE requires full sector coverage")
        if self.availability == "PARTIAL" and not 0 < self.validSectorCount < self.expectedSectorCount:
            raise ValueError("PARTIAL requires incomplete non-zero coverage")
        if self.availability == "MISSING" and self.validSectorCount != 0:
            raise ValueError("MISSING requires zero coverage")
        return self


class SectorAnalysisMetaResponseDto(_StrictDto):
    formula: SectorFormulaDto
    hierarchy: SectorHierarchyDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[SectorTradeDateAvailabilityDto]

    @model_validator(mode="after")
    def validate_trade_dates(self) -> "SectorAnalysisMetaResponseDto":
        if self.coverageStartDate > self.coverageEndDate:
            raise ValueError("coverageStartDate cannot exceed coverageEndDate")
        dates = [item.tradeDate for item in self.tradeDates]
        if dates != sorted(set(dates)):
            raise ValueError("tradeDates must be unique and strictly ascending")
        if not dates or dates[0] != self.coverageStartDate or dates[-1] != self.coverageEndDate:
            raise ValueError("tradeDates must span the complete coverage range")
        return self


class SectorAnalysisTradingDayDto(_StrictDto):
    expectedTradeDate: date
    observedTradeDate: date | None = None
    expectedAvailability: SectorAvailabilityValue
    expectedSectorCount: int = Field(ge=0)
    expectedValidSectorCount: int = Field(ge=0)
    observedAvailability: SectorAvailabilityValue | None = None
    observedValidSectorCount: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "SectorAnalysisTradingDayDto":
        if self.expectedSectorCount == 0:
            if (
                self.expectedAvailability != "MISSING"
                or self.expectedValidSectorCount != 0
                or self.observedTradeDate is not None
                or self.observedAvailability is not None
                or self.observedValidSectorCount != 0
            ):
                raise ValueError("zero expected count is reserved for an unavailable response shell")
            return self
        SectorTradeDateAvailabilityDto(
            tradeDate=self.expectedTradeDate,
            availability=self.expectedAvailability,
            expectedSectorCount=self.expectedSectorCount,
            validSectorCount=self.expectedValidSectorCount,
        )
        if self.observedTradeDate is None:
            if self.observedAvailability is not None or self.observedValidSectorCount != 0:
                raise ValueError("missing observed date cannot have observed coverage")
            return self
        if self.observedAvailability is None:
            raise ValueError("observed date requires observed availability")
        SectorTradeDateAvailabilityDto(
            tradeDate=self.observedTradeDate,
            availability=self.observedAvailability,
            expectedSectorCount=self.expectedSectorCount,
            validSectorCount=self.observedValidSectorCount,
        )
        return self


class SectorAnalysisPageStatusDto(_StrictDto):
    status: SectorAnalysisStatusValue
    displayText: str
    asOfTime: datetime


class SectorAnalysisDebugInfoDto(_StrictDto):
    expectedTradeDate: date
    observedTradeDate: date | None = None
    scope: SectorMomentumScopeValue | None = None
    expectedSectorCount: int = Field(ge=0)
    expectedValidSectorCount: int = Field(ge=0)
    observedValidSectorCount: int = Field(ge=0)
    sampleSectorCodes: list[str] = Field(max_length=5)


class SectorParentSelectionDto(_StrictDto):
    level1Code: str | None = None
    level1Name: str | None = None
    level2Code: str | None = None
    level2Name: str | None = None


class SectorRankingRowDto(_StrictDto):
    listPosition: int = Field(ge=1)
    strengthRank: int | None = Field(default=None, ge=1)
    sectorCode: str
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    parentSectorCode: str | None = None
    parentSectorName: str | None = None
    hierarchyPath: str
    returnPct: float | None = None
    percentile: float | None = Field(default=None, ge=0, le=100)
    canDrillDown: bool

    @model_validator(mode="after")
    def validate_nullable_rank(self) -> "SectorRankingRowDto":
        values = (self.returnPct, self.strengthRank, self.percentile)
        if any(value is None for value in values) and not all(value is None for value in values):
            raise ValueError("returnPct, strengthRank and percentile must be null together")
        if self.returnPct is None and any(value is not None for value in values):
            raise ValueError("null returnPct cannot carry ranking values")
        return self


class SectorRankingDto(_StrictDto):
    formulaKey: Literal["sector-cross-sectional-momentum"]
    formulaVersion: Literal[1]
    hierarchyVersion: str
    scope: SectorMomentumScopeValue
    period: SectorMomentumPeriodValue
    direction: SectorMomentumDirectionValue
    parentSelection: SectorParentSelectionDto
    totalCount: int = Field(ge=0)
    calculableCount: int = Field(ge=0)
    rows: list[SectorRankingRowDto]

    @model_validator(mode="after")
    def validate_rows(self) -> "SectorRankingDto":
        if self.calculableCount > self.totalCount or len(self.rows) != self.totalCount:
            raise ValueError("ranking counts do not match rows")
        if [row.listPosition for row in self.rows] != list(range(1, self.totalCount + 1)):
            raise ValueError("listPosition must be continuous")
        if sum(row.returnPct is not None for row in self.rows) != self.calculableCount:
            raise ValueError("calculableCount does not match rows")
        return self


class SectorMomentumRankingsResponseDto(_StrictDto):
    status: SectorAnalysisStatusValue
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    ranking: SectorRankingDto | None = None
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: SectorAnalysisDebugInfoDto | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "SectorMomentumRankingsResponseDto":
        if self.pageStatus.status != self.status:
            raise ValueError("pageStatus must match response status")
        if self.status in {"READY", "DELAYED"}:
            if self.ranking is None or self.ranking.calculableCount <= 0:
                raise ValueError("READY and DELAYED require calculable ranking rows")
        elif self.ranking is not None:
            raise ValueError("EMPTY and ERROR cannot carry ranking data")
        _validate_response_status(
            status=self.status,
            trading_day=self.tradingDay,
            exception_code=self.exceptionCode,
        )
        return self


class SectorMomentumDetailDto(_StrictDto):
    sectorCode: str
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    hierarchyPath: str
    scopeTitle: str
    returnPct: float | None = None
    percentile: float | None = Field(default=None, ge=0, le=100)
    currentScopeStrengthRank: int | None = Field(default=None, ge=1)
    currentScopeCalculableCount: int = Field(ge=0)
    currentScopeTotalCount: int = Field(ge=0)
    globalLevelStrengthRank: int | None = Field(default=None, ge=1)
    globalLevelCalculableCount: int = Field(ge=0)
    globalLevelTotalCount: int = Field(ge=0)
    parentStrengthRank: int | None = Field(default=None, ge=1)
    parentCalculableCount: int | None = Field(default=None, ge=0)
    parentTotalCount: int | None = Field(default=None, ge=0)
    formulaKey: Literal["sector-cross-sectional-momentum"]
    formulaVersion: Literal[1]
    hierarchyVersion: str


class RollingReturnPointDto(_StrictDto):
    tradeDate: date
    returnPct: float | None = None


class HistoricalRankPointDto(_StrictDto):
    tradeDate: date
    strengthRank: int | None = Field(default=None, ge=1)
    calculableCount: int = Field(ge=0)
    totalCount: int = Field(ge=0)
    percentile: float | None = Field(default=None, ge=0, le=100)


class SectorMomentumHistoryResponseDto(_StrictDto):
    status: SectorAnalysisStatusValue
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    detail: SectorMomentumDetailDto | None = None
    rollingReturns: list[RollingReturnPointDto]
    historicalRanks: list[HistoricalRankPointDto]
    message: str | None = None
    exceptionCode: str | None = None
    debugInfo: SectorAnalysisDebugInfoDto | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "SectorMomentumHistoryResponseDto":
        if self.pageStatus.status != self.status:
            raise ValueError("pageStatus must match response status")
        if self.status in {"READY", "DELAYED"}:
            if self.detail is None:
                raise ValueError("READY and DELAYED require detail")
            return_dates = [point.tradeDate for point in self.rollingReturns]
            rank_dates = [point.tradeDate for point in self.historicalRanks]
            if return_dates != rank_dates or return_dates != sorted(set(return_dates)):
                raise ValueError("history series must share unique ascending dates")
            if not return_dates:
                raise ValueError("READY and DELAYED require history points")
        elif self.detail is not None or self.rollingReturns or self.historicalRanks:
            raise ValueError("EMPTY and ERROR cannot carry history data")
        _validate_response_status(
            status=self.status,
            trading_day=self.tradingDay,
            exception_code=self.exceptionCode,
        )
        return self


def _validate_response_status(
    *,
    status: SectorAnalysisStatusValue,
    trading_day: SectorAnalysisTradingDayDto,
    exception_code: str | None,
) -> None:
    if status == "READY":
        if trading_day.observedTradeDate != trading_day.expectedTradeDate:
            raise ValueError("READY requires matching expected and observed dates")
        if trading_day.expectedAvailability == "MISSING" or exception_code is not None:
            raise ValueError("READY cannot represent missing data or an exception")
    elif status == "DELAYED":
        if (
            trading_day.observedTradeDate is None
            or trading_day.observedTradeDate >= trading_day.expectedTradeDate
            or trading_day.expectedAvailability not in {"PARTIAL", "MISSING"}
            or trading_day.observedAvailability != "COMPLETE"
            or exception_code != "SA_SOURCE_DELAYED"
        ):
            raise ValueError("DELAYED trading-day contract is invalid")
    elif status == "EMPTY":
        if exception_code != "SA_SOURCE_EMPTY":
            raise ValueError("EMPTY requires SA_SOURCE_EMPTY")
    elif status == "ERROR" and exception_code not in {
        "SA_HIERARCHY_UNAVAILABLE",
        "SA_QUERY_FAILED",
    }:
        raise ValueError("ERROR requires a registered error exceptionCode")
