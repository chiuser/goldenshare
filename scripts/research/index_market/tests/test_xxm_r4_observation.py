"""LLD §7 actual observations; §14 literals, no market replay or old oracle.

The two observe_rows tool tests at the bottom belong to P4 tool migration; the
P3 step-1 command selects calculator observation nodes, not that old runner.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from scripts.research.index_market.tests.test_xxm_r4_rules import CASES, PERIODS, _time
from scripts.research.index_market.xxm import history_disappearance_screen as observation
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar

SOURCE = "observation-literal-unit"
TOP = [(100, 200, 2), (90, 0, -2), (101, 100, 2), (102, 100, 2)]
AB = [(100, 300, 2), (90, 0, -2), (120, 200, 2), (110, 0, -2)]


def stamp(index):
    return (date(2023, 1, 1) + timedelta(days=index - 1)).isoformat()


def bar(index, values):
    close, dif, hist = values
    return XxmBar(stamp(index), close, dif, dif-hist/2, hist)


def run(values, enabled=True):
    calc = XxmCalculator(period="day", source_identity=SOURCE, record_decisions=enabled)
    steps = [calc.step(bar(i, value)) for i, value in enumerate(values, 1)]
    return calc, steps, [step.decision for step in steps]


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("number,data", CASES)
def test_all_rule_literals_record_identical_business_without_waiting(number, data, period):
    plain = XxmCalculator(period=period, source_identity="trace-"+str(number))
    observed = XxmCalculator(period=period, source_identity="trace-"+str(number), record_decisions=True)
    for index, (c, d, h) in enumerate(data.values, 1):
        item = XxmBar(_time(period,index),c,d,d-h/2,h)
        before = plain.snapshot()
        normal, traced = plain.step(item), observed.step(item)
        assert replace(traced, decision=None) == normal
        assert normal.decision is None and plain.snapshot() == observed.snapshot()
        fact = traced.decision
        assert fact["before"] == {
            "state": before["state"], "wave": before["wave"],
            "reference": None if before["reference"] is None else {
                "startTime":before["reference"]["start"], "endTime":before["reference"]["end"],
                "price":before["reference"]["price"], "dif":before["reference"]["dif"],
                "priceAt":before["reference"]["price_at"], "difAt":before["reference"]["dif_at"]},
            "previousDif":before["previous"]["dif"] if before["previous"] else None,
            "activeStructureId":before["activeStructure"]["id"] if before["activeStructure"] else None}
        assert "rearm" not in fact and "decision" not in plain.snapshot()
        assert fact["referenceAfter"] == normal.point["activeReference"]
        assert fact["structureId"] == (normal.structures[-1]["id"] if normal.structures else None)
        assert fact["structureStatus"] == (normal.structures[-1]["status"] if normal.structures else None)
        assert observed._decision_context is None


def test_actual_selector_once_b_priority_and_no_fabricated_a_check(monkeypatch):
    calls=[]
    original=XxmCalculator._select_eligible_reference
    def select(self, item, wave, history):
        calls.append(item.time)
        return original(self,item,wave,history)
    monkeypatch.setattr(XxmCalculator,"_select_eligible_reference",select)
    calc,_,facts=run(AB+[(130,100,2),(131,100,2)])
    assert calls == [stamp(6)]
    assert facts[-1]["selectionCalls"] == [{"stage":"activation","selected":calc.reference.reference()}]
    checks=facts[-1]["referenceChecks"]
    assert [(v["candidate"],v["checked"],v["pricePassed"],v["difPassed"],v["referenceBroken"]) for v in checks] == [
        ("B",True,True,None,None),("B",True,True,True,False),("A",False,None,None,None)]
    retained=calc.step(bar(7,(119,100,2))).decision
    assert retained["branch"] == "retained" and retained["selectionCalls"] == []
    assert all(v["referenceBroken"] is None and not v["checked"] for v in retained["referenceChecks"])


def test_failed_price_gate_and_a_price_do_not_claim_unperformed_dif_checks():
    _,_,facts=run(AB+[(119,100,2),(119,100,2)])
    assert [(v["candidate"],v["pricePassed"],v["difPassed"],v["referenceBroken"]) for v in facts[-1]["referenceChecks"]] == [
        ("B",False,None,None),("A",None,None,None)]
    values=[(130,300,2),(90,0,-2),(120,200,2),(110,0,-2),(125,250,2),(129,250,2)]
    _,_,facts=run(values)
    assert [(v["candidate"],v["pricePassed"],v["difPassed"],v["referenceBroken"]) for v in facts[-1]["referenceChecks"]] == [
        ("B",True,None,None),("B",True,False,True),("A",False,None,None)]


@pytest.mark.parametrize("sign",[1,-1])
@pytest.mark.parametrize("hist",[2,0])
def test_same_bar_switch_preserves_actual_b_break_and_never_runs_turn(sign,hist,monkeypatch):
    values=AB+[(130,100,2),(131,100,2),(132,201,hist)]
    if sign == -1:
        values=[(200-c,-d,-h) for c,d,h in values]
    checks=[]
    original=XxmCalculator._current_reference_qualifies
    def qualifies(self,item,wave,ref,nearest):
        if item.time == stamp(7):
            checks.append(ref.start)
        return original(self,item,wave,ref,nearest)
    monkeypatch.setattr(XxmCalculator,"_current_reference_qualifies",qualifies)
    calc,steps,facts=run(values)
    assert checks == [stamp(1)]  # Only A; B's break was checked by the actual DULL branch.
    fact=facts[-1]
    assert fact["before"]["reference"]["dif"] == sign*200
    assert fact["referenceAfter"]["dif"] == sign*300 and fact["switched"]
    assert fact["branch"] == "reference_switch" and fact["turn"]["referenceBroken"] is True
    assert fact["turn"]["checked"] is False
    assert steps[-1].events == () and calc.state == "DULL"
    assert steps[-2].events[0]["eventReference"]["dif"] == sign*200
    assert fact["selectionCalls"][0]["stage"] == "same_bar_rescue"


def test_structure_actions_and_zero_basis_have_real_observed_branches():
    _,steps,facts=run(TOP+[(103,99,2),(104,100,-2)])
    assert facts[-2]["branch"] == "dif_turn" and facts[-2]["structureStatus"] == "ASSESSING"
    assert steps[-1].events == () and facts[-1]["branch"] == "structure_locked"
    assert facts[-1]["structureStatus"] == "LOCKED" and not facts[-1]["turn"]["checked"]
    _,_,facts=run(TOP+[(103,0,2),(99,1,2)])
    assert facts[-1]["branch"] == "retained" and facts[-1]["turn"]["threshold"] == 0
    assert "为0" in facts[-1]["turn"]["reason"]
    _,_,facts=run([(100,0,0),(101,1,0)])
    assert facts[-1]["branch"] == "leading_zero" and facts[-1]["wave"] is None


def test_copies_restore_mode_and_failed_final_construction_are_isolated(monkeypatch):
    calc,steps,_=run(TOP)
    before=calc.snapshot()
    steps[-1].decision["referenceChecks"][0]["wave"]["dif"]=-999
    steps[-1].decision["before"]["wave"]["price"]=-999
    assert calc.snapshot() == before
    calc.restore(before)
    assert calc.record_decisions and calc._decision_context is None
    with monkeypatch.context() as m:
        def fail(*args):
            raise RuntimeError("constructed observation failed")
        m.setattr(calc,"_finish_step",fail)
        with pytest.raises(RuntimeError):
            calc.step(bar(5,(103,99,2)))
    assert calc.snapshot() == before and calc._decision_context is None
    assert calc.step(bar(5,(103,99,2))).events[0]["type"] == "STRUCTURE"
    disabled=XxmCalculator(period="day",source_identity="no-context")
    monkeypatch.setattr(disabled,"_begin_decision",lambda value: pytest.fail("default allocated context"))
    assert disabled.step(bar(1,(100,0,0))).decision is None


@pytest.mark.parametrize("value",[None,0,1,"true",[]])
def test_recording_flag_requires_a_real_boolean(value):
    with pytest.raises(ValueError):
        XxmCalculator(period="day",source_identity=SOURCE,record_decisions=value)


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
