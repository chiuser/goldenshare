"""Exact wire projection; charts consume these amounts and weights unchanged."""
from dataclasses import dataclass
from fractions import Fraction

from src.biz.schemas.wealth.market.trading_assistant.positions import (
    Allocation, AllocationSlice, PositionAccountRound, PositionRow, PositionsSummary, WeightedStock)
from src.biz.schemas.wealth.market.trading_assistant.value_types import decimal_cents
from src.biz.services.wealth.market.trading_assistant.calculation.precision import (
    format_cents, format_return_pct, round_ratio_half_up)
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents


def weight(numerator, denominator):
    return format_return_pct(numerator, denominator) if denominator and numerator is not None else None


def exact_price(price: Fraction):
    cents = price * 100
    return format_cents(round_ratio_half_up(cents.numerator, cents.denominator))


@dataclass(frozen=True, slots=True)
class HoldingPart:
    account_ref: object
    fact: object
    published: object | None
    status: str
    reason: str | None


def account_round(part):
    item = part.published
    value, fact = item.value, part.fact
    valuation, fees = value.valuation, value.valuation.liquidation
    return PositionAccountRound(accountRef=part.account_ref,
        roundRef=dict(accountId=part.account_ref.accountId, roundId=str(value.round_id),
                      roundNumber=item.round_number, status="OPEN"),
        openedOn=value.opened_on.isoformat(), openingSource=item.opening_source,
        quantity=str(fact.quantity), availableQuantity=None if fact.available_quantity is None else str(fact.available_quantity),
        buyInvestmentAmount=format_cents(value.buy_input_cents), sellNetProceedsAmount=format_cents(value.sell_net_cents),
        dynamicCostAmount=format_cents(valuation.dynamic_cost_cents), dynamicCostPrice=valuation.dynamic_cost_price,
        price=exact_price(value.source_price), marketValue=format_cents(fees.gross_cents),
        valuationDate=value.valuation_date.isoformat(), priceDate=value.price_date.isoformat(), valuationMethod=value.valuation_method,
        estimatedSellCommission=format_cents(fees.commission_cents), estimatedStampTax=format_cents(fees.stamp_tax_cents),
        estimatedTotalFeeAmount=format_cents(fees.commission_cents + fees.stamp_tax_cents),
        estimatedNetProceeds=format_cents(fees.net_cash_change_cents),
        holdingProfitAmount=format_cents(valuation.result.profit_cents), holdingReturnPct=valuation.result.return_pct,
        dayProfitAmount=None if item.day_profit_cents is None else format_cents(item.day_profit_cents),
        recordsScope=dict(accountId=part.account_ref.accountId, roundId=str(value.round_id)),
        dataStatus=part.status, reason=part.reason)


def combined_status(states):
    if not states:
        return "Empty"
    unique = set(states)
    return next(iter(unique)) if len(unique) == 1 else "Partial"


def holding_row(stock, parts, industry):
    known = all(part.published is not None for part in parts)
    quantity = sum(part.fact.quantity for part in parts)
    available = (None if any(part.fact.available_quantity is None for part in parts) else
                 str(sum(part.fact.available_quantity for part in parts)))
    rounds = [account_round(part) for part in parts if part.published is not None]
    status = combined_status([part.status for part in parts])
    reason = next((part.reason for part in parts if part.reason), None)
    if industry.reason:
        status, reason = "Partial", industry.reason
    endpoints = {(part.published.value.source_price, part.published.value.quote_at,
                  part.published.value.valuation_date, part.published.value.price_date,
                  part.published.value.valuation_method) for part in parts if part.published is not None}
    if known and len(endpoints) != 1:
        known = False
        status, reason = "Partial", "分账户估值依据尚未一致，请查看分账户详情或稍后重新读取"
    fields = dict.fromkeys(("dynamicCostPrice", "dynamicCostAmount", "price", "marketValue", "holdingProfitAmount",
        "holdingReturnPct", "dayProfitAmount", "estimatedSellCommission", "estimatedStampTax",
        "estimatedTotalFeeAmount", "estimatedNetProceeds", "quoteAt", "valuationDate", "priceDate", "valuationMethod"))
    if known:
        def total(field):
            values = [getattr(item, field) for item in rounds]
            return None if any(value is None for value in values) else sum(decimal_cents(value) for value in values)
        for field in ("dynamicCostAmount", "marketValue", "holdingProfitAmount", "dayProfitAmount",
                      "estimatedSellCommission", "estimatedStampTax", "estimatedTotalFeeAmount", "estimatedNetProceeds"):
            value = total(field)
            fields[field] = None if value is None else format_cents(value)
        fields["dynamicCostPrice"] = format_cents(round_ratio_half_up(total("dynamicCostAmount"), quantity))
        fields["holdingReturnPct"] = format_return_pct(total("holdingProfitAmount"), total("buyInvestmentAmount"))
        price, quote_at, valuation_date, price_date, method = next(iter(endpoints))
        fields.update(price=exact_price(price), quoteAt=quote_at.isoformat(), valuationDate=valuation_date.isoformat(),
                      priceDate=price_date.isoformat(), valuationMethod=method)
    return PositionRow(stockRef=stock, quantity=str(quantity), availableQuantity=available,
        **fields, stockValueWeightPct=None, totalAssetWeightPct=None,
        industry=industry.name, accountRounds=[dict(accountId=r.accountRef.accountId,
            roundId=r.roundRef.roundId, roundNumber=r.roundRef.roundNumber) for r in rounds],
        dataStatus=status, reason=reason)


def allocation_slices(rows, denominator, cash=None):
    if not denominator:
        return None
    weighted = [WeightedStock(stockRef=row.stockRef, marketValue=row.marketValue,
                              weightPct=weight(decimal_cents(row.marketValue), denominator)) for row in rows]
    slices = [AllocationSlice(kind="STOCK", stockRef=item.stockRef, marketValue=item.marketValue,
                             weightPct=item.weightPct, members=[]) for item in weighted[:7]]
    if len(weighted) > 7:
        value = sum(decimal_cents(item.marketValue) for item in weighted[7:])
        slices.append(AllocationSlice(kind="OTHER", stockRef=None, marketValue=format_cents(value),
            weightPct=weight(value, denominator), members=weighted[7:]))
    if cash is not None and cash > 0:
        slices.append(AllocationSlice(kind="CASH", stockRef=None, marketValue=format_cents(cash),
                                     weightPct=weight(cash, denominator), members=[]))
    return slices


def summarize(rows, *, cash, parts, day_snapshots, is_today):
    rows = sorted(rows, key=lambda row: (row.marketValue is None,
        -decimal_cents(row.marketValue) if row.marketValue is not None else 0, row.stockRef.tsCode))
    complete = all(row.marketValue is not None for row in rows)
    stock_value = sum(decimal_cents(row.marketValue) for row in rows) if complete else None
    assets = cash + stock_value if stock_value is not None else None
    weighted_rows = [row.model_copy(update={
        "stockValueWeightPct":weight(decimal_cents(row.marketValue), stock_value) if row.marketValue else None,
        "totalAssetWeightPct":weight(decimal_cents(row.marketValue), assets) if row.marketValue else None}) for row in rows]
    profit = sum(decimal_cents(row.holdingProfitAmount) for row in rows) if complete and rows else None
    capital = sum(part.published.value.buy_input_cents for part in parts) if complete else None
    daily_ready = bool(day_snapshots) and all(item is not None for item in day_snapshots) and is_today
    daily_profit = sum(numeric_cents(item.day_profit_amount) for item in day_snapshots
                       if item.day_profit_amount is not None) if daily_ready else None
    daily_capital = sum(numeric_cents(item.day_capital_amount) for item in day_snapshots
                        if item.day_capital_amount is not None) if daily_ready else None
    if not daily_capital:
        daily_profit = None
    largest = (WeightedStock(stockRef=rows[0].stockRef, marketValue=rows[0].marketValue,
               weightPct=weight(decimal_cents(rows[0].marketValue), stock_value)) if stock_value else None)
    summary = PositionsSummary(cashAmount=format_cents(cash),
        stockMarketValue=None if stock_value is None else format_cents(stock_value),
        totalAssets=None if assets is None else format_cents(assets),
        holdingProfitAmount=None if profit is None else format_cents(profit), holdingReturnPct=weight(profit, capital),
        dayProfitAmount=None if daily_profit is None else format_cents(daily_profit),
        dayReturnPct=weight(daily_profit, daily_capital), positionCount=len(rows), largestPosition=largest,
        top3WeightPct=weight(sum(decimal_cents(row.marketValue) for row in rows[:3]), stock_value) if complete else None,
        cashWeightPct=weight(cash, assets), stockAssetWeightPct=weight(stock_value, assets))
    allocation = Allocation(stockMarketValue=summary.stockMarketValue, totalAssets=summary.totalAssets,
        stockValueSlices=allocation_slices(rows, stock_value) if complete else None,
        totalAssetSlices=allocation_slices(rows, assets, cash) if complete else None)
    return weighted_rows, summary, allocation
