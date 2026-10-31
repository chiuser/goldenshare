from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

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
    pendingRearmId: str | None

    @model_validator(mode="after")
    def consistent_state(self):
        if self.close <= 0 or not all(math.isfinite(v) for v in (self.close, self.dif, self.dea, self.hist)):
            raise ValueError("Invalid XXM values")
        if (self.ordinaryState == "NONE" and (self.ordinaryDirection is not None or self.activeReference is not None)) or (
            self.ordinaryState != "NONE" and (self.ordinaryDirection is None or self.activeReference is None)
        ):
            raise ValueError("XXM state/reference mismatch")
        if self.pendingRearmId is not None and (self.ordinaryState != "NONE" or self.pendingBottomHistoryId is not None):
            raise ValueError("Waiting rearm cannot be active dulling or structure")
        return self


class InternalXxmDto(BaseModel):
    """Complete r4 facts, validated before any public response is projected."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class InternalXxmReferenceDto(InternalXxmDto):
    startTime: str
    endTime: str
    price: float = Field(gt=0)
    dif: float
    priceAt: str
    difAt: str

    @field_validator("price", "dif", mode="before")
    @classmethod
    def original_number(cls, value):
        if type(value) not in (int, float):
            raise ValueError("XXM values must be original numbers")
        return value

    @model_validator(mode="after")
    def chronology(self):
        if not (self.startTime <= self.priceAt <= self.endTime
                and self.startTime <= self.difAt <= self.endTime):
            raise ValueError("XXM reference extreme outside its segment")
        return self


class InternalXxmPointDto(InternalXxmDto):
    time: str
    close: float = Field(gt=0)
    dif: float
    dea: float
    hist: float
    ordinaryState: Literal["NONE", "DULL", "STRUCTURE"]
    ordinaryDirection: Literal["TOP", "BOTTOM"] | None
    activeReference: InternalXxmReferenceDto | None
    activeStructureId: str | None

    @field_validator("close", "dif", "dea", "hist", mode="before")
    @classmethod
    def original_number(cls, value):
        if type(value) not in (int, float):
            raise ValueError("XXM values must be original numbers")
        return value

    @model_validator(mode="after")
    def state_relationship(self):
        if self.ordinaryState == "NONE":
            if any(v is not None for v in (self.ordinaryDirection, self.activeReference, self.activeStructureId)):
                raise ValueError("NONE cannot carry an active relationship")
        elif self.ordinaryDirection is None or self.activeReference is None:
            raise ValueError("Active XXM state requires direction and reference")
        if (self.ordinaryState == "STRUCTURE") != (self.activeStructureId is not None):
            raise ValueError("STRUCTURE requires its unique active structure")
        if self.activeStructureId == "":
            raise ValueError("Empty XXM structure identity")
        return self


class InternalXxmEventDto(InternalXxmDto):
    id: str = Field(min_length=1)
    time: str
    direction: Literal["TOP", "BOTTOM"]
    type: Literal["DULL", "STRUCTURE", "CANCEL"]
    route: Literal["activation", "dif_turn", "dif_return", "color_flip", "dif_break", "dif_break_on_flip", "structure_price_break"]
    fromState: Literal["NONE", "DULL", "STRUCTURE"]
    eventReference: InternalXxmReferenceDto
    relatedStructureId: str | None

    @model_validator(mode="after")
    def event_relationship(self):
        routes = {"DULL": {"activation", "dif_return"}, "STRUCTURE": {"dif_turn", "color_flip"},
                  "CANCEL": {"dif_break", "dif_break_on_flip", "structure_price_break"}}
        if self.route not in routes[self.type]:
            raise ValueError("XXM event type/route mismatch")
        expected_from = "NONE" if self.route == "activation" else "DULL" if self.type == "STRUCTURE" else "STRUCTURE"
        if self.type != "CANCEL" and self.fromState != expected_from:
            raise ValueError("XXM event fromState mismatch")
        if self.type == "CANCEL" and self.fromState not in ("DULL", "STRUCTURE"):
            raise ValueError("Cancellation requires an active relationship")
        if self.route == "structure_price_break" and self.fromState != "STRUCTURE":
            raise ValueError("Old structure price cancellation must target STRUCTURE")
        related = self.type == "STRUCTURE" or self.fromState == "STRUCTURE"
        if related != (self.relatedStructureId is not None) or self.relatedStructureId == "":
            raise ValueError("XXM event structure association mismatch")
        return self


class InternalXxmWaveDto(InternalXxmDto):
    sign: int
    start: str
    end: str
    count: int
    price: float
    dif: float
    price_at: str
    dif_at: str

    @model_validator(mode="before")
    @classmethod
    def native_fields(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Wave must contain native fields")
        if any(type(value.get(key)) is not int for key in ("sign", "count")):
            raise ValueError("Wave sign/count must be integers")
        if any(type(value.get(key)) not in (int, float) for key in ("price", "dif")):
            raise ValueError("Wave must retain original numbers")
        return value


class InternalXxmStructureDto(InternalXxmDto):
    id: str = Field(min_length=1)
    direction: Literal["TOP", "BOTTOM"]
    structureEventId: str = Field(min_length=1)
    formedAt: str
    formationRoute: Literal["dif_turn", "color_flip"]
    originSegmentStart: str
    originalReference: InternalXxmReferenceDto
    priceExtreme: float = Field(gt=0)
    priceExtremeAt: str
    status: Literal["ASSESSING", "FOLLOWING", "FINISHED", "DISAPPEARED"]
    originWave: InternalXxmWaveDto | None
    firstOppositeAt: str | None
    nextSameColorStart: str | None
    trackingEndedAt: str | None
    disappearedAt: str | None
    disappearanceReason: Literal["dif_return", "reference_dif_break", "structure_price_break"] | None

    @field_validator("priceExtreme", mode="before")
    @classmethod
    def original_number(cls, value):
        if type(value) not in (int, float):
            raise ValueError("XXM price must be an original number")
        return value

    @model_validator(mode="after")
    def lifecycle(self):
        from src.biz.services.wealth.market.index_detail_xxm.snapshot_validation import validate_structure_facts

        raw = self.model_dump()
        upper = max(value for value in (self.formedAt, self.firstOppositeAt,
                    self.nextSameColorStart, self.trackingEndedAt, self.disappearedAt) if value is not None)
        # Only the full response knows algorithm/source identity. It validates
        # IDs below; this shared guard checks the same native lifecycle facts.
        validate_structure_facts(raw, period="day" if len(self.formedAt) == 10 else "m60", upper=upper)
        return self


class InternalXxmSourceDto(InternalXxmDto):
    kind: Literal["daily_factor", "minute_gold"]
    inputId: str = Field(min_length=1)
    startTime: str | None
    computedThrough: str | None
    initialHistoryIncomplete: bool
    indicatorVersion: int | None


class InternalXxmMetaDto(InternalXxmDto):
    count: int = Field(ge=0)
    responseStart: str | None
    responseEnd: str | None


class InternalXxmDataStatusDto(InternalXxmDto):
    status: Literal["READY", "DELAYED", "EMPTY"]
    message: str | None
    asOf: str | None


class InternalXxmResponseDto(InternalXxmDto):
    tsCode: Literal["000001.SH"]
    period: Literal["day", "m60", "m90", "m120"]
    algorithmVersion: str
    specHash: str
    source: InternalXxmSourceDto
    points: list[InternalXxmPointDto]
    events: list[InternalXxmEventDto]
    structures: list[InternalXxmStructureDto]
    meta: InternalXxmMetaDto
    dataStatus: InternalXxmDataStatusDto

    def _id(self, *parts):
        import hashlib

        values = (self.algorithmVersion, self.specHash, self.tsCode, self.period, *parts)
        return hashlib.sha256("|".join(map(str, values)).encode()).hexdigest()[:24]

    @model_validator(mode="after")
    def complete_facts(self):
        if self.algorithmVersion != MAIN_SPEC.algorithm_version or self.specHash != MAIN_SPEC.spec_hash:
            raise ValueError("Unsupported XXM identity")
        times = [point.time for point in self.points]
        if times != sorted(set(times)) or self.meta.count != len(times):
            raise ValueError("Invalid XXM point window")
        if (self.meta.responseStart != (times[0] if times else None)
                or self.meta.responseEnd != (times[-1] if times else None)):
            raise ValueError("XXM window bounds mismatch")
        event_ids = {event.id for event in self.events}
        records = {record.id: record for record in self.structures}
        if (len(event_ids) != len(self.events) or len(records) != len(self.structures)
                or event_ids.intersection(records)):
            raise ValueError("Duplicate XXM identity")
        if [(record.formedAt, record.id) for record in self.structures] != sorted(
                (record.formedAt, record.id) for record in self.structures):
            raise ValueError("XXM structures are not in formation order")
        event_times = [event.time for event in self.events]
        if event_times != sorted(event_times) or any(stamp not in times for stamp in event_times):
            raise ValueError("XXM events must be ordered and visible")
        ordinary_times = set()
        for event in self.events:
            if event.route == "structure_price_break":
                if event.time in ordinary_times:
                    raise ValueError("Old structure events must precede the current ordinary event")
            elif event.time in ordinary_times:
                raise ValueError("Multiple ordinary events on one bar")
            else:
                ordinary_times.add(event.time)
        through, start = self.source.computedThrough, self.source.startTime
        if self.dataStatus.asOf != through:
            raise ValueError("XXM asOf mismatch")
        if self.source.kind != ("daily_factor" if self.period == "day" else "minute_gold"):
            raise ValueError("XXM source kind/period mismatch")
        if self.period == "day" and self.source.indicatorVersion is not None:
            raise ValueError("Daily XXM must not invent an indicator version")
        if self.dataStatus.status == "EMPTY":
            if times or self.events or self.structures or through is not None or start is not None:
                raise ValueError("Nonempty XXM EMPTY response")
            return self
        if start is None or through is None or not start <= through:
            raise ValueError("XXM source interval is missing")

        def stamp(value):
            XxmBar(value, 1., 0., 0., 0.).validate(self.period)
            if not start <= value <= through:
                raise ValueError("XXM fact outside source interval")

        def reference(value):
            for value_time in (value.startTime, value.endTime, value.priceAt, value.difAt):
                stamp(value_time)

        stamp(start)
        stamp(through)
        for record in self.structures:
            for value in (record.formedAt, record.originSegmentStart, record.priceExtremeAt,
                          record.firstOppositeAt, record.nextSameColorStart, record.trackingEndedAt, record.disappearedAt):
                if value is not None:
                    stamp(value)
            if record.originWave is not None:
                for value in (record.originWave.start, record.originWave.end,
                              record.originWave.price_at, record.originWave.dif_at):
                    stamp(value)
            reference(record.originalReference)
            sign = 1 if record.direction == "TOP" else -1
            event_id = self._id(record.formedAt, "STRUCTURE", sign, record.originalReference.startTime)
            if record.structureEventId != event_id or record.id != self._id("structure", event_id):
                raise ValueError("XXM structure identity mismatch")
        for point in self.points:
            stamp(point.time)
            if point.activeReference is not None:
                reference(point.activeReference)
                if point.activeReference.endTime >= point.time:
                    raise ValueError("XXM active reference is not historical")
            if point.activeStructureId is not None:
                record = records.get(point.activeStructureId)
                if (record is None or not record.formedAt <= point.time
                        or record.firstOppositeAt is not None and point.time >= record.firstOppositeAt
                        or record.disappearedAt is not None and point.time >= record.disappearedAt
                        or point.ordinaryDirection != record.direction
                        or point.activeReference != record.originalReference):
                    raise ValueError("XXM active structure invalid at point time")
        events = {event.id: event for event in self.events}
        points_by_time = {point.time: (index, point) for index, point in enumerate(self.points)}
        for event in self.events:
            reference(event.eventReference)
            sign = 1 if event.direction == "TOP" else -1
            if event.eventReference.endTime >= event.time or event.id != self._id(
                    *( (event.time, "CANCEL", "structure_price_break", event.relatedStructureId)
                       if event.route == "structure_price_break" else
                       (event.time, event.type, sign, event.eventReference.startTime) )):
                raise ValueError("XXM event identity/reference mismatch")
            index, point = points_by_time[event.time]
            if event.route in ("activation", "dif_return", "dif_turn"):
                expected_state = "STRUCTURE" if event.route == "dif_turn" else "DULL"
                if (point.ordinaryState != expected_state or point.ordinaryDirection != event.direction
                        or point.activeReference != event.eventReference):
                    raise ValueError("XXM event and final point state/direction/reference disagree")
                if event.route == "dif_turn" and point.activeStructureId != event.relatedStructureId:
                    raise ValueError("XXM formation event and final point structure disagree")
            elif event.route != "structure_price_break" and point.ordinaryState != "NONE":
                raise ValueError("XXM flip/cancellation must leave the final point in NONE")
            # The response window need not include the preceding source bar.
            # When it does, fromState is an existing fact, not a recomputation.
            if event.route != "structure_price_break" and index and event.fromState != self.points[index - 1].ordinaryState:
                raise ValueError("XXM event fromState disagrees with the preceding visible point")
            if event.relatedStructureId is not None:
                record = records.get(event.relatedStructureId)
                if (record is None or record.direction != event.direction
                        or record.originalReference != event.eventReference):
                    raise ValueError("XXM event structure is missing or mismatched")
                if event.type == "STRUCTURE":
                    if (record.structureEventId != event.id or record.formedAt != event.time
                            or record.formationRoute != event.route):
                        raise ValueError("XXM formation association mismatch")
                elif (record.status != "DISAPPEARED" or record.disappearedAt != event.time
                      or record.disappearanceReason != ("dif_return" if event.route == "dif_return"
                                                        else "structure_price_break" if event.route == "structure_price_break"
                                                        else "reference_dif_break")):
                    raise ValueError("XXM disappearance association mismatch")
        for record in self.structures:
            event = events.get(record.structureEventId)
            if record.formedAt in times and (event is None or event.relatedStructureId != record.id):
                raise ValueError("XXM visible structure has no formation event")
        following_directions = [record.direction for record in self.structures if record.status == "FOLLOWING"]
        if len(set(following_directions)) != len(following_directions):
            raise ValueError("Multiple followed structures for one direction")
        assessing = [record for record in self.structures if record.status == "ASSESSING"]
        if len(assessing) > 1:
            raise ValueError("Multiple active XXM structures")
        if self.points and self.points[-1].time == through:
            last = self.points[-1]
            expected_active = [last.activeStructureId] if last.ordinaryState == "STRUCTURE" else []
            if [record.id for record in assessing] != expected_active:
                raise ValueError("Latest XXM point and assessing structure disagree")
        return self


class XxmEventDto(XxmDto):
    id: str
    time: str
    direction: Literal["TOP", "BOTTOM"]
    type: Literal["DULL", "STRUCTURE", "CANCEL", "RESEARCH_HISTORICAL_WITHDRAWAL", "STRUCTURE_DISAPPEARED"]
    route: Literal["activation", "dif_turn", "dif_return", "color_flip", "dif_break", "dif_break_on_flip", "historical_price_break", "reactivation"]
    fromState: Literal["NONE", "DULL", "STRUCTURE"]
    eventReference: XxmReferenceDto | None
    relatedTopHistoryId: str | None
    relatedBottomHistoryId: str | None
    relatedRearmId: str | None

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
    endReason: Literal["original_reference_break", "new_bottom_DULL", "new_bottom_STRUCTURE", "historical_price_break", "structure_disappeared"] | None
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
        if self.endReason == "structure_disappeared" and self.leftOriginAt is not None:
            raise ValueError("Same-segment disappearance after origin exit")
        return self


class XxmRearmRecordDto(XxmDto):
    id: str = Field(min_length=1)
    direction: Literal["BOTTOM"]
    bottomHistoryId: str = Field(min_length=1)
    structureEventId: str = Field(min_length=1)
    structureConfirmedAt: str
    structureRoute: Literal["dif_turn"]
    segmentStart: str
    nearestPriceGate: float = Field(gt=0)
    reference: XxmReferenceDto
    disappearedAt: str
    observedThrough: str
    status: Literal["WAITING", "REACTIVATED", "INVALIDATED", "SEGMENT_ENDED"]
    endedAt: str | None
    endReason: Literal["price_requalified", "reference_dif_break", "color_flip", "zero"] | None

    @model_validator(mode="after")
    def consistent(self):
        if not (self.reference.startTime <= self.reference.endTime < self.segmentStart
                <= self.structureConfirmedAt < self.disappearedAt <= self.observedThrough) or self.reference.price <= 0:
            raise ValueError("Invalid rearm chronology/reference")
        if self.status == "WAITING":
            if self.endedAt is not None or self.endReason is not None:
                raise ValueError("WAITING record has an ending")
        else:
            reasons = {"REACTIVATED": ("price_requalified",), "INVALIDATED": ("reference_dif_break",),
                       "SEGMENT_ENDED": ("color_flip", "zero")}
            if (self.endReason not in reasons[self.status] or self.endedAt is None
                    or not self.disappearedAt < self.endedAt == self.observedThrough):
                raise ValueError("Invalid rearm ending")
        return self

    def validate_cutoff(self, period: str, through: str):
        for stamp in (self.reference.startTime, self.reference.endTime, self.segmentStart, self.structureConfirmedAt,
                      self.disappearedAt, self.observedThrough, self.endedAt):
            if stamp is not None:
                XxmBar(stamp, 1., 0., 0., 0.).validate(period)
        if self.observedThrough > through or self.status == "WAITING" and self.observedThrough != through:
            raise ValueError("Rearm observation outside real cutoff")


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
    rearmRecords: list[XxmRearmRecordDto]
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
        rearms = {r.id: r for r in self.rearmRecords}
        event_ids = {event.id for event in self.events}
        if (len(top) != len(self.topHistories) or len(bottom) != len(self.bottomHistories)
                or set(top) & set(bottom) or len(event_ids) != len(self.events)
                or len(rearms) != len(self.rearmRecords) or set(rearms) & (set(top) | set(bottom) | event_ids)
                or any(not key for key in (*top, *bottom, *event_ids, *rearms))):
            raise ValueError("Duplicate or empty XXM identity")
        through = self.source.computedThrough
        if self.dataStatus.asOf != through:
            raise ValueError("XXM source asOf mismatch")
        if self.dataStatus.status == "EMPTY":
            if times or self.events or top or bottom or rearms or through is not None:
                raise ValueError("Nonempty XXM EMPTY response")
            return self
        if through is None or self.source.startTime is None or any(
                not self.source.startTime <= stamp <= through for stamp in times):
            raise ValueError("XXM point outside source")
        def validate_time(stamp):
            XxmBar(stamp, 1., 0., 0., 0.).validate(self.period)
        validate_time(through)
        if sum(r.status == "WAITING" for r in rearms.values()) > 1:
            raise ValueError("Multiple waiting rearm records")
        for r in rearms.values():
            r.validate_cutoff(self.period, through)
            h = bottom.get(r.bottomHistoryId)
            if (h is None or h.structureEventId != r.structureEventId or h.confirmedAt != r.structureConfirmedAt
                    or h.confirmationRoute != r.structureRoute or h.originSegmentStart != r.segmentStart
                    or h.originalReference != r.reference or h.endReason != "structure_disappeared"
                    or h.endedAt != r.disappearedAt):
                raise ValueError("Rearm original structure association mismatch")
        for h in bottom.values():
            if h.endReason == "structure_disappeared" and sum(r.bottomHistoryId == h.id for r in rearms.values()) != 1:
                raise ValueError("Disappeared structure has no unique rearm record")
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
            if point.pendingRearmId is not None:
                r = rearms.get(point.pendingRearmId)
                if r is None or point.time < r.disappearedAt or r.endedAt is not None and point.time >= r.endedAt:
                    raise ValueError("Point rearm association missing at point time")
            for key, records in ((point.pendingTopHistoryId, top), (point.pendingBottomHistoryId, bottom)):
                if key is not None:
                    h = records.get(key)
                    if h is None or not h.confirmedAt <= point.time or (h.endedAt is not None and point.time >= h.endedAt):
                        raise ValueError("XXM point history association missing at point time")
        points_by_time = {point.time: point for point in self.points}
        rearm_events = set()
        for event in self.events:
            point = points_by_time[event.time]
            historical = event.type == "RESEARCH_HISTORICAL_WITHDRAWAL"
            disappeared = event.type == "STRUCTURE_DISAPPEARED"
            if disappeared or event.route == "reactivation":
                key = (event.relatedRearmId, event.type)
                if key in rearm_events:
                    raise ValueError("Duplicate rearm transition")
                rearm_events.add(key)
            associated = historical or event.type == "STRUCTURE" or disappeared
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
                elif disappeared:
                    r = rearms.get(event.relatedRearmId)
                    if (event.direction != "BOTTOM" or event.route != "dif_return" or event.fromState != "STRUCTURE"
                            or r is None or r.bottomHistoryId != own_id or r.disappearedAt != event.time
                            or r.reference != event.eventReference or point.pendingRearmId != r.id):
                        raise ValueError("Same-segment disappearance association mismatch")
                elif (h.confirmedAt != event.time or h.confirmationRoute != event.route
                      or (event.direction == "BOTTOM" and h.structureEventId != event.id)):
                    raise ValueError("XXM structure association mismatch")
            if event.route == "reactivation":
                r = rearms.get(event.relatedRearmId)
                if (event.type != "DULL" or event.direction != "BOTTOM" or event.fromState != "NONE"
                        or r is None or r.status != "REACTIVATED" or r.endedAt != event.time
                        or r.reference != event.eventReference or point.ordinaryState != "DULL"
                        or point.pendingRearmId is not None):
                    raise ValueError("Reactivation association mismatch")
            elif not disappeared and event.relatedRearmId is not None:
                raise ValueError("Unexpected rearm event association")
        visible_events = {event.id: event for event in self.events}
        for h in bottom.values():
            event = visible_events.get(h.structureEventId)
            if event is not None and (event.direction != "BOTTOM" or event.type != "STRUCTURE"
                    or event.relatedBottomHistoryId != h.id or event.time != h.confirmedAt or event.route != h.confirmationRoute):
                raise ValueError("BOTTOM reverse structure association mismatch")
        return self
