from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .news_briefs import MarketNewsDebugInfoDto, NewsListPanelDto, NewsWindowDto, PageStatusDto


class StockNewsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsWindow: NewsWindowDto
    pageStatus: PageStatusDto
    stockNews: NewsListPanelDto
    debugInfo: MarketNewsDebugInfoDto | None = None
