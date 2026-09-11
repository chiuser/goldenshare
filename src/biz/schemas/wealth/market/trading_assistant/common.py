"""Shared combinations. Nullability never implies an optional response key."""

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

from .value_types import (AccountName, BrokerName, BusinessDate, EntityId, Instant, Money,
                          PositiveVersion, ReturnPct, StockCode, Version, decimal_cents)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True, serialize_by_alias=True)


class ReadContextAccount(Contract):
    accountId: EntityId
    factVersion: PositiveVersion
    calculationTargetVersion: PositiveVersion
    publishedGenerationId: EntityId | None


class ReadContext(Contract):
    # Opaque on the wire. Decoding, basis comparison and ownership belong to M3.
    contextToken: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9_-]+$")]
    accounts: list[ReadContextAccount]
    targetThrough: Instant

    @model_validator(mode="after")
    def sorted_unique_accounts(self):
        ids = [account.accountId for account in self.accounts]
        if ids != sorted(set(ids)):
            raise ValueError("Read context accounts must be sorted and unique")
        return self


class AccountRef(Contract):
    accountId: EntityId
    name: AccountName
    brokerName: BrokerName


class StockRef(Contract):
    tsCode: StockCode
    name: StrictStr


class AccountScopeInput(Contract):
    accountMode: Literal["ALL", "SINGLE"]
    accountId: EntityId | None = None

    @model_validator(mode="after")
    def validate_account_scope(self):
        if self.accountMode == "ALL" and "accountId" in self.model_fields_set:
            raise ValueError("ALL must omit accountId")
        if self.accountMode == "SINGLE" and self.accountId is None:
            raise ValueError("SINGLE requires accountId")
        return self


class ScopeInput(AccountScopeInput):
    stockMode: Literal["ALL", "SINGLE"]
    tsCode: StockCode | None = None

    @model_validator(mode="after")
    def validate_stock_scope(self):
        if self.stockMode == "ALL" and "tsCode" in self.model_fields_set:
            raise ValueError("ALL must omit tsCode")
        if self.stockMode == "SINGLE" and self.tsCode is None:
            raise ValueError("SINGLE requires tsCode")
        return self


class Scope(Contract):
    accountMode: Literal["ALL", "SINGLE"]
    accounts: list[AccountRef]
    stockMode: Literal["ALL", "SINGLE"]
    stockRef: StockRef | None

    @model_validator(mode="after")
    def consistent(self):
        ids = [a.accountId for a in self.accounts]
        if len(ids) != len(set(ids)) or (self.accountMode == "SINGLE" and len(ids) != 1):
            raise ValueError("Invalid account scope")
        if (self.stockMode == "SINGLE") != (self.stockRef is not None):
            raise ValueError("Invalid stock scope")
        return self


ReadState = Literal["Ready", "Empty", "Delayed", "Partial", "Error", "Recalculating"]


class AccountCoverage(Contract):
    accountId: EntityId
    initializedOn: BusinessDate
    effectiveStartDate: BusinessDate | None
    targetThroughDate: BusinessDate | None
    calculatedThroughDate: BusinessDate | None
    valuationAt: Instant | None
    dataStatus: ReadState
    reason: StrictStr | None

    @model_validator(mode="after")
    def range_valid(self):
        if (self.effectiveStartDate is None) != (self.targetThroughDate is None):
            raise ValueError("Incomplete effective range")
        if self.effectiveStartDate and self.effectiveStartDate > self.targetThroughDate:
            raise ValueError("Inverted effective range")
        return self


class Coverage(Contract):
    dataStatus: ReadState
    reason: StrictStr | None
    isFinal: StrictBool
    accounts: list[AccountCoverage]

    @model_validator(mode="after")
    def finality(self):
        if self.isFinal and self.dataStatus in ("Partial", "Delayed", "Error", "Recalculating"):
            raise ValueError("Incomplete coverage cannot be final")
        return self


class ReturnTriple(Contract):
    profitAmount: Money | None
    capitalAmount: Money | None
    returnPct: ReturnPct | None

    @model_validator(mode="after")
    def complete_triple(self):
        values = (self.profitAmount, self.capitalAmount, self.returnPct)
        if any(v is None for v in values) and not all(v is None for v in values):
            raise ValueError("Return triple must be complete or entirely null")
        if self.capitalAmount is not None and decimal_cents(self.capitalAmount) <= 0:
            raise ValueError("Return denominator must be positive")
        return self


T = TypeVar("T")


class Page(Contract, Generic[T]):
    items: list[T]
    nextCursor: StrictStr | None


class CommandIdentity(Contract):
    requestId: EntityId
    attemptId: EntityId
    expectedRequestStateVersion: Version | None = None

    @model_validator(mode="after")
    def absent_or_version(self):
        if "expectedRequestStateVersion" in self.model_fields_set and self.expectedRequestStateVersion is None:
            raise ValueError("Omit the state version on an initial attempt")
        return self


OperationType = Literal[
    "ACCOUNT_CREATE", "INITIALIZATION_CORRECT", "FEES_UPDATE", "TRADE_CREATE", "TRADE_CORRECT", "TRADE_VOID",
    "CASH_FLOW_CREATE", "CASH_FLOW_CORRECT", "CASH_FLOW_VOID", "CALCULATION_RETRY", "PLAN_CREATE", "ALERT_CREATE",
    "RULE_CONDITIONS_UPDATE", "RULE_CLOSE", "ROBOT_CANDIDATE_CREATE", "ROBOT_TEST", "ROBOT_CONFIRM", "NOTIFICATION_RETRY",
]


class MutationReceipt(Contract, Generic[T]):
    requestId: EntityId
    attemptId: EntityId
    operationType: OperationType
    acceptedAt: Instant
    result: T
