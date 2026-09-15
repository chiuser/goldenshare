"""Rule checkpoint golden cases, independent of database, quotes and notifications."""

from decimal import Decimal, localcontext

import pytest

from src.biz.schemas.wealth.market.trading_assistant.rules import Conditions
from src.biz.services.wealth.market.trading_assistant.condition_evaluator import (
    evaluate_checkpoint,
)


def conditions(price=None, volume=None):
    return Conditions(priceCondition=price, volumeCondition=volume)


@pytest.mark.parametrize("operator,bounds,price,expected", [
    ("LTE", {"upper": "11.80"}, "11.80", True),
    ("LTE", {"upper": "11.80"}, "11.800000190734863", False),
    ("GTE", {"lower": "11.74"}, "11.74", True),
    ("GTE", {"lower": "11.74"}, "11.739999771118164", False),
    ("BETWEEN", {"lower": "10.00", "upper": "11.00"}, "10.00", True),
    ("BETWEEN", {"lower": "10.00", "upper": "11.00"}, "11.00", True),
    ("BETWEEN", {"lower": "10.00", "upper": "11.00"}, "11.00001", False),
])
def test_exact_price_comparison(operator, bounds, price, expected):
    rule = conditions({"operator": operator, **bounds})
    result = evaluate_checkpoint(rule, Decimal(price), None)
    assert result.price_satisfied is expected
    assert result.satisfied is expected
    assert result.volume_satisfied is None


@pytest.mark.parametrize("operator,shares,expected", [
    ("GTE", 1234, True), ("GTE", 1233, False),
    ("LTE", 1234, True), ("LTE", 1235, False), ("LTE", 0, True),
])
def test_lots_are_converted_to_integer_shares(operator, shares, expected):
    rule = conditions(volume={"operator": operator, "thresholdLots": "12.34"})
    result = evaluate_checkpoint(rule, None, shares)
    assert result.satisfied is expected
    assert result.volume_satisfied is expected
    assert result.price_satisfied is None


def test_conditions_must_match_at_same_checkpoint_without_carrying_a_previous_hit():
    rule = conditions({"operator": "LTE", "upper": "10.00"},
                      {"operator": "GTE", "thresholdLots": "10.00"})
    assert not evaluate_checkpoint(rule, Decimal("9.00"), 900).satisfied
    assert not evaluate_checkpoint(rule, Decimal("11.00"), 1000).satisfied
    assert evaluate_checkpoint(rule, Decimal("10.00"), 1000).satisfied


@pytest.mark.parametrize("price", [None, 11.8, Decimal("NaN"), Decimal("Infinity"),
                                   Decimal("0"), Decimal("-1")])
def test_missing_or_invalid_enabled_price_is_not_a_nontrigger_result(price):
    with pytest.raises(ValueError):
        evaluate_checkpoint(conditions({"operator": "LTE", "upper": "12.00"}), price, None)


@pytest.mark.parametrize("shares", [None, True, -1, 1.5, Decimal("10")])
def test_invalid_enabled_volume_is_not_a_nontrigger_result(shares):
    with pytest.raises(ValueError):
        evaluate_checkpoint(conditions(volume={"operator": "GTE", "thresholdLots": "1.00"}),
                            None, shares)


def test_disabled_fields_have_no_source_dependency():
    assert evaluate_checkpoint(conditions({"operator": "LTE", "upper": "12.00"}),
                               Decimal("11.80"), None).satisfied
    assert evaluate_checkpoint(conditions(volume={"operator": "GTE", "thresholdLots": "1.00"}),
                               None, 100).satisfied


def test_comparison_does_not_depend_on_decimal_context_precision():
    rule = conditions({"operator": "GTE", "lower": "999999999999999999.99"},
                      {"operator": "GTE", "thresholdLots": "999999999999999999.99"})
    with localcontext() as context:
        context.prec = 3
        assert evaluate_checkpoint(rule, Decimal("999999999999999999.99"),
                                   99999999999999999999).satisfied
