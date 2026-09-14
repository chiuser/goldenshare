"""Project SQL day-group totals without rounding an average back into facts."""
from src.biz.schemas.wealth.market.trading_assistant.records import TradeDayGroup
from src.biz.services.wealth.market.trading_assistant.calculation.precision import (
    format_cents, format_return_pct, round_ratio_half_up,
)
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents, numeric_integer


def project_trade_day_group(row, *, account_ref, stock_ref, closed_state, reason):
    quantity = numeric_integer(row.quantity)
    gross = numeric_cents(row.gross_amount)
    cost = numeric_cents(row.allocated_cost) if closed_state == "Ready" else None
    profit = numeric_cents(row.closed_profit_amount) if closed_state == "Ready" else None
    return TradeDayGroup(accountRef=account_ref, stockRef=stock_ref, tradeDate=row.occurred_on.isoformat(),
        direction=row.direction, quantity=str(quantity), grossAmount=format_cents(gross),
        averagePrice=format_cents(round_ratio_half_up(gross, quantity)),
        commissionAmount=format_cents(numeric_cents(row.commission_amount)),
        stampTaxAmount=format_cents(numeric_cents(row.stamp_tax_amount)),
        netCashChange=format_cents(numeric_cents(row.net_cash_change)), tradeCount=row.trade_count,
        recordsScope=dict(accountId=account_ref.accountId, tsCode=stock_ref.tsCode,
                          tradeDate=row.occurred_on.isoformat(), direction=row.direction),
        allocatedCost=format_cents(cost) if cost is not None else None,
        closedProfitAmount=format_cents(profit) if profit is not None else None,
        closedReturnPct=format_return_pct(profit, cost) if cost is not None else None,
        closedDataStatus=closed_state, reason=reason)
