"""Projection must keep distinct published endpoints out of aggregate ratios."""
from datetime import date, datetime, timezone
from fractions import Fraction
from uuid import uuid4

from src.biz.schemas.wealth.market.trading_assistant.common import AccountRef, StockRef
from src.biz.queries.wealth.market.trading_assistant.current_positions import CurrentHoldingValue
from src.biz.queries.wealth.market.trading_assistant.positions_facts import HoldingFact
from src.biz.queries.wealth.market.trading_assistant.positions_industry import IndustryMembership
from src.biz.queries.wealth.market.trading_assistant.positions_projection import HoldingPart, holding_row, summarize
from src.biz.queries.wealth.market.trading_assistant.positions_published import PublishedHolding
from src.biz.services.wealth.market.trading_assistant.calculation.daily import PositionState
from src.biz.services.wealth.market.trading_assistant.calculation.fees import FeeSnapshot
from src.biz.services.wealth.market.trading_assistant.calculation.returns import value_round


def part(price):
    account, round_id = uuid4(), uuid4()
    value = CurrentHoldingValue(account_id=account, stock_code="000001.SZ", round_id=round_id,
        quantity=100, fee_version_id=uuid4(), valuation=value_round(PositionState(100, 100, 100000, 100000, 0), Fraction(price), FeeSnapshot(0, 0, 0)),
        opened_on=date(2026, 9, 11), source_price=Fraction(price), quote_at=datetime(2026, 9, 11, 7, tzinfo=timezone.utc),
        buy_input_cents=100000, sell_net_cents=0, valuation_date=date(2026, 9, 11), price_date=date(2026, 9, 11), valuation_method="SAME_DAY_CLOSE")
    return HoldingPart(AccountRef(accountId=str(account), name="账户", brokerName="券商"), HoldingFact("000001.SZ", 100, 100),
        PublishedHolding(value, 1, "INITIALIZATION", 0), "Ready", None)


def test_disagreeing_published_prices_keep_rounds_but_not_false_weights():
    parts = [part(10), part(12)]
    row = holding_row(StockRef(tsCode="000001.SZ", name="股票"), parts, IndustryMembership(None))
    assert row.quantity == "200" and row.availableQuantity == "200"
    assert len(row.accountRounds) == 2 and row.dataStatus == "Partial"
    assert row.marketValue is None and row.price is None and row.holdingReturnPct is None
    rows, summary, allocation = summarize([row], cash=10000, parts=parts, day_snapshots=[], is_today=True)
    assert summary.cashAmount == "100.00" and summary.stockMarketValue is None
    assert summary.top3WeightPct is None and rows[0].stockValueWeightPct is None
    assert allocation.stockValueSlices is None and allocation.totalAssetSlices is None
