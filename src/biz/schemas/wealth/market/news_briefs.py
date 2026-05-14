from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PageStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
SessionStatusValue = Literal["PRE_OPEN", "TRADING", "BREAK", "CLOSED"]
SeverityValue = Literal["info", "warn", "error"]
NewsCategoryValue = Literal["market", "stock"]
NewsPanelKeyValue = Literal["newsBriefs", "stockNews"]


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


class MarketNewsDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleStatusItemDto]
    exceptions: list[ModuleExceptionItemDto]


class NewsSubjectRefDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjectType: Literal["stock"]
    subjectCode: str
    subjectName: str | None = None


class NewsPanelItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsId: str
    publishTime: datetime
    displayTime: str
    title: str
    category: NewsCategoryValue
    source: str | None = None
    subject: NewsSubjectRefDto | None = None
    priority: int | None = Field(default=0)
    url: str | None = None
    clickable: Literal[False] = False


class NewsListPanelDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    panelKey: NewsPanelKeyValue
    visibleItemCount: int = Field(ge=1)
    updatedAt: datetime
    items: list[NewsPanelItemDto]
    sortRule: Literal["publishTime_desc_priority_desc"] = "publishTime_desc_priority_desc"
    clickablePolicy: Literal["disabled"] = "disabled"


class NewsBriefsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    newsBriefs: NewsListPanelDto
    debugInfo: MarketNewsDebugInfoDto | None = None
