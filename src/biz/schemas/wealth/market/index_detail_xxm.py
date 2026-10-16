from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


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
    pendingBottomHistoryId: str | None

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
    relatedBottomHistoryId: str | None

    @model_validator(mode="after")
    def consistent_route(self):
        if (self.type == "RESEARCH_HISTORICAL_WITHDRAWAL") != (self.route == "historical_price_break"):
            raise ValueError("Historical route requires a historical event")
        return self


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


class XxmBottomHistoryDto(XxmDto):
    id: str = Field(min_length=1)
    structureEventId: str = Field(min_length=1)
    confirmedAt: str
    confirmationRoute: Literal["dif_turn", "color_flip"]
    originSegmentStart: str
    leftOriginAt: str | None
    priceLow: float = Field(gt=0)
    priceLowAt: str
    originalReference: XxmReferenceDto
    status: Literal["PENDING", "ENDED"]
    endedAt: str | None
    endReason: Literal["original_reference_break", "new_bottom_DULL", "new_bottom_STRUCTURE", "historical_price_break"] | None
    observedThrough: str
    ageBars: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def consistent_history(self):
        if not (self.originSegmentStart <= self.priceLowAt <= self.confirmedAt <= self.observedThrough
                and self.originalReference.startTime <= self.originalReference.endTime < self.originSegmentStart):
            raise ValueError("Invalid BOTTOM history chronology")
        if self.leftOriginAt is not None and not self.confirmedAt <= self.leftOriginAt <= self.observedThrough:
            raise ValueError("Invalid BOTTOM origin exit")
        if self.status == "PENDING":
            if self.endedAt is not None or self.endReason is not None:
                raise ValueError("Pending BOTTOM history has an ending")
        elif (self.endedAt is None or self.endReason is None
              or not self.confirmedAt < self.endedAt == self.observedThrough):
            raise ValueError("Invalid BOTTOM history ending")
        if self.endReason == "historical_price_break" and self.leftOriginAt is None:
            raise ValueError("BOTTOM price break before origin exit")
        return self


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
    bottomHistories: list[XxmBottomHistoryDto]
    meta: XxmMetaDto
    dataStatus: XxmDataStatusDto

    @model_validator(mode="after")
    def consistent_window(self):
        if self.algorithmVersion != MAIN_SPEC.algorithm_version or self.specHash != MAIN_SPEC.spec_hash:
            raise ValueError("Unsupported XXM identity")
        times = [point.time for point in self.points]
        if times != sorted(set(times)) or self.meta.count != len(times):
            raise ValueError("XXM point window is invalid")
        if self.meta.responseStart != (times[0] if times else None) or self.meta.responseEnd != (times[-1] if times else None):
            raise ValueError("XXM window bounds mismatch")
        if any(event.time not in times for event in self.events):
            raise ValueError("XXM event outside response window")
        top = {h.id: h for h in self.topHistories}
        bottom = {h.id: h for h in self.bottomHistories}
        event_ids = {event.id for event in self.events}
        if (len(top) != len(self.topHistories) or len(bottom) != len(self.bottomHistories)
                or set(top) & set(bottom) or len(event_ids) != len(self.events)
                or any(not key for key in (*top, *bottom, *event_ids))):
            raise ValueError("Duplicate or empty XXM identity")
        through = self.source.computedThrough
        if self.dataStatus.asOf != through:
            raise ValueError("XXM source asOf mismatch")
        if self.dataStatus.status == "EMPTY":
            if times or self.events or top or bottom or through is not None:
                raise ValueError("Nonempty XXM EMPTY response")
            return self
        if through is None or self.source.startTime is None or any(
                not self.source.startTime <= stamp <= through for stamp in times):
            raise ValueError("XXM point outside source")
        def validate_time(stamp):
            XxmBar(stamp, 1., 0., 0., 0.).validate(self.period)
        validate_time(through)
        if sum(h.status == "PENDING" for h in bottom.values()) > 1:
            raise ValueError("Multiple pending BOTTOM histories")
        for h in bottom.values():
            for stamp in (h.confirmedAt, h.originSegmentStart, h.priceLowAt, h.observedThrough,
                          h.originalReference.startTime, h.originalReference.endTime, h.leftOriginAt, h.endedAt):
                if stamp is not None:
                    validate_time(stamp)
            if h.observedThrough > through or (h.status == "PENDING" and h.observedThrough != through):
                raise ValueError("BOTTOM history contains future or incomplete observation")
            if h.originalReference.price <= 0:
                raise ValueError("Invalid BOTTOM original price")
        for point in self.points:
            for key, records in ((point.pendingTopHistoryId, top), (point.pendingBottomHistoryId, bottom)):
                if key is not None:
                    h = records.get(key)
                    if h is None or not h.confirmedAt <= point.time or (h.endedAt is not None and point.time >= h.endedAt):
                        raise ValueError("XXM point history association missing at point time")
        for event in self.events:
            historical = event.type == "RESEARCH_HISTORICAL_WITHDRAWAL"
            associated = historical or event.type == "STRUCTURE"
            own_id = event.relatedTopHistoryId if event.direction == "TOP" else event.relatedBottomHistoryId
            other_id = event.relatedBottomHistoryId if event.direction == "TOP" else event.relatedTopHistoryId
            records = top if event.direction == "TOP" else bottom
            if other_id is not None or (associated and (not own_id or own_id not in records)) or (not associated and own_id is not None):
                raise ValueError("XXM event direction/history association mismatch")
            if associated:
                h = records[own_id]
                if historical:
                    if (event.route != "historical_price_break" or h.status != "ENDED"
                            or h.endReason != "historical_price_break" or h.endedAt != event.time
                            or h.originalReference != event.eventReference):
                        raise ValueError("XXM historical disappearance association mismatch")
                elif (h.confirmedAt != event.time or h.confirmationRoute != event.route
                      or (event.direction == "BOTTOM" and h.structureEventId != event.id)):
                    raise ValueError("XXM structure association mismatch")
        visible_events = {event.id: event for event in self.events}
        for h in bottom.values():
            event = visible_events.get(h.structureEventId)
            if event is not None and (event.direction != "BOTTOM" or event.type != "STRUCTURE"
                    or event.relatedBottomHistoryId != h.id or event.time != h.confirmedAt or event.route != h.confirmationRoute):
                raise ValueError("BOTTOM reverse structure association mismatch")
        return self
