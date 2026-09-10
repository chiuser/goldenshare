"""Synthetic structure snapshots only; no third-party import, replay or Lake."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from scripts.research.index_market.chan.minute_structure import (
    SPEC, CLASS_FIELDS, classify, endpoint, execute, grouped, owner_of,
    state, take_snapshot,
)


def element(index):
    return NS(idx=index,is_sure=True,get_begin_klu=lambda:NS(idx=index),get_end_klu=lambda:NS(idx=index))


def segment(index, start, end, up=True, sure=False):
    return NS(idx=index,start_bi=element(start),end_bi=element(end),bi_list=[element(i) for i in range(start,end+1)],
              is_sure=sure,is_up=lambda:up,get_begin_klu=lambda:NS(idx=start),get_end_klu=lambda:NS(idx=end),
              get_begin_val=lambda:100.,get_end_val=lambda:105.)


def center(low=99.,high=103.,sure=False):
    return NS(begin=NS(idx=1),end=NS(idx=3),begin_bi=element(1),end_bi=element(3),low=low,high=high,
              peak_low=98.,peak_high=106.,is_sure=sure,bi_lst=[element(1),element(2),element(3)],
              bi_in=element(0),bi_out=element(4),is_one_bi_zs=lambda:False)


def fixture():
    rows = [dict(time=f'2024-01-01 {10+i:02d}:00:00',close=104.) for i in range(6)]
    parent = segment(0,0,3)
    bi = NS(idx=2,seg_idx=0,parent_seg=parent)
    kl = NS(seg_list=[parent],segseg_list=[],segzs_list=NS(zs_lst=[center()]))
    return rows,kl,NS(bi=bi)


def test_snapshot_golden_and_missing_higher_segment():
    rows,kl,bsp = fixture()
    s = take_snapshot(kl,bsp,rows,5)
    assert s['owner']['index']==0 and not s['owner']['sure']
    assert s['pointer_live'] and s['pointer_matches_owner']
    assert s['classes']==dict(owner_state='UP_PROVISIONAL',latest_segment_state='UP_PROVISIONAL',
                               last_confirmed_direction='MISSING',higher_segment_state='MISSING',
                               higher_center_position='ABOVE',higher_centers_relation='INSUFFICIENT')


def test_snapshot_does_not_repaint_when_engine_objects_mutate():
    rows,kl,bsp = fixture()
    s = take_snapshot(kl,bsp,rows,5)
    frozen = deepcopy(s)
    kl.seg_list[0].is_sure = True
    kl.seg_list[0].end_bi.idx = 100
    kl.segzs_list.zs_lst[0].high = 1000.
    kl.segzs_list.zs_lst.clear()
    assert s==frozen


def test_stale_pointer_not_treated_as_live_owner():
    rows,kl,bsp = fixture()
    stale = segment(0,0,3,sure=True)
    bsp.bi.parent_seg = stale
    s = take_snapshot(kl,bsp,rows,5)
    assert not s['pointer_live'] and not s['pointer_matches_owner']
    assert s['parent_pointer']['sure'] and not s['owner']['sure']
    assert s['classes']['owner_state']=='UP_PROVISIONAL'


def test_next_segment_index_is_not_an_existing_owner():
    rows,kl,bsp = fixture()
    bsp.bi.idx, bsp.bi.seg_idx, bsp.bi.parent_seg = 5,1,None
    s = take_snapshot(kl,bsp,rows,5)
    assert s['owner'] is None and s['classes']['owner_state']=='MISSING'
    assert s['latest_segment'] is not None


def test_overlapping_segment_owners_rejected():
    with pytest.raises(ValueError,match='multiple'):
        owner_of([segment(0,0,3),segment(1,2,5)],2)


@pytest.mark.parametrize('index',[-1,6])
def test_future_or_negative_endpoint_rejected(index):
    rows,_,_ = fixture()
    with pytest.raises(ValueError,match='prefix'):
        endpoint(NS(idx=index),rows,5)


def test_future_center_member_rejected():
    rows,kl,bsp = fixture()
    kl.segzs_list.zs_lst[0].bi_lst.append(element(6))
    with pytest.raises(ValueError,match='prefix'):
        take_snapshot(kl,bsp,rows,5)


@pytest.mark.parametrize('close,position',[(99.,'INSIDE'),(103.,'INSIDE'),(98.9,'BELOW'),(103.1,'ABOVE')])
def test_center_price_boundaries(close,position):
    rows,kl,bsp = fixture()
    snapshot = take_snapshot(kl,bsp,rows,5)
    assert classify(snapshot,close)['higher_center_position']==position


@pytest.mark.parametrize('low,high,relation',[(103.,105.,'OVERLAP'),(103.1,105.,'UP_DISJOINT'),(96.,98.9,'DOWN_DISJOINT'),(97.,99.,'OVERLAP')])
def test_center_step_relation_with_touching_edges(low,high,relation):
    rows,kl,bsp = fixture()
    kl.segzs_list.zs_lst.append(center(low,high))
    s = take_snapshot(kl,bsp,rows,5)
    assert s['classes']['higher_centers_relation']==relation


def test_missing_center_explicit_and_latest_vs_confirmed_distinct():
    rows,kl,bsp = fixture()
    kl.segzs_list.zs_lst=[]
    kl.seg_list[0].is_sure=True
    kl.seg_list.append(segment(1,4,5,up=False))
    s = take_snapshot(kl,bsp,rows,5)
    assert s['classes']['latest_segment_state']=='DOWN_PROVISIONAL'
    assert s['classes']['last_confirmed_direction']=='UP'
    assert s['classes']['higher_center_position']=='MISSING'


def test_group_totals_keep_missing_and_years():
    records=[]
    for year,q,cat in [('2024',.1,'MISSING'),('2025',-.1,'MISSING'),('2025',.2,'UP_SURE')]:
        records.append(dict(date=year+'-01-01',q=q,mae=-.01,structure={'classes':dict.fromkeys(CLASS_FIELDS,cat)}))
    result=grouped(records)
    for field in CLASS_FIELDS:
        assert sum(r['all']['n'] for r in result[field].values())==3
        assert result[field]['MISSING']['all']['q']==0.
        assert result[field]['MISSING']['without_2024']['n']==1
        assert result[field]['MISSING']['without_2024']['q']==-.1
    assert state(None)=='MISSING'


@pytest.mark.parametrize('patch',[dict(tail_count=5),dict(version='other'),dict(omit_year='2025')])
def test_unapproved_configuration_stops_before_external_io(tmp_path,patch):
    with pytest.raises(ValueError,match='unapproved'):
        execute(tmp_path/'source',tmp_path/'result',replace(SPEC,**patch))
