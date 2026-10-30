from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
from typing import Any, Literal, TypedDict, TYPE_CHECKING

if TYPE_CHECKING:
    from .forecast_math import Interval


XxmPeriod = Literal["day", "m60", "m90", "m120"]


@dataclass(frozen=True, slots=True)
class XxmBar:
    time: str
    close: float
    dif: float
    dea: float
    hist: float
    completed: bool = True

    def validate(self, period: XxmPeriod) -> None:
        values = (self.close, self.dif, self.dea, self.hist)
        if (self.completed is not True or not isinstance(self.time, str) or not self.time
                or any(type(value) not in (int, float) for value in values)):
            raise ValueError("XXM requires numeric completed bars and a valid time")
        try:
            if self.close <= 0 or not all(math.isfinite(value) for value in values):
                raise ValueError("XXM requires finite completed bars and positive closes")
            if period == "day":
                if date.fromisoformat(self.time).isoformat() != self.time:
                    raise ValueError("Invalid daily time")
            elif period in ("m60", "m90", "m120"):
                stamp = datetime.fromisoformat(self.time)
                if stamp.utcoffset() != timedelta(hours=8):
                    raise ValueError("Minute endpoint must include +08:00")
            else:
                raise ValueError("Unsupported XXM period")
        except (TypeError, OverflowError) as exc:
            raise ValueError("Malformed XXM bar") from exc


@dataclass(slots=True)
class Wave:
    sign: int
    start: str
    end: str
    count: int
    price: float
    dif: float
    price_at: str
    dif_at: str

    def reference(self) -> dict[str, Any]:
        return {"startTime": self.start, "endTime": self.end, "price": self.price, "dif": self.dif,
                "priceAt": self.price_at, "difAt": self.dif_at}


class XxmStructureRecord(TypedDict):
    id: str
    direction: Literal["TOP", "BOTTOM"]
    structureEventId: str
    formedAt: str
    formationRoute: Literal["dif_turn", "color_flip"]
    originSegmentStart: str
    originalReference: XxmReferenceFacts
    priceExtreme: float
    priceExtremeAt: str
    status: Literal["ASSESSING", "LOCKED", "DISAPPEARED"]
    lockedAt: str | None
    disappearedAt: str | None
    disappearanceReason: Literal["dif_return", "reference_dif_break"] | None


class XxmReferenceFacts(TypedDict):
    startTime: str
    endTime: str
    price: float
    dif: float
    priceAt: str
    difAt: str


class XxmWaveFacts(TypedDict):
    sign: int
    start: str
    end: str
    count: int
    price: float
    dif: float
    price_at: str
    dif_at: str


class XxmDecisionBefore(TypedDict):
    state: Literal["NONE", "DULL", "STRUCTURE"]
    reference: XxmReferenceFacts | None
    wave: XxmWaveFacts | None
    previousDif: float | None
    activeStructureId: str | None


class XxmReferenceCheck(TypedDict):
    stage: Literal["nearest_price_gate", "activation", "same_bar_rescue", "not_entered"]
    candidate: Literal["B", "A"]
    wave: XxmWaveFacts
    checked: bool
    pricePassed: bool | None
    difPassed: bool | None
    referenceBroken: bool | None
    reason: str


class XxmSelectionCall(TypedDict):
    stage: Literal["activation", "same_bar_rescue"]
    selected: XxmReferenceFacts | None


class XxmTurnFacts(TypedDict):
    previousDif: float | None
    currentDif: float
    threshold: float | None
    referenceBroken: bool | None
    checked: bool
    reason: str


class XxmDecision(TypedDict):
    time: str
    rawSign: int
    before: XxmDecisionBefore
    wave: XxmWaveFacts | None
    referenceAfter: XxmReferenceFacts | None
    referenceChecks: list[XxmReferenceCheck]
    selectionCalls: list[XxmSelectionCall]
    turn: XxmTurnFacts
    switched: bool
    structureId: str | None
    structureStatus: Literal["ASSESSING", "LOCKED", "DISAPPEARED"] | None
    branch: str
    reason: str


@dataclass(frozen=True, slots=True)
class XxmStep:
    point: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    structures: tuple[XxmStructureRecord, ...]
    decision: XxmDecision | None = None


@dataclass(frozen=True, slots=True)
class ForecastPrecheck:
    snapshot: dict[str, Any]
    direction: Literal["TOP", "BOTTOM"] | None
    references: dict[str, XxmReferenceFacts | None]
    active_role: Literal["NEAR", "FAR"] | None
    nearest_decision: dict[str, str | None]
    stop_reason: str | None


@dataclass(frozen=True, slots=True)
class ComparisonRanges:
    certain_true: tuple[Interval, ...]
    certain_false: tuple[Interval, ...]
    undecided: tuple[Interval, ...]


@dataclass(frozen=True, slots=True)
class ForecastConditionDraft:
    outcome: str
    reference_role: Literal["NEAR", "FAR"]
    price_ranges: tuple[dict[str, Any], ...]
    predicates: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ReferenceForecast:
    conditions: tuple[ForecastConditionDraft, ...]
    relationship_ranges: tuple[Interval, ...]
    relationship_precision_ranges: tuple[Interval, ...]
    precision_ranges: tuple[Interval, ...]


@dataclass(frozen=True, slots=True)
class ForecastKernelResult:
    status: str
    reason_code: str | None
    target_endpoint: str | None
    bars_ahead: Literal[1] | None
    references: dict[str, XxmReferenceFacts | None]
    selected_reference: Literal["NEAR", "FAR"] | None
    nearest_decision: dict[str, str | None]
    far_evaluated: bool
    conditions: tuple[ForecastConditionDraft, ...]
    precision_ranges: tuple[dict[str, Any], ...]
