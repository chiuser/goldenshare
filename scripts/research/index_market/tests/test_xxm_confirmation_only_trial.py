"""Literal, single-calculator tests for next-stage LLD 0.6.

No test calls the comparison entry point, loads market input, or replays r2
beside the experiment. Expected states and values below are hand calculated.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import inspect

import pytest

from scripts.research.index_market.xxm.confirmation_only_trial import (
    ROOT, TRIAL_SPEC, ConfirmationTrialSpec, TwoDigitTurnCalculator,
    calculator_source_identity, quantize_dif, validate_step_copy, verify_baseline,
)
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


PREFIX = [(100, 50, 2), (99, 30, -2), (101, 41.01, 2), (102, 41.01, 2)]
BOTTOM_PREFIX = [(100, -50, -2), (101, -30, 2), (99, -41, -2), (98, -41, -2)]


def bars(values):
    return tuple(XxmBar((date(2020, 1, 1) + timedelta(days=i)).isoformat(),
                        float(c), float(d), float(d) - float(h) / 2, float(h))
                 for i, (c, d, h) in enumerate(values))


def trial(values, *, identity="literal-input", spec=TRIAL_SPEC):
    calculator = TwoDigitTurnCalculator(source_identity=identity, trial_spec=spec)
    return calculator, [calculator.step(bar) for bar in bars(values)]


def ordinary(step):
    return [(event["type"], event["route"], event["direction"])
            for event in step.events if event["type"] != "RESEARCH_HISTORICAL_WITHDRAWAL"]


@pytest.mark.parametrize("raw,expected", [
    ("40.057", "40"), ("-8.086", "-8.0"), ("41.01", "41"), ("40.99", "40"),
    ("41.9", "41"), ("41.4", "41"), ("-8.101", "-8.1"), ("-8.099", "-8.0"),
    ("0", "0"), ("0.008086", "0.0080"), ("99.99", "99"), ("100", "100"),
])
def test_q_uses_literal_significant_digits_toward_zero(raw, expected):
    assert quantize_dif(Decimal(raw)) == Decimal(expected)


@pytest.mark.parametrize("previous,current,state", [
    (41.01, 40.99, "STRUCTURE"),  # raw move <1%, but 41 -> 40
    (41.9, 41.4, "DULL"),       # raw move >1%, both read 41
    (41, 40, "STRUCTURE"),       # both arithmetic rules say turn
    (41.01, 41.0, "DULL"),      # changed raw value, equal reading
])
def test_top_formation_has_independent_literal_state_prefix(previous, current, state):
    values = [(100, 50, 2), (99, 30, -2), (101, previous, 2), (102, previous, 2), (103, current, 2)]
    calculator, steps = trial(values)
    assert [step.point["ordinaryState"] for step in steps[:4]] == ["NONE", "NONE", "NONE", "DULL"]
    assert ordinary(steps[3]) == [("DULL", "activation", "TOP")]
    assert calculator.state == state
    assert ordinary(steps[4]) == ([("STRUCTURE", "dif_turn", "TOP")] if state == "STRUCTURE" else [])
    assert steps[4].point["activeReference"] == {
        "startTime": "2020-01-01", "endTime": "2020-01-01", "price": 100.0, "dif": 50.0,
    }
    if state == "STRUCTURE":
        assert steps[4].histories[0]["pricePeak"] == 103
        assert steps[4].histories[0]["confirmedAt"] == "2020-01-05"


@pytest.mark.parametrize("previous,current,state", [
    (-8.101, -8.099, "STRUCTURE"), (-8.19, -8.10, "DULL"), (-8.1, -8.0, "STRUCTURE"),
])
def test_bottom_formation_is_a_literal_negative_value_example(previous, current, state):
    _, steps = trial([(100, -20, -2), (101, -5, 2), (99, previous, -2), (98, previous, -2), (97, current, -2)])
    assert ordinary(steps[3]) == [("DULL", "activation", "BOTTOM")]
    assert steps[4].point["ordinaryState"] == state
    assert ordinary(steps[4]) == ([("STRUCTURE", "dif_turn", "BOTTOM")] if state == "STRUCTURE" else [])
    if state == "STRUCTURE":
        history = steps[4].bottom_histories[0]
        assert history["priceLow"] == 97 and history["confirmedAt"] == "2020-01-05"
        assert history["structureEventId"] == steps[4].events[0]["id"]
        assert steps[4].events[0]["relatedBottomHistoryId"] == history["id"]


def test_activation_does_not_immediately_form_even_when_dif_already_turns():
    _, steps = trial([(100, 50, 2), (99, 30, -2), (101, 42, 2), (102, 41, 2)])
    assert not steps[2].events
    assert ordinary(steps[3]) == [("DULL", "activation", "TOP")]
    assert steps[3].point["ordinaryState"] == "DULL"


def test_top_formation_still_requires_positive_dif_and_two_current_bars():
    _, steps = trial([(100, 50, 2), (99, -3, -2), (101, -1, 2), (102, -1, 2)])
    assert not steps[2].events and not steps[3].events
    assert steps[3].point["ordinaryState"] == "NONE"


def test_zero_previous_dif_is_compared_without_zero_histogram_confusion():
    _, steps = trial([(100, -10, -2), (101, -1, 2), (99, 0, -2), (98, 0, -2), (97, .01, -2)])
    assert ordinary(steps[3]) == [("DULL", "activation", "BOTTOM")]
    assert ordinary(steps[4]) == [("STRUCTURE", "dif_turn", "BOTTOM")]
    assert steps[4].point["hist"] == -2


def test_top_return_from_zero_previous_and_equal_reading_remain_distinct():
    _, steps = trial(PREFIX + [(103, 40.99, 2), (103, 40.98, 2), (103, 0, 2), (103, .01, 2)])
    assert ordinary(steps[4]) == [("STRUCTURE", "dif_turn", "TOP")]
    assert not steps[5].events  # 40 -> 40 is not a return
    assert steps[6].point["ordinaryState"] == "STRUCTURE"
    assert ordinary(steps[7]) == [("DULL", "dif_return", "TOP")]
    assert steps[7].histories[0]["endReason"] == "new_top_DULL"


@pytest.mark.parametrize("hist,expected", [
    (-2, [("STRUCTURE", "color_flip", "TOP")]), (0, []),
])
def test_color_flip_and_zero_keep_the_original_r2_policy(hist, expected):
    _, steps = trial(PREFIX + [(101, 41.01, hist)])
    assert ordinary(steps[-1]) == expected
    assert steps[-1].point["ordinaryState"] == "NONE"


@pytest.mark.parametrize("mirrored", [False, True])
def test_raw_reference_break_precedes_return_and_is_not_quantized(mirrored):
    values = PREFIX + [(103, 40.99, 2), (104, 50.001, 2)]
    if mirrored:
        values = [(200-c, -d, -h) for c, d, h in values]
    _, steps = trial(values)
    assert ordinary(steps[-1]) == [("CANCEL", "dif_break", "BOTTOM" if mirrored else "TOP")]
    assert steps[-1].point["ordinaryState"] == "NONE"
    assert steps[-1].point["activeReference"] is None


@pytest.mark.parametrize("last_values,expected_dif", [
    ([(121, 30, 2), (122, 31, 2)], 40),
    ([(121, 40, 2), (122, 40, 2)], None),
    ([(109, 10, 2), (119, 10, 2)], None),
])
def test_original_two_reference_pool_and_nearest_price_gate(last_values, expected_dif):
    prefix = [(100, 50, 2), (90, 0, -2), (110, 40, 2), (90, 0, -2), (120, 20, 2), (90, 0, -2)]
    calculator, steps = trial(prefix + last_values)
    assert len(calculator.history[1]) == 2
    if expected_dif is None:
        assert not steps[-1].events and calculator.reference is None
    else:
        assert ordinary(steps[-1]) == [("DULL", "activation", "TOP")]
        assert steps[-1].events[0]["eventReference"]["dif"] == expected_dif
        assert steps[-1].events[0]["eventReference"]["price"] == 110


def test_bottom_reference_rescue_is_inherited_before_raw_break():
    _, steps = trial([(90, -30, -2), (105, -5, 2), (100, -10, -2), (105, -5, 2),
                      (95, -8, -2), (94, -8, -2), (89, -12, -2)])
    assert steps[5].point["activeReference"]["dif"] == -10
    assert not steps[6].events
    assert steps[6].point["ordinaryState"] == "DULL"
    assert steps[6].point["activeReference"]["dif"] == -30


def test_bottom_return_uses_the_original_price_wait_and_reactivation():
    _, steps = trial(BOTTOM_PREFIX + [(97, -40, -2), (101, -41, -2), (99, -42, -2), (96, -41, -2)])
    assert ordinary(steps[4]) == [("STRUCTURE", "dif_turn", "BOTTOM")]
    assert ordinary(steps[5]) == [("STRUCTURE_DISAPPEARED", "dif_return", "BOTTOM")]
    assert steps[5].point["ordinaryState"] == "NONE"
    waiting = steps[5].rearm_records[0]
    assert waiting["status"] == "WAITING" and waiting["nearestPriceGate"] == 100
    assert waiting["structureEventId"] == steps[4].events[0]["id"]
    assert waiting["bottomHistoryId"] == steps[4].bottom_histories[0]["id"]
    assert steps[5].events[0]["relatedBottomHistoryId"] == waiting["bottomHistoryId"]
    assert steps[5].bottom_histories[0]["endReason"] == "structure_disappeared"
    assert ordinary(steps[6]) == [("DULL", "reactivation", "BOTTOM")]
    assert steps[6].rearm_records[0]["status"] == "REACTIVATED"
    assert steps[6].events[0]["relatedRearmId"] == waiting["id"]
    assert ordinary(steps[7]) == [("STRUCTURE", "dif_turn", "BOTTOM")]


def test_bottom_return_keeps_dull_if_current_price_still_qualifies():
    _, steps = trial(BOTTOM_PREFIX + [(97, -40, -2), (96, -41, -2)])
    assert ordinary(steps[5]) == [("DULL", "dif_return", "BOTTOM")]
    assert steps[5].point["ordinaryState"] == "DULL"
    assert not steps[5].rearm_records


@pytest.mark.parametrize("hist,reason", [(2, "color_flip"), (0, "zero")])
def test_wait_ends_on_original_color_or_zero_policy(hist, reason):
    _, steps = trial(BOTTOM_PREFIX + [(97, -40, -2), (101, -41, -2), (99, -41, hist)])
    assert steps[-1].rearm_records[0]["status"] == "SEGMENT_ENDED"
    assert steps[-1].rearm_records[0]["endReason"] == reason
    assert not steps[-1].events


def test_top_history_retains_actual_peak_and_does_not_expire_at_26_bars():
    values = PREFIX + [(103, 40.99, 2)] + [(102, 39, -2)] * 30
    calculator, steps = trial(values)
    original = deepcopy(steps[4])
    assert calculator.pending is not None
    assert calculator.pending["pricePeak"] == 103
    assert calculator.pending["ageBars"] == 30
    assert steps[4] == original
    next_bar = XxmBar("2020-02-05", 104, 39, 40, -2)
    last = calculator.step(next_bar)
    assert [(event["type"], event["route"]) for event in last.events] == [
        ("RESEARCH_HISTORICAL_WITHDRAWAL", "historical_price_break")]
    assert last.histories[0]["endReason"] == "historical_price_break"
    assert last.events[0]["relatedTopHistoryId"] == original.histories[0]["id"]


def test_identity_is_stable_across_input_ranges_and_separate_from_r2():
    first, steps = trial(PREFIX + [(103, 40.99, 2)], identity="range-one")
    second, other = trial(PREFIX + [(103, 40.99, 2)], identity="range-two")
    assert steps == other  # range metadata is not part of algorithm/event identity
    assert first.source_identity != second.source_identity
    assert calculator_source_identity("r2", "range-one") != first.source_identity
    assert first.spec is MAIN_SPEC and MAIN_SPEC.algorithm_version == "xxm-direction-v0.1-r2"
    # Independently apply the documented hash format to a literal event key.
    base_key = "|".join([MAIN_SPEC.algorithm_version, MAIN_SPEC.spec_hash, "000001.SH", "day",
                         "2020-01-04", "DULL", "1", "2020-01-01"])
    base_id = hashlib.sha256(base_key.encode()).hexdigest()[:24]
    expected_id = hashlib.sha256((TRIAL_SPEC.research_hash + "|" + base_id).encode()).hexdigest()[:24]
    assert steps[3].events[0]["id"] == expected_id and expected_id != base_id


def test_rule_hash_excludes_input_dates_paths_and_budgets_but_includes_research_version():
    alternate = replace(TRIAL_SPEC, default_start_date="2025-01-01", default_end_date="2025-06-01",
                        source_path="literal.csv", source_sha256="0" * 64, max_bars=50, timeout_seconds=1)
    assert alternate.research_hash == TRIAL_SPEC.research_hash
    assert replace(TRIAL_SPEC, research_version="independent-literal-v2").research_hash != TRIAL_SPEC.research_hash
    with pytest.raises(FrozenInstanceError):
        TRIAL_SPEC.max_bars = 1


def test_in_memory_resume_keeps_bottom_rearm_identifiers_and_does_not_modify_snapshot():
    values = BOTTOM_PREFIX + [(97, -40, -2), (101, -41, -2), (99, -42, -2), (96, -41, -2)]
    full, expected = trial(values)
    prefix, first = trial(values[:6])
    saved = prefix.snapshot()
    original = deepcopy(saved)
    resumed = TwoDigitTurnCalculator(source_identity="literal-input")
    resumed.restore(saved)
    actual = first + [resumed.step(bar) for bar in bars(values)[6:]]
    assert actual == expected and resumed.snapshot() == full.snapshot()
    assert saved == original
    saved["state"]["pendingRearm"]["status"] = "tampered"
    assert resumed.pending_rearm is None


@pytest.mark.parametrize("case", ["mode", "research", "base", "source", "extra", "bare", "inner", "inner_rearm"])
def test_bad_restore_is_atomic_and_rejects_cross_group_or_inner_tampering(case):
    target, _ = trial(BOTTOM_PREFIX + [(97, -40, -2), (101, -41, -2)])
    before = target.snapshot()
    invalid = deepcopy(before)
    if case == "mode": invalid["mode"] = "r2"
    if case == "research": invalid["researchSpecHash"] = "other"
    if case == "base": invalid["baseSpecHash"] = "other"
    if case == "source": invalid["sourceIdentity"] = "other"
    if case == "extra": invalid["unexpected"] = None
    if case == "bare": invalid = invalid["state"]
    if case == "inner": invalid["state"]["sourceIdentity"] = "other"
    if case == "inner_rearm": invalid["state"]["pendingRearm"]["structureEventId"] = "wrong"
    with pytest.raises(ValueError): target.restore(invalid)
    assert target.snapshot() == before


def test_r2_and_research_cannot_restore_each_others_wrapped_or_unwrapped_state():
    # Only construct r2 for isolation checks; do not run its step beside a trial.
    baseline = XxmCalculator(period="day", source_identity=calculator_source_identity("r2", "literal-input"))
    calculator, _ = trial(PREFIX + [(103, 40.99, 2)])
    before_r2, before_trial = baseline.snapshot(), calculator.snapshot()
    for invalid in (calculator.snapshot(), calculator.snapshot()["state"]):
        with pytest.raises(ValueError): baseline.restore(invalid)
        assert baseline.snapshot() == before_r2
    with pytest.raises(ValueError): calculator.restore(baseline.snapshot())
    assert calculator.snapshot() == before_trial
    other_version = TwoDigitTurnCalculator(source_identity="literal-input", trial_spec=replace(TRIAL_SPEC, research_version="literal-v2"))
    with pytest.raises(ValueError): other_version.restore(before_trial)
    assert other_version.processed == 0


@pytest.mark.parametrize("change", [
    {"completed": False}, {"dif": float("nan")}, {"hist": float("inf")},
    {"close": 0}, {"time": "20200106"}, {"time": "2020-01-04"},
])
def test_invalid_next_bar_is_rejected_before_mutation_and_valid_next_still_works(change):
    calculator, _ = trial(PREFIX)
    before = calculator.snapshot()
    valid = bars(PREFIX + [(103, 40.99, 2)])[-1]
    with pytest.raises(ValueError): calculator.step(replace(valid, **change))
    assert calculator.snapshot() == before
    assert ordinary(calculator.step(valid)) == [("STRUCTURE", "dif_turn", "TOP")]


def test_different_future_cannot_mutate_the_returned_prefix():
    calculator, prefix = trial(PREFIX)
    original = deepcopy(prefix)
    snapshot = calculator.snapshot()
    calculator.step(bars(PREFIX + [(103, 40.99, 2)])[-1])
    alternate = TwoDigitTurnCalculator(source_identity="literal-input")
    alternate.restore(snapshot)
    alternate.step(bars(PREFIX + [(103, 42, 2)])[-1])
    assert prefix == original and snapshot["state"]["state"] == "DULL"


def test_source_baselines_and_copied_step_are_protected(tmp_path):
    assert len(verify_baseline()) == 3
    for relative, _ in TRIAL_SPEC.baseline_sha256:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    verify_baseline(root=tmp_path)
    target = tmp_path / TRIAL_SPEC.baseline_sha256[0][0]
    target.write_bytes(target.read_bytes() + b"\n# deliberate corruption\n")
    with pytest.raises(ValueError, match="Baseline source changed"):
        verify_baseline(root=tmp_path)
    changed = replace(TRIAL_SPEC, baseline_sha256=())
    with pytest.raises(ValueError, match="baseline Spec"):
        verify_baseline(spec=changed)


@pytest.mark.parametrize("old,new", [
    ("wave.price, wave.price_at = bar.close, bar.time", "wave.price, wave.price_at = bar.dif, bar.time"),
    ("del pool[:-self.spec.max_refs]", "del pool[:-3]"),
    ('event_type, route = "STRUCTURE", "color_flip"', 'event_type, route = "DULL", "color_flip"'),
    ("wave.count >= self.spec.min_bars", "wave.count >= 1"),
    ("sign * (wave.dif - ref.dif) > 0", "sign * (wave.dif - ref.dif) >= 0"),
    ("self._advance_rearm(bar)", "self._advance_rearm(self.previous)"),
    ("direction, event_ref = sign, ref", "direction, event_ref = -sign, ref"),
    ('self.state == "DULL" and delta < 0', 'self.state == "DULL" and delta <= 0'),
    ("basis = self.previous.dif", "basis = wave.dif"),
])
def test_ast_guard_rejects_mutations_outside_the_two_approved_predicates(old, new):
    base = inspect.getsource(XxmCalculator.step)
    source = inspect.getsource(TwoDigitTurnCalculator.step)
    assert old in source
    with pytest.raises(ValueError): validate_step_copy(base, source.replace(old, new, 1))
    validate_step_copy(base, source)


@pytest.mark.parametrize("mode,identity", [("other", "input"), ("r2", ""), ("two_digit", None)])
def test_invalid_source_identity_is_rejected(mode, identity):
    with pytest.raises(ValueError): calculator_source_identity(mode, identity)


@pytest.mark.parametrize("kwargs", [{"period": "m90"}, {"ts_code": "399001.SZ"}])
def test_trial_does_not_expand_product_scope(kwargs):
    with pytest.raises(ValueError): TwoDigitTurnCalculator(source_identity="literal-input", **kwargs)
