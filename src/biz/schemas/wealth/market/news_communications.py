from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .news_briefs import MarketNewsDebugInfoDto, NewsListPanelDto, NewsWindowDto, PageStatusDto


class NewsCommunicationsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsWindow: NewsWindowDto
    pageStatus: PageStatusDto
    newsCommunications: NewsListPanelDto
    debugInfo: MarketNewsDebugInfoDto | None = None
