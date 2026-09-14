"""Synthetic acceptance for actual B3 provenance; no live research execution."""
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from scripts.research.index_market.chan import stock_b3_origin_audit as a
from scripts.research.index_market.tests.test_stock_exit_structure_review import fixture


@pytest.mark.parametrize('raw,caller,expected',[
    ('3a','treat_bsp3_after',('zs','next_seg')),('3b','treat_bsp3_before',('cmp_zs','seg'))])
def test_actual_producer_names(raw,caller,expected):
    assert a.source_names(raw,caller)==expected
    with pytest.raises(ValueError):a.source_names(raw,'nearest_center')
    with pytest.raises(ValueError):a.source_names('3b' if raw=='3a' else '3a',caller)


def test_distances_strict_boundaries_not_buffered():
    assert a.distance(10,10)==0
    assert a.distance(10,9)==.1
    assert a.distance(10,11)==-.1
    with pytest.raises(ValueError):a.distance(0,1)


def test_object_identity_and_latest_calculation_not_conflated():
    records={};old=object();new=object();z=object();seg=object()
    a.remember(records,old,'3a',1,{'v':1},z,seg)
    a.remember(records,old,'3a',1,{'v':1},z,seg)
    assert len(records[old]['3a']['alternatives'])==1
    a.remember(records,old,'3a',1,{'v':2},z,seg)
    assert len(records[old]['3a']['alternatives'])==2
    a.remember(records,old,'3a',2,{'v':3},z,seg)
    assert [v['source'] for v in records[old]['3a']['alternatives']]==[{'v':3}]
    a.remember(records,new,'3b',2,{'v':4},z,seg)
    assert '3a' not in records[new]


def test_multiplicity_budget(monkeypatch):
    monkeypatch.setattr(a,'SPEC',replace(a.SPEC,max_origins=1))
    records={};p=object()
    a.remember(records,p,'3a',0,{'v':1},None,None)
    with pytest.raises(ValueError):a.remember(records,p,'3a',0,{'v':2},None,None)


def binding():
    rows,kl,e=fixture();bi=kl.bi_list[1];bi.dir=NS(name='DOWN')
    point=kl.bs_point_lst.bsp_store_flat_dict[1];point.is_buy=True;point.type=[NS(value='3a')]
    e.update(buy=True,types=['3a'],group='B3')
    z=NS(begin=bi.begin_klc.lst[0],end=bi.end_klc.lst[0],low=7.8,high=8.0,peak_low=7.8,peak_high=8.2,
         is_sure=False,bi_in=kl.bi_list[0],bi_out=kl.bi_list[-1],begin_bi=bi,end_bi=bi,bi_lst=[bi])
    seg=type('CSeg',(),{})();seg.start_bi=kl.bi_list[0];seg.end_bi=kl.bi_list[-1]
    seg.idx=0;seg.seg_idx=None;seg.dir=NS(name='DOWN');seg.is_sure=False;seg.bi_list=kl.bi_list;seg.zs_lst=[z]
    conf=type('CPointConfig',(),{})();conf.bsp3_follow_1=False
    kl.zs_list.zs_lst=[z]
    source=a.origin_snapshot(rows,3,bi,z,seg,conf)
    snap=a.review.snapshot(kl,rows,e)
    origins={'3a':dict(index=3,alternatives=[dict(source=source,center=z,segment=seg)])}
    return rows,kl,e,z,seg,source,snap,origins


def test_provenance_freeze_readonly_and_next_open_not_in_snapshot():
    rows,kl,e,z,seg,source,snap,origins=binding()
    out=a.freeze_origins(rows,e,snap,origins,kl)
    assert out['status']=='unique'
    assert not out['origins'][0]['center_sure'] and not out['origins'][0]['segment_sure']
    assert out['origins'][0]['geometry_at_confirmation']
    assert 'execution_observation' not in out
    assert out['origins'][0]['close_to_center']==pytest.approx((8.5-8)/8.5)
    assert a.freeze_origins(rows[:4],e,snap,origins,kl)==out


@pytest.mark.parametrize('change',['missing','ambiguous','boundary','detached'])
def test_unresolved_origins_are_not_silently_repaired(change):
    rows,kl,e,z,seg,source,snap,origins=binding()
    if change=='missing':origins={}
    elif change=='ambiguous':origins['3a']['alternatives']*=2
    elif change=='boundary':z.high=8.3
    else:kl.zs_list.zs_lst=[]
    out=a.freeze_origins(rows,e,snap,origins,kl)
    if change in ['missing','ambiguous']:assert out['status']==change
    elif change=='boundary':
        assert out['origins'][0]['boundary_changed']
        assert not out['origins'][0]['geometry_at_confirmation']
        assert out['origins'][0]['source']['objects'][source['refs']['center']]['high']==8.0
    else:assert not out['origins'][0]['center_in_current_list']


def test_generation_future_reference_or_geometry_rejected():
    rows,kl,e,z,seg,source,snap,origins=binding()
    source['index']=4
    with pytest.raises(ValueError,match='as of'):a.freeze_origins(rows,e,snap,origins,kl)
    source['index']=3;source['objects'][source['refs']['center']]['high']=9
    with pytest.raises(ValueError,match='violates'):a.freeze_origins(rows,e,snap,origins,kl)
    with pytest.raises(ValueError,match='future'):a.origin_snapshot(rows,1,kl.bi_list[1],z,seg,None)


def test_equality_to_center_is_valid():
    rows,kl,e,z,seg,source,snap,origins=binding()
    z.high=8.2;source['objects'][source['refs']['center']]['high']=8.2
    out=a.freeze_origins(rows,e,snap,origins,kl)
    assert out['origins'][0]['geometry_at_confirmation']


def test_mixed_raw_types_do_not_create_more_b3_opportunities(monkeypatch):
    monkeypatch.setattr(a,'SPEC',replace(a.SPEC,counts=(('C',1),)))
    data=dict(cases=[dict(event_ids=['b3','b2'])],events=[dict(event_id='b3',group='B3',buy=True,types=['2','3b']),dict(event_id='b2',group='B2',buy=True)])
    assert a.select_targets(data,'C')==[data['events'][0]]
    data['events'][0]['buy']=False
    with pytest.raises(ValueError):a.select_targets(data,'C')


def test_case_selection_is_chronological_not_profit(monkeypatch):
    monkeypatch.setattr(a,'SPEC',replace(a.SPEC,cases=(('C','t1'),)))
    es=[dict(event_id='b',code='C',signal_time='t2',types=['3b']),dict(event_id='a',code='C',signal_time='t1',types=['3a'])]
    assert a.case_ids(es)==['a','b']
    assert a.case_ids(es[::-1])==['a','b']
    with pytest.raises(ValueError):a.case_ids(es[:1])


def test_worker_source_failure_propagates(monkeypatch):
    def fail():raise ValueError('source drift')
    monkeypatch.setattr(a.audit,'source_gate',fail)
    sent=[];a.worker('C',[],NS(send=sent.append,close=lambda:None))
    assert sent==[dict(status='failed',error='ValueError: source drift')]


def test_existing_output_rejected_before_reading_any_sources(tmp_path):
    with pytest.raises(ValueError,match='new child'):a.execute(tmp_path)
