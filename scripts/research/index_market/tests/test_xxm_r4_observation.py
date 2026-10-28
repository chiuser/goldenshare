"""P2/LLD section 7: independent literals against the unique formal r4.

These are artificial completed bars, not market/API or forecast acceptance.
No old calculator, temporary migration helper or result file is used.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from scripts.research.index_market.tests.xxm_product_v1_cases import CASES, PERIODS
from scripts.research.index_market.xxm import history_disappearance_screen as observation
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
    # Independent artificial DEA, not a source fallback or production MACD.
    return XxmBar(stamp(index), close, dif, dif - hist / 2, hist)


def run(values, enabled=True):
    calc = XxmCalculator(period="day", source_identity=SOURCE, record_decisions=enabled)
    steps = [calc.step(bar(i, value)) for i, value in enumerate(values, 1)]
    return calc, steps, [step.decision for step in steps]


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_all_p1_points_and_events_are_literal_and_recording_does_not_change_business(case, period):
    plain = XxmCalculator(period=period, source_identity=case.name)
    observed = XxmCalculator(period=period, source_identity=case.name, record_decisions=True)
    values = [XxmBar(**item) for item in case.inputs(period)]
    normal = [plain.step(item) for item in values]
    traced = [observed.step(item) for item in values]
    assert [replace(item, decision=None) for item in traced] == normal
    assert all(item.decision is None for item in normal)
    assert all(item.decision is not None for item in traced)
    assert observed.snapshot() == plain.snapshot()
    for check in case.checks:
        current = traced[check.at - 1]
        refs = {ref.name: {"startTime": values[ref.start - 1].time, "endTime": values[ref.end - 1].time,
                           "price": ref.price, "dif": ref.dif} for ref in case.references}
        assert current.point["ordinaryState"] == check.state
        assert current.point["ordinaryDirection"] == check.direction
        assert current.point["activeReference"] == refs.get(check.reference)
        assert [(event["type"], event["route"], event["direction"], event["eventReference"])
                for event in current.events] == [(kind, route, direction, refs.get(ref))
                                                for kind, route, direction, ref in check.events]


def test_real_selection_is_called_once_and_does_not_check_a_after_b_passes(monkeypatch):
    calls = []
    original = XxmCalculator._select_eligible_reference
    def select(self, wave, history):
        calls.append(wave.end)
        return original(self, wave, history)
    monkeypatch.setattr(XxmCalculator, "_select_eligible_reference", select)
    values = [(110, 29, 2), (120, 30, 2), (100, 10, -2),
              (115, 19, 2), (120, 20, 2), (110, 10, -2), (130, 14, 2), (131, 15, 2)]
    calc, steps, decisions = run(values)
    assert calls == [stamp(5), stamp(8)]  # One actual selection in each eligible segment.
    assert calc.reference.start == stamp(4)
    d = decisions[-1]
    assert len(d["selectionCalls"]) == 1
    assert d["selectionCalls"][0]["stage"] == "activation"
    assert d["selectionCalls"][0]["selected"] == steps[-1].point["activeReference"]
    assert [c["candidate"] for c in d["referenceChecks"]] == ["B", "B", "A"]
    assert [(c["checked"], c["pricePassed"], c["difPassed"]) for c in d["referenceChecks"]] == [
        (True, True, None), (True, True, True), (False, None, None)]
    assert d["turn"]["checked"] is False
    retained = calc.step(bar(9, (132, 15, 2))).decision
    assert retained["selectionCalls"] == []
    assert all(c["stage"] == "not_entered" and not c["checked"] and c["difPassed"] is None
               for c in retained["referenceChecks"])


def test_b_gate_failure_has_only_real_b_check_and_unchecked_a():
    values = [(110, 29, 2), (120, 30, 2), (100, 10, -2),
              (115, 19, 2), (120, 20, 2), (110, 10, -2), (118, 14, 2), (119, 15, 2)]
    calc, steps, decisions = run(values)
    assert calc.reference is None and not steps[-1].events
    checks = decisions[-1]["referenceChecks"]
    assert [(c["candidate"], c["checked"], c["pricePassed"], c["difPassed"]) for c in checks] == [
        ("B", True, False, None), ("A", False, None, None)]


def test_a_price_failure_does_not_invent_a_dif_check():
    values = [(125, 29, 2), (130, 30, 2), (100, 10, -2),
              (115, 19, 2), (120, 20, 2), (110, 10, -2), (124, 24, 2), (125, 25, 2)]
    _, steps, decisions = run(values)
    assert not steps[-1].events
    assert [(c["candidate"], c["pricePassed"], c["difPassed"]) for c in decisions[-1]["referenceChecks"]] == [
        ("B", True, None), ("B", True, False), ("A", False, None)]


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("switch_hist", [2, 0])
def test_same_bar_switch_keeps_original_event_and_observes_real_before_after(sign, switch_hist, monkeypatch):
    source = [(100, 41.186, 2), (90, 0, -2), (120, 24.935, 2), (90, 0, -2),
              (130, 17.649, 2), (131, 17.649, 2), (132, 26.754, switch_hist)]
    values = source if sign == 1 else [(300-c, -d, -h) for c, d, h in source]
    calls = []
    actual = XxmCalculator._select_eligible_reference
    def select(self, wave, history):
        calls.append(wave.end)
        return actual(self, wave, history)
    monkeypatch.setattr(XxmCalculator, "_select_eligible_reference", select)
    calc, steps, decisions = run(values)
    d = decisions[-1]
    assert calls.count(stamp(7)) == 1
    assert steps[-2].events[0]["eventReference"]["dif"] == sign * 24.935
    assert not steps[-1].events and calc.state == "DULL"
    assert d["before"]["reference"]["dif"] == sign * 24.935
    assert d["referenceAfter"]["dif"] == sign * 41.186 and d["switched"] is True
    assert [c["stage"] for c in d["referenceChecks"]] == ["nearest_price_gate", "same_bar_rescue", "same_bar_rescue"]
    assert d["selectionCalls"][0]["stage"] == "same_bar_rescue"
    assert d["turn"]["checked"] is True and d["turn"]["referenceBroken"] is False
    assert steps[-2].events[0]["eventReference"]["dif"] == sign * 24.935


def test_flip_break_zero_and_zero_basis_are_observed_without_rechecking():
    _, steps, decisions = run(TOP + [(102, 40, -2)])
    assert [(e["type"], e["route"]) for e in steps[-1].events] == [("STRUCTURE", "color_flip")]
    assert decisions[-1]["before"]["reference"]["dif"] == 50
    assert decisions[-1]["referenceAfter"] is None
    assert decisions[-1]["turn"]["checked"] is False
    _, steps, decisions = run(TOP + [(103, 51, 2)])
    assert steps[-1].events[0]["type"] == "CANCEL"
    assert decisions[-1]["turn"]["referenceBroken"] is True and not decisions[-1]["turn"]["checked"]
    _, steps, decisions = run(TOP + [(102, 40, 0)])
    assert steps[-1].events[0]["route"] == "dif_turn"
    assert decisions[-1]["turn"]["threshold"] == .41 and decisions[-1]["rawSign"] == 0
    values = [(100, -10, -2), (110, 1, 2), (99, -1, -2), (98, 0, -2), (97, .1, -2)]
    _, steps, decisions = run(values)
    assert not steps[-1].events and decisions[-1]["turn"]["checked"]
    assert decisions[-1]["turn"]["threshold"] == 0 and "为0" in decisions[-1]["turn"]["reason"]
    _, steps, decisions = run([(100, 0, 0), (101, 0, 0)])
    assert decisions[-1]["branch"] == "leading_zero" and decisions[-1]["wave"] is None
    assert not steps[-1].events and decisions[-1]["referenceChecks"] == []


def test_waiting_reactivation_and_invalidated_reference_use_actual_records():
    values = BOTTOM + [(100, -9, 0), (100, -9.1, 0), (98.5, -9.2, 0)]
    _, steps, decisions = run(values)
    assert decisions[7]["branch"] == "waiting" and decisions[7]["rearm"]["status"] == "WAITING"
    assert decisions[7]["rearm"]["blocked"] and not decisions[7]["turn"]["checked"]
    assert steps[8].events[0]["route"] == "reactivation"
    assert decisions[8]["referenceAfter"]["dif"] == -11
    assert decisions[8]["rearm"]["status"] == "REACTIVATED" and not decisions[8]["turn"]["checked"]
    _, steps, decisions = run(BOTTOM + [(100, -9, 0), (98, -12, 0)])
    assert steps[-1].rearm_records[0]["status"] == "INVALIDATED"
    assert decisions[-1]["rearm"]["referenceBroken"] is True


@pytest.mark.parametrize("dif", [-20, -5])
def test_true_red_ends_wait_without_claiming_reference_was_checked(dif):
    # Saved original DIF=-11. A real red bar ends waiting before DIF is checked,
    # even if its raw DIF would otherwise have passed that breaking condition.
    values = BOTTOM + [(100, -9, 0), (100, dif, 2)]
    observed, steps, decisions = run(values)
    plain, normal, _ = run(values, enabled=False)
    assert steps[-1].rearm_records[0]["status"] == "SEGMENT_ENDED"
    assert steps[-1].rearm_records[0]["endReason"] == "color_flip"
    assert decisions[-1]["rearm"]["referenceBroken"] is None
    assert [replace(item, decision=None) for item in steps] == normal
    assert observed.snapshot() == plain.snapshot()


def test_record_copies_restore_flag_and_failure_context_are_isolated(monkeypatch):
    calc, steps, _ = run(TOP)
    state = calc.snapshot()
    old = deepcopy(steps[-1])
    steps[-1].decision["referenceChecks"][0]["wave"]["dif"] = -999
    steps[-1].decision["before"]["wave"]["price"] = -999
    assert calc.snapshot() == state and old.decision["before"]["wave"]["price"] == 101
    assert calc._decision_context is None and "decision" not in state and "record_decisions" not in state
    calc.restore(state)
    assert calc.record_decisions is True and calc._decision_context is None
    wrong = deepcopy(state)
    wrong["reference"] = None
    with pytest.raises(ValueError):
        calc.restore(wrong)
    assert calc.snapshot() == state and calc.record_decisions
    with monkeypatch.context() as m:
        m.setattr(calc, "_finish_step", lambda step: (_ for _ in ()).throw(RuntimeError("injected")))
        with pytest.raises(RuntimeError):
            calc.step(bar(5, (102, 40, 2)))
    assert calc._decision_context is None and old.decision["time"] == stamp(4)
    new = calc.step(bar(6, (102, 40, 2)))
    assert new.decision["time"] == stamp(6)
    disabled = XxmCalculator(period="day", source_identity="no-context")
    monkeypatch.setattr(disabled, "_begin_decision", lambda value: pytest.fail("default allocated context"))
    assert disabled.step(bar(1, (100, 0, 0))).decision is None


@pytest.mark.parametrize("value", [None, 0, 1, "true", []])
def test_recording_flag_requires_a_real_boolean(value):
    with pytest.raises(ValueError):
        XxmCalculator(period="day", source_identity=SOURCE, record_decisions=value)


def test_observe_rows_is_pure_bounded_and_checks_its_own_deadline(monkeypatch):
    from pathlib import Path
    values = [bar(i, value) for i, value in enumerate(TOP, 1)]
    monkeypatch.setattr(Path, "write_text", lambda *a, **k: pytest.fail("result write"))
    calls = []
    result = observation.observe_rows(values, period="day", source_identity=SOURCE, check=lambda: calls.append(1))
    assert len(result) == 4 and result[-1].decision is not None and len(calls) >= 10
    assert result[-1].events[0]["type"] == "DULL"
    ticks = iter([0., 0., 21.])
    monkeypatch.setattr(observation.time, "perf_counter", lambda: next(ticks))
    with pytest.raises(TimeoutError, match="20"):
        observation.observe_rows(values, period="day", source_identity=SOURCE, check=lambda: None)


def test_observe_rows_rejects_row_and_result_limits_and_memory(monkeypatch):
    values = (bar(i + 1, (100, 1, 2)) for i in range(1001))
    with pytest.raises(ValueError, match="1000"):
        observation.observe_rows(values, period="day", source_identity=SOURCE, check=lambda: None)
    class Large:
        def encode(self, *args):
            return b'x' * (16 * 1024 * 1024 + 1)
    with monkeypatch.context() as m:
        m.setattr(observation.json, "dumps", lambda *a, **k: Large())
        with pytest.raises(ValueError, match="16MiB"):
            observation.observe_rows([bar(1, TOP[0])], period="day", source_identity=SOURCE, check=lambda: None)
    class Usage:
        ru_maxrss = 257 * 1024 * 1024 if observation.sys.platform == 'darwin' else 257 * 1024
    monkeypatch.setattr(observation.resource, "getrusage", lambda *a: Usage())
    with pytest.raises(ValueError, match="256MiB"):
        observation.observe_rows([], period="day", source_identity=SOURCE, check=lambda: None)


def test_failed_active_switch_keeps_cancellation_and_a_price_failure():
    values = [(140, 41.186, 2), (90, 0, -2), (120, 24.935, 2), (110, 0, -2),
              (129, 17, 2), (130, 17.649, 2), (131, 26.754, 2)]
    calc, steps, decisions = run(values)
    d = decisions[-1]
    assert calc.state == "NONE" and d["referenceAfter"] is None and d["switched"] is False
    assert [(e["type"], e["route"]) for e in steps[-1].events] == [("CANCEL", "dif_break")]
    assert [(c["candidate"], c["pricePassed"], c["difPassed"]) for c in d["referenceChecks"][1:]] == [
        ("B", True, False), ("A", False, None)]
    assert d["turn"]["referenceBroken"] is True and not d["turn"]["checked"]


def test_equal_active_b_is_retained_without_claiming_an_a_check():
    values = [(100, 41.186, 2), (90, 0, -2), (120, 24.935, 2), (110, 0, -2),
              (129, 17, 2), (130, 17.649, 2), (131, 24.935, 2)]
    _, steps, decisions = run(values)
    d = decisions[-1]
    assert not steps[-1].events and d["branch"] == "retained"
    assert d["referenceAfter"]["dif"] == 24.935 and d["selectionCalls"] == []
    assert not d["switched"] and all(not c["checked"] for c in d["referenceChecks"])


def test_selector_returns_actual_pool_object_and_invalid_input_preserves_previous_facts(monkeypatch):
    actual = XxmCalculator._select_eligible_reference
    returned = []
    def select(self, wave, history):
        result = actual(self, wave, history)
        returned.append(result)
        return result
    monkeypatch.setattr(XxmCalculator, "_select_eligible_reference", select)
    calc, steps, _ = run(TOP)
    assert len(returned) == 1 and returned[0] is calc.history[1][-1]
    before, previous = calc.snapshot(), deepcopy(steps[-1])
    with pytest.raises(ValueError):
        calc.step(XxmBar(stamp(5), True, 40, 39, 2))
    assert calc.snapshot() == before and steps[-1] == previous and calc._decision_context is None
