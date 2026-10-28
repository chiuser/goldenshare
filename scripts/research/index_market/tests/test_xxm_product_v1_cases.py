"""P1 material checks only; this suite does NOT execute r4 or compare r2.

The future calculator/forecast assertions are P2/P3 acceptance work.  These
checks keep the supplied literal inputs, expected links and hand arithmetic
usable without importing a current or proposed product implementation.
"""
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path

import pytest

from scripts.research.index_market.tests.xxm_product_v1_cases import (
    CASES, DATES, FORECAST_MATH, PERIODS,
)


BY_NAME = {case.name: case for case in CASES}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_literal_case_is_complete_and_has_explicit_source_values(case):
    assert case.why and case.rules
    assert set(case.rules) <= {"R05", "R06", "R07", "R08", "R09", "R10"}
    assert 1 <= len(case.values) <= len(DATES)
    for close, dif, dea, hist in case.values:
        assert all(type(value) in (float, int) for value in (close, dif, dea, hist))
        assert close > 0
        # Source values are four literals, not DEA derived by a fixture helper.
        assert Decimal(str(hist)) == 2 * (Decimal(str(dif)) - Decimal(str(dea)))
    assert case.checks
    assert len({c.at for c in case.checks}) == len(case.checks)
    assert list(c.at for c in case.checks) == sorted(c.at for c in case.checks)
    refs = {r.name: r for r in case.references}
    assert len(refs) == len(case.references)
    for ref in refs.values():
        assert 1 <= ref.start <= ref.end <= len(case.values)
        assert ref.price > 0
    for check in case.checks:
        assert 1 <= check.at <= len(case.values)
        assert check.state in {"NONE", "DULL", "STRUCTURE"}
        assert (check.direction is None) == (check.state == "NONE")
        assert check.reference is None or check.reference in refs
        assert (check.reference is None) == (check.state == "NONE")
        for kind, route, direction, reference in check.events:
            assert kind in {"DULL", "STRUCTURE", "CANCEL", "STRUCTURE_DISAPPEARED",
                            "RESEARCH_HISTORICAL_WITHDRAWAL"}
            assert route in {"activation", "reactivation", "dif_turn", "dif_return", "color_flip",
                             "dif_break", "dif_break_on_flip", "historical_price_break"}
            assert direction in {"TOP", "BOTTOM"}
            assert reference in refs
        assert len(dict(check.facts)) == len(check.facts)


@pytest.mark.parametrize("period", PERIODS)
def test_four_period_inputs_only_change_time_format(period):
    assert len(set(DATES)) == len(DATES)
    assert all(date.fromisoformat(t).isoformat() == t for t in DATES)
    for case in CASES:
        values = case.inputs(period)
        assert len(values) == len(case.values)
        assert [v["time"] for v in values] == sorted(v["time"] for v in values)
        for index, item in enumerate(values):
            assert item["completed"] is True
            assert set(item) == {"time", "close", "dif", "dea", "hist", "completed"}
            assert (item["close"], item["dif"], item["dea"], item["hist"]) == case.values[index]
            if period == "day":
                assert item["time"] == DATES[index]
            else:
                assert item["time"] == DATES[index] + "T15:00:00+08:00"
                assert datetime.fromisoformat(item["time"]).utcoffset().total_seconds() == 28800
    with pytest.raises(ValueError):
        CASES[0].inputs("m30")


def test_records_are_immutable_and_no_generated_product_identity_is_present():
    assert len(BY_NAME) == len(CASES) == 37
    with pytest.raises(FrozenInstanceError):
        CASES[0].name = "other"
    with pytest.raises(FrozenInstanceError):
        CASES[0].checks[0].state = "DULL"
    with pytest.raises(FrozenInstanceError):
        BY_NAME["nearest_before_stronger_far"].references[0].dif = 999
    assert not hasattr(CASES[0], "spec_hash")
    assert not hasattr(CASES[0], "event_id")


def test_reference_choices_are_independent_literal_expectations():
    nearest = BY_NAME["nearest_before_stronger_far"]
    assert nearest.references[0].dif == 30 and nearest.references[1].dif == 20
    assert nearest.checks[-1].reference == "B"
    assert nearest.checks[-1].events == (("DULL", "activation", "TOP", "B"),)
    farther = BY_NAME["far_only_after_near_fails"]
    assert 26 > 20 and 26 < 30 and 132 > 130
    assert farther.checks[-1].reference == "A"
    for name in ("near_price_gate_blocks_far", "first_price_equality_rejected",
                 "first_dif_equality_rejected", "third_candidate_not_searched"):
        assert BY_NAME[name].checks[-1].state == "NONE"
        assert BY_NAME[name].checks[-1].events == ()
    assert dict(BY_NAME["third_candidate_not_searched"].checks[-1].facts)["pool_starts"] == (3, 5)


def test_missing_reference_one_bar_true_flip_and_price_fall_are_separate_counterexamples():
    no_reference = BY_NAME["no_completed_same_color_reference"]
    assert no_reference.references == ()
    assert dict(no_reference.checks[0].facts)["count"] == 2
    assert no_reference.checks[0].events == ()
    one_bar = BY_NAME["one_nonzero_colored_bar_is_insufficient"]
    assert one_bar.values[-1] == (101, 40, 39, 2)
    assert 101 > 100 and 40 < 50
    assert dict(one_bar.checks[0].facts)["count"] == 1
    assert one_bar.checks[0].events == ()
    flip = BY_NAME["true_flip_never_rescues_with_eligible_a"]
    assert flip.values[-1][-1] == -2
    assert 132 > 100 and 26.754 < 41.186  # A qualifies on its own.
    assert 26.754 > 24.935  # B is strictly broken.
    assert flip.checks[-1].events == (("CANCEL", "dif_break_on_flip", "TOP", "B"),)
    falling = BY_NAME["price_fall_alone_does_not_cancel_existing_dull"]
    assert falling.values[-1] == (99, 41, 40, 2)
    assert 99 < falling.references[0].price
    assert falling.checks[-1].state == "DULL" and falling.checks[-1].reference == "B"
    assert falling.checks[-1].events == ()


def test_same_bar_switch_and_late_far_keep_different_event_histories():
    same = BY_NAME["same_bar_near_to_far_switch"]
    assert same.checks[0].at == 6 and same.checks[0].reference == "B"
    assert same.checks[1].at == 7 and same.checks[1].reference == "A"
    assert same.checks[1].events == ()
    assert dict(same.checks[1].facts)["original_event@6.reference"] == "B"
    assert same.checks[-1].events == (("STRUCTURE", "dif_turn", "TOP", "A"),)
    late = BY_NAME["far_qualifies_only_next_bar"]
    assert late.checks[0].at == 7
    assert late.checks[0].events == (("CANCEL", "dif_break", "TOP", "B"),)
    assert late.checks[1].at == 8
    assert late.checks[1].events == (("DULL", "activation", "TOP", "A"),)
    assert dict(late.checks[1].facts)["preserve_event@7"] is True
    assert BY_NAME["structure_does_not_use_dull_switch"].checks[-1].state == "NONE"


def test_zero_cases_distinguish_count_first_entry_and_real_flip():
    insufficient = BY_NAME["zero_does_not_supply_second_colored_bar"]
    assert insufficient.checks[0].events == ()
    assert dict(insufficient.checks[0].facts)["count"] == 1
    permitted = BY_NAME["zero_day_first_activation"]
    assert permitted.values[-1][-1] == 0
    assert permitted.checks[-1].events == (("DULL", "activation", "TOP", "B"),)
    assert dict(permitted.checks[-1].facts)["count"] == 2
    flip = BY_NAME["true_flip_confirms_without_one_percent"]
    assert flip.checks[-1].state == "NONE"
    assert flip.checks[-1].events == (("STRUCTURE", "color_flip", "TOP", "B"),)
    assert dict(flip.checks[-1].facts)["top_history.price"] == 102
    assert flip.values[-1][0] == 999


def test_waiting_links_and_current_close_threshold_are_literal():
    started = BY_NAME["bottom_current_close_starts_waiting"].checks[-1]
    assert started.events == (("STRUCTURE_DISAPPEARED", "dif_return", "BOTTOM", "B"),)
    facts = dict(started.facts)
    assert facts["wait.nearest_price"] == 99
    assert facts["wait.structure_event"] == "event@6"
    assert facts["wait.disappeared_event"] == "event@7"
    resumed = BY_NAME["zero_day_bottom_reactivation"].checks[-1]
    assert resumed.events == (("DULL", "reactivation", "BOTTOM", "B"),)
    facts = dict(resumed.facts)
    assert facts["wait.structure_event"] == "event@6"
    assert facts["event@8.related_wait"] == "wait@7"
    assert facts["event@8.related_bottom_history"] is None
    assert 98.5 < 99
    assert dict(BY_NAME["waiting_price_equality_not_reactivated"].checks[-1].facts)["wait.status"] == "WAITING"
    assert dict(BY_NAME["waiting_reference_break_invalidates"].checks[-1].facts)["wait.status"] == "INVALIDATED"
    assert dict(BY_NAME["waiting_true_red_ends_segment"].checks[-1].facts)["wait.end_reason"] == "color_flip"


def test_adjacent_one_percent_and_zero_basis_have_hand_checked_expectations():
    assert F(100) - F(99) == abs(F(100)) / 100
    assert F(100) - F("99.1") < abs(F(100)) / 100
    assert BY_NAME["exact_one_percent_zero_target"].checks[-1].state == "STRUCTURE"
    assert BY_NAME["less_than_one_percent_remains_dull"].checks[-1].state == "DULL"
    previous_zero = BY_NAME["previous_zero_dif_is_not_skipped"]
    assert previous_zero.values[-2][1] == 0
    assert previous_zero.checks[-1].events == ()
    assert previous_zero.checks[-1].state == "STRUCTURE"
    assert F("40.35") - F("39.9") >= abs(F("39.9")) / 100
    assert F("40.35") - F(40) < abs(F(40)) / 100


def test_fraction_projection_is_independent_and_uses_one_percent_only():
    m = FORECAST_MATH
    assert m["first_dif_p"] == F(2, 13) - F(2, 27)
    assert m["first_dif_b"] == F(102 * 11, 13) - F(100 * 25, 27)
    assert -m["first_dif_b"] / m["first_dif_p"] == m["entry_lower"]
    assert (10 - m["first_dif_b"]) / m["first_dif_p"] == m["entry_upper"]
    assert m["entry_lower_inclusive"] is False and m["entry_upper_inclusive"] is False
    assert m["first_dif_p"] * m["P"] + m["first_dif_b"] == m["D1"] == F(22, 13)
    assert F(4, 5) * m["dea"] + F(1, 5) * m["D1"] == m["DEA1"] == F(-82, 65)
    assert m["D1"] - m["DEA1"] == m["D1_minus_D2_at_zero"] == F(192, 65)
    assert m["one_percent"] == F(22, 1300)
    assert m["D1_minus_D2_at_zero"] > m["one_percent"]


def test_entry_interval_has_explicit_full_state_premises_not_only_a_dif_subcondition():
    m = FORECAST_MATH
    context = m["entry_context"]
    assert context == {
        "direction": "TOP", "state": "NONE", "colored_count": 1,
        "current_close": 100, "wave_price": 100, "wave_dif": 2,
        "current_dea": -2, "current_hist": 8,
        "nearest_reference": {"price": 70, "dif": 10}, "far_reference": None,
        "next_colored_count": 2, "precision": "full_float",
    }
    assert m["e12"] - m["e26"] == context["wave_dif"]
    assert 2 * (context["wave_dif"] - context["current_dea"]) == context["current_hist"]
    assert context["wave_price"] > context["nearest_reference"]["price"]
    assert context["wave_dif"] < context["nearest_reference"]["dif"]
    assert m["entry_lower"] > context["nearest_reference"]["price"]
    # Throughout 0<D1<10: hist1=8/5*(D1+2)>0, so count becomes two;
    # max(previous wave DIF2, D1)<10 and price gate is already satisfied.
    assert F(8, 5) * (F(0) + 2) > 0
    assert context["colored_count"] + 1 == context["next_colored_count"] == 2
    assert context["wave_dif"] < 10 and context["far_reference"] is None


def test_zero_target_inclusion_does_not_include_zero_price_or_real_flip_equality():
    m = FORECAST_MATH
    ap, k, b = m["second_dif_p"], m["second_dif_c"], m["second_dif_b"]
    zero, turn = m["zero_target_C_at_P100"], m["turn_target_C_at_P100"]
    assert ap * 100 + k * zero + b == m["DEA1"]
    assert ap * 100 + k * turn + b == m["D1"] * F(99, 100)
    assert zero > 0 and turn > zero
    assert m["zero_target_lower_inclusive"] is True
    assert m["color_flip_upper_inclusive"] is False
    assert m["positive_close_lower"] == 0
    assert m["positive_close_lower_inclusive"] is False
    # The two immediate sides of the zero-histogram boundary have opposite
    # signs under exact Fraction recurrence.  At equality hist is exactly 0.
    for c, expected_sign in ((zero - F(1, 100), -1), (zero, 0), (zero + F(1, 100), 1)):
        d2 = ap * 100 + k * c + b
        a2 = F(4, 5) * m["DEA1"] + F(1, 5) * d2
        hist = 2 * (d2 - a2)
        assert (hist > 0) - (hist < 0) == expected_sign
        assert m["D1"] - d2 > m["one_percent"]
    for c, state, route in m["literal_outcomes"]:
        d2 = ap * 100 + k * c + b
        hist = F(8, 5) * (d2 - m["DEA1"])
        if c == 40:
            assert hist < 0 and (state, route) == ("STRUCTURE", "color_flip")
        elif c == 100:
            assert hist > 0 and m["D1"] - d2 >= m["one_percent"]
            assert (state, route) == ("STRUCTURE", "dif_turn")
        else:
            assert c == 110 and hist > 0 and d2 - m["D1"] > 0
            assert (state, route) == ("DULL", None)


def test_source_rounding_tie_is_unresolved_not_a_deterministic_first_entry():
    m = FORECAST_MATH
    assert m["daily_tie_raw_dif"] == F(1, 2000)
    assert m["daily_tie_options"] == (F(0), F(1, 1000))
    assert min(m["daily_tie_options"]) == 0 < max(m["daily_tie_options"])
    assert m["daily_tie_result"] == "PRECISION_UNRESOLVED"


def test_sample_module_has_no_runtime_algorithm_or_io_dependency():
    path = Path(__file__).with_name("xxm_product_v1_cases.py")
    tree = ast.parse(path.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert set(imports) == {"__future__", "dataclasses", "fractions"}
    forbidden_calls = {"open", "read_text", "write_text", "connect", "step", "solve", "exec", "eval"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            assert name not in forbidden_calls
