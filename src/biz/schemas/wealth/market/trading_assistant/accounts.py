"""Account and ledger command payloads; no persistence or authorization here."""

from typing import Literal
from pydantic import StrictStr, model_validator

from .common import AccountRef, CommandIdentity, Contract, ReadState, StockRef
from .value_types import AggregateQuantity, compare_share_quantities
from .value_types import (AccountName, AvailableQuantity, BrokerName, BusinessDate, EntityId, Instant,
                          Money, NonnegativeInput, NonnegativeMoney, Note, PositiveInput,
                          PositiveMoney, PositiveVersion, Quantity, StampTaxInput, StockCode)


class InitializationPositionInput(Contract):
    clientRowId: StrictStr
    tsCode: StockCode
    quantity: Quantity
    availableQuantity: AvailableQuantity
    costPrice: PositiveInput

    @model_validator(mode="after")
    def valid_quantity(self):
        if not self.clientRowId or self.availableQuantity > self.quantity:
            raise ValueError("Invalid initial row identity or available quantity")
        return self


class FeeInputs(Contract):
    commissionRateWan: NonnegativeInput
    minimumCommission: NonnegativeInput
    stampTaxRatePct: StampTaxInput


class FeeSettingsDto(FeeInputs):
    accountId: EntityId
    feeVersionId: EntityId


class InitializationInput(Contract):
    initialCash: NonnegativeInput
    initialPositions: list[InitializationPositionInput]

    @model_validator(mode="after")
    def unique_positions(self):
        stocks = [p.tsCode for p in self.initialPositions]
        rows = [p.clientRowId for p in self.initialPositions]
        if len(stocks) != len(set(stocks)) or len(rows) != len(set(rows)):
            raise ValueError("Duplicate initial stock or client row")
        return self


class CreateAccountInput(InitializationInput, FeeInputs):
    name: AccountName
    brokerName: BrokerName


class CreateAccountCommand(CreateAccountInput, CommandIdentity):
    pass


class TradePreviewInput(Contract):
    tsCode: StockCode
    direction: Literal["BUY", "SELL"]
    tradeDate: BusinessDate
    price: PositiveInput
    quantity: Quantity


class TradeInput(TradePreviewInput):
    note: Note | None = None


class TradeCommand(TradeInput, CommandIdentity):
    pass


class CorrectTradeCommand(TradeCommand):
    expectedRevision: PositiveVersion


class CashFlowInput(Contract):
    direction: Literal["IN", "OUT"]
    occurredOn: BusinessDate
    amount: PositiveInput
    note: Note | None = None


class CashFlowCommand(CashFlowInput, CommandIdentity):
    pass


class CorrectCashFlowCommand(CashFlowCommand):
    expectedRevision: PositiveVersion


class VoidCommand(CommandIdentity):
    expectedRevision: PositiveVersion


class CorrectInitializationCommand(InitializationInput, CommandIdentity):
    expectedRevision: PositiveVersion


class UpdateFeesCommand(FeeInputs, CommandIdentity):
    expectedFeeVersionId: EntityId


class AccountSummary(AccountRef):
    initializedOn: BusinessDate
    factVersion: PositiveVersion
    feeVersionId: EntityId


class InitializationPosition(InitializationPositionInput):
    stockRef: StockRef
    costAmount: NonnegativeMoney


class Initialization(Contract):
    accountId: EntityId
    initializedOn: BusinessDate
    initializationId: EntityId
    initializationRevision: PositiveVersion
    initialCash: NonnegativeMoney
    initialPositions: list[InitializationPosition]


class InitializationDetail(Initialization):
    name: AccountName
    brokerName: BrokerName
    factVersion: PositiveVersion


class CreateAccountResult(Contract):
    account: AccountSummary
    initialization: Initialization
    fees: FeeSettingsDto


class FeeBreakdown(Contract):
    grossAmount: PositiveMoney
    commissionAmount: NonnegativeMoney
    stampTaxAmount: NonnegativeMoney
    netCashChange: Money
    feeVersionId: EntityId


class TradeResult(FeeBreakdown):
    accountId: EntityId
    tradeId: EntityId
    revision: PositiveVersion
    factVersion: PositiveVersion
    affectedFromDate: BusinessDate


class CashFlowResult(Contract):
    accountId: EntityId
    cashFlowId: EntityId
    revision: PositiveVersion
    factVersion: PositiveVersion
    netCashChange: Money
    affectedFromDate: BusinessDate


class InitializationCorrectionResult(Contract):
    accountId: EntityId
    initializationId: EntityId
    initializationRevision: PositiveVersion
    factVersion: PositiveVersion
    affectedFromDate: BusinessDate


class AccountsResponse(Contract):
    items: list[AccountSummary]


class InitializationDefaults(Contract):
    stampTaxRatePct: StampTaxInput
    commissionRateUnit: Literal["WAN"]
    stampTaxRateUnit: Literal["PERCENT"]
    currency: Literal["CNY"]


class EntryContext(Contract):
    accountId: EntityId
    factVersion: PositiveVersion
    occurredOn: BusinessDate
    cashThrough: Instant
    availableCash: NonnegativeMoney
    stockRef: StockRef | None
    quantity: AggregateQuantity | None
    availableQuantity: AggregateQuantity | None
    fees: FeeSettingsDto
    calendarDataStatus: ReadState
    reason: StrictStr | None

    @model_validator(mode="after")
    def stock_and_account_context(self):
        if self.accountId != self.fees.accountId:
            raise ValueError("Fee settings belong to another account")
        if self.stockRef is None:
            if self.quantity is not None or self.availableQuantity is not None:
                raise ValueError("Unrequested stock quantities must be null")
        elif (self.quantity is None) != (self.availableQuantity is None):
            raise ValueError("Incomplete stock quantity context")
        if self.quantity is not None and compare_share_quantities(self.availableQuantity, self.quantity) > 0:
            raise ValueError("Available quantity exceeds total quantity")
        return self


class TradeVoidResult(TradeResult):
    status: Literal["VOID"]


class CashFlowVoidResult(CashFlowResult):
    status: Literal["VOID"]
