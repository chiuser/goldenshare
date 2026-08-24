from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .news_common import NewsCategoryValue, NewsContentSourceValue, NewsPanelKeyValue


PageStatusValue = Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
SeverityValue = Literal["info", "warn", "error"]


class NewsWindowDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Literal["CN_A"]
    startAt: datetime
    endAt: datetime
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


class NewsPanelItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsId: str
    contentSource: NewsContentSourceValue
    publishTime: datetime
    displayTime: str
    title: str
    category: NewsCategoryValue
    source: str | None = None
    readerMode: Literal["URL", "HTML", "TEXT"]
    clickable: Literal[True] = True


class NewsListPanelDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windowStartAt: datetime
    windowEndAt: datetime
    panelKey: NewsPanelKeyValue
    visibleItemCount: int = Field(ge=1)
    updatedAt: datetime
    items: list[NewsPanelItemDto]
    sortRule: Literal["publishTime_desc"] = "publishTime_desc"
    clickablePolicy: Literal["reader"] = "reader"


class NewsBriefsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsWindow: NewsWindowDto
    pageStatus: PageStatusDto
    newsBriefs: NewsListPanelDto
    debugInfo: MarketNewsDebugInfoDto | None = None
