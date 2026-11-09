from typing import Literal

from pydantic import Field, model_validator

from .index_detail_xxm import (
    InternalXxmResponseDto, InternalXxmStructureDto, XxmDto, XxmReferenceDto, XxmResponseDto, XxmWaveDto,
)


class XxmDebugPointDto(XxmDto):
    time: str
    activeReference: XxmReferenceDto | None
    activeStructureId: str | None


class XxmDebugEventDto(XxmDto):
    id: str
    route: Literal["activation", "dif_turn", "dif_return", "color_flip", "dif_break", "dif_break_on_flip", "structure_price_break"]
    fromState: Literal["NONE", "DULL", "STRUCTURE"]
    eventReference: XxmReferenceDto
    relatedStructureId: str | None


class XxmStructureDto(InternalXxmStructureDto):
    originWave: XxmWaveDto | None

    @model_validator(mode="after")
    def lifecycle(self):
        # Native lifecycle validation is performed on the reconstructed complete
        # internal response below; the wire wave deliberately uses camelCase.
        return self


class XxmDebugDto(XxmDto):
    sourceInputId: str = Field(min_length=1)
    points: list[XxmDebugPointDto]
    events: list[XxmDebugEventDto]
    structures: list[XxmStructureDto]


class XxmDebugResponseDto(XxmResponseDto):
    debug: XxmDebugDto

    @model_validator(mode="after")
    def complete_debug(self):
        raw = self.model_dump()
        details = raw.pop("debug")
        if ([p["time"] for p in details["points"]] != [p["time"] for p in raw["points"]]
                or [e["id"] for e in details["events"]] != [e["id"] for e in raw["events"]]):
            raise ValueError("Debug/public order mismatch")
        raw["source"]["inputId"] = details["sourceInputId"]
        raw["points"] = [dict(p, **q) for p, q in zip(raw["points"], details["points"])]
        raw["events"] = [dict({k:v for k,v in p.items() if k != "displayOnChart"}, **q) for p,q in zip(raw["events"],details["events"])]
        for record in details["structures"]:
            wave = record["originWave"]
            if wave is not None:
                wave["price_at"], wave["dif_at"] = wave.pop("priceAt"), wave.pop("difAt")
        raw["structures"] = details["structures"]
        InternalXxmResponseDto.model_validate(raw)
        from goldenshare_technical_indicators.xxm.event_display import event_display_flags
        flags = event_display_flags(raw["events"])
        if any(event.displayOnChart != flags[event.id] for event in self.events):
            raise ValueError("Incorrect display selection")
        return self
