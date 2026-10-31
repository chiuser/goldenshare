"""LLD RC74–96: independent literal finite-following timelines (no market reads)."""
from copy import deepcopy
from dataclasses import asdict
from unittest.mock import patch

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar

DATES = ('2023-01-03','2023-01-04','2023-01-05','2023-01-06','2023-01-09','2023-01-10',
         '2023-01-11','2023-01-12','2023-01-13','2023-01-16','2023-01-17','2023-01-18')
T = [(100,200,2),(90,0,-2),(101,100,2),(102,100,2)]
TS = T+[(103,99,2)]
TF = TS+[(90,98,-2)]
TN = TF+[(102,97,2),(103,96,2)]


def values(top, sign):
    return top if sign == 1 else [(200-c,-d,-h) for c,d,h in top]


def bars(rows, period='day'):
    return [XxmBar(t if period == 'day' else t+'T15:00:00+08:00',c,d,d-h/2,h)
            for t,(c,d,h) in zip(DATES, rows)]


def run(rows, period='day', observe=False):
    c=XxmCalculator(period=period,source_identity='finite-literals',record_decisions=observe)
    return c,[c.step(b) for b in bars(rows,period)]


# Expected old-record changes are handwritten row/status pairs. No calculator supplies expected.
CASES = [
 ('74',TF+[(104,97,2)],[(5,'ASSESSING'),(6,'FOLLOWING'),(7,'DISAPPEARED')],[7]),
 ('75',TF+[(104,97,-2)],[(5,'ASSESSING'),(6,'FOLLOWING')],[]),
 ('76',TF+[(103,97,2),(103,96,2),(104,95,2)],[(5,'ASSESSING'),(6,'FOLLOWING'),(7,'FOLLOWING'),(9,'DISAPPEARED')],[9]),
 ('77',TF+[(102,97,2),(104,96,2)],[(5,'ASSESSING'),(6,'FOLLOWING'),(7,'FOLLOWING'),(8,'DISAPPEARED')],[8]),
 ('78',TS+[(105,98.5,2),(110,98,-2),(104,97,2),(106,96,2)],
  [(5,'ASSESSING'),(7,'FOLLOWING'),(8,'FOLLOWING'),(9,'DISAPPEARED')],[9]),
 ('78zero',TS+[(105,98.5,0),(110,98,-2),(104,97,2),(106,96,2)],
  [(5,'ASSESSING'),(7,'FOLLOWING'),(8,'FOLLOWING'),(9,'DISAPPEARED')],[9]),
 ('80',TN+[(120,95,-2),(121,94,2)],[(5,'ASSESSING'),(6,'FOLLOWING'),(7,'FOLLOWING'),(9,'FINISHED')],[]),
 ('81',TN+[(102,98,2),(104,97,2)],[(5,'ASSESSING'),(6,'FOLLOWING'),(7,'FOLLOWING'),(10,'DISAPPEARED')],[10]),
 ('82',TF+[(110,97,0),(104,96,2)],[(5,'ASSESSING'),(6,'FOLLOWING'),(8,'DISAPPEARED')],[8]),
 ('83',TF+[(102,97,2),(104,96,0)],[(5,'ASSESSING'),(6,'FOLLOWING'),(7,'FOLLOWING'),(8,'DISAPPEARED')],[8]),
 ('84',TN+[(102,95,0),(102,94,2)],[(5,'ASSESSING'),(6,'FOLLOWING'),(7,'FOLLOWING')],[]),
 ('85',TF+[(104,97,2),(102,96,2),(104,95,2)],[(5,'ASSESSING'),(6,'FOLLOWING'),(7,'DISAPPEARED')],[7]),
 ('87',TN+[(102,95,-2),(103,98,2),(104,99,2)],
  [(5,'ASSESSING'),(6,'FOLLOWING'),(7,'FOLLOWING'),(9,'FINISHED')],[]),
 ('flip-lifecycle',T+[(90,100,-2),(101,99,2),(102,98,2),(120,97,-2),(121,96,2)],
  [(5,'FOLLOWING'),(6,'FOLLOWING'),(8,'FINISHED')],[]),
]


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
@pytest.mark.parametrize('case,rows,changes,cancels',CASES,ids=[c[0] for c in CASES])
def test_literal_following_timeline(period,sign,case,rows,changes,cancels):
    c,steps=run(values(rows,sign),period)
    old=steps[4].structures[0]
    actual=[(i,r['status']) for i,s in enumerate(steps,1) for r in s.structures if r['id']==old['id']]
    assert actual==changes
    actual_cancel=[i for i,s in enumerate(steps,1) for e in s.events if e['route']=='structure_price_break' and e['relatedStructureId']==old['id']]
    assert actual_cancel==cancels
    ledger=[r for s in steps for r in s.structures if r['id']==old['id']]
    assert all(r['priceExtreme']==(103 if sign==1 else 97) for r in ledger) if case!='flip-lifecycle' else all(r['priceExtreme']==(102 if sign==1 else 98) for r in ledger)
    if case.startswith('78'):
        assert ledger[-1]['originWave']['price']==(105 if sign==1 else 95)
        assert ledger[-1]['originWave']['end']==steps[5].point['time']
        assert ledger[-1]['originWave']['count']==(3 if case.endswith('zero') else 4)
    if cancels:
        e=next(e for e in steps[cancels[0]-1].events if e['route']=='structure_price_break')
        assert e['eventReference']==old['originalReference'] and e['fromState']=='STRUCTURE'
        assert e['id']==c._id(e['time'],'CANCEL','structure_price_break',old['id'])
    if case=='74':
        assert steps[-1].point['ordinaryState']=='NONE' and c.wave.count==1
    if case in ('76','77'):
        assert [e['type'] for e in steps[-1].events]==['CANCEL','DULL']
    if case=='83':
        assert c.wave.count==1 and steps[-1].point['ordinaryState']=='NONE'
    if case=='87':
        assert steps[-1].point['activeReference']['startTime']==steps[2].point['time']


@pytest.mark.parametrize('sign',[1,-1])
def test_rc86_new_color_flip_id_is_the_only_future_target(sign):
    c,s=run(values(TS+[(104,100,2),(90,99,-2),(105,98,2)],sign))
    first=s[4].structures[0];second=s[6].structures[0]
    assert first['id']!=second['id']
    assert s[5].structures[0]['disappearanceReason']=='dif_return'
    assert s[-1].events[0]['relatedStructureId']==second['id']
    assert first['id'] not in [e['relatedStructureId'] for e in s[-1].events]


DUAL=[(100,200,2),(90,-200,-2),(101,100,2),(102,100,2),(103,99,2),
      (89,-100,-2),(88,-100,-2),(87,-101,-2),(104,90,2)]


@pytest.mark.parametrize('sign',[1,-1])
def test_rc88_old_cancel_and_new_other_direction_structure_both_survive(sign):
    c,s=run(values(DUAL,sign),observe=True)
    assert [e['route'] for e in s[-1].events]==['structure_price_break','color_flip']
    assert [r['status'] for r in s[-1].structures]==['DISAPPEARED','FOLLOWING']
    assert s[-1].point['ordinaryState']=='NONE'
    assert s[-1].decision['branch']=='color_flip'
    assert len(s[-1].decision['structureFollowChecks'])==1


@pytest.mark.parametrize('sign',[1,-1])
def test_rc96_two_slots_finish_and_disappear_independently(sign):
    rows=DUAL[:-1]+[(102,90,2),(102,91,2),(86,-90,-2)]
    c,s=run(values(rows,sign),observe=True)
    assert sum(v is not None for v in run(values(rows[:9],sign))[0].followed_structures.values())==2
    assert sorted(r['status'] for r in s[-1].structures)==['DISAPPEARED','FINISHED']
    assert len(s[-1].decision['structureFollowChecks'])==2
    assert len(s[-1].events)==1


@pytest.mark.parametrize('sign',[1,-1])
@pytest.mark.parametrize('zero',[False,True])
def test_rc89_past_price_breach_cannot_be_forged_back_to_following(sign,zero):
    rows=TF+([(102,97,2),(104,96,0),(102,95,2)] if zero else [(104,97,2),(102,96,2)])
    c,s=run(values(rows,sign));raw=c.snapshot();frozen=deepcopy(raw)
    fake=deepcopy(s[5].structures[0]);fake['nextSameColorStart']=s[6].point['time']
    raw['followedStructures'][fake['direction']]=fake
    with pytest.raises(ValueError,match='already broken'):
        c.restore(raw)
    assert c.snapshot()==frozen
    # Valid empty slot, separator crossing, and equality all remain accepted.
    for positive in [rows,TF+[(104,97,-2)],TF+[(103,97,2)]]:
        other,_=run(values(positive,sign));other.restore(other.snapshot())


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('case,rows,changes,cancels',CASES,ids=[c[0] for c in CASES])
def test_rc90_every_cut_restore_and_observation_preserve_complete_business(period,case,rows,changes,cancels):
    for sign in [1,-1]:
        all_bars=bars(values(rows,sign),period)
        plain,expected=run(values(rows,sign),period)
        observed,observations=run(values(rows,sign),period,True)
        assert [(s.point,s.events,s.structures) for s in expected]==[(s.point,s.events,s.structures) for s in observations]
        assert plain.snapshot()==observed.snapshot()
        for observed_step in observations:
            assert len(observed_step.decision['structureFollowChecks'])<=2
            for check in observed_step.decision['structureFollowChecks']:
                assert check['relatedStructureId']
                assert set(check['originWave'])=={'price','price_at'}
                assert (type(check['pricePassed']) is bool) if check['checked'] else check['pricePassed'] is None
        for cut in range(len(all_bars)+1):
            child=XxmCalculator(period=period,source_identity='finite-literals')
            for b in all_bars[:cut]: child.step(b)
            snap=child.snapshot();restored=XxmCalculator(period=period,source_identity='finite-literals')
            restored.restore(snap)
            assert [restored.step(b) for b in all_bars[cut:]]==expected[cut:]
            assert restored.snapshot()==plain.snapshot()


@pytest.mark.parametrize('sign',[1,-1])
@pytest.mark.parametrize('prefix',[TF,TF+[(102,97,2)]])
def test_rc95_failure_after_old_updates_leaves_all_inputs_and_outputs_unchanged(sign,prefix):
    c,previous=run(values(prefix,sign),observe=True);before=c.snapshot();copies=deepcopy(previous)
    with patch.object(c,'_validate_step',side_effect=ValueError('injected final failure')):
        with pytest.raises(ValueError): c.step(bars(values(prefix+[(104,96,2)],sign))[-1])
    assert c.snapshot()==before and previous==copies and c._decision_context is None


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
@pytest.mark.parametrize('begun',[False,True])
@pytest.mark.parametrize('fault',['finished','nan','future','direction','origin','separator','extra','duplicate','old_field'])
def test_rc89_literal_invalid_following_slots_are_atomic(period,sign,begun,fault):
    rows=TF+[(90,97,-2)]+([(102,96,2)] if begun else [])
    c,steps=run(values(rows,sign),period);before=c.snapshot();bad=deepcopy(before)
    direction='TOP' if sign==1 else 'BOTTOM';r=bad['followedStructures'][direction]
    if fault=='finished': r['status']='FINISHED'
    elif fault=='nan': r['originWave']['price']=float('nan')
    elif fault=='future': r['nextSameColorStart']=bars(values(rows+[(102,95,2)],sign),period)[-1].time
    elif fault=='direction': r['direction']='BOTTOM' if sign==1 else 'TOP'
    elif fault=='origin': r['originWave']=deepcopy(bad['history']['1' if sign==1 else '-1'][0])
    elif fault=='separator': r['firstOppositeAt']=steps[6].point['time']
    elif fault=='extra': bad['followedStructures']['third']=None
    elif fault=='duplicate': bad['followedStructures']['BOTTOM' if sign==1 else 'TOP']=deepcopy(r)
    else: r['lockedAt']=None
    saved=deepcopy(bad)
    with pytest.raises(ValueError): c.restore(bad)
    assert c.snapshot()==before
    if fault!='nan': assert bad==saved
    c.restore(before)


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
@pytest.mark.parametrize('rows',[DUAL,DUAL[:-1]+[(102,90,2),(102,91,2),(86,-90,-2)]])
def test_rc90_dual_slot_restore_all_cuts(period,sign,rows):
    c,expected=run(values(rows,sign),period)
    for cut in range(len(rows)+1):
        child,_=run(values(rows[:cut],sign),period)
        restored=XxmCalculator(period=period,source_identity='finite-literals')
        restored.restore(child.snapshot())
        assert [restored.step(b) for b in bars(values(rows,sign),period)[cut:]]==expected[cut:]
        assert restored.snapshot()==c.snapshot()


def test_pure_core_has_no_file_network_or_database_side_effects(monkeypatch):
    import builtins
    import socket
    from pathlib import Path
    def forbidden(*args,**kwargs): raise AssertionError('IO forbidden in pure core')
    monkeypatch.setattr(builtins,'open',forbidden)
    monkeypatch.setattr(Path,'read_text',forbidden)
    monkeypatch.setattr(Path,'write_text',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    c,steps=run(DUAL)
    child=XxmCalculator(period='day',source_identity='finite-literals')
    child.restore(c.snapshot())
    assert child.snapshot()==c.snapshot() and len(steps[-1].events)==2


@pytest.mark.parametrize('leading_zero',[False,True])
@pytest.mark.parametrize('invalid',[0,False,{},[]])
def test_empty_or_leading_zero_progress_requires_actual_none_slots(leading_zero,invalid):
    c,_=run([(100,0,0)] if leading_zero else [])
    before=c.snapshot();bad=deepcopy(before);bad['followedStructures']['TOP']=invalid
    with pytest.raises(ValueError): c.restore(bad)
    assert c.snapshot()==before
    c.restore(before)


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
@pytest.mark.parametrize('sign',[1,-1])
def test_rc89_original_far_reference_may_be_pruned_but_closed_origin_must_remain(period,sign):
    rows=[(100,300,2),(90,0,-2),(120,200,2),(110,0,-2),(130,201,2),(131,201,2),
          (132,198,2),(100,197,-2),(131,196,2),(132,195,2)]
    c,s=run(values(rows,sign),period);record=next(r for r in c.followed_structures.values() if r)
    assert record['originalReference']['startTime']==s[0].point['time']
    assert record['originWave']['start']==s[4].point['time']
    assert all(w.start!=record['originalReference']['startTime'] for w in c.history[sign])
    old=c.snapshot();c.restore(old)
    assert c.snapshot()==old
    child=XxmCalculator(period=period,source_identity='finite-literals');child.restore(old)
    assert child.followed_structures==c.followed_structures
