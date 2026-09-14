"""Exact current-stock contribution/industry projections, including counterexamples."""
from itertools import permutations
from types import SimpleNamespace

from src.biz.schemas.wealth.market.trading_assistant.common import StockRef
from src.biz.queries.wealth.market.trading_assistant.positions_analysis import contributions, industry_allocations
from src.biz.queries.wealth.market.trading_assistant.positions_industry import IndustryMembership


def row(code, amount, value="100.00"):
    return SimpleNamespace(stockRef=StockRef(tsCode=code, name=code), marketValue=value,
                           holdingProfitAmount=amount, dayProfitAmount=amount)


def test_sign_ties_and_permutations():
    rows = [row("B", "10.00"), row("A", "10.00"), row("C", "-3.00"), row("D", "0.00")]
    expected = contributions(rows, "holdingProfitAmount")
    assert expected.maxPositive.stockRef.tsCode == "A"
    assert expected.maxNegative.stockRef.tsCode == "C"
    assert (expected.positiveAmount, expected.negativeAmount) == ("20.00", "-3.00")
    assert (expected.positiveCount, expected.negativeCount, expected.flatCount) == (2, 1, 1)
    for permuted in permutations(rows):
        assert contributions(permuted, "holdingProfitAmount") == expected


def test_unknown_is_not_flat_or_a_complete_extreme_and_yesterday_not_today():
    rows = [row("A", "999999999999999999999999.99"), row("B", None)]
    result = contributions(rows, "holdingProfitAmount")
    assert result.unknownCount == 1 and result.flatCount == 0 and result.dataStatus == "Partial"
    assert result.positiveAmount == "999999999999999999999999.99"
    assert result.maxPositive is None and result.maxNegative is None
    daily = contributions(rows, "dayProfitAmount", unavailable=True, status="Delayed")
    assert daily.unknownCount == 2 and daily.positiveCount == 0 and daily.dataStatus == "Delayed"
    assert contributions([], "dayProfitAmount").dataStatus == "Empty"


def test_industry_keeps_all_codes_unclassified_and_unknown_denominator():
    rows = [row(str(i), "0.00") for i in range(11)]
    memberships = {str(i): IndustryMembership("同名行业", code=f"BK{i:04}.DC") for i in range(10)}
    memberships["10"] = IndustryMembership(None)
    result = industry_allocations(rows, memberships, 110000)
    assert len(result) == 11 and len({item.industryCode for item in result}) == 11
    assert all(item.weightPct == "9.09" for item in result)
    assert result[-1].industryName == "未分类" and result[-1].marketValue == "100.00"
    rows[0].marketValue = None
    result = industry_allocations(rows, memberships, None)
    assert all(item.weightPct is None for item in result)
    assert next(item for item in result if item.industryCode == "BK0000.DC").marketValue is None
    assert len(result) == 11


def test_same_industry_sum_uses_exact_cents_and_zero_has_no_weight():
    rows = [row("A", "0.00", "0.01"), row("B", "0.00", "0.02")]
    memberships = {code: IndustryMembership("行业", code="BK1.DC") for code in ("A", "B")}
    assert industry_allocations(rows, memberships, 3)[0].marketValue == "0.03"
    assert industry_allocations(rows, memberships, 3)[0].weightPct == "100.00"
    assert industry_allocations(rows, memberships, 0)[0].weightPct is None
