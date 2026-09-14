"""M4.4 daily groups preserve published closed facts and unknown states."""
import pytest
from pydantic import ValidationError
from src.biz.schemas.wealth.market.trading_assistant.records import TradeDayGroup, TradeRecord

ID = "00000000-0000-0000-0000-000000000001"
GROUP = dict(accountRef=dict(accountId=ID, name="账户", brokerName="券商"), tradeDate="2026-09-07",
    stockRef=dict(tsCode="600036.SH", name="招商银行"), direction="SELL", quantity="5000",
    grossAmount="201600.00", averagePrice="40.32", commissionAmount="50.40", stampTaxAmount="100.80",
    netCashChange="201448.80", tradeCount=2,
    recordsScope=dict(accountId=ID, tsCode="600036.SH", tradeDate="2026-09-07", direction="SELL"),
    allocatedCost="200050.00", closedProfitAmount="1398.80", closedReturnPct="0.70",
    closedDataStatus="Ready", reason=None)


def test_formal_day_group_and_real_zero():
    assert TradeDayGroup(**GROUP).closedProfitAmount == "1398.80"
    assert TradeDayGroup(**{**GROUP, "allocatedCost": "201448.80", "closedProfitAmount": "0.00",
        "closedReturnPct": "0.00"}).closedProfitAmount == "0.00"


@pytest.mark.parametrize("state", ["Delayed", "Partial", "Error", "Recalculating"])
def test_unpublished_groups_preserve_raw_facts(state):
    row = TradeDayGroup(**{**GROUP, "allocatedCost": None, "closedProfitAmount": None,
        "closedReturnPct": None, "closedDataStatus": state, "reason": "闭环结果未就绪"})
    assert row.quantity == "5000" and row.netCashChange == "201448.80"


def test_buy_group_is_not_zero_closed_profit():
    row = {**GROUP, "direction": "BUY", "recordsScope": {**GROUP["recordsScope"], "direction": "BUY"},
        "stampTaxAmount": "0.00", "netCashChange": "-201650.40", "allocatedCost": None,
        "closedProfitAmount": None, "closedReturnPct": None, "closedDataStatus": "Empty", "reason": "买入无闭环"}
    assert TradeDayGroup(**row).closedProfitAmount is None
    with pytest.raises(ValidationError):
        TradeDayGroup(**{**row, "closedProfitAmount": "0.00"})


@pytest.mark.parametrize("patch", [
    {"allocatedCost": None}, {"allocatedCost": "0.00"}, {"closedProfitAmount": "1398.79"},
    {"closedDataStatus": "Recalculating"}, {"closedDataStatus": "Empty"}, {"tradeCount": 0},
    {"reason": "旧状态"}, {"netCashChange": "201600.00"}, {"extra": 1},
    {"recordsScope": {**GROUP["recordsScope"], "direction": "BUY"}},
])
def test_inconsistent_group_rejected(patch):
    with pytest.raises(ValidationError):
        TradeDayGroup(**{**GROUP, **patch})


@pytest.mark.parametrize("field", ["allocatedCost", "closedProfitAmount", "closedReturnPct", "closedDataStatus", "reason"])
def test_new_keys_are_required_even_when_nullable(field):
    with pytest.raises(ValidationError):
        TradeDayGroup(**{key: value for key, value in GROUP.items() if key != field})


TRADE = dict(accountRef=GROUP["accountRef"], stockRef=GROUP["stockRef"], tradeId=ID, revision="1",
    tradeDate="2026-09-07", recordedAt="2026-09-07T16:00:00+08:00", acceptedAt="2026-09-07T16:00:00+08:00",
    direction="SELL", quantity=1, price="10.00", grossAmount="10.00", commissionAmount="0.00",
    stampTaxAmount="0.00", netCashChange="10.00", feeVersionId=ID, commissionRateWan="0.00",
    minimumCommission="0.00", stampTaxRatePct="0.00", note=None, status="ACTIVE", closedDataStatus="Ready", closedReason=None)


@pytest.mark.parametrize("state", ["Empty", "Delayed", "Partial", "Error", "Recalculating"])
def test_raw_trade_retains_amount_while_closed_unavailable(state):
    record = TradeRecord(**{**TRADE, "closedDataStatus": state, "closedReason": "未关联当前已发布闭环"})
    assert record.netCashChange == "10.00"


@pytest.mark.parametrize("patch", [{"closedDataStatus": "Delayed"}, {"closedReason":"过期原因"},
    {"closedDataStatus":"Error", "closedReason":" "}, {"status":"VOID"},
    {"direction":"BUY", "netCashChange":"-10.00"}])
def test_raw_trade_rejects_inconsistent_closed_state(patch):
    with pytest.raises(ValidationError):
        TradeRecord(**{**TRADE, **patch})


@pytest.mark.parametrize("field", ["closedDataStatus", "closedReason"])
def test_trade_closed_keys_required(field):
    with pytest.raises(ValidationError):
        TradeRecord(**{key:value for key,value in TRADE.items() if key != field})
