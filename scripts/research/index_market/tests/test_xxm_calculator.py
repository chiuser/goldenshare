"""Current artificial core regressions, based on product LLD §§3, 14.

The old price-withdrawal/waiting assertions have been replaced by independent
current-rule literals.  The three explicitly named legacy source/prediction
nodes at the bottom remain untouched for their later P4/P5 migration; the
step-1 command selects only CURRENT_CORE_NODES and does not run those nodes.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

import pytest

from scripts.research.index_market.xxm.frozen_inputs import load_frozen_inputs
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC, XxmSpec
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar

ROOT = Path(__file__).resolve().parents[4] / "reports/xxm_macd_structure_20261011"
BASE = [(100, 10, 2), (101, 12, 2), (99, 9, -2), (100, 9, 2), (102, 10, 2), (103, 9.8, 2)]
TOP = [(100,200,2),(90,0,-2),(101,100,2),(102,100,2)]
BOTTOM = [(100,-200,-2),(110,0,2),(99,-100,-2),(98,-100,-2)]

CURRENT_CORE_NODES = (
    "test_first_activation_uses_current_close_not_an_earlier_extreme",
    "test_raw_two_pool_nearest_then_farther_and_strict_price_gate",
    "test_turn_exact_threshold_zero_basis_and_independent_extremes",
    "test_structure_return_ignores_price_and_direct_break_has_priority",
    "test_color_flip_freezes_old_structure_and_locks_without_expiry",
    "test_snapshot_clone_restore_and_failed_restore_are_isolated",
    "test_fixed_formal_rule_identity_rejects_policy_changes",
)


def bars(values, period="day"):
    result=[]
    for index,(close,dif,hist) in enumerate(values):
        stamp=(date(2023,1,3)+timedelta(days=index)).isoformat()
        if period != "day":
            stamp+="T15:00:00+08:00"
        result.append(XxmBar(stamp,close,dif,dif-hist/2,hist))
    return result


def run(values, *, spec=MAIN_SPEC, period="day"):
    calc=XxmCalculator(period=period, source_identity="synthetic", spec=spec)
    return calc,[calc.step(item) for item in bars(values,period)]


@pytest.mark.parametrize("sign",[1,-1])
def test_first_activation_uses_current_close_not_an_earlier_extreme(sign):
    # RC13/14: the first same-colour root crosses price, but count is only one.
    values=([(100,200,2),(90,0,-2),(101,100,2),(99,100,2)] if sign==1 else
            [(100,-200,-2),(110,0,2),(99,-100,-2),(101,-100,-2)])
    calc,steps=run(values)
    assert all(step.events == () for step in steps)
    assert calc.state == "NONE" and calc.wave.count == 2
    assert calc.wave.price == (101 if sign==1 else 99)
    valid=(102,100,2) if sign==1 else (98,-100,-2)
    activated=calc.step(bars(values+[valid])[-1])
    assert [(event["type"],event["route"]) for event in activated.events] == [("DULL","activation")]
    assert activated.events[0]["eventReference"]["price"] == 100


def test_raw_two_pool_nearest_then_farther_and_strict_price_gate():
    # Original independent two-pool sample; only the nearest two completed reds.
    prefix=[(100,50,2),(90,0,-2),(110,40,2),(90,0,-2),(120,20,2),(90,0,-2)]
    _,steps=run(prefix+[(121,30,2),(122,31,2)])
    assert steps[-1].events[0]["eventReference"]["dif"] == 40
    _,steps=run(prefix+[(121,40,2),(122,40,2)])
    assert not steps[-1].events  # Both B is exceeded and A is equal, so no ref.
    _,steps=run(prefix+[(109,10,2),(119,10,2)])
    assert not steps[-1].events  # Nearest price cannot be bypassed by old A.
    prefix[4]=(120,40,2)
    _,steps=run(prefix+[(121,30,2),(122,31,2)])
    assert steps[-1].events[0]["eventReference"]["startTime"] == "2023-01-07"


@pytest.mark.parametrize("sign",[1,-1])
def test_turn_exact_threshold_zero_basis_and_independent_extremes(sign):
    prefix=TOP if sign==1 else BOTTOM
    calc,steps=run(prefix+[(103 if sign==1 else 97,sign*99,sign*2)])
    assert [(event["type"],event["route"]) for event in steps[-1].events] == [("STRUCTURE","dif_turn")]
    assert steps[-1].structures[0]["status"] == "ASSESSING"
    assert calc.active_structure["priceExtreme"] == (103 if sign==1 else 97)
    # P=0 suppresses only the adjacent-percent path, not real opposite colour.
    calc,steps=run(prefix+[(103 if sign==1 else 97,0,sign*2),(104 if sign==1 else 96,sign,sign*2)])
    assert steps[-2].events[0]["type"] == "STRUCTURE"
    assert steps[-1].events == () and calc.state == "STRUCTURE"
    split=([(100,200,2),(105,190,2),(104,210,2),(90,0,-2),(106,100,2),(107,101,2)] if sign==1 else
           [(100,-200,-2),(95,-190,-2),(96,-210,-2),(110,0,2),(94,-100,-2),(93,-101,-2)])
    _,steps=run(split)
    ref=steps[-1].events[0]["eventReference"]
    assert ref["price"] == (105 if sign==1 else 95)
    assert ref["dif"] == sign*210
    assert ref["priceAt"] == "2023-01-04" and ref["difAt"] == "2023-01-05"


@pytest.mark.parametrize("sign",[1,-1])
def test_structure_return_ignores_price_and_direct_break_has_priority(sign):
    prefix=TOP if sign==1 else BOTTOM
    calc,steps=run(prefix+[(103 if sign==1 else 97,sign*99,sign*2)])
    original=deepcopy(steps[-1].structures[0])
    returned=calc.step(bars(prefix+[(103 if sign==1 else 97,sign*99,sign*2),
                                   (99 if sign==1 else 101,sign*100,sign*2)])[-1])
    assert [(event["type"],event["route"]) for event in returned.events] == [("DULL","dif_return")]
    assert calc.state == "DULL" and calc.reference.dif == sign*200 and calc.active_structure is None
    assert returned.structures[0]["id"] == original["id"]
    assert returned.structures[0]["status"] == "DISAPPEARED"
    assert returned.structures[0]["disappearanceReason"] == "dif_return"
    assert steps[-1].structures[0] == original and original["status"] == "ASSESSING"
    # An immediate original-reference break skips any intermediate DULL.
    calc,steps=run(prefix+[(103 if sign==1 else 97,sign*99,sign*2),
                          (104 if sign==1 else 96,sign*201,sign*2)])
    assert [(event["type"],event["route"]) for event in steps[-1].events] == [("CANCEL","dif_break")]
    assert calc.state == "NONE" and calc.reference is None
    assert steps[-1].structures[0]["disappearanceReason"] == "reference_dif_break"


@pytest.mark.parametrize("sign",[1,-1])
def test_color_flip_freezes_old_structure_and_locks_without_expiry(sign):
    prefix=TOP if sign==1 else BOTTOM
    formed=(103 if sign==1 else 97,sign*99,sign*2)
    opposite=(104 if sign==1 else 96,sign*98,-sign*2)
    values=prefix+[formed,opposite]+[(105 if sign==1 else 95,sign*97,-sign*2)]*150
    calc,steps=run(values)
    creation=steps[4].structures[0]
    locked=steps[5].structures[0]
    assert creation["status"] == "ASSESSING" and locked["status"] == "LOCKED"
    assert locked["id"] == creation["id"] and locked["formedAt"] == "2023-01-07"
    assert locked["lockedAt"] == "2023-01-08" and steps[5].events == ()
    assert locked["priceExtreme"] == (103 if sign==1 else 97)
    assert all(not step.events and not step.structures for step in steps[6:])
    assert calc.state == "NONE" and calc.active_structure is None
    assert creation["status"] == "ASSESSING" and locked["status"] == "LOCKED"


@pytest.mark.parametrize("period",["day","m60","m90","m120"])
def test_snapshot_clone_restore_and_failed_restore_are_isolated(period):
    values=TOP+[(103,99,2),(104,98,-2),(105,97,-2)]
    inputs=bars(values,period)
    full,expected=run(values,period=period)
    first=XxmCalculator(period=period,source_identity="synthetic")
    prefix=[first.step(item) for item in inputs[:5]]
    before=first.snapshot()
    restored=XxmCalculator(period=period,source_identity="synthetic")
    restored.restore(json.loads(json.dumps(before)))
    assert prefix+[restored.step(item) for item in inputs[5:]] == expected
    assert full.snapshot() == restored.snapshot()
    copied=clone(first)
    copied.reference.price=1
    assert first.snapshot() == before
    bad=deepcopy(before)
    bad["activeStructure"]["originalReference"]["dif"]=float("nan")
    with pytest.raises(ValueError):
        first.restore(bad)
    assert first.snapshot() == before
    first.step(inputs[5])
    first.restore(before)  # Valid rewind before the first opposite bar.
    assert first.snapshot() == before and first.active_structure["status"] == "ASSESSING"
    assert first.step(inputs[5]).structures[0]["status"] == "LOCKED"
    assert first.spec.algorithm_version == "xxm-direction-v0.2-r4"
    assert first.spec.spec_hash == MAIN_SPEC.spec_hash
    for rejected in [replace(inputs[-1], completed=False),replace(inputs[-1], dif=float("nan"))]:
        current=first.snapshot()
        with pytest.raises(ValueError):
            first.step(rejected)
        assert first.snapshot() == current
    wrong=XxmCalculator(period=period,source_identity="other")
    with pytest.raises(ValueError):
        wrong.restore(before)


@pytest.mark.parametrize("override",[{"dif_turn_pct":.75},{"max_refs":3},{"min_bars":1},
                                      {"min_bars":True},{"historical_min_bars":2},
                                      {"top_activation_requires_positive_dif":False}])
def test_fixed_formal_rule_identity_rejects_policy_changes(override):
    with pytest.raises(ValueError):
        XxmSpec(**override)


# P4/P5 legacy nodes: original functions/decorators preserved verbatim below.
# They are not part of the step-1 current-core command or a claimed pass result.

def same_segment_bar(n, close, dif, hist=-2.):
    return XxmBar(f'2020-01-{n:02d}', close, dif, dif-hist/2, hist)


def same_segment_setup(gate=1.):
    c = XxmCalculator(period='day', source_identity='synthetic', spec=XxmSpec(dif_turn_pct=gate))
    for b in [same_segment_bar(1,100,-10),same_segment_bar(2,99,-11),same_segment_bar(3,105,-5,2),
              same_segment_bar(4,98,-9),same_segment_bar(5,97,-9.2),same_segment_bar(6,98,-8.8)]:
        c.step(b)
    assert c.state == 'STRUCTURE'
    return c


@pytest.mark.parametrize("gate", [0.75, 1.0, 1.2])
def test_entire_frozen_ordinary_and_historical_baseline(gate):
    from scripts.research.index_market.xxm.frozen_inputs import assert_expected_recognition
    series, _ = load_frozen_inputs(ROOT)
    # Preserve the original independent source/oracle identity. New full-step
    # expected files were locked before the parent calculator was modified.
    assert hashlib.sha256((ROOT / "replay_color_flip.py").read_bytes()).hexdigest() == "f472817f85fa8b152501ad659a4afcefe8f903f5b19f8db6bb62403c6ce301ba"
    for freq, values in series.items():
        assert_expected_recognition(values, 'legacy', f'm{freq}', gate)



def test_entry_partition_uses_current_price_and_keeps_waiting_copy():
    from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import activation_signature
    from src.biz.services.wealth.market.index_detail_xxm.forecast_entry import solve_entry_ranges
    c = same_segment_setup();c.step(same_segment_bar(7,100,-9));before=c.snapshot()
    solve = solve_entry_ranges
    projection = ProjectionState(110.,119.,-8.)
    result=solve(c,projection,'2020-01-08')
    assert result['ranges']
    assert all(r['reference']['price']==99 for r in result['ranges'])
    signature=activation_signature
    assert signature(c,projection,98.5,'2020-01-08')['price']==99
    assert signature(c,projection,99.,'2020-01-08') is None
    assert signature(c,projection,100.,'2020-01-08') is None
    assert c.snapshot()==before



@pytest.mark.parametrize('gate',[.75,1.,1.2])
def test_full_four_period_top_oracle_and_first_activation_are_preserved(gate):
    from scripts.research.index_market.xxm.acceptance import load_source
    from scripts.research.index_market.xxm.frozen_inputs import assert_expected_recognition
    source=ROOT.parent/'xxm_source_audit_20261013_213852'
    for period in ('day','m60','m90','m120'):
        assert_expected_recognition(load_source(source,period), 'source', period, gate)
