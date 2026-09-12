"""Current holdings and allocation output; no valuation or UI aggregation."""

from pydantic import StrictStr, model_validator
from typing import Literal

from .common import AccountRef, Contract, Coverage, ReadContext, ReadState, Scope, StockRef
from .records import RoundRef
from .value_types import AggregateQuantity, PositiveAggregateQuantity, compare_share_quantities
from .scopes import RecordsScope
from .value_types import (AvailableQuantity, BusinessDate, Count, EntityId, Instant, Money, NonnegativeMoney,
                          Quantity, ReturnPct, WeightPct, decimal_cents)


class AccountRound(Contract):
    accountId: EntityId
    roundId: EntityId
    roundNumber: Quantity


class PositionRow(Contract):
    stockRef: StockRef
    quantity: PositiveAggregateQuantity
    availableQuantity: AggregateQuantity
    dynamicCostPrice: Money | None
    dynamicCostAmount: Money | None
    price: NonnegativeMoney | None
    marketValue: NonnegativeMoney | None
    holdingProfitAmount: Money | None
    holdingReturnPct: ReturnPct | None
    dayProfitAmount: Money | None
    stockValueWeightPct: WeightPct | None
    totalAssetWeightPct: WeightPct | None
    estimatedSellCommission: NonnegativeMoney | None
    estimatedStampTax: NonnegativeMoney | None
    estimatedNetProceeds: Money | None
    industry: StrictStr | None
    quoteAt: Instant | None
    accountRounds: list[AccountRound]
    dataStatus: ReadState
    reason: StrictStr | None

    @model_validator(mode="after")
    def quantities(self):
        if compare_share_quantities(self.availableQuantity, self.quantity) > 0:
            raise ValueError("Available quantity exceeds holding quantity")
        identities = [(item.accountId, item.roundId) for item in self.accountRounds]
        if not identities or len(identities) != len(set(identities)):
            raise ValueError("Holding requires unique account round references")
        if self.dataStatus == "Ready" and any(value is None for value in (
            self.dynamicCostPrice, self.dynamicCostAmount, self.price, self.marketValue,
            self.estimatedSellCommission, self.estimatedStampTax, self.estimatedNetProceeds,
            self.holdingProfitAmount, self.holdingReturnPct,
        )):
            raise ValueError("Ready holding requires complete current valuation")
        return self


class WeightedStock(Contract):
    stockRef: StockRef
    marketValue: NonnegativeMoney
    weightPct: WeightPct


class AllocationSlice(Contract):
    kind: Literal["STOCK", "CASH", "OTHER"]
    stockRef: StockRef | None
    marketValue: NonnegativeMoney
    weightPct: WeightPct
    members: list[WeightedStock]

    @model_validator(mode="after")
    def slice_members(self):
        if (self.kind == "STOCK") != (self.stockRef is not None):
            raise ValueError("Only a stock slice has a stock reference")
        if self.kind == "OTHER":
            codes = [member.stockRef.tsCode for member in self.members]
            if not codes or len(codes) != len(set(codes)):
                raise ValueError("Other slice requires all unique stock members")
            if sum(decimal_cents(item.marketValue) for item in self.members) != decimal_cents(self.marketValue):
                raise ValueError("Other slice value must equal member values")
        elif self.members:
            raise ValueError("Cash and individual stock slices have no members")
        return self


class PositionsSummary(Contract):
    cashAmount: NonnegativeMoney | None
    stockMarketValue: NonnegativeMoney | None
    totalAssets: NonnegativeMoney | None
    holdingProfitAmount: Money | None
    holdingReturnPct: ReturnPct | None
    dayProfitAmount: Money | None
    dayReturnPct: ReturnPct | None
    positionCount: Count | None
    largestPosition: WeightedStock | None


class Allocation(Contract):
    stockMarketValue: NonnegativeMoney | None
    totalAssets: NonnegativeMoney | None
    stockValueSlices: list[AllocationSlice] | None
    totalAssetSlices: list[AllocationSlice] | None

    @model_validator(mode="after")
    def known_denominators(self):
        for denominator, slices in ((self.stockMarketValue, self.stockValueSlices),
                                    (self.totalAssets, self.totalAssetSlices)):
            if (denominator is None or decimal_cents(denominator) == 0) and slices is not None:
                raise ValueError("Unknown or zero denominator has no allocation slices")
        if self.stockValueSlices is not None and any(item.kind == "CASH" for item in self.stockValueSlices):
            raise ValueError("Cash is excluded from the stock value pie")
        return self


class PositionsResponse(Contract):
    scope: Scope
    readContext: ReadContext
    coverage: Coverage
    items: list[PositionRow]
    summary: PositionsSummary
    allocation: Allocation

    @model_validator(mode="after")
    def unique_stocks(self):
        codes = [item.stockRef.tsCode for item in self.items]
        if len(codes) != len(set(codes)):
            raise ValueError("Cross-account holdings must be aggregated by stock")
        return self


class ContributionExtreme(Contract):
    stockRef: StockRef
    profitAmount: Money


class HoldingContributions(Contract):
    maxPositive: ContributionExtreme | None
    maxNegative: ContributionExtreme | None
    positiveCount: Count
    negativeCount: Count
    flatCount: Count
    positiveAmount: NonnegativeMoney
    negativeAmount: Money
    unknownCount: Count
    dataStatus: ReadState
    reason: StrictStr | None

    @model_validator(mode="after")
    def signed_extremes(self):
        if self.dataStatus == "Ready" and self.unknownCount:
            raise ValueError("Unknown contributions cannot be reported as complete")
        if self.maxPositive is not None and decimal_cents(self.maxPositive.profitAmount) <= 0:
            raise ValueError("Positive extreme must be positive")
        if self.maxNegative is not None and decimal_cents(self.maxNegative.profitAmount) >= 0:
            raise ValueError("Negative extreme must be negative")
        if decimal_cents(self.negativeAmount) > 0:
            raise ValueError("Negative contribution sum cannot be positive")
        return self


class IndustryAllocation(Contract):
    industryCode: StrictStr | None
    industryName: StrictStr
    marketValue: NonnegativeMoney | None
    weightPct: WeightPct | None
    classificationStatus: Literal["CLASSIFIED", "UNCLASSIFIED"]

    @model_validator(mode="after")
    def classification_identity(self):
        if (self.classificationStatus == "CLASSIFIED") != (self.industryCode is not None):
            raise ValueError("Industry classification and code mismatch")
        return self


class PositionsAnalysis(Contract):
    scope: Scope
    readContext: ReadContext
    coverage: Coverage
    largestPosition: WeightedStock | None
    top3WeightPct: WeightPct | None
    top5WeightPct: WeightPct | None
    cashWeightPct: WeightPct | None
    cashAmount: NonnegativeMoney | None
    industries: list[IndustryAllocation]
    cumulative: HoldingContributions
    daily: HoldingContributions


class PositionAccountRound(Contract):
    accountRef: AccountRef
    roundRef: RoundRef
    openedOn: BusinessDate
    openingSource: Literal["INITIALIZATION", "TRADE"]
    quantity: PositiveAggregateQuantity
    availableQuantity: AggregateQuantity
    buyInvestmentAmount: NonnegativeMoney
    sellNetProceedsAmount: Money
    dynamicCostAmount: Money
    dynamicCostPrice: Money
    price: NonnegativeMoney | None
    marketValue: NonnegativeMoney | None
    estimatedSellCommission: NonnegativeMoney | None
    estimatedStampTax: NonnegativeMoney | None
    estimatedNetProceeds: Money | None
    holdingProfitAmount: Money | None
    holdingReturnPct: ReturnPct | None
    dayProfitAmount: Money | None
    recordsScope: RecordsScope
    dataStatus: ReadState
    reason: StrictStr | None

    @model_validator(mode="after")
    def current_round(self):
        if self.roundRef.status != "OPEN" or self.roundRef.accountId != self.accountRef.accountId:
            raise ValueError("Position must refer to its account's open round")
        if compare_share_quantities(self.availableQuantity, self.quantity) > 0:
            raise ValueError("Available quantity exceeds held quantity")
        return self


class PositionDetail(Contract):
    scope: Scope
    readContext: ReadContext
    coverage: Coverage
    stockRef: StockRef
    accountRounds: list[PositionAccountRound]
