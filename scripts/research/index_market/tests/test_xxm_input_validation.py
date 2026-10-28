"""Artificial values for r4 LLD §3.2; no source data or dual replay.

The six-bar sequence is hand checked from the registered r2 rules: its fifth
bar first activates TOP, and the sixth DIF falls 2%, forming a structure.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


@pytest.mark.parametrize("field", ["close", "dif", "dea", "hist"])
@pytest.mark.parametrize("value", [True, False, None, "2", float("nan"), float("inf"), -float("inf")])
def test_invalid_numeric_fields_are_value_errors_before_mutation(field, value):
    calc = XxmCalculator(period="day", source_identity="input-unit")
    calc.step(XxmBar("2025-03-03", 100, 10, 9, 2))
    before = deepcopy(calc.snapshot())
    bad = replace(XxmBar("2025-03-04", 101, 11, 10, 2), **{field: value})
    with pytest.raises(ValueError):
        calc.step(bad)
    assert calc.snapshot() == before
    calc.step(XxmBar("2025-03-04", 101, 11, 10, 2))
    assert calc.processed == 2 and calc.wave.price == 101


@pytest.mark.parametrize("completed", [False, 0, 1, None, "True", "False"])
def test_completion_flag_requires_actual_true(completed):
    with pytest.raises(ValueError):
        XxmBar("2025-03-03", 100, 0, 0, 0, completed=completed).validate("day")


@pytest.mark.parametrize("value", [None, 20250303, "", "2025-3-03", "2025-02-30", date(2025, 3, 3),
                                        datetime(2025, 3, 3), "2025-03-03T15:00:00+08:00"])
def test_daily_time_is_not_coerced_or_repaired(value):
    with pytest.raises(ValueError):
        XxmBar(value, 100, 0, 0, 0).validate("day")


@pytest.mark.parametrize("period", ["m60", "m90", "m120"])
@pytest.mark.parametrize("stamp", [None, "", "bad", "2025-03-03T15:00:00", "2025-03-03T15:00:00+00:00"])
def test_minute_time_requires_existing_plus_eight_semantics(period, stamp):
    with pytest.raises(ValueError):
        XxmBar(stamp, 100, 0, 0, 0).validate(period)


@pytest.mark.parametrize("close", [0, -1, -0.5])
def test_close_must_remain_positive(close):
    with pytest.raises(ValueError):
        XxmBar("2025-03-03", close, -2, -1, -2).validate("day")


@pytest.mark.parametrize("period,stamp", [("day", "2025-03-03"),
    ("m60", "2025-03-03T10:30:00+08:00"), ("m90", "2025-03-03T11:00:00+08:00"),
    ("m120", "2025-03-03T11:30:00+08:00")])
def test_ordinary_int_float_and_zero_indicators_remain_valid(period, stamp):
    assert XxmBar(stamp, 100, 0, -1, 2).validate(period) is None
    assert XxmBar(stamp, 100.5, -3.5, 0.0, -7.0).validate(period) is None
    assert XxmBar(stamp, 100, 0, 0, 0).validate(period) is None


@pytest.mark.parametrize("stamp", ["2025-03-03", "2025-03-02"])
def test_duplicate_or_reverse_time_rejects_without_advancing(stamp):
    calc = XxmCalculator(period="day", source_identity="input-unit")
    calc.step(XxmBar("2025-03-03", 100, 0, 0, 0))
    before = deepcopy(calc.snapshot())
    with pytest.raises(ValueError):
        calc.step(XxmBar(stamp, 101, 1, 0, 2))
    assert calc.snapshot() == before
    calc.step(XxmBar("2025-03-04", 101, 1, 0, 2))
    assert calc.processed == 2 and calc.wave.sign == 1 and calc.wave.count == 1


def test_normal_r2_hand_sequence_retains_original_policy_and_events():
    dates = ("2025-03-03", "2025-03-04", "2025-03-05", "2025-03-06", "2025-03-07", "2025-03-10")
    values = ((100, 10, 9, 2), (101, 12, 11, 2), (99, 9, 10, -2),
              (100, 9, 8, 2), (102, 10, 9, 2), (103, 9.8, 8.8, 2))
    calc = XxmCalculator(period="day", source_identity="input-unit")
    steps = [calc.step(XxmBar(stamp, *value)) for stamp, value in zip(dates, values)]
    assert [s.point["ordinaryState"] for s in steps] == ["NONE", "NONE", "NONE", "NONE", "DULL", "STRUCTURE"]
    assert [tuple(e["type"] for e in s.events) for s in steps] == [(), (), (), (), ("DULL",), ("STRUCTURE",)]
    assert steps[4].events[0]["route"] == "activation"
    assert steps[5].events[0]["route"] == "dif_turn"
    assert steps[5].events[0]["eventReference"] == {
        "startTime": "2025-03-03", "endTime": "2025-03-04", "price": 101, "dif": 12}
    assert calc.pending["pricePeak"] == 103 and calc.pending["confirmedAt"] == "2025-03-10"
