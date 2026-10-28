"""LLD 12.2: literal decisions plus real-method delegation checks."""
from copy import deepcopy
from datetime import date, timedelta

import pytest

from scripts.research.index_market.xxm.r4_observation import ObservedR2Calculator, ObservedR4Calculator
from scripts.research.index_market.xxm.r4_reference_trial import R4Calculator
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


SOURCE = "observation-literal-unit"
TOP = [(100, 50, 2), (90, 0, -2), (101, 40, 2), (102, 41, 2)]
BOTTOM = [(100, -10, -2), (99, -11, -2), (105, -5, 2),
          (98, -9, -2), (97, -9.2, -2), (98, -8.8, -2)]


def stamp(index):
    return (date(2023, 1, 1) + timedelta(days=index - 1)).isoformat()


def bar(index, values):
    close, dif, hist = values
    return XxmBar(stamp(index), close, dif, dif - hist / 2, hist)


def run(kind, values):
    calc = kind(period="day", source_identity=SOURCE)
    steps, decisions = [], []
    for i, value in enumerate(values, 1):
        steps.append(calc.step(bar(i, value)))
        decisions.append(calc.last_decision)
    return calc, steps, decisions


@pytest.mark.parametrize("kind,parent", [(ObservedR2Calculator, XxmCalculator),
                                         (ObservedR4Calculator, R4Calculator)])
def test_real_parent_step_and_selector_are_called_exactly_once(kind, parent, monkeypatch):
    calls = {"step": 0, "select": 0}
    original_step, original_select = parent.step, parent._select_eligible_reference
    def step(self, value):
        calls["step"] += 1
        return original_step(self, value)
    def select(self, wave, history):
        calls["select"] += 1
        return original_select(self, wave, history)
    monkeypatch.setattr(parent, "step", step)
    monkeypatch.setattr(parent, "_select_eligible_reference", select)
    calc, steps, decisions = run(kind, TOP)
    assert calls == {"step": 4, "select": 1}
    assert [(e["type"], e["route"]) for e in steps[-1].events] == [("DULL", "activation")]
    assert calc.state == "DULL" and calc.wave.count == 2
    assert decisions[-1]["selectedReference"] == {
        "reference": {"startTime": stamp(1), "endTime": stamp(1), "price": 100, "dif": 50},
        "startedAt": stamp(4), "action": "activation", "rearmId": None}


@pytest.mark.parametrize("kind,order,selected", [
    (ObservedR2Calculator, ["A", "B"], 1), (ObservedR4Calculator, ["B", "A"], 4)])
def test_actual_priority_and_short_circuit_are_not_relabelled(kind, order, selected):
    values = [(110, 29, 2), (120, 30, 2), (100, 10, -2),
              (115, 19, 2), (120, 20, 2), (110, 10, -2), (130, 14, 2), (131, 15, 2)]
    calc, steps, decisions = run(kind, values)
    assert [(e["type"], e["route"]) for e in steps[-1].events] == [("DULL", "activation")]
    decision = decisions[-1]
    checks = decision["referenceChecks"]
    assert checks[0]["stage"] == "nearest_price_gate" and checks[0]["pricePassed"] is True
    assert [c["candidate"] for c in checks[1:]] == order
    assert (checks[1]["checked"], checks[1]["pricePassed"], checks[1]["difPassed"]) == (True, True, True)
    assert (checks[2]["checked"], checks[2]["pricePassed"], checks[2]["difPassed"]) == (False, None, None)
    assert calc.reference.start == stamp(selected)
    assert decision["turn"]["checked"] is False and decision["turn"]["referenceBroken"] is None
    assert decision["selectedReference"]["startedAt"] == stamp(8)
    calc.step(bar(9, (132, 15, 2)))
    later = calc.last_decision
    assert later["selectedReference"]["startedAt"] == stamp(8)
    assert later["selectedReference"]["action"] == "retained"
    assert all(c["checked"] is False and c["pricePassed"] is None and c["difPassed"] is None
               for c in later["referenceChecks"])


@pytest.mark.parametrize("kind", [ObservedR2Calculator, ObservedR4Calculator])
def test_failed_nearest_gate_does_not_claim_full_candidate_checks(kind):
    values = [(110, 29, 2), (120, 30, 2), (100, 10, -2),
              (115, 19, 2), (120, 20, 2), (110, 10, -2), (118, 14, 2), (119, 15, 2)]
    calc, steps, decisions = run(kind, values)
    assert not steps[-1].events and calc.state == "NONE"
    checks = decisions[-1]["referenceChecks"]
    assert (checks[0]["checked"], checks[0]["pricePassed"], checks[0]["difPassed"]) == (True, False, None)
    # A has DIF30 and B has DIF20. The failed B-price gate returns before
    # r2's strongest-DIF sort, so both groups retain the natural B,A order.
    assert [c["candidate"] for c in checks] == ["B", "B", "A"]
    assert [c["wave"]["dif"] for c in checks[1:]] == [20, 30]
    assert all((c["checked"], c["pricePassed"], c["difPassed"]) == (False, None, None) for c in checks[1:])


def test_price_failure_leaves_dif_unknown_and_no_a_is_invented():
    values = [(125, 29, 2), (130, 30, 2), (100, 10, -2),
              (115, 19, 2), (120, 20, 2), (110, 10, -2), (124, 24, 2), (125, 25, 2)]
    calc, steps, decisions = run(ObservedR4Calculator, values)
    assert not steps[-1].events and calc.reference is None
    checks = decisions[-1]["referenceChecks"]
    assert [(c["candidate"], c["pricePassed"], c["difPassed"]) for c in checks] == [
        ("B", True, None), ("B", True, False), ("A", False, None)]
    _, _, only_b = run(ObservedR4Calculator, TOP)
    assert all(c["candidate"] == "B" for c in only_b[-1]["referenceChecks"])
    assert only_b[2]["referenceChecks"][0]["checked"] is False
    assert only_b[2]["referenceChecks"][0]["difPassed"] is None


@pytest.mark.parametrize("kind", [ObservedR2Calculator, ObservedR4Calculator])
def test_true_flip_keeps_old_event_reference_but_not_new_active_reference(kind):
    _, steps, decisions = run(kind, TOP + [(102, 40, -2)])
    decision = decisions[-1]
    assert [(e["type"], e["route"], e["direction"]) for e in steps[-1].events] == [
        ("STRUCTURE", "color_flip", "TOP")]
    assert decision["before"]["reference"]["dif"] == 50
    assert steps[-1].events[0]["eventReference"]["dif"] == 50
    assert decision["selectedReference"] is None and steps[-1].point["ordinaryState"] == "NONE"
    assert decision["wave"]["sign"] == -1
    assert decision["turn"]["referenceBroken"] is False and decision["turn"]["checked"] is False


@pytest.mark.parametrize("kind", [ObservedR2Calculator, ObservedR4Calculator])
def test_real_reference_break_prevents_turn_check(kind):
    _, steps, decisions = run(kind, TOP + [(103, 51, 2)])
    assert [(e["type"], e["route"]) for e in steps[-1].events] == [("CANCEL", "dif_break")]
    turn = decisions[-1]["turn"]
    assert turn["referenceBroken"] is True and turn["checked"] is False
    assert decisions[-1]["selectedReference"] is None


@pytest.mark.parametrize("kind,state,checked,broken", [
    (ObservedR2Calculator, "NONE", False, None), (ObservedR4Calculator, "STRUCTURE", True, False)])
def test_zero_observation_preserves_each_actual_policy(kind, state, checked, broken):
    _, steps, decisions = run(kind, TOP + [(102, 40, 0)])
    d = decisions[-1]
    assert steps[-1].point["ordinaryState"] == state and d["rawSign"] == 0
    assert d["turn"]["checked"] is checked and d["turn"]["referenceBroken"] is broken
    assert d["turn"]["previousDif"] == 41 and d["turn"]["currentDif"] == 40
    assert d["turn"]["threshold"] == .41


def test_leading_zero_is_not_a_selection_or_turn_check():
    calc, steps, decisions = run(ObservedR4Calculator, [(100, 0, 0), (101, 0, 0)])
    assert all(not s.events for s in steps)
    assert decisions[-1]["wave"] is None and decisions[-1]["branch"] == "leading_zero"
    assert decisions[-1]["referenceChecks"] == [] and decisions[-1]["selectedReference"] is None
    assert decisions[-1]["turn"]["checked"] is False
    assert calc.processed == 2


def test_previous_zero_uses_actual_protected_branch_not_a_fake_turn():
    values = [(100, -10, -2), (110, 1, 2), (99, -1, -2), (98, 0, -2), (97, .1, -2)]
    _, steps, decisions = run(ObservedR4Calculator, values)
    assert steps[-2].events[0]["type"] == "DULL" and not steps[-1].events
    assert decisions[-1]["turn"]["checked"] is True
    assert decisions[-1]["turn"]["previousDif"] == 0
    assert decisions[-1]["turn"]["threshold"] == 0
    assert "为0" in decisions[-1]["turn"]["reason"]


def test_rescue_without_new_event_records_actual_call_and_post_rescue_break_check():
    values = [(110, -20, -2), (120, 0, 2), (100, -10, -2), (115, 0, 2),
              (90, -8, -2), (89, -9, -2), (88, -12, -2)]
    calc, steps, decisions = run(ObservedR4Calculator, values)
    assert steps[-2].events[0]["eventReference"]["startTime"] == stamp(3)
    assert not steps[-1].events and calc.state == "DULL"
    d = decisions[-1]
    assert d["before"]["reference"]["dif"] == -10
    assert [c["stage"] for c in d["referenceChecks"]] == [
        "nearest_price_gate", "bottom_rescue", "bottom_rescue"]
    assert [(c["candidate"], c["difPassed"]) for c in d["referenceChecks"][1:]] == [("B", False), ("A", True)]
    assert d["selectedReference"]["reference"]["dif"] == -20
    assert d["selectedReference"]["action"] == "rescue" and d["selectedReference"]["startedAt"] == stamp(7)
    assert d["turn"]["referenceBroken"] is False and d["turn"]["checked"] is True


def test_waiting_and_reactivation_reuse_saved_reference_and_rearm_relation():
    values = BOTTOM + [(100, -9, 0), (100, -9.1, 0), (98.5, -9.2, 0), (98, -9.1, 0)]
    _, steps, decisions = run(ObservedR4Calculator, values)
    assert [(e["type"], e["route"]) for e in steps[6].events] == [("STRUCTURE_DISAPPEARED", "dif_return")]
    assert decisions[7]["branch"] == "waiting" and decisions[7]["turn"]["checked"] is False
    assert decisions[7]["turn"]["referenceBroken"] is False
    assert all(not c["checked"] and c["pricePassed"] is None for c in decisions[7]["referenceChecks"])
    selected = decisions[8]["selectedReference"]
    assert selected["action"] == "reactivation" and selected["startedAt"] == stamp(9)
    assert selected["reference"]["startTime"] == stamp(1)
    assert selected["rearmId"] == steps[8].events[0]["relatedRearmId"]
    assert decisions[8]["turn"]["checked"] is False
    assert decisions[8]["turn"]["referenceBroken"] is False
    assert decisions[9]["selectedReference"]["action"] == "retained"
    assert decisions[9]["selectedReference"]["rearmId"] == selected["rearmId"]
    assert decisions[9]["selectedReference"]["startedAt"] == stamp(9)


@pytest.mark.parametrize("last,status,broken", [
    ((98, -12, 0), "INVALIDATED", True), ((101, -12, 2), "SEGMENT_ENDED", None)])
def test_waiting_break_is_only_recorded_if_the_saved_reference_was_checked(last, status, broken):
    _, steps, decisions = run(ObservedR4Calculator, BOTTOM + [(100, -9, 0), last])
    assert steps[-1].rearm_records[0]["status"] == status
    assert decisions[-1]["turn"]["checked"] is False
    assert decisions[-1]["turn"]["referenceBroken"] is broken


@pytest.mark.parametrize("kind,parent", [(ObservedR2Calculator, XxmCalculator),
                                         (ObservedR4Calculator, R4Calculator)])
def test_observation_copies_do_not_mutate_parent_or_previously_returned_facts(kind, parent):
    calc, observed, decisions = run(kind, TOP + [(102, 40, 2)])
    # Additional equivalence check; literal business assertions above remain
    # independent of the direct parent's output.
    bare = parent(period="day", source_identity=SOURCE)
    actual = [bare.step(bar(i, v)) for i, v in enumerate(TOP + [(102, 40, 2)], 1)]
    assert observed == actual and calc.snapshot() == bare.snapshot()
    before = calc.snapshot()
    prior = deepcopy(decisions[3])
    calc.last_decision["before"]["wave"]["price"] = -999
    calc.last_decision["referenceChecks"][0]["wave"]["price"] = -999
    assert calc.snapshot() == before and decisions[3] == prior
    old_decision = deepcopy(calc.last_decision)
    with pytest.raises(ValueError):
        calc.step(XxmBar(stamp(6), True, 40, 39, 2))
    assert calc.snapshot() == before and calc.last_decision == old_decision


def test_observed_selector_returns_the_same_real_parent_object(monkeypatch):
    calc = ObservedR4Calculator(period="day", source_identity=SOURCE)
    # Record actual object identity without substituting detector decisions.
    returned = []
    original = R4Calculator._select_eligible_reference
    def select(self, wave, history):
        value = original(self, wave, history)
        returned.append(value)
        return value
    monkeypatch.setattr(R4Calculator, "_select_eligible_reference", select)
    for i, value in enumerate(TOP, 1):
        calc.step(bar(i, value))
    assert len(returned) == 1
    chosen = calc._select_eligible_reference(calc.wave, calc.history[1])
    assert chosen is returned[-1] and chosen is calc.history[1][-1]
