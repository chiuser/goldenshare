from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PageStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
SessionStatusValue = Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
DirectionValue = Literal["UP", "DOWN", "FLAT", "UNKNOWN"]
SeverityValue = Literal["info", "warn", "error"]


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


class SubjectRefDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjectType: Literal["index"]
    subjectCode: str
    subjectName: str | None = None


class MajorIndexRowDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: SubjectRefDto
    point: float | None = None
    change: float | None = None
    changePct: float | None = None
    amount: float | None = None
    direction: DirectionValue


class MajorIndicesDefinitionDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definitionKey: str
    version: str
    fixedCount: Literal[10] = 10


class MajorIndicesPayloadDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: MajorIndicesDefinitionDto
    rows: list[MajorIndexRowDto] = Field(min_length=10, max_length=10)


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


class MajorIndicesDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class MajorIndicesResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    majorIndices: MajorIndicesPayloadDto
    debugInfo: MajorIndicesDebugInfoDto | None = None

