"""Applications use qfq prices; no minute reader or rule execution is imported."""

from typing import Annotated, Literal
from pydantic import Field, StrictBool, StrictStr, model_validator

from .common import AccountRef, CommandIdentity, Contract, Page, StockRef
from .value_types import (BusinessDate, Count, DeadlineAt, EntityId, Instant, NonnegativeMoney,
                          PositiveInput, PositiveVersion, Quantity, SourceDecimal, StockCode, Version, decimal_cents)


class PriceLTE(Contract):
    operator: Literal["LTE"]
    upper: PositiveInput


class PriceGTE(Contract):
    operator: Literal["GTE"]
    lower: PositiveInput


class PriceBetween(Contract):
    operator: Literal["BETWEEN"]
    lower: PositiveInput
    upper: PositiveInput

    @model_validator(mode="after")
    def ordered(self):
        if decimal_cents(self.lower) > decimal_cents(self.upper):
            raise ValueError("Price lower bound exceeds upper bound")
        return self


PriceCondition = Annotated[PriceLTE | PriceGTE | PriceBetween, Field(discriminator="operator")]


class VolumeCondition(Contract):
    operator: Literal["GTE", "LTE"]
    thresholdLots: PositiveInput


class Conditions(Contract):
    priceCondition: PriceCondition | None
    volumeCondition: VolumeCondition | None

    @model_validator(mode="after")
    def at_least_one(self):
        if self.priceCondition is None and self.volumeCondition is None:
            raise ValueError("Enable at least one condition")
        return self


class CreateRuleInput(Conditions):
    stockCode: StockCode
    deadlineAt: DeadlineAt
    source: Literal["TRADING_ASSISTANT", "STOCK_DETAIL"]


class CreatePlanInput(CreateRuleInput):
    accountId: EntityId
    direction: Literal["BUY", "SELL"]
    notifyEnabled: StrictBool = False
    robotId: EntityId | None = None

    @model_validator(mode="after")
    def notification_target(self):
        if self.notifyEnabled != (self.robotId is not None):
            raise ValueError("Robot required exactly when notifications are enabled")
        return self


class CreateAlertInput(CreateRuleInput):
    robotId: EntityId


class CreatePlanCommand(CreatePlanInput, CommandIdentity):
    pass


class CreateAlertCommand(CreateAlertInput, CommandIdentity):
    pass


class ReviseConditionsCommand(Conditions, CommandIdentity):
    expectedStateVersion: PositiveVersion


class CloseRuleCommand(CommandIdentity):
    expectedStateVersion: PositiveVersion


class ConditionVersion(Contract):
    ruleVersionId: EntityId
    versionNo: PositiveVersion
    effectiveAt: Instant
    deadlineAt: DeadlineAt
    conditions: Conditions
    conditionSummary: StrictStr


class HistoricalConditionVersion(ConditionVersion):
    validThroughAt: Instant


class Maintenance(Contract):
    canEditConditions: StrictBool
    canClose: StrictBool
    editUnavailableReason: StrictStr | None
    closeUnavailableReason: StrictStr | None


CheckStatus = Literal["PENDING", "CHECKING", "WAITING_DATA", "FAILED", "COMPLETED"]
RuleStatus = Literal["ACTIVE", "ENDED", "CLOSED"]
NotificationState = Literal["PENDING", "SENDING", "SUCCEEDED", "FAILED", "UNKNOWN"]


class NotificationSummary(Contract):
    notificationId: EntityId | None
    state: NotificationState | Literal["NOT_ENABLED", "NOT_CREATED"]
    stateVersion: Version | None
    robotId: EntityId | None
    robotName: StrictStr | None
    canRetry: StrictBool
    reason: StrictStr | None

    @model_validator(mode="after")
    def notification_identity(self):
        absent = self.state in ("NOT_ENABLED", "NOT_CREATED")
        if absent:
            if self.notificationId is not None or self.stateVersion is not None or self.canRetry:
                raise ValueError("No notification means no sending identity or retry")
        elif self.notificationId is None or self.stateVersion is None or self.robotId is None:
            raise ValueError("Notification requires its own identity and version")
        if self.canRetry and self.state != "FAILED":
            raise ValueError("Only a confirmed failure may be retryable")
        return self


class PriceLTEEvidence(PriceLTE):
    actualValue: SourceDecimal
    satisfied: StrictBool
    checkpointAt: Instant


class PriceGTEEvidence(PriceGTE):
    actualValue: SourceDecimal
    satisfied: StrictBool
    checkpointAt: Instant


class PriceBetweenEvidence(PriceBetween):
    actualValue: SourceDecimal
    satisfied: StrictBool
    checkpointAt: Instant


PriceEvidence = Annotated[PriceLTEEvidence | PriceGTEEvidence | PriceBetweenEvidence, Field(discriminator="operator")]


class VolumeEvidence(VolumeCondition):
    actualValue: SourceDecimal
    satisfied: StrictBool
    checkpointAt: Instant


class FinalResult(Contract):
    triggered: StrictBool
    decidedAt: Instant
    ruleVersionId: EntityId | None
    firstTriggeredAt: Instant | None
    priceCheck: PriceEvidence | None
    volumeCheck: VolumeEvidence | None
    coverageSummary: StrictStr

    @model_validator(mode="after")
    def trigger_evidence(self):
        if self.triggered:
            if self.ruleVersionId is None or self.firstTriggeredAt is None:
                raise ValueError("Trigger requires its actual version and first checkpoint")
            checks = [item for item in (self.priceCheck, self.volumeCheck) if item is not None]
            if not checks or any(not item.satisfied or item.checkpointAt != self.firstTriggeredAt for item in checks):
                raise ValueError("Enabled trigger evidence must agree at one checkpoint")
        elif self.firstTriggeredAt is not None:
            raise ValueError("Untriggered result has no first trigger time")
        return self


class MissingRange(Contract):
    # Python reserves `from`; the wire keeps the approved key.
    from_: Instant = Field(alias="from")
    through: Instant


class CheckRecord(Contract):
    checkId: EntityId
    checkNo: Quantity
    ruleVersionId: EntityId
    tradeDate: BusinessDate
    requestedFrom: Instant
    requestedThrough: Instant
    startedAt: Instant
    completedAt: Instant | None
    status: CheckStatus
    checkedThroughAt: Instant | None
    marketObservedAt: Instant | None
    coverageSummary: StrictStr
    missingRanges: list[MissingRange]
    failureReason: StrictStr | None
    evidenceSummary: StrictStr


class RuleRow(Contract):
    ruleId: EntityId
    ruleVersionId: EntityId
    stockRef: StockRef
    createdAt: Instant
    effectiveAt: Instant
    deadlineAt: DeadlineAt
    conditions: Conditions
    conditionSummary: StrictStr
    ruleStatus: RuleStatus
    checkStatus: CheckStatus
    finalResult: FinalResult | None
    notificationSummary: NotificationSummary

    @model_validator(mode="after")
    def final_state(self):
        if (self.ruleStatus == "ENDED") != (self.finalResult is not None):
            raise ValueError("Only ended rules have a final result")
        return self


class PlanRow(RuleRow):
    accountRef: AccountRef
    direction: Literal["BUY", "SELL"]


class AlertRow(RuleRow):
    pass


class RuleCounts(Contract):
    planCount: Count
    alertCount: Count


class PlansResponse(Page[PlanRow]):
    counts: RuleCounts


class AlertsResponse(Page[AlertRow]):
    counts: RuleCounts


class RuleDetailFields(Contract):
    stateVersion: PositiveVersion
    serverNow: Instant
    maintenance: Maintenance
    closedAt: Instant | None
    endedAt: Instant | None
    currentConditionVersion: ConditionVersion
    checkedAt: Instant | None
    marketObservedAt: Instant | None
    coverageSummary: StrictStr
    missingRanges: list[MissingRange]
    failureReason: StrictStr | None


class PlanDetail(PlanRow, RuleDetailFields):
    pass


class AlertDetail(AlertRow, RuleDetailFields):
    pass


class ReviseConditionsResult(Contract):
    operationType: Literal["REVISE_CONDITIONS"]
    ruleId: EntityId
    acceptedStateVersion: PositiveVersion
    ruleVersionId: EntityId
    effectiveAt: Instant
    conditions: Conditions
    conditionSummary: StrictStr


class CloseRuleResult(Contract):
    operationType: Literal["CLOSE"]
    ruleId: EntityId
    acceptedStateVersion: PositiveVersion
    ruleVersionId: EntityId
    closedAt: Instant
    ruleStatus: Literal["CLOSED"]
    finalResult: None
