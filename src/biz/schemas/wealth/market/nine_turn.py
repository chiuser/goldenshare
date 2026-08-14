from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


NineTurnSubjectType = Literal["stock", "index"]
NineTurnPeriod = Literal["day", "5", "15", "30", "60", "90", "120"]
NineTurnDirection = Literal["UP", "DOWN"]
NineTurnSequenceNumber = Literal[1, 2, 3, 4, 5, 6, 7, 8, 9]
NineTurnDataStatus = Literal["READY", "DELAYED", "EMPTY", "PARTIAL"]


class NineTurnMarkerDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradeDate: date
    tradeTime: datetime | None = None
    direction: NineTurnDirection
    sequenceNumber: NineTurnSequenceNumber
    completed: bool


class NineTurnDataStatusDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: NineTurnDataStatus
    code: str | None = None
    message: str | None = None
    expectedEndDate: date | None = None
    observedEndDate: date | None = None


class NineTurnMetaDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceRowCount: int
    matchedRowCount: int
    missingRowCount: int
    markerCount: int
    limit: int
    hasMore: bool
    nextCursor: str | None = None
    startDate: date | None = None
    endDate: date
    observedStartDate: date | None = None
    observedEndDate: date | None = None
    comparisonLag: Literal[4] = 4
    signalThreshold: Literal[9] = 9
    formulaVersion: Literal[1] = 1


class NineTurnSeriesDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjectType: NineTurnSubjectType
    tsCode: str
    period: NineTurnPeriod
    markers: list[NineTurnMarkerDto]
    latestMarker: NineTurnMarkerDto | None = None
    dataStatus: NineTurnDataStatusDto
    meta: NineTurnMetaDto
    debugInfo: dict[str, Any] | None = None
