from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_contract import (
    SectorRelativeRotationStatus,
)


Level = Literal[1, 2, 3]
Count = Annotated[int, Field(ge=0, strict=True)]
Percent = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False, strict=True)]
Number = Annotated[float, Field(allow_inf_nan=False, strict=True)]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Evidence = Literal[
    "PRICE_VOLUME",
    "MEMBER_BREADTH",
    "TURNOVER_BREADTH",
    "DUAL_MOMENTUM",
    "RELATIVE_ROTATION",
    "MA20_BREADTH",
]
EVIDENCE_ORDER = (
    "PRICE_VOLUME",
    "MEMBER_BREADTH",
    "TURNOVER_BREADTH",
    "DUAL_MOMENTUM",
    "RELATIVE_ROTATION",
    "MA20_BREADTH",
)
Event = Literal[
    "HEAD_GAINER",
    "HEAD_LOSER",
    "STRENGTHENING",
    "WEAKENING",
    "COUNTER_TREND_STRENGTHENING",
    "RISING_BUT_WEAKENING",
]
MISSING_REASON_FIELDS = (
    ("HISTORY", "missingHistoryCount"),
    ("DATE", "missingDateCount"),
    ("PRICE", "missingPriceCount"),
    ("MEMBER", "missingMemberCount"),
    ("AMOUNT", "missingAmountCount"),
    ("ADJ_FACTOR", "missingAdjFactorCount"),
    ("GROUP_SIZE", "missingGroupSizeCount"),
    ("COVERAGE", "missingCoverageCount"),
    ("PREVIOUS_BATCH", "missingPreviousBatchCount"),
    ("OTHER", "missingOtherCount"),
)


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SectorDailyInsightMetaRequest(_StrictDto):
    market: Literal["CN_A"] = "CN_A"


class SectorDailyInsightSnapshotRequest(SectorDailyInsightMetaRequest):
    tradeDate: date
    industryLevel: Level
    batchKey: UUID
    hierarchyVersion: str = Field(min_length=1, max_length=128)
    debug: Literal["0", "1"] = "0"

    @field_validator("tradeDate", mode="before")
    @classmethod
    def validate_date(cls, value):
        if isinstance(value, str):
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError("tradeDate must use YYYY-MM-DD")
            return parsed
        if type(value) is not date:
            raise ValueError("tradeDate must be a date")
        return value

    @field_validator("industryLevel", mode="before")
    @classmethod
    def validate_level(cls, value):
        if value in ("1", "2", "3"):
            return int(value)
        if type(value) is not int:
            raise ValueError("industryLevel must be 1, 2 or 3")
        return value

    @field_validator("hierarchyVersion")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if value != value.strip() or not value.strip():
            raise ValueError("hierarchyVersion must be nonblank")
        return value


class SectorDailyInsightDateContextDto(_StrictDto):
    requestedTradeDate: date
    observedTradeDate: date | None
    previousTradeDate: date | None
    mode: Literal["AUTO"] = "AUTO"
    isDelayed: bool
    asOf: datetime
    delayReason: str | None


class SectorDailyInsightTradeDateDto(_StrictDto):
    tradeDate: date
    availability: Literal["PUBLISHED", "MISSING"]
    batchKey: UUID | None
    hierarchyVersion: Text | None
    publishedAt: datetime | None

    @model_validator(mode="after")
    def validate_identity(self):
        identity = (self.batchKey, self.hierarchyVersion, self.publishedAt)
        if self.availability == "PUBLISHED" and any(
            value is None for value in identity
        ):
            raise ValueError("published date requires a complete identity")
        if self.availability == "MISSING" and any(
            value is not None for value in identity
        ):
            raise ValueError("missing date cannot carry a batch")
        return self


class SectorDailyInsightMetaResponseDto(_StrictDto):
    status: Literal["READY", "DELAYED", "EMPTY", "ERROR"]
    message: str | None
    exceptionCode: str | None
    contractKey: Literal["sector-daily-insight"] = "sector-daily-insight"
    contractVersion: Literal[1] = 1
    formulaBundleVersion: Text
    templateVersion: Text
    levels: list[Level]
    defaultLevel: Literal[1] = 1
    dateContext: SectorDailyInsightDateContextDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[SectorDailyInsightTradeDateDto]
    defaultTradeDate: date | None
    defaultBatchKey: UUID | None
    hierarchyVersion: Text | None

    @model_validator(mode="after")
    def validate_meta(self):
        if self.levels != [1, 2, 3]:
            raise ValueError("levels must follow the frozen order")
        dates = [day.tradeDate for day in self.tradeDates]
        if dates != sorted(set(dates)) or any(
            not self.coverageStartDate <= day <= self.coverageEndDate for day in dates
        ):
            raise ValueError(
                "coverage dates must be unique, ordered and within coverage"
            )
        context = self.dateContext
        if (
            context.requestedTradeDate != self.coverageEndDate
            or context.observedTradeDate != self.defaultTradeDate
        ):
            raise ValueError("date context must match coverage and default")
        published = [day for day in self.tradeDates if day.availability == "PUBLISHED"]
        if self.defaultTradeDate is None:
            if (
                published
                or self.status != "EMPTY"
                or self.defaultBatchKey is not None
                or self.hierarchyVersion is not None
                or context.isDelayed
            ):
                raise ValueError("empty metadata cannot carry a default batch")
        else:
            if not published or published[-1].tradeDate != self.defaultTradeDate:
                raise ValueError("default must be the latest published date")
            selected = published[-1]
            if (self.defaultBatchKey, self.hierarchyVersion) != (
                selected.batchKey,
                selected.hierarchyVersion,
            ):
                raise ValueError("default batch identity does not match coverage")
            delayed = self.defaultTradeDate < context.requestedTradeDate
            if (
                self.status != ("DELAYED" if delayed else "READY")
                or context.isDelayed != delayed
            ):
                raise ValueError("default status does not match dates")
        if context.previousTradeDate is not None and (
            context.observedTradeDate is None
            or context.previousTradeDate >= context.observedTradeDate
        ):
            raise ValueError("previous date must precede the observed date")
        return self


class SectorDailyInsightSummaryDto(_StrictDto):
    sectorCount: Count
    calculableCount: Count
    missingCount: Count
    upCount: Count
    downCount: Count
    flatCount: Count
    medianChangePct1d: Number | None
    dualMomentumCount20d80: Count
    leadingImprovingCount20d5d: Count
    priceVolumeJointCount20d: Count
    breadthUpShareAbove50Count: Count
    missingHistoryCount: Count
    missingDateCount: Count
    missingPriceCount: Count
    missingMemberCount: Count
    missingAmountCount: Count
    missingAdjFactorCount: Count
    missingGroupSizeCount: Count
    missingCoverageCount: Count
    missingPreviousBatchCount: Count
    missingOtherCount: Count

    @model_validator(mode="after")
    def validate_counts(self):
        if (
            self.sectorCount != self.calculableCount + self.missingCount
            or self.calculableCount != self.upCount + self.downCount + self.flatCount
        ):
            raise ValueError("summary counts must be conserved")
        if (self.calculableCount > 0) != (self.medianChangePct1d is not None):
            raise ValueError("median availability must match calculable count")
        if any(
            value > self.sectorCount
            for key, value in self.model_dump().items()
            if key.endswith("Count")
        ):
            raise ValueError("summary count cannot exceed the sector pool")
        # Reasons cover independent methods: their sum need not equal missingCount.
        return self


class SectorDailyInsightItemDto(_StrictDto):
    sectorCode: str = Field(pattern=r"^BK[0-9]{4}\.DC$")
    sectorName: Text
    hierarchyPath: Text
    industryLevel: Level
    eventType: Event
    returnPct1d: Number | None
    returnPct5d: Number | None
    returnPct20d: Number | None
    currentRank20d: Annotated[int, Field(ge=1, strict=True)] | None
    currentRankableCount20d: Count | None
    currentPercentile20d: Percent | None
    previousRank20d: Annotated[int, Field(ge=1, strict=True)] | None
    previousRankableCount20d: Count | None
    previousPercentile20d: Percent | None
    rankChange: Annotated[int, Field(strict=True)] | None
    percentileChangePp: (
        Annotated[float, Field(ge=-100, le=100, allow_inf_nan=False, strict=True)]
        | None
    )
    priceVolumeStateCurrent: (
        Literal["JOINT", "PRICE_ONLY", "AMOUNT_ONLY", "NEUTRAL"] | None
    )
    priceVolumeStatePrevious: (
        Literal["JOINT", "PRICE_ONLY", "AMOUNT_ONLY", "NEUTRAL"] | None
    )
    dualQualification20d80Current: (
        Literal["QUALIFIED", "NOT_QUALIFIED", "NOT_EVALUATED"] | None
    )
    dualQualification20d80Previous: (
        Literal["QUALIFIED", "NOT_QUALIFIED", "NOT_EVALUATED"] | None
    )
    rotationStatus20dCurrent: SectorRelativeRotationStatus | None
    rotationStatus20dPrevious: SectorRelativeRotationStatus | None
    memberUpPctCurrent: Percent | None
    memberUpPctPrevious: Percent | None
    turnoverUpPctCurrent: Percent | None
    turnoverUpPctPrevious: Percent | None
    ma20AbovePctCurrent: Percent | None
    ma20AbovePctPrevious: Percent | None
    primaryEvidenceType: Evidence | None
    secondaryEvidenceTypes: list[Evidence] = Field(max_length=2)
    templateKey: Literal["sector-daily-insight"]
    templateVersion: Text
    renderedText: Text

    @model_validator(mode="after")
    def validate_facts(self):
        for prefix in ("current", "previous"):
            rank = getattr(self, f"{prefix}Rank20d")
            count = getattr(self, f"{prefix}RankableCount20d")
            percentile = getattr(self, f"{prefix}Percentile20d")
            if (rank is None) != (percentile is None) or (
                rank is not None and (count is None or not 1 <= rank <= count)
            ):
                raise ValueError("rank, denominator and percentile must agree")
        have_ranks = (
            self.currentRank20d is not None and self.previousRank20d is not None
        )
        if have_ranks:
            if self.rankChange != self.previousRank20d - self.currentRank20d:
                raise ValueError("rankChange must use the two published ranks")
            delta = Decimal(str(self.currentPercentile20d)) - Decimal(
                str(self.previousPercentile20d)
            )
            if (
                self.percentileChangePp is None
                or Decimal(str(self.percentileChangePp)) != delta
            ):
                raise ValueError(
                    "percentileChangePp must equal the published difference"
                )
        elif self.rankChange is not None or self.percentileChangePp is not None:
            raise ValueError("missing comparison cannot carry changes")
        if self.eventType not in ("HEAD_GAINER", "HEAD_LOSER") and not have_ranks:
            raise ValueError("change events require both dates")
        evidence = (
            [self.primaryEvidenceType] if self.primaryEvidenceType else []
        ) + self.secondaryEvidenceTypes
        if len(evidence) > 2 or evidence != sorted(
            set(evidence), key=EVIDENCE_ORDER.index
        ):
            raise ValueError("evidence must be unique, ordered and at most two total")
        if self.secondaryEvidenceTypes and self.primaryEvidenceType is None:
            raise ValueError("secondary evidence requires primary evidence")
        return self


class SectorDailyInsightMissingReasonDto(_StrictDto):
    reasonCode: Text
    count: Count


class SectorDailyInsightSnapshotResponseDto(_StrictDto):
    status: Literal["READY", "EMPTY", "ERROR"]
    message: str | None
    exceptionCode: str | None
    requestedTradeDate: date
    observedTradeDate: date
    previousTradeDate: date | None
    batchKey: UUID
    hierarchyVersion: Text
    formulaBundleVersion: Text
    templateVersion: Text
    publishedAt: datetime
    calculatedAt: datetime
    industryLevel: Level
    summary: SectorDailyInsightSummaryDto
    headGainers: list[SectorDailyInsightItemDto]
    headLosers: list[SectorDailyInsightItemDto]
    strengthening: list[SectorDailyInsightItemDto]
    weakening: list[SectorDailyInsightItemDto]
    missingSectorCount: Count
    missingReasonCounts: list[SectorDailyInsightMissingReasonDto]

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.requestedTradeDate != self.observedTradeDate:
            raise ValueError("snapshot cannot fall back")
        if (
            self.previousTradeDate is not None
            and self.previousTradeDate >= self.observedTradeDate
        ):
            raise ValueError("previous date must precede current date")
        if (
            self.missingSectorCount != self.summary.missingCount
            or len(self.headGainers) != self.summary.upCount
            or len(self.headLosers) != self.summary.downCount
        ):
            raise ValueError("full lists and missing count must match summary")
        if self.status != ("READY" if self.has_display_facts() else "EMPTY"):
            raise ValueError("status must reflect usable facts")
        for rows, events, direction in (
            (self.headGainers, {"HEAD_GAINER"}, -1),
            (self.headLosers, {"HEAD_LOSER"}, 1),
            (self.strengthening, {"STRENGTHENING", "COUNTER_TREND_STRENGTHENING"}, -1),
            (self.weakening, {"WEAKENING", "RISING_BUT_WEAKENING"}, 1),
        ):
            if (
                len({row.sectorCode for row in rows}) != len(rows)
                or len(rows) > self.summary.sectorCount
            ):
                raise ValueError("each full list must contain unique industries")
            keys = []
            for row in rows:
                if (
                    row.industryLevel != self.industryLevel
                    or row.templateVersion != self.templateVersion
                    or row.eventType not in events
                ):
                    raise ValueError(
                        "item identity or event disagrees with its snapshot"
                    )
                head = row.eventType.startswith("HEAD_")
                value = row.returnPct1d if head else row.percentileChangePp
                if value is None or direction * value >= 0:
                    raise ValueError("event direction must match its fact")
                if not head:
                    entered = (
                        (row.previousPercentile20d < 80 <= row.currentPercentile20d)
                        if direction == -1
                        else (
                            row.previousPercentile20d > 20 >= row.currentPercentile20d
                        )
                    )
                    if abs(value) < 10 and not entered:
                        raise ValueError(
                            "change event does not meet the frozen threshold"
                        )
                    countertrend = (
                        (row.returnPct1d is not None and row.returnPct1d < 0)
                        if direction == -1
                        else (row.returnPct1d is not None and row.returnPct1d > 0)
                    )
                    special_event = (
                        "COUNTER_TREND_STRENGTHENING"
                        if direction == -1
                        else "RISING_BUT_WEAKENING"
                    )
                    if (row.eventType == special_event) != countertrend:
                        raise ValueError(
                            "countertrend label must match the one-day return"
                        )
                keys.append((direction * value, row.sectorCode))
            if keys != sorted(keys):
                raise ValueError("full list must retain the published order")
        if self.summary.missingPreviousBatchCount and (
            self.strengthening or self.weakening
        ):
            raise ValueError("missing previous batch cannot yield change events")
        expected_reasons = [
            (code, getattr(self.summary, field))
            for code, field in MISSING_REASON_FIELDS
            if getattr(self.summary, field)
        ]
        if [
            (row.reasonCode, row.count) for row in self.missingReasonCounts
        ] != expected_reasons:
            raise ValueError("missing reasons must match the ordered summary counts")
        rows = self.headGainers + self.headLosers + self.strengthening + self.weakening
        facts_by_sector = {}
        for row in rows:
            facts = row.model_dump(exclude={"eventType", "renderedText"})
            if (
                row.sectorCode in facts_by_sector
                and facts_by_sector[row.sectorCode] != facts
            ):
                raise ValueError(
                    "one industry cannot carry different facts across panels"
                )
            facts_by_sector[row.sectorCode] = facts
        if (
            len(
                {
                    row.currentRankableCount20d
                    for row in rows
                    if row.currentRankableCount20d is not None
                }
            )
            > 1
        ):
            raise ValueError("current rows must share one level denominator")
        if (
            len(
                {
                    row.previousRankableCount20d
                    for row in rows
                    if row.previousRankableCount20d is not None
                }
            )
            > 1
        ):
            raise ValueError("previous rows must share one level denominator")
        for row in rows:
            if any(
                count is not None and count > self.summary.sectorCount
                for count in (row.currentRankableCount20d, row.previousRankableCount20d)
            ):
                raise ValueError("rankable denominator cannot exceed the level pool")
        return self

    def has_display_facts(self) -> bool:
        return bool(
            self.summary.calculableCount
            or self.headGainers
            or self.headLosers
            or self.strengthening
            or self.weakening
            or self.summary.dualMomentumCount20d80
            or self.summary.leadingImprovingCount20d5d
            or self.summary.priceVolumeJointCount20d
            or self.summary.breadthUpShareAbove50Count
        )
