from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.biz.schemas.wealth.market.stock_detail import StockDetailStockRefDto


class StockDetailNewsDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matchMethod: Literal["CODE_EXACT", "FULL_NAME_EXACT", "SHORT_NAME_EXACT"]


class StockDetailNewsItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsId: str
    publishTime: datetime
    title: str
    debugInfo: StockDetailNewsDebugInfoDto | None = None


class StockDetailNewsMetaDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    limit: int
    startAt: datetime
    endAt: datetime


class StockDetailNewsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stockRef: StockDetailStockRefDto
    items: list[StockDetailNewsItemDto]
    meta: StockDetailNewsMetaDto
