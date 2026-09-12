"""Original record and closed-sale fields, design §4.35.3."""

from typing import Generic, Literal, TypeVar
from pydantic import StrictStr, model_validator

from .accounts import FeeBreakdown, FeeInputs
from .value_types import AggregateQuantity, PositiveAggregateQuantity, compare_share_quantities
from .common import AccountRef, Contract, Coverage, Page, ReadContext, ReadState, Scope, StockRef
from .scopes import RecordsScope
from .value_types import (AvailableQuantity, BusinessDate, Count, EntityId, Instant, Money,
                          NonnegativeMoney, Note, PositiveMoney, PositiveVersion, Quantity, ReturnPct, StockCode,
                          decimal_cents)


class RoundRef(Contract):
    accountId: EntityId
    roundId: EntityId
    roundNumber: Quantity
    status: Literal["OPEN", "CLOSED"]


class DayGroup(Contract):
    accountId: EntityId
    tsCode: StockCode
    tradeDate: BusinessDate


class TradeRecord(FeeBreakdown, FeeInputs):
    accountRef: AccountRef
    tradeId: EntityId
    revision: PositiveVersion
    tradeDate: BusinessDate
    recordedAt: Instant
    acceptedAt: Instant
    stockRef: StockRef
    direction: Literal["BUY", "SELL"]
    quantity: Quantity
    price: PositiveMoney
    note: Note | None
    status: Literal["ACTIVE", "VOID"]

    @model_validator(mode="after")
    def ledger_amounts(self):
        gross = decimal_cents(self.price) * self.quantity
        commission, tax = decimal_cents(self.commissionAmount), decimal_cents(self.stampTaxAmount)
        if gross != decimal_cents(self.grossAmount):
            raise ValueError("Trade amount does not match entered price and quantity")
        expected = gross - commission - tax if self.direction == "SELL" else -gross - commission
        if decimal_cents(self.netCashChange) != expected or (self.direction == "BUY" and tax != 0):
            raise ValueError("Trade cash flow or buy-side tax is inconsistent")
        return self


class CashFlowRecord(Contract):
    accountRef: AccountRef
    cashFlowId: EntityId
    revision: PositiveVersion
    occurredOn: BusinessDate
    recordedAt: Instant
    acceptedAt: Instant
    direction: Literal["IN", "OUT"]
    amount: PositiveMoney
    netCashChange: Money
    note: Note | None
    status: Literal["ACTIVE", "VOID"]

    @model_validator(mode="after")
    def signed_cash(self):
        amount = decimal_cents(self.amount)
        if decimal_cents(self.netCashChange) != (amount if self.direction == "IN" else -amount):
            raise ValueError("Cash flow direction does not match the signed change")
        return self


class ClosedTrade(Contract):
    accountRef: AccountRef
    stockRef: StockRef
    tradeId: EntityId
    sellRevision: PositiveVersion
    tradeDate: BusinessDate
    recordedAt: Instant
    roundRef: RoundRef
    quantity: Quantity
    price: PositiveMoney
    grossAmount: PositiveMoney
    commissionAmount: NonnegativeMoney
    stampTaxAmount: NonnegativeMoney
    totalFeeAmount: NonnegativeMoney
    netProceeds: Money
    dayOpeningUnitCost: Money
    allocatedCost: NonnegativeMoney
    dayEndQuantity: AggregateQuantity
    dayGroup: DayGroup
    calculationRuleVersion: PositiveVersion
    dayResultId: EntityId
    profitAmount: Money
    returnPct: ReturnPct

    @model_validator(mode="after")
    def consistent(self):
        if not (self.accountRef.accountId == self.roundRef.accountId == self.dayGroup.accountId):
            raise ValueError("Mixed account references")
        if self.stockRef.tsCode != self.dayGroup.tsCode or self.tradeDate != self.dayGroup.tradeDate:
            raise ValueError("Mixed day group")
        fees = decimal_cents(self.commissionAmount) + decimal_cents(self.stampTaxAmount)
        if decimal_cents(self.price) * self.quantity != decimal_cents(self.grossAmount):
            raise ValueError("Closed sale amount does not match its entered price and quantity")
        if fees != decimal_cents(self.totalFeeAmount):
            raise ValueError("Fee total mismatch")
        if decimal_cents(self.grossAmount) - fees != decimal_cents(self.netProceeds):
            raise ValueError("Net proceeds mismatch")
        if decimal_cents(self.netProceeds) - decimal_cents(self.allocatedCost) != decimal_cents(self.profitAmount):
            raise ValueError("Closed profit mismatch")
        if decimal_cents(self.allocatedCost) <= 0:
            raise ValueError("Invalid closed cost denominator")
        return self


class TradeGroupScope(DayGroup):
    direction: Literal["BUY", "SELL"]


class TradeDayGroup(Contract):
    accountRef: AccountRef
    tradeDate: BusinessDate
    stockRef: StockRef
    direction: Literal["BUY", "SELL"]
    quantity: PositiveAggregateQuantity
    grossAmount: NonnegativeMoney
    averagePrice: NonnegativeMoney
    commissionAmount: NonnegativeMoney
    stampTaxAmount: NonnegativeMoney
    netCashChange: Money
    tradeCount: Count
    recordsScope: TradeGroupScope


class CompletedRound(Contract):
    accountId: EntityId
    accountName: StrictStr
    stockRef: StockRef
    roundId: EntityId
    roundNumber: Quantity
    openedOn: BusinessDate
    closedOn: BusinessDate
    openingSource: Literal["INITIALIZATION", "TRADE"]
    roundProfitAmount: Money
    roundReturnPct: ReturnPct

    @model_validator(mode="after")
    def dates_valid(self):
        if self.closedOn < self.openedOn:
            raise ValueError("Round ends before it opens")
        return self


RecordT = TypeVar("RecordT", TradeRecord, CashFlowRecord, TradeDayGroup, ClosedTrade)


class RecordsResponse(Page[RecordT], Generic[RecordT]):
    scope: Scope
    requestedStartDate: BusinessDate
    requestedEndDate: BusinessDate
    readContext: ReadContext
    coverage: Coverage

    @model_validator(mode="after")
    def valid_range(self):
        if self.requestedStartDate > self.requestedEndDate:
            raise ValueError("Inverted records range")
        if not self.items and self.nextCursor is not None:
            raise ValueError("Empty page cannot have a next cursor")
        return self


class CashFlowDetail(Contract):
    record: CashFlowRecord
    revisions: Page[CashFlowRecord]
    readContext: ReadContext


class TradeDetail(Contract):
    record: TradeRecord
    revisions: Page[TradeRecord]
    readContext: ReadContext
    closedTrade: ClosedTrade | None
    closedDataStatus: ReadState
    reason: StrictStr | None

    @model_validator(mode="after")
    def matching_closed_sale(self):
        closed = self.closedTrade
        if closed is not None and (
            self.record.direction != "SELL" or self.record.status != "ACTIVE"
            or self.closedDataStatus != "Ready"
            or closed.tradeId != self.record.tradeId
            or closed.sellRevision != self.record.revision
            or closed.accountRef.accountId != self.record.accountRef.accountId
            or closed.stockRef.tsCode != self.record.stockRef.tsCode
        ):
            raise ValueError("Closed trade does not match the effective source sale")
        return self


class RecordsSummary(Contract):
    scope: Scope
    requestedStartDate: BusinessDate
    requestedEndDate: BusinessDate
    readContext: ReadContext
    tradeCount: Count
    buyCount: Count
    sellCount: Count
    cashInAmount: NonnegativeMoney
    cashOutAmount: NonnegativeMoney
    closedTradeCount: Count | None
    closedProfitAmount: Money | None
    closedDataStatus: ReadState
    reason: StrictStr | None

    @model_validator(mode="after")
    def valid_summary(self):
        if self.requestedStartDate > self.requestedEndDate:
            raise ValueError("Inverted summary range")
        if self.tradeCount != self.buyCount + self.sellCount:
            raise ValueError("Trade count mismatch")
        if (self.closedTradeCount is None) != (self.closedProfitAmount is None):
            raise ValueError("Incomplete closed trade summary")
        return self


class ClosedRecordsSummary(Contract):
    closedTradeCount: Count | None
    closedProfitAmount: Money | None
    dataStatus: ReadState
    reason: StrictStr | None


class ClosedRecordsResponse(RecordsResponse[ClosedTrade]):
    recordsScope: RecordsScope
    summary: ClosedRecordsSummary


class CompletedRoundsResponse(Page[CompletedRound]):
    scope: Scope
    closedStartDate: BusinessDate
    closedEndDate: BusinessDate
    coverage: Coverage
    completedRoundCount: Count | None


class RoundInitializationSource(Contract):
    initializedOn: BusinessDate
    openedOn: BusinessDate
    initializationId: EntityId
    initializationRevision: PositiveVersion
    quantity: Quantity
    costPrice: NonnegativeMoney
    costAmount: NonnegativeMoney


class RoundDetail(Contract):
    accountRef: AccountRef
    stockRef: StockRef
    roundRef: RoundRef
    openedOn: BusinessDate
    closedOn: BusinessDate | None
    openingSource: Literal["INITIALIZATION", "TRADE"]
    initializationSource: RoundInitializationSource | None
    buyQuantity: PositiveAggregateQuantity
    sellQuantity: AggregateQuantity
    buyInvestmentAmount: NonnegativeMoney
    sellNetProceedsAmount: Money
    roundProfitAmount: Money | None
    roundReturnPct: ReturnPct | None
    closedTradeCount: Count
    recordsScope: RecordsScope

    @model_validator(mode="after")
    def full_round(self):
        if self.roundRef.accountId != self.accountRef.accountId:
            raise ValueError("Mixed round account")
        if (self.openingSource == "INITIALIZATION") != (self.initializationSource is not None):
            raise ValueError("Initialization source must match the opening source")
        if compare_share_quantities(self.sellQuantity, self.buyQuantity) > 0:
            raise ValueError("Round cannot sell more shares than it acquired")
        if self.roundRef.status == "CLOSED":
            if self.closedOn is None or self.closedOn < self.openedOn or self.buyQuantity != self.sellQuantity:
                raise ValueError("Closed round requires a valid ending and balanced quantities")
            if self.roundProfitAmount is None or self.roundReturnPct is None:
                raise ValueError("Closed round requires its fixed return")
            if decimal_cents(self.roundProfitAmount) != decimal_cents(self.sellNetProceedsAmount) - decimal_cents(self.buyInvestmentAmount):
                raise ValueError("Closed round profit does not reconcile")
        elif self.closedOn is not None:
            raise ValueError("Open round cannot have a closing date")
        return self
