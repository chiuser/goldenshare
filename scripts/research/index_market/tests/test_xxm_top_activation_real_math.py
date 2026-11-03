"""Hand-computed rational endpoints, LLD P5-13; no detector or forecast oracle."""
from fractions import Fraction as F
import pytest
from scripts.research.index_market.xxm.top_activation_math import pair, daily_options
from scripts.research.index_market.xxm.top_activation_real_math import meet, minus, interval


def test_interval_subtraction_preserves_strict_boundary_and_single_point():
    a = (F(0), F(10), False, False)
    assert minus(a, (F(3), F(7), False, False)) == [
        (F(0), F(3), False, True), (F(7), F(10), True, False)]
    assert meet(a, (F(10), F(11), True, True)) is None
    assert meet((F(3), F(3), True, True), a) == (F(3), F(3), True, True)
    assert minus(a, (F(0), F(10), True, True)) == []


def test_disjoint_closed_touch_and_empty_singletons():
    a = (F(1), F(2), True, True)
    assert meet(a, (F(2), F(3), True, True)) == (F(2), F(2), True, True)
    assert minus(a, (F(2), F(3), True, True)) == [(F(1), F(2), True, False)]
    assert minus(a, (F(3), F(4), True, True)) == [a]
    assert meet((F(2), F(2), False, True), a) is None


def test_rational_serialization_keeps_sign_and_open_closed_flags():
    assert pair(F(1, 3)) == [1, 3]
    assert pair(F(-2, 5)) == [-2, 5]
    assert interval((F(1, 3), F(2, 5), False, True)) == {
        "lower": [1, 3], "upper": [2, 5], "lowerInclusive": False, "upperInclusive": True}


@pytest.mark.parametrize("value,expected", [
    (F(5, 10000), [F(0), F(1, 1000)]),
    (F(-5, 10000), [F(-1, 1000), F(0)]),
    (F(5, 10000) - F(2, 10**10), [F(0)]),
    (F(5, 10000) + F(2, 10**10), [F(1, 1000)]),
    (F(-5, 10000) - F(2, 10**10), [F(-1, 1000)]),
    (F(-5, 10000) + F(2, 10**10), [F(0)]),
    (F(5, 10000) - F(1, 10**10), [F(0), F(1, 1000)]),
    (F(-5, 10000) + F(1, 10**10), [F(-1, 1000), F(0)]),
    (F(1234, 1000), [F(1234, 1000)]),
])
def test_three_decimal_source_ties_and_both_signs(value, expected):
    assert daily_options(value) == expected
