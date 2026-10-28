"""Independent artificial cases from r4 LLD sections 4, 5.5, 7 and 10.

These cases replay only R4.  R2 objects below are empty identity-rejection
targets, never a second replay or a source of expected trading decisions.
"""
from __future__ import annotations

import ast
import builtins
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import socket
import sys

import pytest

from scripts.research.index_market.xxm import r4_reference_trial as trial
from scripts.research.index_market.xxm.r4_reference_trial import R4Calculator, R4TrialSpec, R4_TRIAL_SPEC
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


SOURCE = "r4-literal-input"
# Registered rule identity, not a fingerprint of any source file.
PARENT_RULE_HASH = "6db425730c72f22ea756c121a832f27c966d1324ef0a72a2312a3c572038724d"
RULE_FIELDS = {
    "research_version": "xxm-research-r4-v1",
    "reference_policy": "nearest_then_farther_two",
    "zero_policy": "neutral_real_opposite",
    "allow_zero_activation": True,
    "allow_zero_reactivation": True,
    "dif_turn_pct": 1.0,
    "max_refs": 2,
    "min_colored_bars": 2,
    "max_input_bars": 1000,
    "deadline_seconds": 20.0,
    "max_memory_bytes": 256 * 1024 ** 2,
    "max_result_bytes": 16 * 1024 ** 2,
}
RULE_HASH = hashlib.sha256(json.dumps(
    {**RULE_FIELDS, "parentSpecHash": PARENT_RULE_HASH}, sort_keys=True,
    separators=(",", ":"),
).encode()).hexdigest()


def stamp(index, period="day"):
    day = (date(2020, 1, 1) + timedelta(days=index - 1)).isoformat()
    return day if period == "day" else day + "T15:00:00+08:00"


def bar(index, close, dif, hist, dea=None, *, period="day"):
    return XxmBar(stamp(index, period), close, dif, dif - hist / 2 if dea is None else dea, hist)


def run(values, *, period="day", source=SOURCE):
    calc = R4Calculator(period=period, source_identity=source)
    steps = [calc.step(bar(i, *values_, period=period)) for i, values_ in enumerate(values, 1)]
    return calc, steps


def mirror(values):
    return [(200 - c, -d, -h, *([-extra[0]] if extra else []))
            for c, d, h, *extra in values]


def event_id(*parts, period="day"):
    parent = hashlib.sha256("|".join(map(str, (
        "xxm-direction-v0.1-r2", PARENT_RULE_HASH, "000001.SH", period, *parts,
    ))).encode()).hexdigest()[:24]
    return hashlib.sha256((RULE_HASH + "|" + parent).encode()).hexdigest()[:24]


def event_types(step):
    return [(item["type"], item["route"], item["direction"]) for item in step.events]


TOP_DULL = [(100, 50, 2), (90, 0, -2), (101, 40, 2), (102, 41, 2)]
BOTTOM_STRUCTURE = [(100, -10, -2), (99, -11, -2), (105, -5, 2),
                    (98, -9, -2), (97, -9.2, -2), (98, -8.8, -2)]


def test_rule_spec_is_fixed_and_has_independent_rule_identity():
    assert asdict(R4_TRIAL_SPEC) == RULE_FIELDS
    assert MAIN_SPEC.spec_hash == PARENT_RULE_HASH
    assert R4_TRIAL_SPEC.research_hash == RULE_HASH
    assert R4TrialSpec().research_hash == RULE_HASH
    with pytest.raises(FrozenInstanceError):
        R4_TRIAL_SPEC.max_refs = 3


@pytest.mark.parametrize("field,value", [
    ("allow_zero_activation", False), ("allow_zero_reactivation", False),
    ("dif_turn_pct", .75), ("max_refs", 3), ("min_colored_bars", 1),
    ("reference_policy", "strongest_eligible"), ("zero_policy", "split"),
])
def test_rule_fields_are_not_trial_switches(field, value):
    with pytest.raises(ValueError):
        R4TrialSpec(**{field: value})


def test_product_spec_input_identity_and_research_ids_are_separate():
    calc, steps = run(TOP_DULL)
    assert calc.spec is MAIN_SPEC
    assert calc.input_identity == SOURCE
    assert calc.source_identity == f"r4|{RULE_HASH}|day|{SOURCE}"
    assert steps[-1].events[0]["id"] == event_id(stamp(4), "DULL", 1, stamp(1))
    assert calc.snapshot()["researchHash"] == RULE_HASH
    assert calc.snapshot()["researchVersion"] == "xxm-research-r4-v1"
    assert set(calc.snapshot()) == {"researchVersion", "researchHash", "tsCode", "period", "inputIdentity", "parentState"}
    assert calc.snapshot()["parentState"]["specHash"] == PARENT_RULE_HASH
    assert calc.snapshot()["parentState"]["sourceIdentity"] == calc.source_identity


@pytest.mark.parametrize("price,dif,chosen", [
    (119, 10, None), (120, 10, None), (131, 15, 3),
    (125, 25, None), (131, 25, 1), (131, 30, None),
    (130, 25, None), (131, 20, 1),
])
@pytest.mark.parametrize("bottom", [False, True])
def test_lld_six_reference_cases_through_real_steps(price, dif, chosen, bottom):
    values = [(130, 30, 2), (90, 0, -2), (120, 20, 2), (90, 0, -2),
              (price, dif, 2), (price, dif, 2)]
    calc, steps = run(mirror(values) if bottom else values)
    assert not steps[-2].events  # one real colored bar cannot activate
    if chosen is None:
        assert steps[-1].events == () and calc.state == "NONE" and calc.reference is None
    else:
        assert event_types(steps[-1]) == [("DULL", "activation", "BOTTOM" if bottom else "TOP")]
        assert calc.reference.start == stamp(chosen)
        expected_dif = 20 if chosen == 3 else 30
        assert calc.reference.dif == (-expected_dif if bottom else expected_dif)


@pytest.mark.parametrize("bottom", [False, True])
def test_reference_missing_or_older_third_candidate_cannot_rescue_first_activation(bottom):
    values = [(150, 60, 2), (90, 0, -2), (130, 30, 2), (90, 0, -2),
              (120, 20, 2), (90, 0, -2), (160, 40, 2), (160, 40, 2)]
    calc, steps = run(mirror(values) if bottom else values)
    sign = -1 if bottom else 1
    assert [w.start for w in calc.history[sign]] == [stamp(3), stamp(5)]
    assert steps[-1].events == () and calc.reference is None
    only_b = [(120, 20, 2), (90, 0, -2), (131, 25, 2), (131, 25, 2)]
    calc, steps = run(mirror(only_b) if bottom else only_b)
    assert steps[-1].events == () and calc.reference is None


def test_first_activation_uses_cumulative_close_and_independent_dif_dates():
    calc, steps = run([(120, 50, 2), (110, 0, -2), (125, 20, 2), (119, 25, 2)])
    assert steps[-1].point["close"] == 119
    assert event_types(steps[-1]) == [("DULL", "activation", "TOP")]
    assert calc.wave.price == 125 and calc.wave.price_at == stamp(3)
    assert calc.wave.dif == 25 and calc.wave.dif_at == stamp(4)
    assert calc.reference.start == stamp(1) and calc.reference.count == 1


@pytest.mark.parametrize("current_dif,activates", [(0, False), (-1, False), (2, True)])
def test_first_top_requires_latest_positive_dif_only(current_dif, activates):
    _, steps = run([(120, 20, 2), (110, 0, -2), (131, 1, 2), (132, current_dif, 2)])
    assert [event["type"] for event in steps[-1].events] == (["DULL"] if activates else [])


def test_first_bottom_does_not_add_a_negative_dif_requirement():
    calc, steps = run([(100, -1, -2), (110, 1, 2), (99, 0, -2), (98, 1, -2)])
    assert event_types(steps[-1]) == [("DULL", "activation", "BOTTOM")]
    assert calc.wave.dif == 0 and steps[-1].point["dif"] == 1


@pytest.mark.parametrize("bottom", [False, True])
def test_zero_does_not_supply_second_colored_bar_and_history_needs_no_second_bar(bottom):
    values = [(100, 20, 2), (90, 0, -2), (98, 5, 2), (101, 5, 0), (102, 5, 2)]
    calc, steps = run(mirror(values) if bottom else values)
    assert not steps[2].events and not steps[3].events
    assert event_types(steps[4]) == [("DULL", "activation", "BOTTOM" if bottom else "TOP")]
    assert calc.wave.count == 2 and calc.reference.count == 1


@pytest.mark.parametrize("period", ["day", "m60", "m90", "m120"])
def test_opening_zero_has_no_wave_and_restores_without_fabricated_history(period):
    calc, steps = run([(100, 1, 0), (99, -1, 0)], period=period)
    assert calc.wave is None and calc.processed == 2 and calc.previous.time == stamp(2, period)
    assert all(step.point["ordinaryState"] == "NONE" and not step.events for step in steps)
    assert calc.history == {1: [], -1: []}
    child = R4Calculator(period=period, source_identity=SOURCE)
    child.restore(calc.snapshot())
    result = child.step(bar(3, 100, 2, 2, period=period))
    assert not result.events and child.wave.start == stamp(3, period) and child.wave.count == 1


@pytest.mark.parametrize("bottom", [False, True])
def test_same_color_through_zeros_keeps_one_wave_and_true_flip_closes_at_last_zero(bottom):
    values = [(100, 10, 2), (105, 11, 0), (102, 10, 2), (104, 9, 0), (103, 8, 0)]
    calc, steps = run(mirror(values) if bottom else values)
    sign = -1 if bottom else 1
    assert calc.wave.sign == sign and calc.wave.count == 2
    assert calc.wave.start == stamp(1) and calc.wave.end == stamp(5)
    assert calc.wave.price == (95 if bottom else 105) and calc.wave.price_at == stamp(2)
    assert calc.wave.dif == (-11 if bottom else 11) and calc.wave.dif_at == stamp(2)
    assert calc.history == {1: [], -1: []} and all(not s.events for s in steps)
    last = calc.step(bar(6, 110 if bottom else 90, 0, 2 if bottom else -2))
    assert not last.events
    assert len(calc.history[sign]) == 1
    assert calc.history[sign][0].end == stamp(5) and calc.history[sign][0].count == 2
    assert calc.wave.start == stamp(6) and calc.wave.sign == -sign


@pytest.mark.parametrize("dif,kind,state", [(40, "STRUCTURE", "STRUCTURE"), (40.9, None, "DULL"),
                                            (41, None, "DULL"),
                                            (50, None, "DULL"), (50.01, "CANCEL", "NONE")])
def test_zero_day_dull_turn_hold_reference_equality_or_strict_break(dif, kind, state):
    calc, _ = run(TOP_DULL)
    result = calc.step(bar(5, 102, dif, 0))
    assert result.point["hist"] == 0 and result.point["ordinaryState"] == state
    assert [e["type"] for e in result.events] == ([] if kind is None else [kind])
    assert calc.wave.start == stamp(3) and calc.wave.count == 2
    if kind == "STRUCTURE":
        assert result.events[0]["route"] == "dif_turn"
        assert result.point["ordinaryDirection"] == "TOP"
    if kind == "CANCEL":
        assert result.events[0]["route"] == "dif_break" and calc.reference is None


@pytest.mark.parametrize("bottom", [False, True])
def test_adjacent_turn_exactly_one_percent_is_inclusive(bottom):
    values = [(100, 200, 2), (90, 0, -2), (101, 90, 2), (102, 100, 2), (102, 99, 0)]
    _, steps = run(mirror(values) if bottom else values)
    assert event_types(steps[-1]) == [("STRUCTURE", "dif_turn", "BOTTOM" if bottom else "TOP")]


def test_return_uses_immediately_previous_zero_day_dif_not_previous_colored_day():
    calc, _ = run(TOP_DULL + [(102, 40, 2), (102, 39.9, 0)])
    result = calc.step(bar(7, 102, 40.35, 2))
    assert event_types(result) == [("DULL", "dif_return", "TOP")]
    assert calc.state == "DULL" and calc.previous.dif == 40.35


def test_previous_zero_dif_blocks_ordinary_turn_without_zero_color_reset():
    calc, steps = run([(100, 10, 2), (90, 0, -2), (101, 1, 2), (102, .5, 2),
                       (102, 0, 0), (102, -1, 2)])
    assert event_types(steps[4]) == [("STRUCTURE", "dif_turn", "TOP")]
    assert steps[5].events == () and calc.state == "STRUCTURE"


@pytest.mark.parametrize("bottom", [False, True])
def test_real_flip_confirms_independently_of_one_percent_and_excludes_new_close(bottom):
    values = TOP_DULL + [(102, 41, 0), (999, 40.9, -2)]
    if bottom:
        values = mirror(TOP_DULL + [(102, 41, 0)]) + [(1, -40.9, 2)]
    calc, steps = run(values)
    result = steps[-1]
    assert event_types(result) == [("STRUCTURE", "color_flip", "BOTTOM" if bottom else "TOP")]
    assert result.point["ordinaryState"] == "NONE" and calc.reference is None
    history = result.bottom_histories[0] if bottom else result.histories[0]
    assert history["priceLow" if bottom else "pricePeak"] == (98 if bottom else 102)
    assert calc.history[-1 if bottom else 1][-1].end == stamp(5)
    if bottom:
        assert history["leftOriginAt"] == stamp(6)


def test_true_flip_checks_original_reference_break_before_structure():
    _, steps = run(TOP_DULL + [(999, 51, -2)])
    assert event_types(steps[-1]) == [("CANCEL", "dif_break_on_flip", "TOP")]
    assert steps[-1].histories == ()


@pytest.mark.parametrize("close,kind,state", [(98, "DULL", "DULL"),
                                             (99, "STRUCTURE_DISAPPEARED", "NONE"),
                                             (100, "STRUCTURE_DISAPPEARED", "NONE")])
def test_bottom_structure_return_on_zero_uses_current_close(close, kind, state):
    calc, _ = run(BOTTOM_STRUCTURE)
    result = calc.step(bar(7, close, -9, 0))
    assert event_types(result) == [(kind, "dif_return", "BOTTOM")]
    assert calc.state == state and calc.wave.sign == -1 and calc.wave.count == 3
    assert result.bottom_histories[0]["leftOriginAt"] is None
    if kind == "DULL":
        assert calc.pending_rearm is None and calc.reference.start == stamp(1)
    else:
        assert calc.pending_rearm["status"] == "WAITING"
        assert calc.pending_rearm["nearestPriceGate"] == 99
        assert result.events[0]["relatedRearmId"] == event_id("rearm", event_id(stamp(6), "STRUCTURE", -1, stamp(1)), stamp(7))


def test_bottom_close_qualification_requires_two_real_colored_bars_even_on_zero():
    calc, _ = run([(100, -10, -2), (110, -5, 2), (99, -9, -2)])
    reference = calc.history[-1][-1]
    incoming_zero = bar(4, 98, -9, 0)
    assert calc.wave.count == 1 and reference.price == 100 and reference.dif == -10
    assert calc._qualifies_bottom_close(incoming_zero, reference, 100) is False
    zero = calc.step(incoming_zero)
    assert not zero.events and calc.wave.count == 1 and calc.state == "NONE"
    colored = calc.step(bar(5, 98, -9, -2))
    assert event_types(colored) == [("DULL", "activation", "BOTTOM")]
    assert calc.wave.count == 2
    assert calc._qualifies_bottom_close(bar(6, 98, -9, 0), reference, 100) is True


def waiting_calculator():
    calc, _ = run(BOTTOM_STRUCTURE + [(100, -9, 0)])
    return calc


@pytest.mark.parametrize("close", [99, 100])
def test_zero_waiting_ignores_earlier_low_when_current_price_not_strictly_qualified(close):
    calc = waiting_calculator()
    result = calc.step(bar(8, close, -9.2, 0))
    assert not result.events and calc.state == "NONE"
    assert calc.pending_rearm["status"] == "WAITING" and calc.wave.price == 97
    assert result.rearm_records[0]["observedThrough"] == stamp(8)


def test_zero_waiting_reactivation_keeps_saved_reference_and_history_ids():
    calc = waiting_calculator()
    result = calc.step(bar(8, 98.5, -9.2, 0))
    structure_id = event_id(stamp(6), "STRUCTURE", -1, stamp(1))
    wait_id = event_id("rearm", structure_id, stamp(7))
    assert event_types(result) == [("DULL", "reactivation", "BOTTOM")]
    assert result.events[0]["relatedRearmId"] == wait_id
    assert result.events[0]["relatedBottomHistoryId"] is None
    assert result.rearm_records[0]["id"] == wait_id
    assert result.rearm_records[0]["structureEventId"] == structure_id
    assert result.rearm_records[0]["bottomHistoryId"] == event_id("bottom-history", structure_id)
    assert result.rearm_records[0]["status"] == "REACTIVATED"
    assert calc.pending_rearm is None and calc.reference.start == stamp(1)
    following = calc.step(bar(9, 98.5, -9.2, 0))
    assert following.events == () and calc.state == "DULL"


@pytest.mark.parametrize("hist,expected_status", [(0, "INVALIDATED"), (-2, "INVALIDATED"),
                                                 (2, "SEGMENT_ENDED")])
def test_waiting_reference_break_precedes_reactivation_and_true_red_ends_origin(hist, expected_status):
    calc = waiting_calculator()
    result = calc.step(bar(8, 98.5, -11.1, hist))
    assert not result.events and calc.pending_rearm is None
    assert result.rearm_records[0]["status"] == expected_status
    assert calc.state == "NONE"


def test_true_green_reactivates_after_unqualified_zero_waiting():
    calc = waiting_calculator()
    assert not calc.step(bar(8, 99, -9.1, 0)).events
    result = calc.step(bar(9, 98.5, -9.1, -2))
    assert event_types(result) == [("DULL", "reactivation", "BOTTOM")]


def test_waiting_does_not_rescue_with_farther_valley_after_saved_reference_breaks():
    calc, _ = run([(110, -20, -2), (120, 0, 2)] + BOTTOM_STRUCTURE + [(100, -9, 0)])
    result = calc.step(bar(10, 98.5, -12, 0))
    assert not result.events and calc.state == "NONE" and calc.reference is None
    assert result.rearm_records[0]["status"] == "INVALIDATED"
    assert result.rearm_records[0]["referenceWave"]["dif"] == -11


@pytest.mark.parametrize("hist", [0, -2])
def test_bottom_dull_rescue_is_near_first_then_far_on_real_or_zero_day(hist):
    calc, steps = run([(110, -20, -2), (120, 0, 2), (100, -10, -2),
                       (120, 0, 2), (90, -9, -2), (90, -9, -2)])
    assert steps[-1].events[0]["eventReference"]["startTime"] == stamp(3)
    result = calc.step(bar(7, 89, -12, hist))
    assert not result.events and calc.state == "DULL"
    assert calc.reference.start == stamp(1) and calc.reference.dif == -20
    formed = calc.step(bar(8, 90, -11, -2))
    structure_id = event_id(stamp(8), "STRUCTURE", -1, stamp(1))
    history_id = event_id("bottom-history", structure_id)
    expected_reference = {"startTime": stamp(1), "endTime": stamp(1), "price": 110, "dif": -20}
    assert event_types(formed) == [("STRUCTURE", "dif_turn", "BOTTOM")]
    assert formed.events[0]["id"] == structure_id
    assert formed.events[0]["eventReference"] == expected_reference
    assert formed.events[0]["relatedBottomHistoryId"] == history_id
    assert formed.bottom_histories[0]["id"] == history_id
    assert formed.bottom_histories[0]["structureEventId"] == structure_id
    assert formed.bottom_histories[0]["originalReference"] == expected_reference
    assert formed.bottom_histories[0]["originSegmentStart"] == stamp(5)
    assert formed.bottom_histories[0]["priceLow"] == 89
    assert formed.bottom_histories[0]["priceLowAt"] == stamp(7)


def test_bottom_structure_does_not_use_dull_rescue():
    calc, _ = run([(110, -20, -2), (120, 0, 2), (100, -10, -2),
                   (120, 0, 2), (90, -9, -2), (90, -9, -2), (90, -8.8, -2)])
    result = calc.step(bar(8, 89, -12, 0))
    assert event_types(result) == [("CANCEL", "dif_break", "BOTTOM")]
    assert calc.reference is None and calc.state == "NONE"


def test_top_history_counts_real_opposite_transition_across_zero_once():
    calc, _ = run(TOP_DULL + [(102, 40, 2)])
    zero = calc.step(bar(6, 102, 39.9, 0))
    assert zero.histories[0]["colorChanges"] == 0 and zero.histories[0]["zeroBars"] == 1
    green = calc.step(bar(7, 101, 39.8, -2))
    assert green.histories[0]["colorChanges"] == 1
    assert green.histories[0]["negativeBars"] == 1 and green.histories[0]["ageBars"] == 2


def test_bottom_history_zero_stays_in_origin_and_freezes_original_price():
    calc, _ = run(BOTTOM_STRUCTURE)
    result = calc.step(bar(7, 96, -8.75, 0))
    assert not result.events and result.bottom_histories[0]["leftOriginAt"] is None
    assert result.bottom_histories[0]["priceLow"] == 97
    assert calc.wave.price == 96
    red = calc.step(bar(8, 98, -8.7, 2))
    assert red.bottom_histories[0]["leftOriginAt"] == stamp(8)
    assert red.bottom_histories[0]["priceLow"] == 97


def test_top_history_can_end_on_later_zero_close_while_structure_remains_and_restores():
    calc, _ = run(TOP_DULL + [(102, 40, 0)])
    result = calc.step(bar(6, 103, 39.9, 0))
    assert event_types(result) == [("RESEARCH_HISTORICAL_WITHDRAWAL", "historical_price_break", "TOP")]
    assert calc.state == "STRUCTURE" and calc.pending is None
    assert result.histories[0]["pricePeak"] == 102
    child = R4Calculator(period="day", source_identity=SOURCE)
    child.restore(calc.snapshot())
    assert child.state == "STRUCTURE" and child.pending is None


def test_bottom_history_withdraws_on_later_zero_after_real_origin_exit():
    calc, _ = run(BOTTOM_STRUCTURE + [(98, -8.7, 0), (98, -8.6, 2)])
    result = calc.step(bar(9, 96, -8.5, 0))
    assert event_types(result) == [("RESEARCH_HISTORICAL_WITHDRAWAL", "historical_price_break", "BOTTOM")]
    assert result.bottom_histories[0]["leftOriginAt"] == stamp(8)
    assert result.bottom_histories[0]["priceLow"] == 97
    assert calc.pending_bottom_history is None


@pytest.mark.parametrize("bottom", [False, True])
def test_lld_zero_first_activation_numeric_case_and_mirror(bottom):
    values = [(100, 6, 2), (99, 4, -2),
              (98, 5.094545454545455, .21409090909, 4.9875),
              (99, 5, .02, 4.99), (100.5175, 4.99, 0, 4.99)]
    calc, steps = run(mirror(values) if bottom else values)
    assert not steps[2].events and not steps[3].events
    assert event_types(steps[4]) == [("DULL", "activation", "BOTTOM" if bottom else "TOP")]
    assert calc.wave.count == 2 and calc.wave.price_at == stamp(5) and calc.wave.dif_at == stamp(3)
    assert calc.wave.price == (99.4825 if bottom else 100.5175)
    assert calc.reference.start == stamp(1)


def test_lld_zero_waiting_reactivation_numeric_case():
    values = [(100, -8, -2), (120, 0, 2), (100, -5.98, -2),
              (99, -5.980363636, -1.963227272, -4.99875),
              (111, -5, -.002, -4.999),
              (100, -5.052421652, -.085474644, -5.009684330),
              (100, -5.035915293, -.041969540, -5.014930523),
              (99.3815265787, -5.014930523, 0, -5.014930523)]
    calc, steps = run(values)
    assert [event_types(s) for s in steps[3:]] == [
        [("DULL", "activation", "BOTTOM")], [("STRUCTURE", "dif_turn", "BOTTOM")],
        [("STRUCTURE_DISAPPEARED", "dif_return", "BOTTOM")], [],
        [("DULL", "reactivation", "BOTTOM")],
    ]
    assert steps[5].rearm_records[0]["status"] == "WAITING"
    assert steps[6].rearm_records[0]["status"] == "WAITING"
    assert steps[7].rearm_records[0]["status"] == "REACTIVATED"
    assert calc.wave.count == 5 and calc.reference.start == stamp(1)


@pytest.mark.parametrize("period", ["day", "m60", "m90", "m120"])
def test_continuation_and_every_prefix_restore_have_literal_state_expectations(period):
    values = BOTTOM_STRUCTURE + [(100, -9, 0), (99, -9.2, 0), (98.5, -9.2, 0)]
    states = ["NONE", "NONE", "NONE", "NONE", "DULL", "STRUCTURE", "NONE", "NONE", "DULL"]
    expected_events = [[], [], [], [], [("DULL", "activation", "BOTTOM")],
                       [("STRUCTURE", "dif_turn", "BOTTOM")],
                       [("STRUCTURE_DISAPPEARED", "dif_return", "BOTTOM")], [],
                       [("DULL", "reactivation", "BOTTOM")]]
    full, full_steps = run(values, period=period)
    assert [s.point["ordinaryState"] for s in full_steps] == states
    assert [event_types(s) for s in full_steps] == expected_events
    for cut in range(len(values) + 1):
        prefix, prefix_steps = run(values[:cut], period=period)
        saved = deepcopy(prefix.snapshot())
        child = R4Calculator(period=period, source_identity=SOURCE)
        child.restore(saved)
        tail = [child.step(bar(i, *values[i - 1], period=period)) for i in range(cut + 1, len(values) + 1)]
        assert [s.point["ordinaryState"] for s in tail] == states[cut:]
        assert [event_types(s) for s in tail] == expected_events[cut:]
        assert prefix.snapshot() == saved and child.snapshot() == full.snapshot()
        assert [s.point["ordinaryState"] for s in prefix_steps] == states[:cut]


def test_r4_snapshots_do_not_share_state_and_can_rewind_used_object():
    calc, _ = run(BOTTOM_STRUCTURE + [(100, -9, 0)])
    waiting = calc.snapshot()
    child = R4Calculator(period="day", source_identity=SOURCE)
    child.restore(waiting)
    child.pending_rearm["referenceWave"]["price"] = 1
    assert calc.pending_rearm["referenceWave"]["price"] == 99
    assert waiting["parentState"]["pendingRearm"]["referenceWave"]["price"] == 99
    calc.step(bar(8, 98.5, -9.2, 0))
    calc.restore(waiting)
    assert calc.state == "NONE" and calc.pending_rearm["status"] == "WAITING"
    assert calc.processed == 7 and calc.previous.time == stamp(7)


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(researchHash="wrong"), lambda s: s.update(researchVersion="other"),
    lambda s: s.update(inputIdentity="other"), lambda s: s.update(period="m60"),
    lambda s: s.update(tsCode="399001.SZ"), lambda s: s.update(extra=1),
    lambda s: s["parentState"].update(sourceIdentity=SOURCE),
    lambda s: s["parentState"].update(specHash="wrong"),
    lambda s: s["parentState"]["wave"].update(dif=float("nan")),
    lambda s: s["parentState"]["reference"].update(price=float("inf")),
    lambda s: s["parentState"].update(reference=None),
    lambda s: s["parentState"].update(state="NONE"),
    lambda s: s["parentState"]["previous"].update(completed=1),
    lambda s: s["parentState"]["wave"].update(count=True),
    lambda s: s["parentState"]["wave"].update(end="2099-01-01"),
])
def test_bad_snapshot_is_rejected_before_any_existing_state_or_input_is_changed(mutate):
    calc, _ = run(TOP_DULL)
    valid = calc.snapshot()
    bad = deepcopy(valid)
    mutate(bad)
    unchanged_bad = repr(bad)
    with pytest.raises(ValueError):
        calc.restore(bad)
    assert calc.snapshot() == valid and repr(bad) == unchanged_bad
    calc.restore(valid)
    assert event_types(calc.step(bar(5, 102, 40, 0))) == [("STRUCTURE", "dif_turn", "TOP")]


def test_bottom_structure_missing_history_is_rejected_but_valid_zero_structure_restores():
    calc, _ = run(BOTTOM_STRUCTURE)
    valid = calc.snapshot()
    bad = deepcopy(valid)
    bad["parentState"]["pendingBottomHistory"] = None
    with pytest.raises(ValueError):
        calc.restore(bad)
    assert calc.snapshot() == valid
    calc.step(bar(7, 98, -8.7, 0))
    child = R4Calculator(period="day", source_identity=SOURCE)
    child.restore(calc.snapshot())
    assert child.state == "STRUCTURE" and child.previous.hist == 0
    assert child.pending_bottom_history["leftOriginAt"] is None


def test_cross_group_sources_periods_and_unwrapped_parent_are_rejected():
    calc, _ = run(TOP_DULL)
    before = calc.snapshot()
    r2 = XxmCalculator(period="day", source_identity=SOURCE)
    with pytest.raises(ValueError):
        r2.restore(before)
    with pytest.raises(ValueError):
        r2.restore(before["parentState"])
    for incoming in (r2.snapshot(), before["parentState"],
                     R4Calculator(period="m60", source_identity=SOURCE).snapshot(),
                     R4Calculator(period="day", source_identity="other").snapshot()):
        with pytest.raises(ValueError):
            calc.restore(incoming)
        assert calc.snapshot() == before
    assert r2.processed == 0 and r2.wave is None


@pytest.mark.parametrize("change", [
    {"close": True}, {"dif": float("nan")}, {"dea": "1"}, {"hist": None},
    {"completed": 1}, {"completed": False}, {"time": None},
    {"time": "2019-12-31"}, {"time": "2020-01-04"},
])
def test_r4_reuses_shared_input_checks_before_mutation(change):
    calc, _ = run(TOP_DULL)
    before = calc.snapshot()
    incoming = replace(bar(5, 102, 40, 0), **change)
    with pytest.raises(ValueError):
        calc.step(incoming)
    assert calc.snapshot() == before
    assert calc.step(bar(5, 102, 40, 0)).events[0]["type"] == "STRUCTURE"


def test_calculation_and_restore_need_no_files_network_database_or_saved_source(monkeypatch):
    calc, _ = run(TOP_DULL)
    saved = calc.snapshot()
    def forbidden(*args, **kwargs):
        raise AssertionError("Calculation attempted external access")
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(Path, "read_text", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(socket.socket, "connect", forbidden)
        child = R4Calculator(period="day", source_identity=SOURCE)
        child.restore(saved)
        result = child.step(bar(5, 102, 40, 0))
        after = child.snapshot()
    assert event_types(result) == [("STRUCTURE", "dif_turn", "TOP")]
    assert after["parentState"]["processed"] == 5


def test_trial_imports_only_the_allowed_calculation_dependencies():
    # Inspect imports for architecture boundaries, never compare source bodies.
    tree = ast.parse(Path(trial.__file__).read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    banned = ("src.app", "qtf", "sqlalchemy", "scripts.research.index_market.xxm.confirmation",
              "src.biz.services.wealth.market.index_detail_daily_wave")
    assert all(not name.startswith(banned) for name in imports)


@pytest.mark.parametrize("filename", ["types.py", "snapshot_validation.py", "calculator.py"])
def test_shared_production_imports_stay_in_standard_library_or_own_directory(filename):
    root = Path(__file__).resolve().parents[4]
    package = "src.biz.services.wealth.market.index_detail_xxm"
    path = root / "src/biz/services/wealth/market/index_detail_xxm" / filename
    # This checks import destinations only, not source-body equality or a hash.
    tree = ast.parse(path.read_text())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                assert node.level == 1, f"{filename} imports above its own directory"
            else:
                names.append(node.module or "")
    assert all(name.split(".")[0] in sys.stdlib_module_names
               or name == package or name.startswith(package + ".") for name in names)
