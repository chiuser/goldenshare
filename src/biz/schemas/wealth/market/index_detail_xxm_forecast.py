from __future__ import annotations

from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .index_detail_xxm import XxmReferenceDto, XxmRearmRecordDto
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC


class Dto(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class PriceRangeDto(Dto):
    lower: float | None
    upper: float | None
    lowerInclusive: bool
    upperInclusive: bool

    @model_validator(mode='after')
    def valid(self):
        if self.lower is not None and (self.lower < 0 or self.lower == 0 and self.lowerInclusive):
            raise ValueError('Prices must be positive')
        if self.lower is None and self.lowerInclusive or self.upper is None and self.upperInclusive:
            raise ValueError('Unbounded endpoint cannot be inclusive')
        if self.upper is not None and (self.upper <= 0 or self.lower is not None and
           (self.upper < self.lower or self.upper == self.lower and not (self.lowerInclusive and self.upperInclusive))):
            raise ValueError('Empty or unordered price interval')
        return self


class CloseRangeDto(PriceRangeDto):
    route: Literal['dif_turn', 'color_flip']
    displayLower: float
    displayUpper: float | None
    displayPlaces: Literal[2, 4]

    @model_validator(mode='after')
    def display_valid(self):
        if self.displayLower <= 0 or self.lower is not None and (self.displayLower < self.lower or self.displayLower == self.lower and not self.lowerInclusive):
            raise ValueError('Display lower must be inside the interval')
        if self.upper is None:
            if self.displayUpper is not None:
                raise ValueError('Unbounded upper cannot have a finite display upper')
        elif self.displayUpper is None or self.displayUpper < self.displayLower or self.displayUpper > self.upper or self.displayUpper == self.upper and not self.upperInclusive:
            raise ValueError('Display upper must be inside the interval')
        return self


class AffineExpressionDto(Dto):
    op: Literal['affine']
    pCoefficient: float
    cCoefficient: float
    constant: float


class ScaleExpressionDto(Dto):
    op: Literal['scale']
    arg: ForecastExpression
    factor: float


class AbsExpressionDto(Dto):
    op: Literal['abs']
    arg: ForecastExpression


class SubExpressionDto(Dto):
    op: Literal['sub']
    args: tuple[ForecastExpression, ForecastExpression]


class RoundedExpressionDto(Dto):
    op: Literal['round3']
    arg: AffineExpressionDto
    guard: float = Field(gt=0)


ForecastExpression = Annotated[Union[AffineExpressionDto, ScaleExpressionDto, AbsExpressionDto,
                                    SubExpressionDto, RoundedExpressionDto], Field(discriminator='op')]
for _expression in (ScaleExpressionDto, AbsExpressionDto, SubExpressionDto):
    _expression.model_rebuild()


class ConditionDto(Dto):
    left: ForecastExpression
    op: Literal['lt', 'le', 'eq', 'ge', 'gt']
    right: ForecastExpression


class EntryRangeDto(Dto):
    entryRangeId: str
    priceRange: PriceRangeDto
    reference: XxmReferenceDto


class EntryExclusionDto(Dto):
    priceRange: PriceRangeDto
    reason: Literal['PRICE_NOT_EXTREME', 'DIF_NOT_DIVERGENT', 'WRONG_COLOR_OR_ZERO',
                    'INSUFFICIENT_BARS', 'PRECISION_UNRESOLVED', 'CURRENT_DIF_NOT_POSITIVE']


class ActivationDto(Dto):
    endpoint: str
    ranges: list[EntryRangeDto]
    exclusions: list[EntryExclusionDto]


class AssumptionDto(Dto):
    policy: Literal['entry_range_then_flat']
    activationEndpoint: str | None
    intermediateEndpoints: list[str]
    intermediateCloseExpression: AffineExpressionDto


class TargetEntryRangeDto(Dto):
    entryRangeIds: list[str]
    priceRange: PriceRangeDto


class TargetEntryExclusionDto(TargetEntryRangeDto):
    reason: Literal['CANCEL_BEFORE_TARGET', 'EARLY_STRUCTURE', 'COLOR_OR_ZERO',
                    'NO_TARGET_SOLUTION', 'PRECISION_UNRESOLVED']


class ReferenceTransitionDto(Dto):
    endpoint: str
    fromReference: XxmReferenceDto
    toReference: XxmReferenceDto


class NextBarBranchDto(Dto):
    branchId: str
    priceRange: PriceRangeDto
    outcome: Literal['PRESERVED','REFERENCE_SWITCHED','STRUCTURE_CONFIRMED','CANCELLED','ZERO_RESET','PRECISION_UNRESOLVED']
    reference: XxmReferenceDto | None
    route: Literal['dif_turn','color_flip','dif_break','dif_break_on_flip'] | None


class NextBarOutcomesDto(Dto):
    endpoint: str
    initialReference: XxmReferenceDto
    branches: list[NextBarBranchDto]

    @model_validator(mode='after')
    def complete(self):
        if not self.branches or len({b.branchId for b in self.branches})!=len(self.branches):
            raise ValueError('Next-bar branches require unique identities')
        ordered=sorted(self.branches,key=lambda b:(b.priceRange.lower or 0,not b.priceRange.lowerInclusive))
        if ordered!=self.branches or (ordered[0].priceRange.lower or 0)!=0 or ordered[-1].priceRange.upper is not None:
            raise ValueError('Next-bar domain must cover all positive prices')
        for a,b in zip(ordered,ordered[1:]):
            if a.priceRange.upper!=b.priceRange.lower or a.priceRange.upperInclusive==b.priceRange.lowerInclusive:
                raise ValueError('Next-bar domain overlaps or has a gap')
        for b in ordered:
            if b.outcome in ('ZERO_RESET','PRECISION_UNRESOLVED'):
                valid=b.reference is None and b.route is None
            elif b.outcome=='REFERENCE_SWITCHED':
                valid=b.reference is not None and b.reference!=self.initialReference and b.reference.dif<self.initialReference.dif and b.route is None
            else:
                valid=b.reference==self.initialReference and b.route in (
                    ('dif_turn','color_flip') if b.outcome=='STRUCTURE_CONFIRMED' else
                    ('dif_break','dif_break_on_flip') if b.outcome=='CANCELLED' else (None,))
            if not valid:raise ValueError('Next-bar outcome/reference/route mismatch')
        return self


class RelationDto(Dto):
    relationId: str
    entryRangeIds: list[str]
    entryDomain: PriceRangeDto | None
    reference: XxmReferenceDto
    initialReference: XxmReferenceDto
    referenceTransitions: list[ReferenceTransitionDto]
    route: Literal['dif_turn', 'color_flip']
    prefixConditions: list[ConditionDto]
    targetConditions: list[ConditionDto]


class CommonConditionDto(Dto):
    relationId: str
    entryRangeIds: list[str]
    entryDomain: PriceRangeDto | None
    reference: XxmReferenceDto
    route: Literal['dif_turn', 'color_flip']
    closeRanges: list[CloseRangeDto]


class ExampleCloseRangeDto(CloseRangeDto):
    relationId: str


class ExampleDto(Dto):
    preClose: float = Field(gt=0)
    entryRangeId: str
    closeRanges: list[ExampleCloseRangeDto]


class ForecastDisplayDto(Dto):
    statusLabel: str
    targetText: str
    conditionsText: str
    asOfText: str


class ForecastResponseDto(Dto):
    tsCode: Literal['000001.SH'] = '000001.SH'
    period: Literal['day', 'm60', 'm90', 'm120']
    forecastVersion: Literal['xxm-key-point-forecast-v0.3-r2']
    forecastSpecHash: str
    detectorSpecHash: str
    sourceInputId: str | None
    calendarInputId: str | None
    computedThrough: str | None
    requestedAsOf: str | None
    mode: Literal['LATEST', 'REPLAY']
    dataStatus: Literal['READY', 'DELAYED', 'EMPTY']
    ordinaryState: Literal['NONE', 'DULL', 'STRUCTURE'] | None
    rearmContext: XxmRearmRecordDto | None
    nextBarOutcomes: NextBarOutcomesDto | None
    direction: Literal['TOP', 'BOTTOM'] | None
    status: Literal['READY', 'CONDITIONAL_ENTRY', 'ENTRY_ONLY', 'NO_CANDIDATE', 'CONFIRMED',
                    'PRECISION_PENDING', 'DELAYED', 'EMPTY']
    reasonCode: Literal['ZERO_WAVE', 'NO_REFERENCE', 'NO_ENTRY_RANGE', 'NO_CONFIRMATION_IN_HORIZON',
                        'SOURCE_DELAYED', 'SOURCE_EMPTY', 'CALIBRATION_FAILED', 'ROUNDING_BOUNDARY', 'NARROW_INTERVAL'] | None
    precisionPolicy: Literal['rounded3_guarded', 'full_float']
    forecastId: str
    targetEndpoint: str | None
    barsAhead: int | None
    activation: ActivationDto | None
    assumption: AssumptionDto | None
    targetEntryRanges: list[TargetEntryRangeDto]
    targetEntryExclusions: list[TargetEntryExclusionDto]
    relations: list[RelationDto]
    commonConditions: list[CommonConditionDto]
    examples: list[ExampleDto]
    applicabilityText: str
    invalidationText: str
    confirmedAt: str | None
    confirmedDirection: Literal['TOP', 'BOTTOM'] | None
    display: ForecastDisplayDto
    refreshAfterMs: int = Field(gt=0)

    @model_validator(mode='after')
    def consistent(self):
        if self.detectorSpecHash != MAIN_SPEC.spec_hash or self.forecastSpecHash != FORECAST_SPEC.spec_hash:
            raise ValueError('Forecast requires the current detector and forecast identities')
        if self.activation and any(e.reason == 'CURRENT_DIF_NOT_POSITIVE' for e in self.activation.exclusions):
            if (self.dataStatus != 'READY' or self.ordinaryState != 'NONE' or self.direction != 'TOP'
                    or self.rearmContext is not None or self.status not in
                    ('CONDITIONAL_ENTRY', 'ENTRY_ONLY', 'NO_CANDIDATE', 'PRECISION_PENDING')):
                raise ValueError('Current-DIF exclusion requires inactive TOP activation')
        success = self.status in ('READY', 'CONDITIONAL_ENTRY')
        if self.rearmContext is not None:
            context = self.rearmContext
            if (self.dataStatus != 'READY' or self.ordinaryState != 'NONE' or self.direction != 'BOTTOM'
                    or self.status not in ('CONDITIONAL_ENTRY', 'ENTRY_ONLY', 'NO_CANDIDATE', 'PRECISION_PENDING')
                    or context.status != 'WAITING' or not self.computedThrough):
                raise ValueError('Waiting rearm requires actual inactive bottom state')
            context.validate_cutoff(self.period, self.computedThrough)
            references = ([r.reference for r in self.activation.ranges] if self.activation else [])
            references += [r.initialReference for r in self.relations]
            if any(r != context.reference for r in references):
                raise ValueError('Waiting activation cannot replace the saved reference')
        if self.nextBarOutcomes is not None:
            if (self.dataStatus!='READY' or self.ordinaryState!='DULL' or self.direction!='BOTTOM'
                    or not self.computedThrough or self.nextBarOutcomes.endpoint<=self.computedThrough):
                raise ValueError('Next-bar outcomes require actual bottom DULL')
        elif (self.dataStatus=='READY' and self.ordinaryState=='DULL' and self.direction=='BOTTOM'
                and self.reasonCode!='CALIBRATION_FAILED'):
            raise ValueError('Actual bottom DULL requires next-bar outcomes')
        if self.precisionPolicy != ('rounded3_guarded' if self.period=='day' else 'full_float'):
            raise ValueError('Precision policy does not match period')
        if self.targetEndpoint is not None:
            if not self.computedThrough or self.targetEndpoint <= self.computedThrough or not self.barsAhead or not 1 <= self.barsAhead <= 20:
                raise ValueError('Invalid single target')
            if self.status not in ('READY', 'CONDITIONAL_ENTRY', 'PRECISION_PENDING'):
                raise ValueError('Unexpected target')
        elif self.barsAhead is not None:
            raise ValueError('barsAhead requires target')
        if success and (self.dataStatus != 'READY' or not self.sourceInputId or not self.calendarInputId or
                        not self.targetEndpoint or not self.relations or self.assumption is None):
            raise ValueError('Missing successful range prediction')
        if not success and (self.relations or self.commonConditions or self.examples or self.assumption):
            raise ValueError('Inactive status cannot carry active confirmation conditions')
        if self.status == 'READY' and (self.ordinaryState != 'DULL' or self.activation or self.targetEntryRanges):
            raise ValueError('READY must use actual locked dulling')
        if self.status in ('CONDITIONAL_ENTRY', 'ENTRY_ONLY') and (self.ordinaryState != 'NONE' or not self.activation or not self.activation.ranges):
            raise ValueError('Conditional activation requires price ranges')
        if self.status == 'CONDITIONAL_ENTRY' and (not self.targetEntryRanges or self.barsAhead < 2):
            raise ValueError('Activation and confirmation are separate bars')
        if self.status == 'CONFIRMED' and (not self.confirmedAt or not self.confirmedDirection):
            raise ValueError('Actual confirmation identity required')
        if self.status in ('DELAYED', 'EMPTY', 'CONFIRMED') and self.activation:
            raise ValueError('No active future activation in this status')
        if len(self.examples) > 3:
            raise ValueError('Only three explanatory examples')
        ids={r.entryRangeId for r in self.activation.ranges} if self.activation else set()
        if self.activation:
            if len(ids) != len(self.activation.ranges) or not self.computedThrough or self.activation.endpoint <= self.computedThrough:
                raise ValueError('Activation IDs/endpoints invalid')
            if len({r.reference.startTime for r in self.activation.ranges}) > 2:
                raise ValueError('Detector only retains two original references')
        def inside(value, price_range):
            return (price_range.lower is None or value > price_range.lower or value==price_range.lower and price_range.lowerInclusive) and (price_range.upper is None or value < price_range.upper or value==price_range.upper and price_range.upperInclusive)
        for part in self.targetEntryRanges+self.targetEntryExclusions:
            if not part.entryRangeIds or not set(part.entryRangeIds)<=ids:
                raise ValueError('Target range must reference activation')
        relation_ids=set()
        relation_map={}
        for r in self.relations:
            if not r.targetConditions or r.relationId in relation_ids or not set(r.entryRangeIds) <= ids:
                raise ValueError('Invalid relation')
            relation_ids.add(r.relationId)
            relation_map[r.relationId]=r
            if self.status == 'CONDITIONAL_ENTRY' and (not r.entryRangeIds or r.entryDomain is None):
                raise ValueError('Relation must state its preceding range')
            if len(r.referenceTransitions)>1 or r.referenceTransitions and self.direction!='BOTTOM':
                raise ValueError('Only one bottom reference transition is possible')
            current=r.initialReference
            for t in r.referenceTransitions:
                activation_at=self.activation.endpoint if self.activation else self.computedThrough
                if (t.fromReference!=current or t.toReference==current or t.toReference.dif>=current.dif
                        or self.assumption is None or t.endpoint not in self.assumption.intermediateEndpoints
                        or t.endpoint<=activation_at or t.endpoint>=self.targetEndpoint):
                    raise ValueError('Invalid reference transition path')
                current=t.toReference
            if current!=r.reference:raise ValueError('Final confirmation reference differs from path')
            if self.activation and any(next(a.reference for a in self.activation.ranges if a.entryRangeId==key)!=r.initialReference for key in r.entryRangeIds):
                raise ValueError('Initial reference differs from activation')
            if self.status=='READY' and self.nextBarOutcomes and r.initialReference!=self.nextBarOutcomes.initialReference:
                raise ValueError('Initial reference differs from current DULL')
        for example in self.examples:
            if example.entryRangeId not in ids or not example.closeRanges or not any(example.entryRangeId in r.entryRangeIds and inside(example.preClose,r.priceRange) for r in self.targetEntryRanges):
                raise ValueError('Invalid explanatory example')
            for close in example.closeRanges:
                r=relation_map.get(close.relationId)
                if (r is None or example.entryRangeId not in r.entryRangeIds or r.entryDomain is None
                        or not inside(example.preClose,r.entryDomain) or close.route!=r.route):
                    raise ValueError('Example must bind its exact relation')
        for c in self.commonConditions:
            if not c.closeRanges or not set(c.entryRangeIds) <= ids or any(r.route != c.route for r in c.closeRanges):
                raise ValueError('Invalid universal sufficient condition')
            r=relation_map.get(c.relationId)
            if r is None or (c.entryRangeIds,c.entryDomain,c.reference,c.route)!=(r.entryRangeIds,r.entryDomain,r.reference,r.route):
                raise ValueError('Common condition must bind its exact relation')
        if self.assumption:
            expression=self.assumption.intermediateCloseExpression
            if expression.cCoefficient!=0:
                raise ValueError('Intermediate close cannot depend on target close')
            if self.status=='CONDITIONAL_ENTRY':
                if self.assumption.activationEndpoint!=self.activation.endpoint or expression.pCoefficient!=1 or expression.constant!=0 or self.targetEndpoint<=self.activation.endpoint:
                    raise ValueError('Conditional path must retain variable preceding close')
            elif self.assumption.activationEndpoint is not None or expression.pCoefficient!=0 or expression.constant<=0:
                raise ValueError('DULL path requires real preceding close')
            stamps=self.assumption.intermediateEndpoints
            if len(stamps)!=self.barsAhead-1:
                raise ValueError('Intermediate path does not match single target')
            if stamps != sorted(set(stamps)) or any(t <= self.computedThrough or t >= self.targetEndpoint for t in stamps):
                raise ValueError('Invalid hypothetical prefix endpoints')
        return self
