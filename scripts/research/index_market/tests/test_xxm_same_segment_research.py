from copy import deepcopy

import pytest

from scripts.research.index_market.xxm.same_segment_candidate import SameSegmentCandidate, clone, candidate_forecast
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState


def bar(n, close, dif, hist=-2.):
    return XxmBar(f'2020-01-{n:02d}', close, dif, dif-hist/2, hist)


def setup_candidate(gate=1.):
    c = SameSegmentCandidate(period='day', source_identity='synthetic', spec=XxmSpec(dif_turn_pct=gate))
    for b in [bar(1,100,-10),bar(2,99,-11),bar(3,105,-5,2),
              bar(4,98,-9),bar(5,97,-9.2),bar(6,98,-8.8)]:
        c.step(b)
    assert c.state == 'STRUCTURE'
    return c


@pytest.mark.parametrize('gate', [.75,1.,1.2])
def test_disappearance_wait_reactivation_and_original_low_are_separate(gate):
    c = setup_candidate(gate)
    structure = c.pending_bottom_history['structureEventId']
    assert c.wave.price == 97
    gone = c.step(bar(7,100,-9))
    assert [(e['type'],e['route']) for e in gone.events] == [('STRUCTURE_DISAPPEARED','dif_return')]
    assert c.state == 'NONE' and c.reference is None and c.pending_bottom_history is None
    assert c.rearm['structureEventId'] == structure and c.rearm['reference']['price'] == 99
    assert gone.bottom_histories[0]['endReason'] == 'structure_disappeared'
    # A prior low of 97 cannot requalify today's 100; a new 98.5 is sufficient.
    reentry = c.step(bar(8,98.5,-9.2))
    assert [(e['type'],e['route']) for e in reentry.events] == [('DULL','reactivation')]
    assert c.state == 'DULL' and c.rearm is None and c.wave.price == 97
    c.step(bar(9,100,-8.8))
    assert c.pending_bottom_history['structureEventId'] != structure


@pytest.mark.parametrize('gate', [.75,1.,1.2])
def test_qualifying_return_is_dull_without_green_and_preserves_successor_structure(gate):
    c = setup_candidate(gate)
    original_structure = c.pending_bottom_history['structureEventId']
    step = c.step(bar(7,98,-9))
    assert [(e['type'],e['route']) for e in step.events] == [('DULL','dif_return')]
    assert c.state == 'DULL' and c.rearm is None and not c.last_rearm_changes
    assert c.pending_bottom_history is None
    assert step.bottom_histories[0]['endReason'] == 'new_bottom_DULL'
    formed = c.step(bar(8,100,-8.8,2))
    assert [(e['type'],e['route']) for e in formed.events] == [('STRUCTURE','color_flip')]
    assert c.pending_bottom_history['structureEventId'] != original_structure
    assert c.pending_bottom_history['priceLow'] == 97


@pytest.mark.parametrize('close,dif', [(99.,-9.),(100.,-9.),(98.,-11.)])
def test_return_must_pass_current_strict_price_and_segment_dif(close,dif):
    c = setup_candidate()
    step = c.step(bar(7,close,dif))
    assert [(e['type'],e['route']) for e in step.events] == [('STRUCTURE_DISAPPEARED','dif_return')]
    assert c.state == 'NONE' and c.rearm is not None


def test_return_keeps_nearest_price_gate_and_true_reference_break_priority():
    c = setup_candidate(); c.history[-1][-1].price = 97.5
    assert c.step(bar(7,98,-9)).events[0]['type'] == 'STRUCTURE_DISAPPEARED'
    c = setup_candidate()
    step = c.step(bar(7,98,-11.1))
    assert [(e['type'],e['route']) for e in step.events] == [('CANCEL','dif_break')]
    assert c.rearm is None


@pytest.mark.parametrize('hist', [0.,2.])
def test_color_or_zero_releases_wait_without_fabricated_cancel(hist):
    c = setup_candidate(); c.step(bar(7,100,-9))
    step = c.step(bar(8,101,-9.2,hist))
    assert not step.events and c.rearm is None
    assert c.last_rearm_changes[0]['status'] == 'SEGMENT_ENDED'
    assert c.last_rearm_changes[0]['endReason'] == ('zero' if hist == 0 else 'color_flip')


def test_reference_and_price_equalities_and_true_dif_break():
    c = setup_candidate(); c.step(bar(7,100,-9))
    assert not c.step(bar(8,99,-9.2)).events
    assert c.rearm is not None
    assert not c.step(bar(9,98.5,-11)).events
    assert c.rearm is not None
    assert not c.step(bar(10,98.5,-10.5)).events  # accumulated DIF equality still blocks
    assert not c.step(bar(11,98.5,-11.1)).events
    assert c.rearm is None and c.last_rearm_changes[0]['endReason'] == 'reference_dif_break'


def test_snapshot_clone_restore_and_failed_restore_are_isolated():
    c = setup_candidate(); c.step(bar(7,100,-9))
    before = c.snapshot()
    child = clone(c)
    child.rearm['reference']['price'] = 1
    assert c.snapshot() == before
    restored = SameSegmentCandidate(period='day',source_identity='synthetic');restored.restore(before)
    assert restored.step(bar(8,98.5,-9.2)) == c.step(bar(8,98.5,-9.2))
    prior = restored.snapshot(); broken = deepcopy(prior);broken['research']['id'] = 'wrong'
    with pytest.raises(ValueError): restored.restore(broken)
    assert restored.snapshot() == prior


def test_top_identification_remains_product_behavior():
    c = SameSegmentCandidate(period='day',source_identity='synthetic')
    base = XxmCalculator(period='day',source_identity='synthetic')
    rows = [bar(1,100,10,2),bar(2,101,11,2),bar(3,95,5),bar(4,102,9,2),
            bar(5,103,9.2,2),bar(6,102,8.8,2),bar(7,100,9,2)]
    for b in rows:
        old,new = base.step(b),c.step(b)
        assert [{k:v for k,v in e.items() if k!='relatedRearmId'} for e in new.events] == list(old.events)


def test_entry_partition_uses_current_price_and_keeps_waiting_copy():
    c = setup_candidate();c.step(bar(7,100,-9));before=c.snapshot()
    _,solve,detector = candidate_forecast()
    projection = ProjectionState(110.,119.,-8.)
    result=solve(c,projection,'2020-01-08')
    assert result['ranges']
    assert all(r['reference']['price']==99 for r in result['ranges'])
    signature=detector['activation_signature']
    assert signature(c,projection,98.5,'2020-01-08')['price']==99
    assert signature(c,projection,99.,'2020-01-08') is None
    assert signature(c,projection,100.,'2020-01-08') is None
    assert c.snapshot()==before


def test_research_namespace_binding_never_replaces_product_clone():
    from src.biz.services.wealth.market.index_detail_xxm import forecast_detector
    old=forecast_detector.clone
    candidate_forecast()
    assert forecast_detector.clone is old
