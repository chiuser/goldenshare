"""Synthetic C2 selection checks; no real reports, Lake or new backtest."""
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from scripts.research.index_market.chan.minute_comparison import SPEC as C1
from scripts.research.index_market.chan.minute_nonoverlap import (
    SPEC, execute, select_nonoverlap, selection_diff, verify_selection,
)


DAYS = ['2024-02-08','2024-02-19','2024-02-20','2024-02-21']


def event(ts, **extra):
    return dict(event_id=ts,signal_time=ts,evaluation=True,group='B3',**extra)


def test_only_policy_and_evidence_metadata_differ():
    a,b=asdict(C1),asdict(SPEC)
    assert {k for k in a if a[k]!=b[k]}=={'variant'}
    assert b['cooldown_days']==20 and b['main_comparisons']==36 and b['min_events']==50


def test_before_equal_and_after_next_session_close():
    ee=[event(ts) for ts in ('2024-02-08 10:30:00','2024-02-19 14:00:00',
                            '2024-02-19 15:00:00','2024-02-20 10:30:00','2024-02-21 10:30:00')]
    kept,ledger=select_nonoverlap(ee,DAYS)
    assert kept==[ee[0],ee[2],ee[4]]
    assert ledger[0]['observation_end']=='2024-02-19 15:00:00'
    assert ledger[1]['reason']=='overlap' and ledger[2]['selected']
    assert ledger[-1]['reason']=='selected_tail'
    assert verify_selection(ee,DAYS,kept,ledger)['sql_selected']==3


def test_rejected_event_does_not_extend_window():
    ee=[event('2024-02-08 15:00:00'),event('2024-02-19 10:30:00'),event('2024-02-20 10:30:00')]
    assert select_nonoverlap(ee,DAYS)[0]==[ee[0],ee[2]]


def test_initialization_other_group_not_occupying_window():
    ee=[event('2024-02-08 10:30:00'),event('2024-02-08 11:30:00'),event('2024-02-08 14:00:00')]
    ee[0]['evaluation']=False
    ee[1]['group']='S3'
    kept,ledger=select_nonoverlap(ee,DAYS)
    assert kept==[ee[2]] and len(ledger)==1
    verify_selection(ee,DAYS,kept,ledger)


def test_selection_needs_no_prices_labels_or_support():
    ee=[event('2024-02-08 10:30:00'),event('2024-02-08 11:30:00'),event('2024-02-19 15:00:00')]
    before=deepcopy(ee)
    a=select_nonoverlap(ee,DAYS)[1]
    ee[0].update(q=-999,supported=False,target_time='2099-01-01 15:00:00')
    ee[1].update(q=999,supported=True)
    assert select_nonoverlap(ee,DAYS)[1]==a
    assert before[0].keys()=={'event_id','signal_time','evaluation','group'}


def test_tail_event_retained_and_later_same_day_blocked():
    ee=[event('2024-02-21 10:30:00'),event('2024-02-21 11:30:00')]
    kept,ledger=select_nonoverlap(ee,DAYS)
    assert kept==ee[:1] and ledger[0]['observation_end'] is None
    verify_selection(ee,DAYS,kept,ledger)


def test_earlier_added_event_can_displace_old_later_event():
    ee=[event('2024-02-08 10:30:00'),event('2024-02-20 10:30:00'),event('2024-02-21 10:30:00')]
    new,_=select_nonoverlap(ee,DAYS)
    delta=selection_diff([ee[0],ee[2]],new)
    assert delta==dict(retained=[ee[0]['event_id']],added=[ee[1]['event_id']],removed=[ee[2]['event_id']])


@pytest.mark.parametrize('kind',['order','duplicate','calendar','outside'])
def test_malformed_inputs_rejected(kind):
    ee=[event('2024-02-08 10:30:00'),event('2024-02-19 15:00:00')]
    days=DAYS
    if kind=='order':
        ee.reverse()
    if kind=='duplicate':
        ee.append(ee[-1])
    if kind=='calendar':
        days=DAYS[::-1]
    if kind=='outside':
        ee=[event('2023-01-01 10:30:00')]
    with pytest.raises(ValueError):
        select_nonoverlap(ee,days)


def test_prefix_is_stable_and_does_not_mutate_inputs():
    ee=[event('2024-02-08 10:30:00'),event('2024-02-19 15:00:00'),event('2024-02-20 15:00:00')]
    before=deepcopy(ee)
    full=select_nonoverlap(ee,DAYS)[0]
    assert select_nonoverlap(ee[:2],DAYS)[0]==[e for e in full if e['signal_time']<=ee[1]['signal_time']]
    assert ee==before


def test_empty_and_independent_method_calls():
    assert select_nonoverlap([],DAYS)==([],[])
    verify_selection([],DAYS,[],[])
    ee=[event('2024-02-08 10:30:00')]
    assert select_nonoverlap(ee,DAYS)==select_nonoverlap(ee,DAYS)


@pytest.mark.parametrize('field,value',[('cooldown_days',1),('tolerance_atr',.5),('seed',1),('min_events',10)])
def test_unapproved_changes_rejected_before_source(field,value,tmp_path,monkeypatch):
    def forbidden(*args): pytest.fail('must not read source')
    monkeypatch.setattr('scripts.research.index_market.chan.minute_nonoverlap.authenticate_reference',forbidden)
    with pytest.raises(ValueError,match='unapproved'):
        execute(tmp_path/'new',replace(SPEC,**{field:value}))


def test_existing_or_outside_output_rejected(tmp_path):
    with pytest.raises(ValueError,match='new child'):
        execute(tmp_path)
