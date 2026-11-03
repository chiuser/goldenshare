"""Literal raw turns/windows, LLD P5-11; no reference selection policy."""
from copy import deepcopy
import pytest
from scripts.research.index_market.xxm.reference_window_review import build_references, sign


def rows(difs, colours, closes=None):
    closes = closes or [100] * len(difs)
    return [dict(trade_time=f"{i:06d}", close=str(c), macd_dif=str(d), macd=str(h))
            for i, (d, h, c) in enumerate(zip(difs, colours, closes, strict=True))]


def test_price_window_includes_peak_excludes_first_opposite_and_is_not_peak_close():
    data = rows([0, -5, -10, -9, -8, -7, -6, -5],
                [1, -1, -1, -1, 1, 1, -1, -1], [110, 105, 100, 98, 90, 95, 97, 96])
    ref, = build_references(data)["references"]
    assert (ref["dif"], ref["peak_first"], ref["confirmed_at"]) == ("-10", "000002", "000003")
    assert (ref["window_last"], ref["first_opposite"], ref["price"], ref["price_at"]) == (
        "000003", "000004", "98", "000003")


def test_plateau_begins_at_its_first_candle():
    data = rows([0, -5, -10, -10, -9, -8, -6, -5],
                [1, -1, -1, -1, -1, 1, -1, -1], [110, 105, 97, 100, 98, 90, 96, 95])
    ref, = build_references(data)["references"]
    assert (ref["peak_first"], ref["peak_last"], ref["price"], ref["price_at"]) == (
        "000002", "000003", "97", "000002")


def test_multiple_raw_valleys_are_not_selected_or_hidden():
    data = rows([0, -9, -10, -3, -5, -2, -4, -1, 0, -6, -5],
                [1, -1, -1, -1, -1, -1, -1, -1, 1, -1, -1])
    before = deepcopy(data)
    result = build_references(data)
    # Index 8 is also a complete red phase: -1 < 0 > -6 confirms its MAX.
    # This raw tool retains both directions, rather than selecting BOTTOM only.
    assert [(r["direction"], r["dif"]) for r in result["references"]] == [
        ("BOTTOM", "-10"), ("BOTTOM", "-5"), ("BOTTOM", "-4"), ("TOP", "0")]
    assert data == before
    def check(value):
        if isinstance(value, dict):
            assert not {"qdif", "eligible", "selected"} & value.keys()
            for item in value.values(): check(item)
        elif isinstance(value, list):
            for item in value: check(item)
    check(result)


def test_open_and_left_censored_phases_are_not_historical_references():
    assert build_references(rows([0, -5, -10, -8, -9, -7], [1, -1, -1, -1, -1, -1]))["references"] == []
    result = build_references(rows([-5, -10, -9, -8], [-1, -1, -1, 1]))
    assert result["references"] == []
    assert result["censored"][0]["reason"] == "left_censored_phase"


def test_zero_does_not_split_a_phase_or_increase_coloured_count():
    result = build_references(rows([0, 1, 2, 1, 0, -1], [0, 1, 0, 1, -1, -1]))
    assert result["assignments"] == [None, 0, 0, 0, 1, 1]
    assert [p["actual_bars"] for p in result["phases"]] == [2, 2]
    assert [sign(x) for x in ("-0.1", "0", "0.1")] == [-1, 0, 1]


@pytest.mark.parametrize("data", [[], rows([1], [1], [0]), rows(["NaN"], [1]), rows([1], ["Infinity"])])
def test_invalid_raw_values_are_still_rejected(data):
    with pytest.raises(ValueError): build_references(data)
