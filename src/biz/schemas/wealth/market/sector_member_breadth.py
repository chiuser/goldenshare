from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.biz.schemas.wealth.market.sector_analysis import (
    SectorHierarchyDto,
    SectorMomentumScopeValue,
    SectorParentSelectionDto,
    SectorTradeDateAvailabilityDto,
)


SectorMemberBreadthMetricValue = Literal["MEMBER_COUNT", "TURNOVER", "MA_POSITION"]
SectorMemberBreadthReasonValue = Literal[
    "SOURCE_MEMBER_EMPTY",
    "MARKET_ROW_MISSING",
    "PCT_CHANGE_MISSING",
    "AMOUNT_MISSING",
    "AMOUNT_NON_POSITIVE",
    "ADJ_FACTOR_MISSING",
    "ADJ_FACTOR_NON_POSITIVE",
    "MA_HISTORY_INSUFFICIENT",
    "MINIMUM_COUNT_NOT_MET",
    "COVERAGE_NOT_MET",
]


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SectorMemberBreadthDateContextDto(_StrictDto):
    expectedTradeDate: date
    defaultTradeDate: date | None = None
    defaultStatus: Literal["READY", "DELAYED", "EMPTY"]
    displayText: str = Field(min_length=1)


class SectorMemberBreadthDefaultsDto(_StrictDto):
    scope: Literal["LEVEL_1"]
    direction: Literal["UP"]
    metric: Literal["MEMBER_COUNT"]
    maPeriod: Literal[20]
    historyRange: Literal[20]


class SectorMemberBreadthMetaResponseDto(_StrictDto):
    formulaKey: Literal["sector-member-breadth"]
    formulaVersion: Literal[1]
    dateCoverageBasis: Literal["INDUSTRY_DAILY"]
    dateContext: SectorMemberBreadthDateContextDto
    hierarchy: SectorHierarchyDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[SectorTradeDateAvailabilityDto]
    scopes: list[SectorMomentumScopeValue]
    directions: list[Literal["UP", "DOWN"]]
    metrics: list[SectorMemberBreadthMetricValue]
    maPeriods: list[Literal[5, 10, 15, 20, 30, 60]]
    historyRanges: list[Literal[20, 30, 60]]
    minimumCalculableCount: Literal[5]
    minimumCoveragePct: Literal[80]
    defaults: SectorMemberBreadthDefaultsDto

    @model_validator(mode="after")
    def validate_frozen_contract(self) -> "SectorMemberBreadthMetaResponseDto":
        if self.scopes != [
            "LEVEL_1",
            "LEVEL_2",
            "LEVEL_3",
            "LEVEL_1_CHILDREN",
            "LEVEL_2_CHILDREN",
        ]:
            raise ValueError("member breadth scopes must match the frozen order")
        if self.directions != ["UP", "DOWN"]:
            raise ValueError("member breadth directions must match the frozen order")
        if self.metrics != ["MEMBER_COUNT", "TURNOVER", "MA_POSITION"]:
            raise ValueError("member breadth metrics must match the frozen order")
        if self.maPeriods != [5, 10, 15, 20, 30, 60]:
            raise ValueError("member breadth MA periods must match the frozen order")
        if self.historyRanges != [20, 30, 60]:
            raise ValueError(
                "member breadth history ranges must match the frozen order"
            )
        dates = [item.tradeDate for item in self.tradeDates]
        if (
            not dates
            or dates != sorted(set(dates))
            or dates[0] != self.coverageStartDate
            or dates[-1] != self.coverageEndDate
        ):
            raise ValueError("member breadth tradeDates must span public coverage")
        if self.dateContext.expectedTradeDate != self.coverageEndDate:
            raise ValueError("member breadth expected date must equal coverage end")
        complete_dates = [
            item.tradeDate
            for item in self.tradeDates
            if item.availability == "COMPLETE"
        ]
        expected = self.tradeDates[-1]
        default_date = self.dateContext.defaultTradeDate
        if expected.availability == "COMPLETE":
            if (
                default_date != expected.tradeDate
                or self.dateContext.defaultStatus != "READY"
            ):
                raise ValueError("complete expected date must be the READY default")
        elif complete_dates:
            if (
                default_date != complete_dates[-1]
                or self.dateContext.defaultStatus != "DELAYED"
            ):
                raise ValueError("incomplete expected date must use latest COMPLETE")
        elif default_date is not None or self.dateContext.defaultStatus != "EMPTY":
            raise ValueError("missing COMPLETE coverage must produce an EMPTY default")
        return self


class SectorMemberBreadthAvailabilityDto(_StrictDto):
    metric: SectorMemberBreadthMetricValue
    calculableSectorCount: int = Field(ge=0)
    eligibleSectorCount: int = Field(ge=0)
    status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    reasonCodes: list[SectorMemberBreadthReasonValue]


class SectorMemberBreadthRankingRowDto(_StrictDto):
    listPosition: int = Field(ge=1)
    rank: int | None = Field(default=None, ge=1)
    rankTotal: int | None = Field(default=None, ge=1)
    sectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    hierarchyPath: str
    sourceMemberCount: int = Field(ge=0)
    calculableCount: int = Field(ge=0)
    coveragePct: float = Field(ge=0, le=100)
    metricValuePct: float | None = Field(default=None, ge=0, le=100)
    qualificationStatus: Literal["ELIGIBLE", "INELIGIBLE"]
    reasonCodes: list[SectorMemberBreadthReasonValue]

    @field_validator("coveragePct", "metricValuePct")
    @classmethod
    def validate_finite_number(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("member breadth ranking values must be finite")
        return value

    @model_validator(mode="after")
    def validate_rank_shape(self) -> "SectorMemberBreadthRankingRowDto":
        if self.calculableCount > self.sourceMemberCount:
            raise ValueError("calculableCount cannot exceed sourceMemberCount")
        rank_values = (self.rank, self.rankTotal, self.metricValuePct)
        if any(value is None for value in rank_values) and not all(
            value is None for value in rank_values
        ):
            raise ValueError("rank, rankTotal and metricValuePct must be null together")
        if self.qualificationStatus == "ELIGIBLE" and self.rank is None:
            raise ValueError("eligible ranking row requires ranking values")
        if self.qualificationStatus == "INELIGIBLE" and self.rank is not None:
            raise ValueError("ineligible ranking row cannot carry ranking values")
        return self


class SectorMemberBreadthRankingsResponseDto(_StrictDto):
    status: Literal["READY", "EMPTY", "ERROR"]
    message: str | None = None
    exceptionCode: str | None = None
    tradeDate: date
    hierarchyVersion: str = Field(min_length=1, max_length=128)
    formulaKey: Literal["sector-member-breadth"]
    formulaVersion: Literal[1]
    scope: SectorMomentumScopeValue
    parentSelection: SectorParentSelectionDto
    direction: Literal["UP", "DOWN"]
    metric: SectorMemberBreadthMetricValue
    maPeriod: Literal[5, 10, 15, 20, 30, 60]
    totalSectorCount: int = Field(ge=0)
    eligibleSectorCount: int = Field(ge=0)
    ineligibleSectorCount: int = Field(ge=0)
    availability: SectorMemberBreadthAvailabilityDto
    defaultSelectedSectorCode: str | None = Field(
        default=None, pattern=r"^BK[0-9]{4}\.DC$"
    )
    rows: list[SectorMemberBreadthRankingRowDto]

    @model_validator(mode="after")
    def validate_response(self) -> "SectorMemberBreadthRankingsResponseDto":
        if self.availability.metric != self.metric:
            raise ValueError("availability metric must match the request metric")
        if (
            self.eligibleSectorCount + self.ineligibleSectorCount
            != self.totalSectorCount
        ):
            raise ValueError("member breadth sector counts do not balance")
        if len(self.rows) != self.totalSectorCount:
            raise ValueError("member breadth rankings must return the full list")
        if [row.listPosition for row in self.rows] != list(
            range(1, self.totalSectorCount + 1)
        ):
            raise ValueError("member breadth listPosition must be continuous")
        if (
            sum(row.qualificationStatus == "ELIGIBLE" for row in self.rows)
            != self.eligibleSectorCount
        ):
            raise ValueError("eligibleSectorCount does not match rows")
        if self.availability.eligibleSectorCount != self.eligibleSectorCount:
            raise ValueError("availability eligible count does not match response")
        if self.availability.calculableSectorCount > self.totalSectorCount:
            raise ValueError("calculable sector count exceeds the comparison pool")
        expected_availability = (
            "UNAVAILABLE"
            if self.availability.calculableSectorCount == 0
            else "AVAILABLE"
            if self.availability.calculableSectorCount == self.totalSectorCount
            else "PARTIAL"
        )
        if self.availability.status != expected_availability:
            raise ValueError("member breadth availability status is inconsistent")
        ranked_rows = [row for row in self.rows if row.rank is not None]
        if ranked_rows:
            rank_total = len(ranked_rows)
            previous_value: float | None = None
            previous_rank = 0
            for position, row in enumerate(ranked_rows, start=1):
                if row.rankTotal != rank_total:
                    raise ValueError("rankTotal must count eligible sectors")
                expected_rank = (
                    previous_rank if row.metricValuePct == previous_value else position
                )
                if row.rank != expected_rank:
                    raise ValueError(
                        "member breadth ranks must use competition ranking"
                    )
                previous_value = row.metricValuePct
                previous_rank = row.rank
            if [row.metricValuePct for row in ranked_rows] != sorted(
                (row.metricValuePct for row in ranked_rows),
                reverse=True,
            ):
                raise ValueError("eligible member breadth rows must be descending")
            if self.defaultSelectedSectorCode != ranked_rows[0].sectorCode:
                raise ValueError("default selection must be the first eligible sector")
        elif self.defaultSelectedSectorCode is not None:
            raise ValueError("no eligible row means no default selection")
        if self.status == "READY":
            if (
                self.availability.calculableSectorCount <= 0
                or self.exceptionCode is not None
            ):
                raise ValueError("READY requires calculable sectors and no exception")
        elif self.status == "EMPTY":
            if (
                self.availability.calculableSectorCount != 0
                or self.exceptionCode != "SA_SOURCE_EMPTY"
            ):
                raise ValueError("EMPTY rankings require unavailable source facts")
        elif self.exceptionCode not in {
            "SA_HIERARCHY_UNAVAILABLE",
            "SA_BREADTH_QUERY_FAILED",
        }:
            raise ValueError("ERROR rankings require an approved query exception")
        return self


class SectorMemberBreadthCompositionDto(_StrictDto):
    metric: SectorMemberBreadthMetricValue
    sourceCount: int = Field(ge=0)
    calculableCount: int = Field(ge=0)
    coveragePct: float = Field(ge=0, le=100)
    eligible: bool
    positiveCount: int = Field(ge=0)
    neutralCount: int = Field(ge=0)
    negativeCount: int = Field(ge=0)
    positivePct: float | None = Field(default=None, ge=0, le=100)
    neutralPct: float | None = Field(default=None, ge=0, le=100)
    negativePct: float | None = Field(default=None, ge=0, le=100)
    reasonCodes: list[SectorMemberBreadthReasonValue]

    @field_validator("coveragePct", "positivePct", "neutralPct", "negativePct")
    @classmethod
    def validate_finite_number(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("member breadth composition values must be finite")
        return value

    @model_validator(mode="after")
    def validate_composition(self) -> "SectorMemberBreadthCompositionDto":
        if self.calculableCount > self.sourceCount:
            raise ValueError("composition calculableCount exceeds sourceCount")
        if (
            self.positiveCount + self.neutralCount + self.negativeCount
            != self.calculableCount
        ):
            raise ValueError(
                "composition directional counts must match calculableCount"
            )
        percentages = (self.positivePct, self.neutralPct, self.negativePct)
        if any(value is None for value in percentages) and not all(
            value is None for value in percentages
        ):
            raise ValueError("composition percentages must be null together")
        if percentages[0] is not None and abs(sum(percentages) - 100) > 1e-6:  # type: ignore[arg-type]
            raise ValueError("composition percentages must sum to 100")
        return self


class SectorMemberBreadthTrendPointDto(_StrictDto):
    tradeDate: date
    memberPct: float | None = Field(default=None, ge=0, le=100)
    turnoverPct: float | None = Field(default=None, ge=0, le=100)
    maPositionPct: float | None = Field(default=None, ge=0, le=100)
    memberReasonCodes: list[SectorMemberBreadthReasonValue]
    turnoverReasonCodes: list[SectorMemberBreadthReasonValue]
    maPositionReasonCodes: list[SectorMemberBreadthReasonValue]

    @field_validator("memberPct", "turnoverPct", "maPositionPct")
    @classmethod
    def validate_finite_number(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("member breadth trend values must be finite")
        return value


class SectorMemberBreadthMemberRowDto(_StrictDto):
    stockName: str | None = None
    stockCode: str = Field(pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
    dailyPctChg: float | None = None
    amountThousandYuan: float | None = Field(default=None, ge=0)
    amountContributionPct: float | None = Field(default=None, ge=0, le=100)
    maRelation: Literal["ABOVE", "EQUAL", "BELOW"] | None = None
    maDistancePct: float | None = None
    reasonCodes: list[SectorMemberBreadthReasonValue]

    @field_validator(
        "dailyPctChg",
        "amountThousandYuan",
        "amountContributionPct",
        "maDistancePct",
    )
    @classmethod
    def validate_finite_number(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("member breadth member values must be finite")
        return value

    @model_validator(mode="after")
    def validate_ma_shape(self) -> "SectorMemberBreadthMemberRowDto":
        if (self.maRelation is None) != (self.maDistancePct is None):
            raise ValueError("maRelation and maDistancePct must be null together")
        return self


class SectorMemberBreadthDetailsResponseDto(_StrictDto):
    status: Literal["READY", "EMPTY", "ERROR"]
    message: str | None = None
    exceptionCode: str | None = None
    tradeDate: date
    hierarchyVersion: str = Field(min_length=1, max_length=128)
    formulaKey: Literal["sector-member-breadth"]
    formulaVersion: Literal[1]
    sectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    hierarchyPath: str
    direction: Literal["UP", "DOWN"]
    maPeriod: Literal[5, 10, 15, 20, 30, 60]
    historyRange: Literal[20, 30, 60]
    compositions: list[SectorMemberBreadthCompositionDto]
    trend: list[SectorMemberBreadthTrendPointDto]
    members: list[SectorMemberBreadthMemberRowDto]

    @model_validator(mode="after")
    def validate_response(self) -> "SectorMemberBreadthDetailsResponseDto":
        if self.status == "READY":
            if self.exceptionCode is not None:
                raise ValueError("READY details cannot carry an exception")
            if [item.metric for item in self.compositions] != [
                "MEMBER_COUNT",
                "TURNOVER",
                "MA_POSITION",
            ]:
                raise ValueError("details compositions must use the frozen order")
            dates = [item.tradeDate for item in self.trend]
            if (
                not dates
                or dates != sorted(set(dates))
                or len(dates) > self.historyRange
                or dates[-1] != self.tradeDate
            ):
                raise ValueError("details trend must end on tradeDate")
            codes = [item.stockCode for item in self.members]
            if len(codes) != len(set(codes)):
                raise ValueError("details members must be unique")
            expected_members = sorted(
                self.members,
                key=lambda row: _member_sort_key(row, direction=self.direction),
            )
            if self.members != expected_members:
                raise ValueError("details members do not follow the frozen order")
        elif self.status == "EMPTY":
            if (
                self.exceptionCode != "SA_BREADTH_SOURCE_EMPTY"
                or self.compositions
                or self.trend
                or self.members
            ):
                raise ValueError("EMPTY details require an empty source shell")
        elif (
            self.exceptionCode
            not in {"SA_HIERARCHY_UNAVAILABLE", "SA_BREADTH_QUERY_FAILED"}
            or self.compositions
            or self.trend
            or self.members
        ):
            raise ValueError("ERROR details require an approved safe empty shell")
        return self


def _member_sort_key(
    row: SectorMemberBreadthMemberRowDto,
    *,
    direction: Literal["UP", "DOWN"],
) -> tuple[bool, float, bool, float, str]:
    daily_sort = (
        0.0
        if row.dailyPctChg is None
        else -row.dailyPctChg
        if direction == "UP"
        else row.dailyPctChg
    )
    amount_sort = 0.0 if row.amountThousandYuan is None else -row.amountThousandYuan
    return (
        row.dailyPctChg is None,
        daily_sort,
        row.amountThousandYuan is None,
        amount_sort,
        row.stockCode,
    )
