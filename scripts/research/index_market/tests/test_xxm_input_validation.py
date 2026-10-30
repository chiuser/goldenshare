"""Artificial values for r4 LLD §3.2; no source data or dual replay.

The six-bar sequence is hand checked from the approved r4 rules: its fifth
bar first activates TOP, and the sixth DIF falls 2%, forming a structure.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC, XxmSpec
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


def test_normal_r4_hand_sequence_retains_approved_events():
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
        "startTime": "2025-03-03", "endTime": "2025-03-04", "price": 101, "dif": 12,
        "priceAt": "2025-03-04", "difAt": "2025-03-04"}
    assert calc.active_structure["priceExtreme"] == 103 and calc.active_structure["formedAt"] == "2025-03-10"


@pytest.mark.parametrize("field,value", [
    ("algorithm_version", "xxm-direction-v0.1-r2"),
    ("dif_turn_pct", 0.75), ("dif_turn_pct", 1.2), ("dif_turn_pct", 1),
    ("dif_turn_pct", True), ("max_refs", 2.0), ("max_refs", True),
    ("min_bars", 2.0), ("min_bars", True),
    ("reference_policy", "strongest_eligible"),
    ("active_reference_policy", "other"), ("zero_policy", "reset"),
    ("allow_zero_activation", 1), ("allow_zero_activation", False),
    ("activation_policy", "cumulative_close"), ("reference_break_policy", "current_only"),
    ("structure_return_policy", "wait_for_price"), ("structure_lock_policy", "later_price_break"),
    ("historical_min_bars", 2), ("historical_min_bars", True),
    ("top_activation_requires_positive_dif", False), ("top_activation_requires_positive_dif", 1),
    ("macd_parameters", [12, 26, 9]), ("macd_parameters", (12.0, 26, 9)),
    ("histogram_multiplier", 2.0), ("color_flip", 1),
    ("flip_requires_turn", 0),
])
def test_formal_spec_has_one_exactly_typed_rule_set(field, value):
    # LLD v1 section 2.2 fixes these values; numeric equality is insufficient.
    with pytest.raises(ValueError):
        XxmSpec(**{field: value})
    assert XxmSpec() == MAIN_SPEC


def test_formal_spec_contains_every_approved_rule_and_hashes_canonical_content():
    from dataclasses import asdict
    import hashlib
    import json

    # Independent literal contract from LLD v1 section 2.2, no research Spec.
    expected = {
        "algorithm_version": "xxm-direction-v0.2-r4", "dif_turn_pct": 1.0,
        "max_refs": 2, "min_bars": 2, "reference_policy": "nearest_then_farther_two",
        "active_reference_policy": "same_bar_near_to_far_on_dull_break",
        "zero_policy": "neutral_real_opposite", "allow_zero_activation": True,
        "activation_policy": "current_close_and_current_dif",
        "reference_break_policy": "strict_break_within_current_segment",
        "structure_return_policy": "adjacent_one_percent_to_dull",
        "structure_lock_policy": "first_valid_opposite_color",
        "historical_min_bars": 1, "top_activation_requires_positive_dif": True,
        "macd_parameters": (12, 26, 9),
        "histogram_multiplier": 2, "color_flip": True, "flip_requires_turn": False,
    }
    assert asdict(MAIN_SPEC) == expected
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    assert MAIN_SPEC.spec_hash == hashlib.sha256(canonical).hexdigest()
    with pytest.raises(TypeError):
        XxmSpec(bottom_dull_reference_policy="prebreak_strongest_eligible_v1")


@pytest.mark.parametrize("field", ["allow_zero_reactivation", "historical_price_only", "fixed_expiry",
                                   "bottom_history_policy", "same_segment_bottom_policy"])
def test_removed_waiting_and_historical_withdrawal_spec_fields_are_not_aliases(field):
    with pytest.raises(TypeError):
        XxmSpec(**{field: None})
