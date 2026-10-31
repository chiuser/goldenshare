"""Closed next-completed-bar contracts; no waiting or multi-bar responses."""
from __future__ import annotations

import math
from typing import Annotated, Literal, Union
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictInt, field_validator, model_validator
from .index_detail_xxm import XxmReferenceDto, XxmWaveDto, InternalXxmWaveDto
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from src.biz.services.wealth.market.index_detail_xxm.forecast_identity import (
    ROOT_FACT_FIELDS, DETAIL_FACT_FIELDS, forecast_result_id, forecast_condition_id,
)


def _expression_number(value):
    if type(value) not in (int, float):
        raise ValueError("Original numeric value required")
    try:
        if not math.isfinite(value):
            raise ValueError("Finite value required")
    except OverflowError as exc:
        raise ValueError("Finite value required") from exc
    return value


ExpressionNumber = Annotated[float, BeforeValidator(_expression_number)]


class Dto(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class AffineExpressionDto(Dto):
    op: Literal["affine"]
    pCoefficient: ExpressionNumber
    cCoefficient: ExpressionNumber
    constant: ExpressionNumber

    @model_validator(mode="after")
    def single_variable(self):
        if self.pCoefficient != 0 or self.cCoefficient not in (0, 1) or (self.cCoefficient == 1 and self.constant != 0):
            raise ValueError("Only constant or current close is allowed")
        return self


class ScaleExpressionDto(Dto):
    op: Literal["scale"]
    arg: ForecastExpression
    factor: ExpressionNumber


class AbsExpressionDto(Dto):
    op: Literal["abs"]
    arg: ForecastExpression


class SubExpressionDto(Dto):
    op: Literal["sub"]
    args: list[ForecastExpression] = Field(min_length=2, max_length=2)


class MacdExpressionDto(Dto):
    op: Literal["macd"]
    e12: ExpressionNumber
    e26: ExpressionNumber
    dea: ExpressionNumber
    field: Literal["dif", "hist"]


class RoundedExpressionDto(Dto):
    op: Literal["round3"]
    arg: ForecastExpression
    guard: ExpressionNumber = Field(gt=0)


ForecastExpression = Annotated[Union[AffineExpressionDto, ScaleExpressionDto, AbsExpressionDto,
    SubExpressionDto, MacdExpressionDto, RoundedExpressionDto], Field(discriminator="op")]
for _expression in (ScaleExpressionDto, AbsExpressionDto, SubExpressionDto, RoundedExpressionDto):
    _expression.model_rebuild()


class ConditionDto(Dto):
    left: ForecastExpression
    op: Literal["lt", "le", "eq", "ge", "gt"]
    right: ForecastExpression


class PriceRangeDto(Dto):
    lower: ExpressionNumber = Field(ge=0)
    upper: ExpressionNumber | None
    lowerInclusive: bool
    upperInclusive: bool

    @model_validator(mode="after")
    def valid(self):
        if (self.lower == 0 and self.lowerInclusive or self.upper is None and self.upperInclusive
                or self.upper is not None and (self.upper < self.lower or self.upper == self.lower and not (self.lower > 0 and self.lowerInclusive and self.upperInclusive))):
            raise ValueError("Empty or invalid positive price range")
        return self


class DisplayPriceRangeDto(PriceRangeDto):
    displayLower: StrictInt | None
    displayUpper: StrictInt | None

    @model_validator(mode="after")
    def integers(self):
        lo = math.ceil(self.lower) + int(not self.lowerInclusive and self.lower == math.ceil(self.lower))
        hi = None if self.upper is None else math.floor(self.upper) - int(not self.upperInclusive and self.upper == math.floor(self.upper))
        expected = (None, None) if hi is not None and lo > hi else (lo, hi)
        if (self.displayLower, self.displayUpper) != expected:
            raise ValueError("Display integers must be the exact valid boundaries")
        for v in expected:
            if v is not None:
                f = float(v)
                if not math.isfinite(f) or int(f) != v:
                    raise ValueError("Display integer cannot be represented")
        return self


class PrecisionRangeDto(Dto):
    priceRange: PriceRangeDto
    reason: Literal["ROUNDING_BOUNDARY"]


Outcome = Literal["DULL_FORMED", "DULL_HELD", "STRUCTURE_FORMED", "STRUCTURE_HELD", "RETURNED_TO_DULL",
    "STRUCTURE_FORMED_AND_FOLLOWING", "STRUCTURE_FOLLOWING", "STRUCTURE_PRICE_DISAPPEARED", "SIGNAL_DISAPPEARED", "REFERENCE_INVALIDATED"]


class ForecastConditionDto(Dto):
    id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    outcome: Outcome
    referenceRole: Literal["NEAR", "FAR"]
    priceRanges: list[DisplayPriceRangeDto] = Field(min_length=1)
    predicates: list[ConditionDto] = Field(min_length=1)


class StructureFollowConditionDto(Dto):
    id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["SIGNAL_DISAPPEARED"]
    relatedStructureId: str = Field(min_length=1)
    direction: Literal["TOP", "BOTTOM"]
    originWave: XxmWaveDto
    nextSameColorStart: str | None
    nextSameColorCount: StrictInt = Field(ge=0)
    priceRanges: list[DisplayPriceRangeDto]
    precisionRanges: list[PrecisionRangeDto]
    predicates: list[ConditionDto] = Field(min_length=1)


class InternalStructureFollowConditionDto(StructureFollowConditionDto):
    originWave: InternalXxmWaveDto


class ForecastReferencesDto(Dto):
    nearest: XxmReferenceDto | None
    farther: XxmReferenceDto | None


class NearestDecisionDto(Dto):
    status: Literal["NOT_EVALUATED", "UNAVAILABLE", "HAS_RANGE", "NO_RANGE", "UNCERTAIN"]
    reason: str | None = Field(min_length=1)


class ForecastDisplayDto(Dto):
    statusLabel: str = Field(min_length=1)
    targetText: str = Field(min_length=1)
    conditionsText: str = Field(min_length=1)
    asOfText: str = Field(min_length=1)


class ForecastResponseDto(Dto):
    tsCode: Literal["000001.SH"]
    period: Literal["day", "m60", "m90", "m120"]
    forecastVersion: str
    forecastSpecHash: str
    detectorSpecHash: str
    computedThrough: str | None
    requestedAsOf: str | None
    mode: Literal["LATEST", "REPLAY"]
    dataStatus: Literal["READY", "DELAYED", "EMPTY"]
    ordinaryState: Literal["NONE", "DULL", "STRUCTURE"] | None
    direction: Literal["TOP", "BOTTOM"] | None
    targetEndpoint: str | None
    barsAhead: Literal[1] | None
    status: Literal["READY", "NO_CANDIDATE", "PRECISION_PENDING", "DELAYED", "EMPTY"]
    reasonCode: Literal["SOURCE_EMPTY", "SOURCE_DELAYED", "ZERO_WAVE", "NO_REFERENCE", "NO_ENTRY_RANGE", "CALIBRATION_FAILED", "ROUNDING_BOUNDARY"] | None
    forecastId: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    display: ForecastDisplayDto
    applicabilityText: str = Field(min_length=1)
    invalidationText: str = Field(min_length=1)
    refreshAfterMs: StrictInt

    @field_validator("barsAhead", mode="before")
    @classmethod
    def original_bar_count(cls, value):
        if value is not None and (type(value) is not int or value != 1):
            raise ValueError("A forecast requires original integer 1 or None")
        return value

    @model_validator(mode="after")
    def public_facts(self):
        if (self.forecastVersion != FORECAST_SPEC.forecast_version or self.forecastSpecHash != FORECAST_SPEC.spec_hash
                or self.detectorSpecHash != MAIN_SPEC.spec_hash or self.refreshAfterMs != FORECAST_SPEC.refresh_after_ms):
            raise ValueError("Unsupported forecast identity")
        if (self.mode == "LATEST") != (self.requestedAsOf is None):
            raise ValueError("Forecast request mode mismatch")
        for stamp in (self.computedThrough, self.requestedAsOf, self.targetEndpoint):
            if stamp is not None:
                XxmBar(stamp, 1., 0., 0., 0.).validate(self.period)
        if (self.targetEndpoint is None) != (self.barsAhead is None):
            raise ValueError("A forecast has exactly one endpoint")
        if self.targetEndpoint is not None and (self.computedThrough is None or self.targetEndpoint <= self.computedThrough):
            raise ValueError("Endpoint must follow real prefix")
        if self.requestedAsOf is not None and self.computedThrough is not None and self.computedThrough > self.requestedAsOf:
            raise ValueError("Future input in replay")
        reasons = {"EMPTY": {"SOURCE_EMPTY"}, "DELAYED": {"SOURCE_DELAYED"},
                   "NO_CANDIDATE": {"ZERO_WAVE", "NO_REFERENCE", "NO_ENTRY_RANGE"},
                   "PRECISION_PENDING": {"CALIBRATION_FAILED", "ROUNDING_BOUNDARY"}, "READY": {None, "ROUNDING_BOUNDARY"}}
        if self.reasonCode not in reasons[self.status]:
            raise ValueError("Forecast status/reason mismatch")
        if self.dataStatus != "READY":
            if self.status != self.dataStatus or self.targetEndpoint is not None:
                raise ValueError("Source state mismatch")
        elif self.status in ("EMPTY", "DELAYED"):
            raise ValueError("Invalid source state")
        if self.dataStatus == "EMPTY":
            if any(x is not None for x in (self.computedThrough, self.ordinaryState, self.direction)):
                raise ValueError("EMPTY has no actual state")
        elif self.computedThrough is None or self.ordinaryState is None:
            raise ValueError("Missing actual prefix state")
        if self.ordinaryState in ("DULL", "STRUCTURE") and self.direction is None:
            raise ValueError("Active state requires direction")
        if self.status == "READY" and self.targetEndpoint is None or self.reasonCode == "CALIBRATION_FAILED" and self.targetEndpoint is not None:
            raise ValueError("Invalid solve target")
        return self


class ForecastDebugDto(Dto):
    sourceInputId: str | None = Field(min_length=1)
    calendarInputId: str | None = Field(min_length=1)
    precisionPolicy: Literal["rounded3_guarded", "full_float"]
    references: ForecastReferencesDto
    selectedReference: Literal["NEAR", "FAR"] | None
    nearestDecision: NearestDecisionDto
    farEvaluated: bool
    conditions: list[ForecastConditionDto]
    precisionRanges: list[PrecisionRangeDto]
    structureFollowConditions: list[StructureFollowConditionDto]


class InternalForecastResponseDto(ForecastResponseDto):
    sourceInputId: str | None = Field(min_length=1)
    calendarInputId: str | None = Field(min_length=1)
    precisionPolicy: Literal["rounded3_guarded", "full_float"]
    references: ForecastReferencesDto
    selectedReference: Literal["NEAR", "FAR"] | None
    nearestDecision: NearestDecisionDto
    farEvaluated: bool
    conditions: list[ForecastConditionDto]
    precisionRanges: list[PrecisionRangeDto]
    structureFollowConditions: list[InternalStructureFollowConditionDto]

    @model_validator(mode="after")
    def complete_facts(self):
        _validate_details(self, self)
        return self


class ForecastDebugResponseDto(ForecastResponseDto):
    debug: ForecastDebugDto

    @model_validator(mode="after")
    def complete_facts(self):
        _validate_details(self, self.debug)
        return self


def _overlap(a, b):
    lo, hi = max(a.lower, b.lower), min(a.upper or math.inf, b.upper or math.inf)
    if lo < hi:
        return True
    if lo > hi:
        return False
    def contains(r):
        return (lo > r.lower or r.lowerInclusive) and (r.upper is None or lo < r.upper or r.upperInclusive)
    return contains(a) and contains(b)


def _ranges(ranges, pending):
    order = [(r.lower, not r.lowerInclusive) for r in ranges]
    if order != sorted(order) or any(_overlap(a, b) for a,b in zip(ranges, ranges[1:])):
        raise ValueError("Unordered or overlapping ranges")
    if any(_overlap(a,b.priceRange) for a in ranges for b in pending):
        raise ValueError("Certain and uncertain ranges overlap")


def _validate_details(root, details):
    if details.precisionPolicy != ("rounded3_guarded" if root.period == "day" else "full_float"):
        raise ValueError("Precision/period mismatch")
    if (details.sourceInputId is None) != (root.dataStatus == "EMPTY"):
        raise ValueError("Invalid source identity")
    if (details.calendarInputId is None) != (root.targetEndpoint is None):
        raise ValueError("Invalid calendar identity")
    if root.targetEndpoint is None and (details.selectedReference is not None or details.farEvaluated or details.conditions or details.precisionRanges or details.structureFollowConditions):
        raise ValueError("Unsolved result has no conditions")
    if details.farEvaluated != (details.selectedReference == "FAR"):
        raise ValueError("Far evaluation differs from selection")
    ref = details.references.nearest if details.selectedReference == "NEAR" else details.references.farther if details.selectedReference == "FAR" else None
    if details.selectedReference is not None and ref is None:
        raise ValueError("Selected reference is absent")
    ids = [c.id for c in details.conditions] + [c.id for c in details.structureFollowConditions]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate forecast condition identity")
    outcomes = [c.outcome for c in details.conditions]
    if len(outcomes) != len(set(outcomes)):
        raise ValueError("Duplicate ordinary outcome")
    allowed = {"NONE": {"DULL_FORMED"}, "DULL": {"DULL_HELD", "STRUCTURE_FORMED", "STRUCTURE_FORMED_AND_FOLLOWING", "STRUCTURE_PRICE_DISAPPEARED", "REFERENCE_INVALIDATED", "SIGNAL_DISAPPEARED"},
               "STRUCTURE": {"STRUCTURE_HELD", "RETURNED_TO_DULL", "STRUCTURE_FOLLOWING", "STRUCTURE_PRICE_DISAPPEARED", "SIGNAL_DISAPPEARED"}, None: set()}
    bindings = set()
    def expr(value):
        if isinstance(value, MacdExpressionDto):
            bindings.add((value.e12,value.e26,value.dea))
        elif isinstance(value, SubExpressionDto):
            for arg in value.args: expr(arg)
        elif isinstance(value, (ScaleExpressionDto, AbsExpressionDto, RoundedExpressionDto)):
            expr(value.arg)
    def stamp(value):
        XxmBar(value,1.,0.,0.,0.).validate(root.period)
        if root.computedThrough is None or value > root.computedThrough:
            raise ValueError("Future reference fact")
    for r in (details.references.nearest, details.references.farther):
        if r:
            for v in (r.startTime,r.endTime,r.priceAt,r.difAt): stamp(v)
            if r.endTime >= root.computedThrough:
                raise ValueError("Reference is not historical")
    if details.references.farther is not None and (details.references.nearest is None or details.references.farther.endTime >= details.references.nearest.startTime):
        raise ValueError("Near/far chronology mismatch")
    for c in details.conditions:
        if c.referenceRole != details.selectedReference or c.outcome not in allowed[root.ordinaryState]:
            raise ValueError("Condition state/reference mismatch")
        _ranges(c.priceRanges,details.precisionRanges)
        for p in c.predicates: expr(p.left); expr(p.right)
    groups = set()
    for c in details.structureFollowConditions:
        if c.direction in groups or (c.nextSameColorStart is None) != (c.nextSameColorCount == 0):
            raise ValueError("Duplicate or invalid followed progress")
        groups.add(c.direction)
        w=c.originWave
        for v in (w.start,w.end,getattr(w,'priceAt',getattr(w,'price_at',None)),getattr(w,'difAt',getattr(w,'dif_at',None))): stamp(v)
        if w.sign != (1 if c.direction == 'TOP' else -1): raise ValueError("Old structure direction mismatch")
        if c.nextSameColorStart is not None:
            stamp(c.nextSameColorStart)
            if c.nextSameColorStart <= w.end: raise ValueError("Old structure progress chronology mismatch")
        _ranges(c.priceRanges,c.precisionRanges)
        for p in c.predicates: expr(p.left); expr(p.right)
    if len(bindings)>1: raise ValueError("Inconsistent original EMA bindings")
    certain=bool(details.conditions or any(c.priceRanges for c in details.structureFollowConditions))
    pending=bool(details.precisionRanges or any(c.precisionRanges for c in details.structureFollowConditions))
    if root.status == 'READY' and not certain or root.status == 'NO_CANDIDATE' and (certain or pending):
        raise ValueError("Forecast status disagrees with conditions")
    if root.status == 'PRECISION_PENDING' and (certain or root.reasonCode == 'ROUNDING_BOUNDARY' and not pending):
        raise ValueError("Uncertain forecast cannot contain certain conditions")
    if root.reasonCode == 'ROUNDING_BOUNDARY' and not pending:
        raise ValueError("Missing precision ranges")
    _validate_identity(root, details)


def _validate_identity(root, details):
    payload = {name: getattr(root, name) for name in ROOT_FACT_FIELDS}
    raw_details = details.model_dump()
    payload.update({name: raw_details[name] for name in DETAIL_FACT_FIELDS})
    if isinstance(details, ForecastDebugDto):
        for condition in payload['structureFollowConditions']:
            wave = condition['originWave']
            wave['price_at'], wave['dif_at'] = wave.pop('priceAt'), wave.pop('difAt')
    if root.forecastId != forecast_result_id(payload):
        raise ValueError("Forecast identity does not match complete facts")
    for condition in details.conditions:
        if condition.id != forecast_condition_id(root.forecastId, condition.outcome):
            raise ValueError("Forecast condition identity mismatch")
    for condition in details.structureFollowConditions:
        if condition.id != forecast_condition_id(root.forecastId, condition.outcome, condition.relatedStructureId):
            raise ValueError("Followed structure condition identity mismatch")
