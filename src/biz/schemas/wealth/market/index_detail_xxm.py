from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class XxmDto(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class XxmReferenceDto(XxmDto):
    startTime: str
    endTime: str
    price: float
    dif: float


class XxmPointDto(XxmDto):
    time: str
    close: float
    dif: float
    dea: float
    hist: float
    ordinaryState: Literal["NONE", "DULL", "STRUCTURE"]
    ordinaryDirection: Literal["TOP", "BOTTOM"] | None
    activeReference: XxmReferenceDto | None
    pendingTopHistoryId: str | None

    @model_validator(mode="after")
    def consistent_state(self):
        if self.close <= 0 or not all(math.isfinite(v) for v in (self.close, self.dif, self.dea, self.hist)):
            raise ValueError("Invalid XXM values")
        if (self.ordinaryState == "NONE" and (self.ordinaryDirection is not None or self.activeReference is not None)) or (
            self.ordinaryState != "NONE" and (self.ordinaryDirection is None or self.activeReference is None)
        ):
            raise ValueError("XXM state/reference mismatch")
        return self


class XxmEventDto(XxmDto):
    id: str
    time: str
    direction: Literal["TOP", "BOTTOM"]
    type: Literal["DULL", "STRUCTURE", "CANCEL", "RESEARCH_HISTORICAL_WITHDRAWAL"]
    route: Literal["activation", "dif_turn", "dif_return", "color_flip", "dif_break", "dif_break_on_flip", "historical_price_break"]
    fromState: Literal["NONE", "DULL", "STRUCTURE"]
    eventReference: XxmReferenceDto | None
    relatedTopHistoryId: str | None


class XxmTopHistoryDto(XxmDto):
    id: str
    confirmedAt: str
    confirmationRoute: Literal["dif_turn", "color_flip"]
    pricePeak: float
    pricePeakAt: str
    originalReference: XxmReferenceDto
    status: Literal["PENDING", "ENDED"]
    endedAt: str | None
    endReason: Literal["original_reference_break", "new_top_DULL", "new_top_STRUCTURE", "historical_price_break"] | None
    observedThrough: str
    ageBars: int


class XxmSourceDto(XxmDto):
    kind: Literal["daily_factor", "minute_gold"]
    inputId: str
    startTime: str | None
    computedThrough: str | None
    initialHistoryIncomplete: bool
    indicatorVersion: int | None


class XxmMetaDto(XxmDto):
    count: int
    responseStart: str | None
    responseEnd: str | None


class XxmDataStatusDto(XxmDto):
    status: Literal["READY", "DELAYED", "EMPTY"]
    message: str | None
    asOf: str | None


class XxmResponseDto(XxmDto):
    tsCode: Literal["000001.SH"]
    period: Literal["day", "m60", "m90", "m120"]
    algorithmVersion: str
    specHash: str
    source: XxmSourceDto
    points: list[XxmPointDto]
    events: list[XxmEventDto]
    topHistories: list[XxmTopHistoryDto]
    meta: XxmMetaDto
    dataStatus: XxmDataStatusDto

    @model_validator(mode="after")
    def consistent_window(self):
        times = [point.time for point in self.points]
        if times != sorted(set(times)) or self.meta.count != len(times):
            raise ValueError("XXM point window is invalid")
        if self.meta.responseStart != (times[0] if times else None) or self.meta.responseEnd != (times[-1] if times else None):
            raise ValueError("XXM window bounds mismatch")
        if any(event.time not in times for event in self.events):
            raise ValueError("XXM event outside response window")
        history_ids = {history.id for history in self.topHistories}
        if any(event.relatedTopHistoryId and event.relatedTopHistoryId not in history_ids for event in self.events):
            raise ValueError("XXM history association missing")
        return self
