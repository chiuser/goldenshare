"""Exact field mapping for an account snapshot candidate, design §4.24.

No completeness, sealing or publication decision is made by this mapper. Those
require the caller's persisted source-page verification and execution fence.
"""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from .calculation.account_day import AccountDayAmounts
from .persistence_values import money_numeric


def snapshot_values(amounts: AccountDayAmounts, *, account_id: UUID, day_result_id: UUID,
                    trade_date: date, valuation_at: datetime) -> dict:
    if (not isinstance(account_id, UUID) or not isinstance(day_result_id, UUID)
            or type(trade_date) is not date or not isinstance(valuation_at, datetime)
            or valuation_at.tzinfo is None or valuation_at.utcoffset() is None):
        raise ValueError("Invalid snapshot identity or valuation time")
    totals = amounts.totals
    if totals.valuation_missing or amounts.day_return.status == "Delayed" or amounts.holding_return.status == "Delayed":
        raise ValueError("Incomplete valuation cannot become a snapshot candidate")
    def nullable_money(value):
        return money_numeric(value) if value is not None else None
    return dict(account_id=account_id, day_result_id=day_result_id, trade_date=trade_date, valuation_at=valuation_at,
        cash_amount=nullable_money(amounts.cash_cents), total_assets=nullable_money(amounts.total_assets_cents),
        stock_market_value=money_numeric(totals.market_value_cents),
        cash_in_amount=money_numeric(amounts.cash_in_cents), cash_out_amount=money_numeric(amounts.cash_out_cents),
        current_buy_input=money_numeric(totals.current_buy_input_cents),
        current_sell_net=money_numeric(totals.current_sell_net_cents),
        dynamic_cost_amount=money_numeric(totals.current_buy_input_cents - totals.current_sell_net_cents),
        estimated_sell_commission=money_numeric(totals.commission_cents),
        estimated_stamp_tax=money_numeric(totals.stamp_tax_cents),
        estimated_net_proceeds=money_numeric(totals.market_value_cents - totals.commission_cents - totals.stamp_tax_cents),
        holding_profit_amount=money_numeric(amounts.holding_return.profit_cents or 0),
        holding_return_pct=Decimal(amounts.holding_return.return_pct) if amounts.holding_return.return_pct is not None else None,
        day_profit_amount=nullable_money(amounts.day_return.profit_cents),
        day_capital_amount=nullable_money(amounts.day_return.capital_cents),
        day_return_pct=Decimal(amounts.day_return.return_pct) if amounts.day_return.return_pct is not None else None,
        closed_trade_count=totals.closed_trade_count, closed_profit_amount=money_numeric(totals.closed_profit_cents))
