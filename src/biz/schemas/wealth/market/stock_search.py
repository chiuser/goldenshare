from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StockSearchItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tsCode: str
    name: str


class StockSearchResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str
    items: list[StockSearchItemDto] = Field(max_length=20)
