"""Independent LLD P5-02 literals; arithmetic only, no calculator or market data."""
from decimal import Decimal
import pytest
from scripts.research.index_market.xxm.near_first_review import decimal_value, quantize_dif


@pytest.mark.parametrize("raw,expected", [
    ("-8.086", "-8.0"), ("40.057", "40"), ("26.912", "26"), ("26.871", "26"),
    ("12.01", "12"), ("11.99", "11"), ("0.008086", "0.0080"),
    ("-0.008086", "-0.0080"), ("0", "0"), ("99.999", "99"), ("100.1", "100"),
    ("41.01", "41"), ("40.99", "40"), ("41.9", "41"), ("41.4", "41"),
    ("-41.01", "-41"), ("-40.99", "-40"),
])
def test_course_two_digit_literals(raw, expected):
    assert quantize_dif(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [True, False, "NaN", "Infinity", "-Infinity", "bad", None])
def test_nonfinancial_values_are_rejected(raw):
    for operation in (decimal_value, quantize_dif):
        with pytest.raises(ValueError):
            operation(raw)
