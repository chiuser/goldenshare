from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from goldenshare_technical_indicators.xxm.spec import MAIN_SPEC
from goldenshare_technical_indicators.xxm.types import XxmBar


XxmTsCode = Annotated[str, Field(strict=True, min_length=9, max_length=9,
                                pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$")]


def _validate_wave_facts(*, sign, start, end, count, price, dif, price_at, dif_at):
    if (type(sign) is not int or sign not in (-1, 1)
            or type(count) is not int or count < 1
            or price <= 0 or not math.isfinite(price) or not math.isfinite(dif)
            or not start <= price_at <= end or not start <= dif_at <= end):
        raise ValueError("Invalid wave facts")


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

    @model_validator(mode="after")
    def wave_facts(self):
        _validate_wave_facts(**self.model_dump())
        return self


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
    nextSameColorCount: StrictInt = Field(ge=0)
    trackingPriceExtreme: float | None
    trackingPriceExtremeAt: str | None
    trackingEndedAt: str | None
    disappearedAt: str | None
    disappearanceReason: Literal["dif_return", "reference_dif_break", "structure_price_break"] | None

    @field_validator("priceExtreme", "trackingPriceExtreme", mode="before")
    @classmethod
    def original_number(cls, value, info):
        if value is None and info.field_name == "trackingPriceExtreme":
            return value
        if type(value) not in (int, float):
            raise ValueError("XXM price must be an original number")
        return value

    @model_validator(mode="after")
    def lifecycle(self):
        from goldenshare_technical_indicators.xxm.snapshot_validation import validate_structure_facts

        raw = self.model_dump()
        upper = max(value for value in (self.formedAt, self.firstOppositeAt,
                    self.nextSameColorStart, self.trackingPriceExtremeAt, self.trackingEndedAt, self.disappearedAt) if value is not None)
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
    tsCode: XxmTsCode
    period: Literal["day", "m30", "m60", "m90", "m120"]
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
        ordinary_by_time, ranks = {}, {}
        for event in self.events:
            if event.route == "structure_price_break":
                record = records.get(event.relatedStructureId)
                rank = 2 if record is not None and record.firstOppositeAt == event.time else 0
            else:
                ordinary_by_time.setdefault(event.time, []).append(event)
                rank = 1
            if rank < ranks.get(event.time, -1):
                raise ValueError("XXM events violate old/current/first-opposite order")
            ranks[event.time] = rank
        reactivations = {}
        for time, ordinary in ordinary_by_time.items():
            if len(ordinary) == 1:
                continue
            if len(ordinary) != 2:
                raise ValueError("Invalid ordinary event count")
            cancel, activation = ordinary
            if (cancel.route != "dif_break" or cancel.fromState != "STRUCTURE"
                    or activation.route != "activation" or cancel.direction != activation.direction
                    or activation.eventReference.endTime >= cancel.eventReference.startTime):
                raise ValueError("Invalid same-bar structure reactivation")
            reactivations[time] = (cancel, activation)
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
                          record.firstOppositeAt, record.nextSameColorStart, record.trackingPriceExtremeAt,
                          record.trackingEndedAt, record.disappearedAt):
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
            pair = reactivations.get(event.time)
            if event.route in ("activation", "dif_return", "dif_turn"):
                expected_state = "STRUCTURE" if event.route == "dif_turn" else "DULL"
                if (point.ordinaryState != expected_state or point.ordinaryDirection != event.direction
                        or point.activeReference != event.eventReference):
                    raise ValueError("XXM event and final point state/direction/reference disagree")
                if event.route == "dif_turn" and point.activeStructureId != event.relatedStructureId:
                    raise ValueError("XXM formation event and final point structure disagree")
            elif event.route != "structure_price_break" and pair is None and point.ordinaryState != "NONE":
                raise ValueError("XXM flip/cancellation must leave the final point in NONE")
            # The response window need not include the preceding source bar.
            # When it does, fromState is an existing fact, not a recomputation.
            if event.route != "structure_price_break" and index and (pair is None or event is pair[0]):
                previous = self.points[index - 1]
                if (event.fromState != previous.ordinaryState or pair is not None and
                        (event.eventReference != previous.activeReference
                         or event.relatedStructureId != previous.activeStructureId)):
                    raise ValueError("XXM event disagrees with the preceding visible point")
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
                      or pair is not None and event is pair[0] and record.firstOppositeAt is not None
                      or record.disappearanceReason != ("dif_return" if event.route == "dif_return"
                                                        else "structure_price_break" if event.route == "structure_price_break"
                                                        else "reference_dif_break")):
                    raise ValueError("XXM disappearance association mismatch")
        for record in self.structures:
            event = events.get(record.structureEventId)
            if record.formedAt in times and (event is None or event.relatedStructureId != record.id):
                raise ValueError("XXM visible structure has no formation event")
            if record.disappearedAt in times:
                endings = [item for item in self.events if item.relatedStructureId == record.id
                           and item.time == record.disappearedAt and item.type != "STRUCTURE"]
                if len(endings) != 1:
                    raise ValueError("XXM visible disappearance must have its complete event")
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


class XxmDto(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class XxmReferenceDto(InternalXxmReferenceDto):
    pass


class XxmWaveDto(XxmDto):
    sign: Literal[-1, 1]
    start: str
    end: str
    count: StrictInt = Field(gt=0)
    price: float = Field(gt=0)
    dif: float
    priceAt: str
    difAt: str

    @field_validator("sign", mode="before")
    @classmethod
    def strict_sign(cls, value):
        if type(value) is not int:
            raise ValueError("Wave sign must be an original integer")
        return value

    @model_validator(mode="after")
    def wave_fields(self):
        _validate_wave_facts(sign=self.sign, start=self.start, end=self.end, count=self.count,
                             price=self.price, dif=self.dif, price_at=self.priceAt, dif_at=self.difAt)
        return self


class XxmPointDto(XxmDto):
    time: str
    close: float = Field(gt=0)
    dif: float
    dea: float
    hist: float
    ordinaryState: Literal["NONE", "DULL", "STRUCTURE"]
    ordinaryDirection: Literal["TOP", "BOTTOM"] | None

    @field_validator("close", "dif", "dea", "hist", mode="before")
    @classmethod
    def numbers(cls, value):
        if type(value) not in (int, float):
            raise ValueError("Original numeric values required")
        return value

    @model_validator(mode="after")
    def state(self):
        if (self.ordinaryState == "NONE") != (self.ordinaryDirection is None):
            raise ValueError("Invalid ordinary direction")
        return self


class XxmEventDto(XxmDto):
    id: str = Field(min_length=1)
    time: str
    direction: Literal["TOP", "BOTTOM"]
    type: Literal["DULL", "STRUCTURE", "CANCEL"]
    displayOnChart: bool


class XxmSourceDto(XxmDto):
    kind: Literal["daily_factor", "minute_gold"]
    startTime: str | None
    computedThrough: str | None
    initialHistoryIncomplete: bool
    indicatorVersion: StrictInt | None


class XxmMetaDto(InternalXxmMetaDto):
    pass


class XxmDataStatusDto(InternalXxmDataStatusDto):
    pass


class XxmResponseDto(XxmDto):
    tsCode: XxmTsCode
    period: Literal["day", "m30", "m60", "m90", "m120"]
    algorithmVersion: str
    specHash: str
    source: XxmSourceDto
    points: list[XxmPointDto]
    events: list[XxmEventDto]
    meta: XxmMetaDto
    dataStatus: XxmDataStatusDto

    @model_validator(mode="after")
    def public_facts(self):
        if self.algorithmVersion != MAIN_SPEC.algorithm_version or self.specHash != MAIN_SPEC.spec_hash:
            raise ValueError("Unsupported XXM identity")
        times = [p.time for p in self.points]
        if times != sorted(set(times)) or self.meta.count != len(times):
            raise ValueError("Invalid public XXM window")
        if (self.meta.responseStart != (times[0] if times else None) or self.meta.responseEnd != (times[-1] if times else None)):
            raise ValueError("Invalid public XXM bounds")
        if self.source.kind != ("daily_factor" if self.period == "day" else "minute_gold"):
            raise ValueError("Invalid source kind")
        if self.period == "day" and self.source.indicatorVersion is not None:
            raise ValueError("Daily source has no indicator version")
        through = self.source.computedThrough
        if self.dataStatus.asOf != through:
            raise ValueError("Invalid public asOf")
        if self.dataStatus.status == "EMPTY":
            if times or self.events or through is not None or self.source.startTime is not None:
                raise ValueError("Nonempty EMPTY result")
        elif not self.source.startTime or not through or self.source.startTime > through:
            raise ValueError("Missing public source interval")
        for stamp in [self.source.startTime, through, *times]:
            if stamp is not None:
                XxmBar(stamp, 1., 0., 0., 0.).validate(self.period)
                if not self.source.startTime <= stamp <= through:
                    raise ValueError("Public point outside source")
        if len({e.id for e in self.events}) != len(self.events) or [e.time for e in self.events] != sorted(e.time for e in self.events):
            raise ValueError("Duplicate or unordered public events")
        for event in self.events:
            if event.time not in times:
                raise ValueError("Event outside visible window")
            if not event.displayOnChart and (event.type != "CANCEL" or not any(
                    e.time == event.time and e.direction == event.direction and e.type == "DULL" and e.displayOnChart for e in self.events)):
                raise ValueError("Invalid hidden event")
        return self
