"""Immutable facts and independent dictionary projections, LLD 14.6.1."""
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Literal

Metric = Literal["CLOSE", "DIF"]
Kind = Literal["MAX", "MIN"]
Color = Literal["RED", "GREEN"]


def decimal_text(value: Decimal) -> str:
    """Change notation only; Decimal.normalize() can round long source values."""
    if value.is_zero():
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True, slots=True)
class DailyPoint:
    date: str
    close: Decimal
    dif: Decimal
    dea: Decimal
    macd: Decimal

    def to_dict(self) -> dict:
        return {"date": self.date, **{
            key: decimal_text(getattr(self, key))
            for key in ("close", "dif", "dea", "macd")
        }}


@dataclass(frozen=True, slots=True)
class Turn:
    id: str
    metric: Metric
    kind: Kind | None
    value: Decimal
    firstDate: str
    lastDate: str
    plateauDates: tuple[str, ...]
    confirmedAt: str | None
    possibleKind: Kind | None = None

    def to_dict(self) -> dict:
        record = dict(id=self.id, metric=self.metric, kind=self.kind,
                      value=decimal_text(self.value), firstDate=self.firstDate,
                      lastDate=self.lastDate, plateauDates=list(self.plateauDates),
                      confirmedAt=self.confirmedAt)
        if self.confirmedAt is None:
            record["possibleKind"] = self.possibleKind
        return record


@dataclass(frozen=True, slots=True)
class Extreme:
    value: Decimal
    dates: tuple[str, ...]

    def to_dict(self) -> dict:
        return dict(value=decimal_text(self.value), dates=list(self.dates))


@dataclass(frozen=True, slots=True)
class HistogramExtreme:
    value: Decimal
    absoluteLength: Decimal
    dates: tuple[str, ...]

    def to_dict(self) -> dict:
        return dict(value=decimal_text(self.value),
                    absoluteLength=decimal_text(self.absoluteLength),
                    dates=list(self.dates))


@dataclass(frozen=True, slots=True)
class Extrema:
    maxClose: Extreme
    minClose: Extreme
    maxDif: Extreme
    minDif: Extreme
    longestRed: HistogramExtreme | None
    longestGreen: HistogramExtreme | None

    def to_dict(self) -> dict:
        return {name: (value.to_dict() if value is not None else None)
                for name in ("maxClose", "minClose", "maxDif", "minDif",
                             "longestRed", "longestGreen")
                for value in (getattr(self, name),)}


@dataclass(frozen=True, slots=True)
class ColorSegment:
    id: str
    color: Color
    startDate: str
    endDate: str
    lastColoredDate: str
    coloredCount: int
    zeroDates: tuple[str, ...]
    isLeftComplete: bool
    isEnded: bool
    endKnownAt: str | None
    turnIds: tuple[str, ...]
    extrema: Extrema

    def to_dict(self) -> dict:
        return dict(id=self.id, color=self.color, startDate=self.startDate,
                    endDate=self.endDate, lastColoredDate=self.lastColoredDate,
                    coloredCount=self.coloredCount, zeroDates=list(self.zeroDates),
                    isLeftComplete=self.isLeftComplete, isEnded=self.isEnded,
                    endKnownAt=self.endKnownAt, turnIds=list(self.turnIds),
                    extrema=self.extrema.to_dict())


@dataclass(frozen=True, slots=True)
class BasicRecords:
    tsCode: str
    period: str
    ruleId: str
    asOf: str | None
    contextStart: str | None
    contextEnd: str | None
    sourcePoints: tuple[DailyPoint, ...]
    turns: tuple[Turn, ...]
    pendingTurns: tuple[Turn, ...]
    colorSegments: tuple[ColorSegment, ...]

    def to_dict(self) -> dict:
        return dict(tsCode=self.tsCode, period=self.period, ruleId=self.ruleId,
                    asOf=self.asOf, contextStart=self.contextStart,
                    contextEnd=self.contextEnd,
                    sourcePoints=[point.to_dict() for point in self.sourcePoints],
                    turns=[turn.to_dict() for turn in self.turns],
                    pendingTurns=[turn.to_dict() for turn in self.pendingTurns],
                    colorSegments=[segment.to_dict() for segment in self.colorSegments])


def _project(value):
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, tuple):
        return [_project(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


class _Record:
    __slots__ = ()

    def to_dict(self) -> dict:
        return {field.name: _project(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class DateRange(_Record):
    startDate: str
    endDate: str


@dataclass(frozen=True, slots=True)
class CalendarDay(_Record):
    exchange: str
    date: str
    isOpen: bool


@dataclass(frozen=True, slots=True)
class PriceEndpoint(_Record):
    date: str
    closedAt: str
    close: Decimal
    tiedDates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Issue(_Record):
    message: str
    dates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PricePoint(_Record):
    date: str
    close: Decimal


@dataclass(frozen=True, slots=True)
class PriceComparison(_Record):
    fromDate: str
    toDate: str
    relation: str


@dataclass(frozen=True, slots=True)
class InternalPriceRelations(_Record):
    highs: tuple[PricePoint, ...]
    lows: tuple[PricePoint, ...]
    highComparisons: tuple[PriceComparison, ...]
    lowComparisons: tuple[PriceComparison, ...]
    status: str


@dataclass(frozen=True, slots=True)
class TailReview(_Record):
    range: DateRange | None
    turnIds: tuple[str, ...]
    extrema: Extrema | None
    strictlyBrokeStart: bool | None
    touchedStart: bool | None


@dataclass(frozen=True, slots=True)
class PriceSegment(_Record):
    id: str
    sourceColorSegmentId: str
    previousColorSegmentId: str | None
    direction: str
    generated: bool
    startSearchRange: DateRange | None
    endSearchRange: DateRange | None
    start: PriceEndpoint | None
    end: PriceEndpoint | None
    startKnownAt: str | None
    isEnded: bool
    endKnownAt: str | None
    startValidity: str
    endValidity: str
    endpointValidity: str
    issues: tuple[Issue, ...]
    internalPriceRelations: InternalPriceRelations | None
    tailReview: TailReview
    extrema: Extrema | None
    difTurnIds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EndpointOffset(_Record):
    difTurnId: str
    priceEndpoint: str
    tradingDayOffset: int


@dataclass(frozen=True, slots=True)
class MappingRecord(_Record):
    sourceColorSegmentId: str
    priceSegmentId: str
    colorRange: DateRange
    priceRange: DateRange | None
    observationIntersection: DateRange | None
    priceObservationIntersection: DateRange | None
    sourceTurnIds: tuple[str, ...]
    priceTurnIds: tuple[str, ...]
    endpointOffsets: tuple[EndpointOffset, ...]
    issues: tuple[Issue, ...]


@dataclass(frozen=True, slots=True)
class BarStats(_Record):
    coloredCount: int
    longestBar: HistogramExtreme


@dataclass(frozen=True, slots=True)
class ThreeBarStats(_Record):
    previous: BarStats
    opposite: BarStats
    next: BarStats


@dataclass(frozen=True, slots=True)
class ThreePriceExtrema(_Record):
    previous: Extreme
    opposite: Extreme
    next: Extreme


@dataclass(frozen=True, slots=True)
class ShortOppositeRecord(_Record):
    previousColorSegmentId: str
    oppositeColorSegmentId: str
    nextColorSegmentId: str
    barStats: ThreeBarStats
    priceHighs: ThreePriceExtrema
    priceLows: ThreePriceExtrema
    difTurnIds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateRecords(_Record):
    priceSegments: tuple[PriceSegment, ...]
    mappings: tuple[MappingRecord, ...]
    shortOppositeSegments: tuple[ShortOppositeRecord, ...]


@dataclass(frozen=True, slots=True)
class AsOfChange(_Record):
    asOf: str
    newConfirmedTurnIds: tuple[str, ...]
    updatedColorSegmentIds: tuple[str, ...]
    updatedPriceSegmentIds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageCounts(_Record):
    leftIncomplete: int
    ungenerated: int
    invalid: int
    unknown: int


@dataclass(frozen=True, slots=True)
class Coverage(_Record):
    mainPointCount: int
    leftIncompleteColorSegmentIds: tuple[str, ...]
    ungeneratedPriceSegmentIds: tuple[str, ...]
    invalidPriceSegmentIds: tuple[str, ...]
    unknownPriceSegmentIds: tuple[str, ...]
    counts: CoverageCounts


@dataclass(frozen=True, slots=True)
class ReviewResult(_Record):
    schemaVersion: int
    tsCode: str
    period: str
    status: str
    ruleId: str
    calculationId: str
    calculatedAt: str
    requestedStart: str
    requestedEnd: str
    observationStart: str | None
    observationEnd: str | None
    contextStart: str | None
    contextEnd: str | None
    asOf: str | None
    sourcePoints: tuple[DailyPoint, ...]
    turns: tuple[Turn, ...]
    pendingTurns: tuple[Turn, ...]
    colorSegments: tuple[ColorSegment, ...]
    priceSegments: tuple[PriceSegment, ...]
    mappings: tuple[MappingRecord, ...]
    shortOppositeSegments: tuple[ShortOppositeRecord, ...]
    asofChanges: tuple[AsOfChange, ...]
    coverage: Coverage

    def to_dict(self) -> dict:
        result = super(ReviewResult, self).to_dict()
        if self.status == "empty":
            keys = ("schemaVersion", "tsCode", "period", "status", "ruleId",
                    "calculationId", "calculatedAt", "requestedStart", "requestedEnd")
            return {key: result[key] for key in keys}
        return result
