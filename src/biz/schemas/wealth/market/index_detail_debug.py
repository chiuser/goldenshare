from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .index_detail import (
    IndexDetailDataStatusValue,
    IndexDetailPageInitDataDto,
    IndexDetailKlineDataDto, IndexSseDailyKlineBarDto,
    IndexDetailSseKlineMetaDto,
    IndexDetailWeightsDataDto,
)
from .nine_turn import NineTurnMarkerDto


IndexDetailSeverity = Literal["info", "warn", "error"]
IndexDetailDebugModule = Literal["pageInit", "quote", "dailyBasic", "breadth", "kline", "weights"]
IndexDetailExceptionModule = Literal[
    "indexDetail",
    "indexDetailPageInit",
    "indexDetailKline",
    "indexDetailWeights",
]
IndexDetailExceptionCode = Literal[
    "ID_REQUEST_INVALID",
    "ID_NOT_FOUND",
    "ID_SOURCE_EMPTY",
    "ID_SOURCE_DELAYED",
    "ID_FACTOR_PARTIAL",
    "ID_BASIC_DAILY_PARTIAL",
    "ID_BASIC_BREADTH_PARTIAL",
    "ID_WEIGHT_EMPTY",
    "ID_WEIGHT_CONTRIBUTION_PARTIAL",
    "ID_QUERY_FAILED",
]


class IndexDetailModuleDebugDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: IndexDetailDebugModule
    status: IndexDetailDataStatusValue | Literal["ERROR"]
    expectedTradeDate: date
    observedTradeDate: date | None
    rowCount: int | None
    missingCount: int | None


class IndexDetailExceptionDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: IndexDetailExceptionModule
    code: IndexDetailExceptionCode
    severity: IndexDetailSeverity
    message: str


class IndexDetailDebugInfoDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[IndexDetailModuleDebugDto]
    exceptions: list[IndexDetailExceptionDto]


class IndexDetailPageInitDebugResponseDto(IndexDetailPageInitDataDto):
    debugInfo: IndexDetailDebugInfoDto


class IndexDetailKlineDebugResponseDto(IndexDetailKlineDataDto):
    debugInfo: IndexDetailDebugInfoDto


class LocalIndexDetailDailyKlineDebugResponseDto(IndexDetailKlineDebugResponseDto):
    period: Literal["day"]
    meta: IndexDetailSseKlineMetaDto
    nineTurnMarkers: list[NineTurnMarkerDto]


class IndexDetailWeightsDebugResponseDto(IndexDetailWeightsDataDto):
    debugInfo: IndexDetailDebugInfoDto


class IndexDetailSseDailyKlineDebugResponseDto(IndexDetailKlineDebugResponseDto):
    period: Literal["day"]
    bars: list[IndexSseDailyKlineBarDto]
    meta: IndexDetailSseKlineMetaDto


class LocalIndexDetailSseDailyKlineDebugResponseDto(LocalIndexDetailDailyKlineDebugResponseDto):
    bars: list[IndexSseDailyKlineBarDto]
