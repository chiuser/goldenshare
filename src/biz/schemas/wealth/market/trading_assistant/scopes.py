"""Typed query inputs; a round never accepts an overriding date/stock range."""

from typing import Annotated, Literal
from pydantic import Field, StrictInt, StrictStr, model_validator

from .common import AccountScopeInput, Contract, Scope, ScopeInput
from .value_types import BusinessDate, EntityId, Month, StockCode


class Pagination(Contract):
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = 20
    cursor: StrictStr | None = None


class DateRange(Contract):
    requestedStartDate: BusinessDate
    requestedEndDate: BusinessDate

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.requestedStartDate > self.requestedEndDate:
            raise ValueError("Inverted date range")
        return self


class RangeQuery(ScopeInput, DateRange):
    readContext: StrictStr | None = None


class CurveQuery(RangeQuery):
    granularity: Literal["DAY", "WEEK", "MONTH"]


class CalendarQuery(Contract):
    accountMode: Literal["ALL", "SINGLE"]
    accountId: EntityId | None = None
    month: Month
    readContext: StrictStr | None = None

    @model_validator(mode="after")
    def account_selection(self):
        if self.accountMode == "SINGLE" and self.accountId is None:
            raise ValueError("Single account requires an ID")
        if self.accountMode == "ALL" and "accountId" in self.model_fields_set:
            raise ValueError("All accounts must omit accountId")
        return self


class RangeRecordsQuery(RangeQuery, Pagination):
    pass


class TradeRecordsQuery(RangeRecordsQuery):
    direction: Literal["BUY", "SELL"] | None = None


class CashRecordsQuery(AccountScopeInput, DateRange, Pagination):
    direction: Literal["IN", "OUT"] | None = None
    readContext: StrictStr | None = None


class AccountReadQuery(AccountScopeInput):
    readContext: StrictStr | None = None


class RecordDetailQuery(Pagination):
    readContext: StrictStr | None = None


class DayContributionsQuery(AccountReadQuery, Pagination):
    pass


class PlansQuery(AccountScopeInput, Pagination):
    pass


class AlertsQuery(Pagination):
    pass


class EntryContextQuery(Contract):
    occurredOn: BusinessDate
    tsCode: StockCode | None = None


class RoundRecordsQuery(Pagination):
    accountId: EntityId
    roundId: EntityId
    readContext: StrictStr | None = None


ClosedRecordsQuery = RangeRecordsQuery | RoundRecordsQuery


class RangeRecordsScope(DateRange):
    scope: Scope


class RoundRecordsScope(Contract):
    accountId: EntityId
    roundId: EntityId


RecordsScope = RangeRecordsScope | RoundRecordsScope


class DayScope(Contract):
    scope: Scope
    date: BusinessDate


class AccountLedgerScope(Contract):
    scopeType: Literal["ACCOUNT_LEDGER"]
    accountId: EntityId


class AccountFeesScope(Contract):
    scopeType: Literal["ACCOUNT_FEES"]
    accountId: EntityId


class AccountCreateScope(Contract):
    scopeType: Literal["ACCOUNT_CREATE"]


class RuleScope(Contract):
    scopeType: Literal["RULE"]
    ruleType: Literal["PLAN", "ALERT"]
    ruleId: EntityId


class RuleCreateScope(Contract):
    scopeType: Literal["RULE_CREATE"]
    ruleType: Literal["PLAN", "ALERT"]
    tsCode: StockCode
    accountId: EntityId | None

    @model_validator(mode="after")
    def plan_account(self):
        if (self.ruleType == "PLAN") != (self.accountId is not None):
            raise ValueError("Only plans require an account")
        return self


class RobotScope(Contract):
    scopeType: Literal["ROBOT"]


class NotificationScope(Contract):
    scopeType: Literal["NOTIFICATION"]
    notificationId: EntityId


RecoveryScope = Annotated[
    AccountLedgerScope | AccountFeesScope | AccountCreateScope | RuleScope | RuleCreateScope | RobotScope | NotificationScope,
    Field(discriminator="scopeType"),
]
