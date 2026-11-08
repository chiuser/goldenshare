"""Literal integer display ranges and the approved m30 M3 next-bar example."""
from copy import deepcopy
import pytest
from goldenshare_technical_indicators.xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast, precheck_next_bar
from src.biz.services.wealth.market.index_detail_xxm.forecast_math import as_interval
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import _range_text, make_display
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState
from goldenshare_technical_indicators.xxm.types import XxmBar


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


def test_m30_actual_candidate_reaches_comparison_and_display_without_mutating_prefix():
    # LLD's independent M3 values: the second red bar at C=100 forms TOP DULL.
    # All four timestamps are literal completed endpoints from the m30 contract.
    calc = XxmCalculator(ts_code="399001.SZ", period="m30", source_identity="m30-m3-literal")
    for stamp, close, dif, hist in (
        ("2023-01-03T10:00:00+08:00", 70, 10, 2),
        ("2023-01-03T10:30:00+08:00", 90, 0, -2),
        ("2023-01-03T11:00:00+08:00", 100, 2, 8),
    ):
        calc.step(XxmBar(stamp, close, dif, dif-hist/2, hist))
    before = calc.snapshot()
    prepared = precheck_next_bar(calc, lambda: None)
    result = forecast(calc, ProjectionState(102, 100, -2), "2023-01-03T11:30:00+08:00",
                      lambda: None, prepared=prepared)
    assert result.status == "READY" and result.bars_ahead == 1
    assert result.selected_reference == "NEAR" and not result.far_evaluated
    assert result.conditions and {item.outcome for item in result.conditions} == {"DULL_FORMED"}
    assert {item.outcome for item in result.conditions
            if any(as_interval(row).contains(100.) for row in item.price_ranges)} == {"DULL_FORMED"}
    shown = make_display(result, prepared=prepared, period="m30", through="2023-01-03T11:00:00+08:00",
                         mode="LATEST", check=lambda: None)
    assert shown["statusLabel"] == "可形成顶钝化"
    assert shown["targetText"] == "2023-01-03 11:30 收盘 · 下一根条件"
    assert shown["asOfText"] == "截至 2023-01-03 11:00 收盘"
    assert "本次只计算近参照条件。" in shown["conditionsText"]
    assert "形成顶钝化。" in shown["conditionsText"]
    assert calc.snapshot() == before
