from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PageStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
SessionStatusValue = Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
SeverityValue = Literal["info", "warn", "error"]
DirectionValue = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]
SectorTypeValue = Literal["INDUSTRY", "CONCEPT", "REGION"]
ToneValue = Literal["UP", "DOWN", "NEUTRAL"]


class TradingDayDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    prevTradeDate: date | None = None
    market: Literal["CN_A"]
    isTradingDay: bool
    sessionStatus: SessionStatusValue
    timezone: Literal["Asia/Shanghai"]


class PageStatusDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PageStatusValue
    displayText: str
    asOfTime: datetime | None = None


class SectorSubjectDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjectType: Literal["sector"]
    subjectCode: str
    subjectName: str | None = None
    sectorType: SectorTypeValue


class SectorMetricDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | None = None
    displayText: str
    unit: Literal["%"] | None = None
    direction: DirectionValue


class SectorLeadingStockDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stockCode: str | None = None
    stockName: str | None = None
    changePct: float | None = None


class SectorRankRowDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    subject: SectorSubjectDto
    metric: SectorMetricDto
    leadingStock: SectorLeadingStockDto | None = None


class SectorRankColumnDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columnKey: str
    title: str
    tone: ToneValue
    metricLabel: str
    rows: list[SectorRankRowDto]


class SectorHeatMapItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: SectorSubjectDto
    changePct: float | None = None
    direction: DirectionValue
    riseStockCount: int | None = None
    fallStockCount: int | None = None
    leadingStock: SectorLeadingStockDto | None = None


class SectorOverviewPayloadDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    status: PageStatusValue
    columns: list[SectorRankColumnDto]
    heatMapItems: list[SectorHeatMapItemDto]


class ModuleStatusItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moduleKey: str
    expectedTradeDate: date
    observedTradeDate: date | None = None
    lagDays: int | None = None
    status: PageStatusValue
    note: str | None = None


class ModuleExceptionItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    code: str
    severity: SeverityValue
    message: str
    details: dict[str, str | int | float | None] | None = None


class SectorOverviewDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class SectorOverviewResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    sectorOverview: SectorOverviewPayloadDto
    debugInfo: SectorOverviewDebugInfoDto | None = None
