from __future__ import annotations

import ast
from copy import deepcopy
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

import pytest

from scripts.research.index_market.xxm.frozen_inputs import load_frozen_inputs
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


ROOT = Path(__file__).resolve().parents[4] / "reports/xxm_macd_structure_20261011"


def bars(values):
    return [XxmBar((date(2020, 1, 1) + timedelta(days=i)).isoformat(), c, d, d - h / 2, h)
            for i, (c, d, h) in enumerate(values)]


def run(values, *, spec=XxmSpec()):
    calc = XxmCalculator(period="day", source_identity="synthetic", spec=spec)
    steps = [calc.step(bar) for bar in bars(values)]
    return calc, steps


BASE = [(100, 10, 2), (101, 12, 2), (99, 9, -2), (100, 9, 2), (102, 10, 2), (103, 9.8, 2)]


def test_activation_structure_retained_context_and_strict_price_only():
    calc, steps = run(BASE + [(103, 9.75, 2), (104, 9.74, 2), (105, 9.73, 2)])
    assert steps[4].events[0]["type"] == "DULL"
    assert steps[5].events[0]["type"] == "STRUCTURE"
    assert not steps[6].events  # equal price does not withdraw
    assert steps[7].events[0]["type"] == "RESEARCH_HISTORICAL_WITHDRAWAL"
    assert steps[7].histories[0]["pricePeak"] == 103
    assert steps[7].histories[0]["endReason"] == "historical_price_break"
    assert not steps[8].events and calc.pending is None


def test_new_top_event_and_dif_break_precede_price_withdrawal():
    _, steps = run(BASE + [(104, 10, 2)])
    assert [event["type"] for event in steps[-1].events] == ["DULL"]
    assert steps[-1].histories[0]["endReason"] == "new_top_DULL"
    _, steps = run(BASE + [(104, 12.1, 2)])
    assert [event["type"] for event in steps[-1].events] == ["CANCEL"]
    assert steps[-1].histories[0]["endReason"] == "original_reference_break"
    assert steps[-1].point["activeReference"] is None


def test_color_flip_keeps_old_event_but_zero_can_confirm_by_actual_dif_turn():
    _, steps = run(BASE[:5] + [(101, 9.99, -2)])
    assert steps[-1].events[0]["route"] == "color_flip"
    assert steps[-1].point["ordinaryState"] == "NONE"
    assert steps[-1].events[0]["direction"] == "TOP"
    assert steps[-1].histories[0]["pricePeak"] == 102
    _, steps = run(BASE[:5] + [(101, 13, -2)])
    assert steps[-1].events[0]["route"] == "dif_break_on_flip"
    _, steps = run(BASE[:5] + [(101, 9, 0)])
    assert [(e["type"], e["route"]) for e in steps[-1].events] == [("STRUCTURE", "dif_turn")]
    assert steps[-1].point["ordinaryState"] == "STRUCTURE"


def test_bottom_event_and_historical_withdrawal_can_coexist():
    values = [(135, -20, -2), (125, 10, 2), (130, -15, -2), (126, 8, 2), (127, 8, 2),
              (127, 7.8, 2), (127, -12, -2), (129, -11, -2)]
    _, steps = run(values)
    assert [(event["direction"], event["type"]) for event in steps[-1].events] == [
        ("BOTTOM", "DULL"), ("TOP", "RESEARCH_HISTORICAL_WITHDRAWAL")]


def test_raw_two_pool_nearest_then_farther_and_strict_price_gate():
    prefix = [(100, 50, 2), (90, 0, -2), (110, 40, 2), (90, 0, -2), (120, 20, 2), (90, 0, -2)]
    _, steps = run(prefix + [(121, 30, 2), (122, 31, 2)])
    assert steps[-1].events[0]["eventReference"]["dif"] == 40  # third older 50 cannot enter pool
    _, steps = run(prefix + [(121, 40, 2), (122, 40, 2)])
    assert not steps[-1].events  # equality does not activate
    _, steps = run(prefix + [(109, 10, 2), (119, 10, 2)])
    assert not steps[-1].events  # earlier eligible peak cannot bypass nearest price
    prefix[4] = (120, 40, 2)
    _, steps = run(prefix + [(121, 30, 2), (122, 31, 2)])
    assert steps[-1].events[0]["eventReference"]["startTime"] == "2020-01-05"


def test_turn_exact_threshold_zero_basis_mirror_and_independent_extremes():
    _, steps = run([(100, 200, 2), (99, 0, -2), (101, 90, 2), (102, 100, 2), (101, 99, 2)])
    assert steps[-1].events[0]["type"] == "STRUCTURE"  # exactly 1%
    _, steps = run([(100, 10, 2), (99, 0, -2), (101, 1, 2), (102, .5, 2), (103, 0, 2), (104, -1, 2)])
    assert steps[3].events[0]["type"] == "DULL"
    assert steps[4].events[0]["type"] == "STRUCTURE"
    assert steps[-1].point['ordinaryState'] == 'STRUCTURE'
    # Zero blocks the ordinary turn. Price 104 still breaks the independently
    # frozen structure peak 103, so its historical event must not be swallowed.
    assert [e['type'] for e in steps[-1].events] == ['RESEARCH_HISTORICAL_WITHDRAWAL']
    _, mirrored = run([(200 - c, -d, -h) for c, d, h in BASE])
    assert mirrored[-1].events[0]["direction"] == "BOTTOM"
    _, steps = run(BASE[:4] + [(105, 10, 2), (103, 9.8, 2)])
    assert steps[-1].histories[0]["pricePeak"] == 105
    assert steps[-1].histories[0]["pricePeakAt"] == "2020-01-05"


def test_resume_causality_identity_and_no_expiry():
    values = BASE + [(102, 9, -2)] * 150 + [(104, 9, -2)]
    full, expected = run(values)
    first, prefix = run(values[:70])
    assert first.pending is not None
    resumed = XxmCalculator(period="day", source_identity="synthetic")
    resumed.restore(json.loads(json.dumps(first.snapshot())))
    suffix = [resumed.step(bar) for bar in bars(values)[70:]]
    assert prefix + suffix == expected
    assert full.snapshot() == resumed.snapshot()
    wrong = XxmCalculator(period="day", source_identity="other")
    with pytest.raises(ValueError): wrong.restore(first.snapshot())
    with pytest.raises(ValueError): first.step(bars(values)[0])
    with pytest.raises(ValueError): XxmCalculator(period="day", source_identity="x").step(replace(bars(BASE)[0], completed=False))
    with pytest.raises(ValueError): XxmCalculator(period="day", source_identity="x").step(replace(bars(BASE)[0], dif=float("nan")))
    assert len(full.history[1]) <= 2 and len(full.history[-1]) <= 2


@pytest.mark.parametrize("gate", [0.75, 1.0, 1.2])
def test_entire_frozen_ordinary_and_historical_baseline(gate):
    from scripts.research.index_market.xxm.frozen_inputs import assert_expected_recognition
    series, _ = load_frozen_inputs(ROOT)
    # Preserve the original independent source/oracle identity. New full-step
    # expected files were locked before the parent calculator was modified.
    assert hashlib.sha256((ROOT / "replay_color_flip.py").read_bytes()).hexdigest() == "f472817f85fa8b152501ad659a4afcefe8f903f5b19f8db6bb62403c6ce301ba"
    for freq, values in series.items():
        assert_expected_recognition(values, 'legacy', f'm{freq}', gate)

# B-group: completed bottom structures keep a separate, frozen history record.
BOTTOM = [(200-c, -d, -h) for c, d, h in BASE]


def test_bottom_freezes_original_close_low_and_waits_for_origin_exit():
    calc, steps = run(BOTTOM + [(96, -9.75, -2), (98, -9.74, 2), (96.5, -9.7, -2), (95, -9.6, -2)])
    created = steps[5].bottom_histories[0]
    assert created['priceLow'] == 97 and created['priceLowAt'] == '2020-01-06'
    assert created['originSegmentStart'] == '2020-01-04' and created['leftOriginAt'] is None
    assert created['structureEventId'] == steps[5].events[0]['id']
    assert steps[5].events[0]['relatedBottomHistoryId'] == created['id']
    assert not steps[6].events  # new low in the original negative segment is not B
    assert steps[7].bottom_histories[0]['leftOriginAt'] == '2020-01-08'  # only real red leaves the original green segment
    event = steps[8].events[-1]
    assert event['direction'] == 'BOTTOM' and event['type'] == 'RESEARCH_HISTORICAL_WITHDRAWAL'
    assert event['relatedTopHistoryId'] is None and event['eventReference'] == created['originalReference']
    assert steps[8].bottom_histories[0]['priceLow'] == 97  # later 96 did not move the saved low
    assert steps[8].point['ordinaryState'] == 'NONE' and steps[8].point['pendingBottomHistoryId'] is None
    assert not steps[9].bottom_histories and calc.pending_bottom_history is None
    assert created['status'] == 'PENDING'  # earlier returned records are isolated


def test_bottom_color_flip_excludes_new_red_close_and_no_ttl():
    calc, steps = run(BOTTOM[:5] + [(50, -9.9, 2)])
    h = steps[-1].bottom_histories[0]
    assert h['confirmationRoute'] == 'color_flip' and h['priceLow'] == 98
    assert h['leftOriginAt'] == h['confirmedAt'] and h['priceLowAt'] == '2020-01-05'
    _, steps = run(BOTTOM + [(98, -9.8, 2)] * 40 + [(96, -9.7, 2)])
    assert steps[-1].bottom_histories[0]['ageBars'] == 41
    assert steps[-1].events[-1]['type'] == 'RESEARCH_HISTORICAL_WITHDRAWAL'
    assert len([e for s in steps for e in s.events if e['direction'] == 'BOTTOM' and e['type'] == 'RESEARCH_HISTORICAL_WITHDRAWAL']) == 1


@pytest.mark.parametrize('close,dif,reason,event', [
    (97, -9.7, None, False), (97.01, -9.7, None, False),
    (96.99, -9.7, 'historical_price_break', True),
    (96.99, -12, 'historical_price_break', True),
    (96.99, -12.0001, 'original_reference_break', False),
])
def test_bottom_strict_boundaries_and_reference_priority(close, dif, reason, event):
    calc, _ = run(BOTTOM + [(98, -9.8, 0)])
    # An isolated postprocessor probe decouples the unchanged ordinary branch.
    before = (calc.state, calc.reference, calc.wave, calc.history)
    events, changes = calc._advance_bottom_history(XxmBar('2020-01-08', close, dif, -11., 2.), None)
    assert changes[0]['endReason'] == reason and bool(events) == event
    assert (calc.state, calc.reference, calc.wave, calc.history) == before


@pytest.mark.parametrize('kind', ['DULL', 'STRUCTURE'])
def test_bottom_successor_signal_precedes_price_break(kind):
    calc, _ = run(BOTTOM + [(98, -9.8, 0)])
    events, changes = calc._advance_bottom_history(XxmBar('2020-01-08', 96, -9.7, -11., 2.),
                                                  {'direction': 'BOTTOM', 'type': kind})
    assert not events and changes[0]['endReason'] == 'new_bottom_' + kind
    assert calc.pending_bottom_history is None


def test_bottom_top_signal_is_not_a_bottom_successor_and_qualified_same_segment_return_is_preserved():
    calc, _ = run(BOTTOM + [(98, -9.8, 0)])
    events, changes = calc._advance_bottom_history(XxmBar('2020-01-08', 96, -9.7, -11., 2.),
                                                  {'direction': 'TOP', 'type': 'STRUCTURE'})
    assert events and changes[0]['endReason'] == 'historical_price_break'
    _, steps = run(BOTTOM + [(96, -10, -2)])
    assert steps[-1].events[0]['route'] == 'dif_return'  # A deliberately remains
    assert steps[-1].bottom_histories[0]['endReason'] == 'new_bottom_DULL'


def test_bottom_snapshot_restore_atomic_strict_and_can_rewind():
    from copy import deepcopy
    calc, _ = run(BOTTOM)
    origin = calc.snapshot()
    # LLD 3.3: a genuine red bar, rather than neutral zero, leaves the origin.
    calc.step(bars(BOTTOM + [(98, -9.8, 2)])[-1])
    exited = calc.snapshot()
    assert exited['pendingBottomHistory']['leftOriginAt'] is not None
    calc.restore(origin)
    assert calc.snapshot() == origin and calc.pending_bottom_history['leftOriginAt'] is None
    mutations = [lambda s: s.pop('pendingBottomHistory'), lambda s: s.update(specHash='old'),
                 lambda s: s.update(sourceIdentity='other'), lambda s: s['pendingBottomHistory'].update(extra=1),
                 lambda s: s['pendingBottomHistory'].update(priceLow=float('nan')),
                 lambda s: s['pendingBottomHistory'].update(priceLow=0),
                 lambda s: s['pendingBottomHistory'].update(ageBars=True),
                 lambda s: s['pendingBottomHistory'].update(ageBars=9999),
                 lambda s: s['pendingBottomHistory'].update(observedThrough='2099-01-01'),
                 lambda s: s['pendingBottomHistory'].update(leftOriginAt='2019-01-01'),
                 lambda s: s['pendingBottomHistory'].update(status='ENDED'),
                 lambda s: s['pendingBottomHistory'].update(id='wrong'),
                 lambda s: s['pendingBottomHistory'].update(originSegmentStart='2020-01-05')]
    for mutate in mutations:
        invalid = deepcopy(origin); mutate(invalid)
        with pytest.raises(ValueError): calc.restore(invalid)
        assert calc.snapshot() == origin
    returned = calc.snapshot(); returned['pendingBottomHistory']['originalReference']['dif'] = 100
    assert calc.snapshot() == origin


@pytest.mark.parametrize('period', ['day', 'm60', 'm90', 'm120'])
def test_bottom_period_identity_and_step_snapshot_continuation(period):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    values = bars(BOTTOM + [(98, -9.8, 0), (96, -9.7, -2)])
    if period != 'day':
        values = [replace(b, time=b.time+'T15:00:00+08:00') for b in values]
    calc = XxmCalculator(period=period, source_identity='B-test')
    for b in values[:6]: calc.step(b)
    child = XxmCalculator(period=period, source_identity='B-test'); child.restore(calc.snapshot())
    assert [child.step(b) for b in values[6:]] == [calc.step(b) for b in values[6:]]
    assert calc.snapshot() == child.snapshot()
    assert calc.spec.algorithm_version == 'xxm-direction-v0.1-r4'
    # Fixed formal fields from LLD section 2.2, verified independently in Spec tests.
    assert calc.spec.spec_hash == 'ebd2afeefd470e19520daa8f86467d58977b02134313b9363a95e71c6b9e356e'


def test_new_top_structure_and_bottom_history_disappearance_are_independent_on_same_bar():
    from copy import deepcopy
    calc, _ = run(BASE[:5])
    # Isolate independent layer coexistence with a previously completed bottom
    # record. The ordinary TOP fixture itself is unchanged and remains causal.
    record = {
        'id': calc._id('bottom-history','prior-bottom'), 'structureEventId':'prior-bottom',
        'confirmedAt':'2019-12-20','confirmationRoute':'dif_turn','originSegmentStart':'2019-12-18',
        'leftOriginAt':'2019-12-23','priceLow':104.,'priceLowAt':'2019-12-19',
        'originalReference':{'startTime':'2019-11-01','endTime':'2019-11-10','price':105.,'dif':-20.},
        'status':'PENDING','endedAt':None,'endReason':None,'observedThrough':'2020-01-05','ageBars':4}
    calc.pending_bottom_history = deepcopy(record)
    step = calc.step(bars(BASE)[-1])
    assert [(e['direction'],e['type']) for e in step.events] == [
        ('TOP','STRUCTURE'),('BOTTOM','RESEARCH_HISTORICAL_WITHDRAWAL')]
    assert step.events[0]['relatedTopHistoryId'] and step.events[0]['relatedBottomHistoryId'] is None
    assert step.events[1]['relatedBottomHistoryId']==record['id'] and step.events[1]['relatedTopHistoryId'] is None
    assert step.point['ordinaryState']=='STRUCTURE' and step.bottom_histories[0]['endReason']=='historical_price_break'


# A1 same-segment cases promoted from the archived research candidate.




from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone, activation_signature
from src.biz.services.wealth.market.index_detail_xxm.forecast_entry import solve_entry_ranges



from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState


def same_segment_bar(n, close, dif, hist=-2.):
    return XxmBar(f'2020-01-{n:02d}', close, dif, dif-hist/2, hist)


def same_segment_setup(gate=1.):
    c = XxmCalculator(period='day', source_identity='synthetic', spec=XxmSpec(dif_turn_pct=gate))
    for b in [same_segment_bar(1,100,-10),same_segment_bar(2,99,-11),same_segment_bar(3,105,-5,2),
              same_segment_bar(4,98,-9),same_segment_bar(5,97,-9.2),same_segment_bar(6,98,-8.8)]:
        c.step(b)
    assert c.state == 'STRUCTURE'
    return c


@pytest.mark.parametrize('gate', [1.0])
def test_disappearance_wait_reactivation_and_original_low_are_separate(gate):
    c = same_segment_setup(gate)
    structure = c.pending_bottom_history['structureEventId']
    assert c.wave.price == 97
    gone = c.step(same_segment_bar(7,100,-9))
    assert [(e['type'],e['route']) for e in gone.events] == [('STRUCTURE_DISAPPEARED','dif_return')]
    assert c.state == 'NONE' and c.reference is None and c.pending_bottom_history is None
    assert c.pending_rearm['structureEventId'] == structure and c.pending_rearm['referenceWave']['price'] == 99
    assert gone.bottom_histories[0]['endReason'] == 'structure_disappeared'
    # A prior low of 97 cannot requalify today's 100; a new 98.5 is sufficient.
    reentry = c.step(same_segment_bar(8,98.5,-9.2))
    assert [(e['type'],e['route']) for e in reentry.events] == [('DULL','reactivation')]
    assert c.state == 'DULL' and c.pending_rearm is None and c.wave.price == 97
    c.step(same_segment_bar(9,100,-8.8))
    assert c.pending_bottom_history['structureEventId'] != structure


@pytest.mark.parametrize('gate', [1.0])
def test_qualifying_return_is_dull_without_green_and_preserves_successor_structure(gate):
    c = same_segment_setup(gate)
    original_structure = c.pending_bottom_history['structureEventId']
    step = c.step(same_segment_bar(7,98,-9))
    assert [(e['type'],e['route']) for e in step.events] == [('DULL','dif_return')]
    assert c.state == 'DULL' and c.pending_rearm is None and not step.rearm_records
    assert c.pending_bottom_history is None
    assert step.bottom_histories[0]['endReason'] == 'new_bottom_DULL'
    formed = c.step(same_segment_bar(8,100,-8.8,2))
    assert [(e['type'],e['route']) for e in formed.events] == [('STRUCTURE','color_flip')]
    assert c.pending_bottom_history['structureEventId'] != original_structure
    assert c.pending_bottom_history['priceLow'] == 97


@pytest.mark.parametrize('close,dif', [(99.,-9.),(100.,-9.),(98.,-11.)])
def test_return_must_pass_current_strict_price_and_segment_dif(close,dif):
    c = same_segment_setup()
    step = c.step(same_segment_bar(7,close,dif))
    assert [(e['type'],e['route']) for e in step.events] == [('STRUCTURE_DISAPPEARED','dif_return')]
    assert c.state == 'NONE' and c.pending_rearm is not None


def test_return_keeps_nearest_price_gate_and_true_reference_break_priority():
    c = same_segment_setup(); c.history[-1][-1].price = 97.5
    assert c.step(same_segment_bar(7,98,-9)).events[0]['type'] == 'STRUCTURE_DISAPPEARED'
    c = same_segment_setup()
    step = c.step(same_segment_bar(7,98,-11.1))
    assert [(e['type'],e['route']) for e in step.events] == [('CANCEL','dif_break')]
    assert c.pending_rearm is None


@pytest.mark.parametrize('hist', [0.,2.])
def test_real_red_releases_wait_but_zero_retains_wait_without_fabricated_cancel(hist):
    c = same_segment_setup(); c.step(same_segment_bar(7,100,-9))
    step = c.step(same_segment_bar(8,101,-9.2,hist))
    assert not step.events
    if hist == 0:
        assert c.pending_rearm is not None
        assert step.rearm_records[0]['status'] == 'WAITING'
        assert step.rearm_records[0]['endReason'] is None
    else:
        assert c.pending_rearm is None
        assert step.rearm_records[0]['status'] == 'SEGMENT_ENDED'
        assert step.rearm_records[0]['endReason'] == 'color_flip'


def test_reference_and_price_equalities_and_true_dif_break():
    c = same_segment_setup(); c.step(same_segment_bar(7,100,-9))
    assert not c.step(same_segment_bar(8,99,-9.2)).events
    assert c.pending_rearm is not None
    assert not c.step(same_segment_bar(9,98.5,-11)).events
    assert c.pending_rearm is not None
    assert not c.step(same_segment_bar(10,98.5,-10.5)).events  # accumulated DIF equality still blocks
    step = c.step(same_segment_bar(11,98.5,-11.1))
    assert not step.events
    assert c.pending_rearm is None and step.rearm_records[0]['endReason'] == 'reference_dif_break'


def test_snapshot_clone_restore_and_failed_restore_are_isolated():
    c = same_segment_setup(); c.step(same_segment_bar(7,100,-9))
    before = c.snapshot()
    child = clone(c)
    child.pending_rearm['referenceWave']['price'] = 1
    assert c.snapshot() == before
    restored = XxmCalculator(period='day',source_identity='synthetic');restored.restore(before)
    assert restored.step(same_segment_bar(8,98.5,-9.2)) == c.step(same_segment_bar(8,98.5,-9.2))
    prior = restored.snapshot(); broken = deepcopy(prior);broken['pendingRearm'] = {'id': 'wrong'}
    with pytest.raises(ValueError): restored.restore(broken)
    assert restored.snapshot() == prior


def test_entry_partition_uses_current_price_and_keeps_waiting_copy():
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


@pytest.mark.parametrize('mutate', [
    lambda s:s.pop('pendingRearm'), lambda s:s.update(extra=True),
    lambda s:s.update(specHash='b2ebada1a7ef0f013cf2b9a447a6a9fee8c73ac660c3fee41a9be13e3ca290e5'),
    lambda s:s['pendingRearm'].update(extra=True), lambda s:s['pendingRearm'].pop('referenceWave'),
    lambda s:s['pendingRearm']['referenceWave'].pop('price_at'),
    lambda s:s['pendingRearm']['referenceWave'].update(count=True),
    lambda s:s['pendingRearm']['referenceWave'].update(dif=float('nan')),
    lambda s:s['pendingRearm'].update(direction='TOP'), lambda s:s['pendingRearm'].update(status='REACTIVATED'),
    lambda s:s['pendingRearm'].update(id='wrong'), lambda s:s['pendingRearm'].update(bottomHistoryId='wrong'),
    lambda s:s['pendingRearm'].update(structureEventId='wrong'),
    lambda s:s['pendingRearm'].update(segmentStart='2020-01-05'),
    lambda s:s['pendingRearm'].update(observedThrough='2020-01-08'),
    lambda s:s['pendingRearm'].update(nearestPriceGate=100),
    lambda s:s.update(state='DULL'), lambda s:s.update(reference=s['pendingRearm']['referenceWave']),
    lambda s:s.update(processed=0), lambda s:s['wave'].update(count=100),
])
def test_rearm_restore_strict_atomic_and_original_pool_identity(mutate):
    c=same_segment_setup();c.step(same_segment_bar(7,100,-9));before=c.snapshot()
    broken=deepcopy(before);mutate(broken)
    with pytest.raises(ValueError):c.restore(broken)
    assert c.snapshot()==before


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
def test_rearm_period_specific_identity_restore_and_rewind(period):
    c=XxmCalculator(period=period,source_identity='same-segment-period')
    values=[same_segment_bar(1,100,-10),same_segment_bar(2,99,-11),same_segment_bar(3,105,-5,2),
            same_segment_bar(4,98,-9),same_segment_bar(5,97,-9.2),same_segment_bar(6,98,-8.8),
            same_segment_bar(7,100,-9),same_segment_bar(8,98.5,-9.2),same_segment_bar(9,100,-8.8)]
    if period!='day':values=[replace(b,time=b.time+'T15:00:00+08:00') for b in values]
    for b in values[:7]:c.step(b)
    waiting=c.snapshot();child=clone(c)
    assert child.step(values[7])==c.step(values[7])
    c.step(values[8]);c.restore(waiting)
    assert c.snapshot()==waiting and c.pending_rearm['observedThrough']==values[6].time
    child=clone(c);child.pending_rearm['referenceWave']['price']=1
    assert c.snapshot()==waiting


@pytest.mark.parametrize('gate',[.75,1.,1.2])
def test_full_four_period_top_oracle_and_first_activation_are_preserved(gate):
    from scripts.research.index_market.xxm.acceptance import load_source
    from scripts.research.index_market.xxm.frozen_inputs import assert_expected_recognition
    source=ROOT.parent/'xxm_source_audit_20261013_213852'
    for period in ('day','m60','m90','m120'):
        assert_expected_recognition(load_source(source,period), 'source', period, gate)
