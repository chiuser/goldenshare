"""P5-16: literal current integer display ranges; no legacy report or forecast execution."""
from copy import deepcopy
import pytest
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import _range_text


def value(lower=10, upper=20, lower_inclusive=True, upper_inclusive=True, lo=10, hi=20):
    return dict(lower=lower, upper=upper, lowerInclusive=lower_inclusive,
                upperInclusive=upper_inclusive, displayLower=lo, displayUpper=hi)


def test_normal_integer_range():
    assert _range_text(value()) == "收盘不低于10点且不高于20点"


def test_single_integer_point():
    assert _range_text(value(12, 12, True, True, 12, 12)) == "收盘等于12点"


def test_unbounded_range():
    assert _range_text(value(10.2, None, False, False, 11, None)) == "收盘不低于11点"


def test_no_usable_integer_is_explicit():
    assert _range_text(value(10.2, 10.3, False, False, None, None)) == "已算出条件范围，暂未生成可用整数点位"


@pytest.mark.parametrize("lo,hi", [(10., 20), (True, 20), (0, 20), (10, False), (10, 20.)])
def test_bad_integer_types_and_nonpositive_values(lo, hi):
    with pytest.raises(ValueError): _range_text(value(lo=lo, hi=hi))


@pytest.mark.parametrize("row", [value(12, 12, False, True, 12, 12),
                                value(12, 12, True, True, 12, 13)])
def test_bad_singleton_bounds(row):
    with pytest.raises(ValueError): _range_text(row)


@pytest.mark.parametrize("row", [value(lo=None), value(10.2, None, False, False, 11, 20),
                                value(0, 20, True, True, 1, 20)])
def test_incomplete_or_impossible_display_fields(row):
    with pytest.raises(ValueError): _range_text(row)


def test_does_not_modify_exact_range_or_integer_fields():
    row = value(10.2, 20.8, False, True, 11, 20)
    original = deepcopy(row)
    assert _range_text(row) == "收盘不低于11点且不高于20点"
    assert row == original
