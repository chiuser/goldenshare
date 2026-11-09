"""The ordinary history response uses published events and the recognition MACD."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GoldXxmPointDto(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    time: str
    close: float = Field(gt=0)
    dif: float
    dea: float
    hist: float
    ordinaryState: None = None
    ordinaryDirection: None = None


class GoldXxmEventDto(BaseModel):
    id: str
    time: str
    type: Literal["DULL", "STRUCTURE", "CANCEL"]
    direction: Literal["TOP", "BOTTOM"]
    displayOnChart: bool


class GoldXxmMetaDto(BaseModel):
    count: int
    responseStart: str | None
    responseEnd: str | None


class GoldXxmStatusDto(BaseModel):
    status: Literal["READY", "DELAYED", "EMPTY"]
    message: str | None
    asOf: str | None


class GoldXxmResponseDto(BaseModel):
    tsCode: str
    period: Literal["day", "m30", "m60", "m90", "m120"]
    algorithmVersion: str
    specHash: str
    points: list[GoldXxmPointDto]
    events: list[GoldXxmEventDto]
    meta: GoldXxmMetaDto
    dataStatus: GoldXxmStatusDto
