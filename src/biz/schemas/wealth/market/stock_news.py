from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .news_briefs import MarketNewsDebugInfoDto, NewsListPanelDto, PageStatusDto, TradingDayDto


class StockNewsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradingDay: TradingDayDto
    pageStatus: PageStatusDto
    stockNews: NewsListPanelDto
    debugInfo: MarketNewsDebugInfoDto | None = None
