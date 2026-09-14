"""Synthetic cohort, provenance and predeclared-screen checks."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import socket
from types import SimpleNamespace

import pytest

from scripts.research.index_market.chan import stock_any_sell_cohort as s


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args,**kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket,'create_connection',deny)


def roster():
    codes=list(dict(s.SPEC.counts))
    return ([dict(code=c,name=c,status='complete') for c in codes],dict(codes=codes),
            dict(stocks=[dict(ts_code=c,name=c) for c in codes]))


def test_frozen_roster_and_count():
    assert len(s.validate_roster(*roster()))==10
    assert sum(dict(s.SPEC.counts).values())==163
    assert sum(n for c,n in s.SPEC.counts if c not in s.policy.SPEC.codes)==133


@pytest.mark.parametrize('change',['missing','duplicate','BJ','name','status','origin','initial'])
def test_bad_roster_rejected(change):
    statuses,origin,initial=roster()
    if change=='missing': statuses.pop()
    elif change=='duplicate': statuses[-1]=deepcopy(statuses[0])
    elif change=='BJ': statuses[0]['code']='920000.BJ'
    elif change=='name': statuses[0]['name']='different'
    elif change=='status': statuses[0]['status']='failed'
    elif change=='origin': origin['codes']=origin['codes'][:-1]
    elif change=='initial': initial['stocks']=initial['stocks'][:-1]
    with pytest.raises(ValueError): s.validate_roster(statuses,origin,initial)


def test_header_hashes_and_spec_drift():
    statuses,origin,initial=roster()
    spec=asdict(s.old.SPEC);spec['source']='original'
    setup=dict(spec=json.loads(json.dumps(spec)),periods={k:list(v) for k,v in s.old.PERIODS.items()},
               source_sha256='calendar-hash',code_sha256={})
    origin.update(previous_source_sha256='initial-hash',code_sha256={})
    initial.update(days=['2025-01-01'],code_sha256={})
    records={'exits/manifest.json':dict(status='complete',setup_sha256='setup-hash',aggregate_sha256='aggregate-hash'),
        'exits/setup.json':setup,'calendar/source.json':origin,'initial/source.json':initial,
        'calendar/status_10.json':statuses,'exits/aggregate.json':[dict(period='full',mode='sell',n=163)]}
    reads=[]
    def read(k,h=None): reads.append((k,h));return records[k]
    store=SimpleNamespace(read=read,original_path=lambda _: 'original')
    assert len(s.load_header(store)['names'])==10
    assert ('exits/setup.json','setup-hash') in reads and ('calendar/source.json','calendar-hash') in reads
    assert ('initial/source.json','initial-hash') in reads and ('exits/aggregate.json','aggregate-hash') in reads
    setup['spec']['max_days']=1
    with pytest.raises(ValueError,match='spec'): s.load_header(store)


@pytest.mark.parametrize('change',['count','identity','types','buy','time'])
def test_common_frozen_identity(change,monkeypatch):
    code='000731.SZ';monkeypatch.setattr(s,'SPEC',replace(s.SPEC,counts=((code,1),)))
    c=dict(code=code,signal_time='t',signal_index=0,event_ids=['e'],types=['B3'])
    e=dict(event_id='e',signal_time='t',buy=True,group='B3')
    s.validate_common([c],[e],['t'],code)
    cases=[c]
    if change=='count': cases=[]
    elif change=='identity': c['code']='002225.SZ'
    elif change=='types': c['types']=['B1']
    elif change=='buy': e['buy']=False
    else: e['signal_time']='future'
    with pytest.raises(ValueError): s.validate_common(cases,[e],['t'],code)


def experiment(deltas=None):
    codes=[f'C{i}' for i in range(8)]
    results={};selection={'membership':{}}
    for i,c in enumerate(codes):
        pairs=[]
        for time in ('2023-01-01','2025-01-01'):
            d=deltas[i] if deltas is not None else .01
            def arm(r):return dict(status='closed',return_value=r,reason='sell',holding_days=1,
                adverse=-.1,favorable=.2,exit_time=time)
            pairs.append(dict(code=c,signal_time=time,before=arm(0),after=arm(d),fixed60=arm(0),delta=d,
                              old_category='nonmatching_only',new_category='matched_sell_exit'))
        results[c]={'pairs':pairs}
        membership={'early':['2023-01-01'],'late':['2025-01-01'],'full':['2023-01-01','2025-01-01']}
        selection['membership'][c]={'periods':deepcopy(membership),'nonoverlap':deepcopy(membership)}
    return results,selection,codes


def test_screen_and_remove_whole_stock():
    r,sel,codes=experiment(); out=s.screening(r,sel,codes)
    assert out['passed'] and out['positive_stocks']==8
    assert out['without_best_stock']['n']==14 and out['best_stock']=='C0'


def test_previous_two_excluded_and_weights_differ():
    r,sel,codes=experiment([.08,0,0,0,0,0,0,0])
    for c in s.policy.SPEC.codes:
        r[c]={'pairs':[dict(r['C0']['pairs'][0],delta=999)]}
    r['C0']['pairs'].append(deepcopy(r['C0']['pairs'][0]))
    summary=s.group_summary(r,sel,codes)
    assert summary['all']['n']==17 and len(summary['stocks'])==8
    assert summary['stock_equal_weight_mean']['after']==pytest.approx(.01)
    assert summary['all']['after']['mean']==pytest.approx(.24/17)
    gates=s.screening(r,sel,codes)['gates']
    assert not gates['without_best_stock_positive'] and not gates['at_least_half_stocks']


@pytest.mark.parametrize('kind',['early','late','nonoverlap','unclosed','mae','empty'])
def test_failed_stability_is_not_passed(kind):
    r,sel,codes=experiment()
    if kind in ('early','late'):
        for c in codes:sel['membership'][c]['periods'][kind]=[]
    elif kind=='nonoverlap':
        for c in codes:sel['membership'][c]['nonoverlap']['full']=[]
    elif kind=='unclosed':r['C0']['pairs'][0]['after']={'status':'unclosed'}
    elif kind=='mae':
        for c in codes:
            for p in r[c]['pairs']:p['after']['adverse']=-.2
    else:codes=[]
    assert not s.screening(r,sel,codes)['passed']


@pytest.mark.parametrize('success',[True,False])
def test_worker_delivery_or_failure_is_not_silently_skipped(monkeypatch,success):
    closed=[]
    receiver=SimpleNamespace(poll=lambda _:True,recv=lambda:dict(status='complete',result={'pairs':[]})
        if success else dict(status='failed',error='source mismatch'),close=lambda:closed.append('receiver'))
    sender=SimpleNamespace(close=lambda:closed.append('sender'))
    process=SimpleNamespace(start=lambda:None,join=lambda **k:None,is_alive=lambda:False,exitcode=0)
    context=SimpleNamespace(Pipe=lambda **k:(receiver,sender),Process=lambda **k:process)
    monkeypatch.setattr(s.multiprocessing,'get_context',lambda method:context)
    monkeypatch.setattr(s.audit,'budget',lambda *args:0)
    if success:assert s.run_process('000731.SZ',0)=={'pairs':[]}
    else:
        with pytest.raises(RuntimeError,match='source mismatch'):s.run_process('000731.SZ',0)
    assert closed==['sender','receiver']
