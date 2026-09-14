"""Synthetic section-32 cases; never loads local uncommitted reports or the Lake."""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from scripts.research.index_market.chan import stock_exit_structure_review as r


def pairs():
    return [dict(code='C',signal_time=f't{i}',delta=d) for i,d in enumerate((.01,.04,.03,.02,-.01,-.04,-.03,-.02,0))]


def test_selection_extreme_median_earliest_and_order():
    selected=r.select_cases(pairs())
    assert [x['case_id'] for x in selected]==['C|t1','C|t3','C|t0','C|t5','C|t7','C|t4']
    assert r.select_cases(list(reversed(pairs())))==selected


def test_ties_and_insufficient_or_duplicate():
    ps=pairs()
    for p in ps:
        p['delta']=.1 if p['delta']>0 else -.1 if p['delta']<0 else 0
    assert r.select_cases(ps)==r.select_cases(list(reversed(ps)))
    assert len({p['case_id'] for p in r.select_cases(ps)})==6
    for invalid in ([],ps[:3],ps+[ps[0]]):
        with pytest.raises(ValueError): r.select_cases(invalid)


def test_label_is_relative_change_not_profit():
    assert r.label(dict(delta=.01,after={'return_value':-.2}))=='better'
    assert r.label(dict(delta=-.01,after={'return_value':.2}))=='worse'
    assert r.label(dict(delta=0))=='unchanged'


@pytest.mark.parametrize('price,expected',[(9,'below'),(10,'inside'),(12,'inside'),(13,'above')])
def test_center_inclusive_boundaries(price,expected):
    assert r.position(price,dict(low=10,high=12))==expected
    assert r.position(price,None)=='missing'


def test_s2_geometry_and_missing():
    line=dict(index=2,begin_value=8,end_value=9)
    prev=dict(index=1,begin_value=10,end_value=8)
    assert r.s2_geometry(line,prev,7.9)==dict(retrace=.5,rebound_below_prior_high=True,confirm_below_prior_low=True)
    assert not r.s2_geometry(line,prev,8)['confirm_below_prior_low']
    assert r.s2_geometry(line,None,8) is None
    assert r.s2_geometry(line,dict(prev,index=0),8) is None
    assert r.s2_geometry(line,dict(prev,end_value=10),8) is None


def fixture():
    rows=[dict(time=f't{i}',close=8.5) for i in range(4)]
    units=[NS(idx=i,low=8+i/10,high=10-i/10) for i in range(4)]
    def bi(idx,first,last,direction):
        b=type('CBi',(),{})()
        b.idx=idx; b.seg_idx=None; b.dir=NS(name=direction); b.is_sure=True; b.parent_seg=None
        b.begin_klc=NS(lst=[units[first]],low=units[first].low,high=units[first].high)
        b.end_klc=NS(lst=[units[last]],low=units[last].low,high=units[last].high)
        return b
    prev=bi(0,0,1,'DOWN'); line=bi(1,1,2,'UP'); following=bi(2,2,3,'DOWN')
    p=NS(bi=line,is_buy=False,type=[NS(value='2')],klu=units[2],relate_bsp1=None)
    kl=NS(bs_point_lst=NS(bsp_store_flat_dict={1:p}),bi_list=[prev,line,following],seg_list=[],zs_list=NS(zs_lst=[]))
    e=dict(event_id='e',signal_index=3,bi_index=1,buy=False,types=['2'],start_index=1,end_index=2,anchor_index=2,group='S2',lag_bars=1)
    return rows,kl,e


def test_snapshot_missing_parent_and_readonly():
    rows,kl,e=fixture(); before=deepcopy(vars(kl.bi_list[1]))
    snap=r.snapshot(kl,rows,e)
    assert snap['features']['parent_state']=='missing'
    assert snap['features']['center_position']=='missing'
    assert snap['features']['latest_sure_segment']=='missing'
    assert vars(kl.bi_list[1])==before


@pytest.mark.parametrize('sure',[True,False])
def test_snapshot_parent_status_not_promoted(sure):
    rows,kl,e=fixture()
    parent=type('CSeg',(),{})(); parent.idx=0;parent.seg_idx=None;parent.is_sure=sure
    parent.dir=NS(name='DOWN');parent.start_bi=kl.bi_list[0];parent.end_bi=kl.bi_list[-1]
    parent.bi_list=kl.bi_list;parent.zs_lst=[];kl.seg_list=[parent]
    kl.bi_list[1].parent_seg=parent
    snap=r.snapshot(kl,rows,e)
    assert snap['features']['parent_state']==f'DOWN/{"sure" if sure else "tentative"}'
    assert snap['features']['latest_sure_segment']==('DOWN' if sure else 'missing')


@pytest.mark.parametrize('corruption',['future','types','unsure','missing_point','parent'])
def test_snapshot_rejects_bad_evidence(corruption):
    rows,kl,e=fixture()
    if corruption=='future': e['signal_index']=1
    elif corruption=='types': e['types']=['3a']
    elif corruption=='unsure': kl.bi_list[1].is_sure=False
    elif corruption=='missing_point': kl.bs_point_lst.bsp_store_flat_dict={}
    else: kl.bi_list[1].parent_seg=NS(bi_list=[])
    with pytest.raises(ValueError): r.snapshot(kl,rows,e)


def test_sink_frame_and_coverage():
    rows,kl,e=fixture();sink=r.SnapshotSink(rows,[e])
    with pytest.raises(ValueError,match='frame'):sink([])
    with pytest.raises(ValueError,match='targets'):sink.finish()
    with pytest.raises(ValueError,match='duplicate'):r.SnapshotSink(rows,[e,e])


def test_sink_first_confirmation_and_exact_capture(monkeypatch):
    rows,kl,e=fixture()
    def fake_replay(sink, emitted):
        i=3;new=emitted
        # kl must be local just as in the frozen production replay.
        kl=engine
        sink([])
    engine=kl;monkeypatch.setattr(r,'replay',fake_replay)
    sink=r.SnapshotSink(rows,[e]);fake_replay(sink,[e]);assert set(sink.finish())=={'e'}
    with pytest.raises(ValueError,match='first-confirmed'):fake_replay(r.SnapshotSink(rows,[e]),[])


def test_multi_type_does_not_multiply_opportunities():
    def s(group):return dict(features=dict(group=group,parent_state='missing',latest_sure_segment='UP',center_position='above'))
    results={'C':dict(pairs=[dict(code='C',signal_time='t',delta=-.1,used_sell_event_ids=['e1','e2'])],snapshots={'e1':s('S1'),'e2':s('S2')})}
    rows=r.feature_rows(results)
    assert len(rows)==1 and rows[0]['group']=='S1|S2'
    assert all(sum(sum(v.values()) for v in table.values())==1 for table in r.descriptive(rows).values())


def test_targets_union_and_missing_event_rejected():
    ps=[dict(code='C',signal_time='t',event_ids=['b'],used_sell_event_ids=['s'])]
    data=dict(events=[dict(event_id='b'),dict(event_id='s')])
    assert r.targets_for(data,ps,{'C|t'})==data['events']
    assert r.targets_for(data,ps,set())==[dict(event_id='s')]
    with pytest.raises(ValueError):r.targets_for({'events':[]},ps,set())


def test_worker_failure_is_explicit(monkeypatch):
    def fail():raise ValueError('unapproved source')
    monkeypatch.setattr(r.audit,'source_gate',fail)
    got=[];sender=NS(send=got.append,close=lambda:None)
    r.stock_worker('C',set(),'x',sender)
    assert got==[dict(status='failed',error='ValueError: unapproved source')]
