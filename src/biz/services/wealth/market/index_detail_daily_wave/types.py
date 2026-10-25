"""Immutable facts and independent dictionary projections, LLD 14.6.1."""
from dataclasses import dataclass
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
