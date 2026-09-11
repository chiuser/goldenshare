"""Declared calculation progress; no worker or scheduling implementation."""

from typing import Literal
from pydantic import StrictStr, model_validator

from .common import CommandIdentity, Contract
from .value_types import BusinessDate, Count, EntityId, Instant, PositiveVersion


class CalculationProgress(Contract):
    completedTradeDateCount: Count
    totalTradeDateCount: Count | None
    currentTradeDate: BusinessDate | None
    lastCompletedTradeDate: BusinessDate | None
    lastBusinessUpdatedAt: Instant | None

    @model_validator(mode="after")
    def completed_not_above_total(self):
        if self.totalTradeDateCount is not None and self.completedTradeDateCount > self.totalTradeDateCount:
            raise ValueError("Completed count exceeds total")
        return self


class CalculationStatus(Contract):
    accountId: EntityId
    calculationTargetVersion: PositiveVersion
    publishedGenerationId: EntityId | None
    affectedFromDate: BusinessDate | None
    stage: Literal["PENDING", "PREPARING", "CALCULATING", "VERIFYING", "PUBLISHING", "PUBLISHED",
                   "WAITING_DATA", "FAILED", "CANCELLED", "SUPERSEDED"]
    progress: CalculationProgress
    reason: StrictStr | None

    @model_validator(mode="after")
    def published_requires_identity(self):
        if self.stage == "PUBLISHED" and self.publishedGenerationId is None:
            raise ValueError("Published result requires generation identity")
        return self


class CalculationRetryInput(Contract):
    calculationTargetVersion: PositiveVersion


class CalculationRetryCommand(CalculationRetryInput, CommandIdentity):
    pass
