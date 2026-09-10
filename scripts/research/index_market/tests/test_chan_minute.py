"""Isolated minute semantics and label goldens; no real Lake or third-party imports."""
from dataclasses import replace
import json

import duckdb
import pytest

from scripts.research.index_market.chan.minute_data import MINUTE, slots, validate
from scripts.research.index_market.chan.minute_replay import MinuteLedger
from scripts.research.index_market.chan.minute_score import (
    block_intervals, label_rows, select_events, summarize,
)
from scripts.research.index_market.chan.run_minute import independent_score_check


def point(**kwargs):
    return dict(buy=True,sure=True,types=['3a'],start_index=0,end_index=1,
                anchor_index=1,start_time='2022-01-04 10:30:00',
                end_time='2022-01-04 11:30:00',anchor_time='2022-01-04 11:30:00',**kwargs)


def test_minute_first_trigger_and_withdrawal():
    ledger = MinuteLedger('000300.SH',60)
    p = point()
    uncertain = dict(p,sure=False)
    assert ledger.step('2022-01-04 14:00:00',2,[uncertain])[0]==[]
    events,_ = ledger.step('2022-01-04 15:00:00',3,[p])
    assert len(events)==1 and events[0]['lag_bars']==2
    assert '|K_60M|' in events[0]['event_id']
    assert '2022-01-04 10:30:00' in events[0]['event_id']
    assert ledger.step('2022-01-05 10:30:00',4,[])[0]==[]
    assert ledger.step('2022-01-05 11:30:00',5,[p])[0]==[]
    assert len(ledger.triggered)==1


@pytest.mark.parametrize('labels,sure', [(['1p'],True),(['2s'],True),(['3b'],False)])
def test_excluded(labels,sure):
    p = dict(point(),types=labels,sure=sure)
    assert MinuteLedger('000300.SH',30).step('2022-01-04 14:00:00',2,[p])[0]==[]


def test_frequency_identity_and_order():
    p = point()
    a = MinuteLedger('000300.SH',30)
    b = MinuteLedger('000300.SH',60)
    assert a.step('2022-01-04 14:00:00',2,[p])[0][0]['event_id'] != b.step('2022-01-04 14:00:00',2,[p])[0][0]['event_id']
    with pytest.raises(ValueError):
        a.step('2022-01-04 14:00:00',3,[p])
    with pytest.raises(ValueError):
        MinuteLedger('000300.SH',15)
    with pytest.raises(ValueError):
        b.step('2022-01-04 15:00:00',3,[dict(p,anchor_index=9)])


def fixture_bars():
    days = ['2022-01-07','2022-01-10','2022-01-11']
    rows = []
    for day in days:
        for slot in slots(60):
            i = len(rows)
            rows.append(dict(code='000300.SH',frequency=60,date=day,time=day+' '+slot,
                open=100+i,close=101+i,low=99+i,high=102+i))
    return rows,days


def test_horizon_days_next_open_weekend_and_tail():
    rows,days = fixture_bars()
    labels = label_rows(rows,days,1)
    assert len(labels)==8
    morning = labels[1]
    assert morning['entry_bar_end']=='2022-01-07 14:00:00'
    assert morning['target_time']=='2022-01-10 15:00:00'
    assert morning['q']==pytest.approx(108/102-1)
    close = labels[3]
    assert close['entry_bar_end']=='2022-01-10 10:30:00'
    assert close['r']==pytest.approx(108/104-1)
    assert close['mae']==pytest.approx(103/104-1)
    assert close['mfe']==pytest.approx(109/104-1)
    assert 8 not in labels
    assert label_rows(rows,days,3)=={}


def test_cooldown_days_not_bars_and_initialization():
    days = [f'2022-01-{i:02}' for i in range(1,31)]
    events = [dict(group='B3',evaluation=i>0,signal_time=days[i]+' 10:30:00') for i in (0,1,2,20,21)]
    selected = select_events(events,days,'B3',True)
    assert [e['signal_time'][:10] for e in selected]==[days[1],days[21]]
    assert len(select_events(events,days,'B3',False))==4


def test_matched_baseline_and_sql_check():
    rows,days = fixture_bars()
    labels = label_rows(rows,days,1)
    event = dict(event_id='x',signal_index=3)
    result,scored = summarize([event],labels)
    assert result['baseline_q']==pytest.approx((labels[3]['q']+labels[7]['q'])/2)
    assert result['lift_q']==pytest.approx(labels[3]['q']-result['baseline_q'])
    assert independent_score_check(rows,scored)
    with pytest.raises(ValueError):
        independent_score_check(rows,[dict(scored[0],q=100)])
    assert summarize([dict(event_id='tail',signal_index=8)],labels)[0]['tail_excluded']==1


def test_bootstrap_deterministic_and_empty():
    rows,days = fixture_bars()
    labels = label_rows(rows,days,1)
    _,scored = summarize([dict(event_id='x',signal_index=3)],labels)
    spec = replace(MINUTE,repetitions=50,blocks=(1,2))
    result = block_intervals(scored,labels,days,spec)
    assert result==block_intervals(scored,labels,days,spec)
    assert result['2']['valid_repetitions']==50
    assert block_intervals([],labels,days,spec)=={}


def quality_con():
    con = duckdb.connect(':memory:')
    con.execute("CREATE TABLE calendar AS SELECT DATE '2022-01-04' AS trade_date,true AS is_open")
    con.execute('''CREATE TABLE prices(ts_code VARCHAR,freq INTEGER,trade_date DATE,
        trade_time TIMESTAMP,open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,
        vol DOUBLE,amount DOUBLE,exchange VARCHAR,partition_date VARCHAR,partition_freq INTEGER)''')
    con.execute('''INSERT INTO prices SELECT '000300.SH',60,DATE '2022-01-04',
        CAST('2022-01-04 '||unnest(?) AS TIMESTAMP),100,101,99,100,1,1,'XSHG','2022-01-04',60''',[list(slots(60))])
    return con


@pytest.mark.parametrize('mutation',[None,
    "DELETE FROM prices WHERE CAST(trade_time AS TIME)=TIME '11:30:00'",
    'INSERT INTO prices SELECT * FROM prices LIMIT 1',
    'UPDATE prices SET freq=30',
    "UPDATE prices SET partition_date='2022-01-05'",
    'UPDATE prices SET open=0',
    'UPDATE prices SET vol=-1',
    'UPDATE prices SET close=NULL',
    'DELETE FROM calendar',
    "UPDATE prices SET trade_time=TIMESTAMP '2022-01-04 09:30:00'"])
def test_quality_grid(mutation):
    spec = replace(MINUTE,codes=('000300.SH',),frequencies=(60,),start='2022-01-04',end='2022-01-04')
    with quality_con() as con:
        if mutation:
            con.execute(mutation)
            with pytest.raises(ValueError):
                validate(con,spec)
        else:
            result,days = validate(con,spec)
            assert result['rows']==4 and days==['2022-01-04']


@pytest.mark.parametrize('tamper', [False,True])
def test_saved_audit_and_tamper(tmp_path,monkeypatch,tamper):
    from scripts.research.index_market.chan import verify_minute
    from scripts.research.index_market.chan.m0_data import digest

    monkeypatch.setattr(verify_minute,'REPO',tmp_path)
    root = tmp_path/'reports'/'test'
    folder = root/'000300.SH_60'
    folder.mkdir(parents=True)
    p = point()
    ledger = MinuteLedger('000300.SH',60)
    events,changes = ledger.step('2022-01-04 14:00:00',2,[p])
    (folder/'events.json').write_text(json.dumps(events))
    (folder/'changes.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in changes))
    hashes = {str(p.relative_to(root)):digest(p.read_bytes()) for p in folder.iterdir()}
    (root/'manifest.json').write_text(json.dumps(dict(artifacts_sha256=hashes,
        spec=dict(codes=['000300.SH'],frequencies=[60]))))
    if tamper:
        (folder/'events.json').write_text('[]')
        with pytest.raises(ValueError,match='artifact changed'):
            verify_minute.audit(root)
    else:
        assert verify_minute.audit(root)['cells'][0]['events']==1
