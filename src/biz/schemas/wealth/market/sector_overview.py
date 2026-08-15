from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


PageStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
SessionStatusValue = Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
SeverityValue = Literal["info", "warn", "error"]
DirectionValue = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]
SectorTypeValue = Literal["INDUSTRY", "CONCEPT", "REGION"]
IndustryRankMetricValue = Literal["CHANGE_PCT_UP", "CHANGE_PCT_DOWN", "MAIN_NET_INFLOW", "UP_COUNT"]
ConceptRankMetricValue = Literal["HEAT_SCORE", "HEAT_DELTA_1D", "CHANGE_PCT", "MAIN_NET_INFLOW"]
RegionRankMetricValue = Literal["CHANGE_PCT", "MAIN_NET_INFLOW", "UP_COUNT"]
HeatStatusValue = Literal["VALID", "INVALID"]
ConceptRankHeatStatusValue = Literal["VALID", "INVALID", "UNKNOWN"]
HeatLevelValue = Literal["BOILING", "HOT", "ACTIVE", "NONE"]
HeatTrendValue = Literal["HEATING", "STABLE", "COOLING", "UNKNOWN"]
HeatInvalidReasonValue = Literal[
    "MEMBER_COUNT_LOW",
    "QUOTE_ELIGIBLE_COUNT_ZERO",
    "QUOTE_COVERAGE_LOW",
    "HISTORY_INSUFFICIENT",
    "FEATURE_MISSING",
]


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TradingDayDto(_StrictDto):
    tradeDate: date
    prevTradeDate: date | None = None
    market: Literal["CN_A"]
    isTradingDay: bool
    sessionStatus: SessionStatusValue
    timezone: Literal["Asia/Shanghai"]


class PageStatusDto(_StrictDto):
    status: PageStatusValue
    displayText: str
    asOfTime: datetime | None = None


class MetricValueDto(_StrictDto):
    value: float | int | None = None
    displayText: str
    direction: DirectionValue


class SectorLeaderStockDto(_StrictDto):
    stockCode: str | None = None
    stockName: str | None = None
    changePct: float | None = None


class SectorMemberStockDto(_StrictDto):
    stockCode: str
    stockName: str | None = None
    changePct: float | None = None
    direction: DirectionValue


class ConceptHeatDto(_StrictDto):
    heatStatus: HeatStatusValue
    invalidReason: HeatInvalidReasonValue | None = None
    heatScore: float | None = None
    heatLevel: HeatLevelValue
    heatDelta1d: float | None = None
    heatTrend: HeatTrendValue
    heatRank: int | None = None
    scoreVersion: str
    tradeDate: date
    calculatedAt: datetime


class ConceptHeatPointDto(_StrictDto):
    tradeDate: date
    heatScore: float | None = None
    heatRank: int | None = None
    heatLevel: HeatLevelValue


class SectorMetricsDto(_StrictDto):
    changePct: float | None = None
    upCount: int | None = None
    downCount: int | None = None
    sourceMemberCount: int = Field(ge=0)
    memberCount: int = Field(ge=0)
    suspendedCount: int = Field(ge=0)
    quoteEligibleCount: int = Field(ge=0)
    validQuoteCount: int = Field(ge=0)
    missingQuoteCount: int = Field(ge=0)
    mainNetInflow: float | None = None
    turnoverAmount: float | None = None
    quoteCoverage: float | None = Field(default=None, ge=0, le=1)


class SectorDetailDto(_StrictDto):
    sectorCode: str
    sectorName: str
    sectorType: SectorTypeValue
    hierarchyPath: str | None = Field(default=None, exclude_if=lambda value: value is None)
    metrics: SectorMetricsDto
    heat: ConceptHeatDto | None = Field(default=None, exclude_if=lambda value: value is None)
    heatHistory: list[ConceptHeatPointDto] | None = Field(default=None, exclude_if=lambda value: value is None)
    leader: SectorLeaderStockDto | None = None
    members: list[SectorMemberStockDto]


class IndustryRankItemDto(_StrictDto):
    rank: int = Field(ge=1)
    sectorCode: str
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    primaryMetric: MetricValueDto
    leader: SectorLeaderStockDto | None = None
    selected: bool


class ConceptRankItemDto(_StrictDto):
    rank: int = Field(ge=1)
    sectorCode: str
    sectorName: str
    changePct: MetricValueDto
    mainNetInflow: MetricValueDto
    leader: SectorLeaderStockDto | None = None
    heatStatus: ConceptRankHeatStatusValue
    heatLevel: HeatLevelValue
    heatTrend: HeatTrendValue
    heatScore: MetricValueDto
    heatDelta1d: MetricValueDto
    selected: bool


class RegionRankItemDto(_StrictDto):
    rank: int = Field(ge=1)
    sectorCode: str
    sectorName: str
    changePct: MetricValueDto
    mainNetInflow: MetricValueDto
    memberCount: int | None = Field(default=None, ge=0)
    upCount: int | None = Field(default=None, ge=0)
    leader: SectorLeaderStockDto | None = None
    selected: bool


class IndustrySelectionDto(_StrictDto):
    level1Code: str | None = None
    level2Code: str | None = None
    level3Code: str | None = None
    detailSectorCode: str | None = None


class IndustryRankColumnDto(_StrictDto):
    level: Literal[1, 2, 3]
    parentSectorCode: str | None = None
    rows: list[IndustryRankItemDto]


class IndustryWorkspaceDto(_StrictDto):
    rankMetric: IndustryRankMetricValue
    selection: IndustrySelectionDto
    columns: list[IndustryRankColumnDto]
    detail: SectorDetailDto | None = None


class ConceptWorkspaceDto(_StrictDto):
    rankMetric: ConceptRankMetricValue
    selectedConceptCode: str | None = None
    rows: list[ConceptRankItemDto]
    detail: SectorDetailDto | None = None


class RegionWorkspaceDto(_StrictDto):
    rankMetric: RegionRankMetricValue
    selectedRegionCode: str | None = None
    rows: list[RegionRankItemDto]
    detail: SectorDetailDto | None = None


class _SectorOverviewPayloadBaseDto(_StrictDto):
    tradeDate: date
    status: PageStatusValue
    view: SectorTypeValue
    asOf: datetime


class IndustrySectorOverviewPayloadDto(_SectorOverviewPayloadBaseDto):
    view: Literal["INDUSTRY"]
    industry: IndustryWorkspaceDto


class ConceptSectorOverviewPayloadDto(_SectorOverviewPayloadBaseDto):
    view: Literal["CONCEPT"]
    concept: ConceptWorkspaceDto


class RegionSectorOverviewPayloadDto(_SectorOverviewPayloadBaseDto):
    view: Literal["REGION"]
    region: RegionWorkspaceDto


SectorOverviewPayloadDto = Annotated[
    IndustrySectorOverviewPayloadDto | ConceptSectorOverviewPayloadDto | RegionSectorOverviewPayloadDto,
    Field(discriminator="view"),
]


class ModuleStatusItemDto(_StrictDto):
    moduleKey: str
    expectedTradeDate: date
    observedTradeDate: date | None = None
    lagDays: int | None = None
    status: PageStatusValue
    note: str | None = None


class ModuleExceptionItemDto(_StrictDto):
    module: str
    code: str
    severity: SeverityValue
    message: str
    details: dict[str, str | int | float | None] | None = None


class SectorOverviewDebugInfoDto(_StrictDto):
    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class SectorOverviewResponseDto(_StrictDto):
    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    sectorOverview: SectorOverviewPayloadDto
    debugInfo: SectorOverviewDebugInfoDto | None = Field(default=None, exclude_if=lambda value: value is None)
