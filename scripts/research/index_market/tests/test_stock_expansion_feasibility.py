"""P0 audit tests: synthetic fixtures only, never read the real Lake."""
from dataclasses import replace
from datetime import date, timedelta
import time

import pytest

from scripts.research.index_market.chan import stock_expansion_feasibility as study


def fixture():
    event = dict(event_id='b3', code='002084.SZ', signal_time='2022-10-10 15:00:00',
                 anchor_time='2022-10-10 14:00:00', anchor_index=0, signal_index=1)
    case = dict(event_ids=['b2','b3'], code=event['code'], signal_time=event['signal_time'],
                frozen_low=10., types=['B2','B3'])
    origin = dict(status='unique', event=event, snapshot=dict(
        refs={'point':{'line':'a'}}, objects={'a':dict(end={'time':event['anchor_time']}, end_value=10.)}))
    rows = [dict(time=event['anchor_time'],low=10.), dict(time=event['signal_time'],low=12.)]
    return case, origin, rows


def test_same_low_mixed_types():
    result = study.compare_low(*fixture())
    assert result['equal'] is True
    assert result['types'] == ['B2','B3']


def test_lower_other_buy_anchor_is_not_same_rule():
    case, origin, rows = fixture()
    case['frozen_low'] = 9.
    assert study.compare_low(case,origin,rows)['equal'] is False


@pytest.mark.parametrize('field,value', [('event_id','wrong'), ('code','000001.SZ'),
    ('signal_time','2022-10-11 15:00:00'), ('anchor_index',2), ('anchor_index',-1),
    ('anchor_time','2022-10-09 14:00:00')])
def test_bad_identity_and_future_anchor(field,value):
    case, origin, rows = fixture()
    origin['event'][field] = value
    with pytest.raises(ValueError):
        study.compare_low(case,origin,rows)


def test_structure_cannot_be_backfilled():
    case, origin, rows = fixture()
    origin['snapshot']['objects']['a']['end_value'] = 9.9
    with pytest.raises(ValueError,match='pullback'):
        study.compare_low(case,origin,rows)


def stock():
    return dict(ts_code='002084.SZ',exchange='SZSE',curr_type='CNY',list_status='L',
                list_date=date(2000,1,1),delist_date=None)


def test_eligible():
    assert study.eligible(stock())


@pytest.mark.parametrize('changes', [dict(ts_code='920001.BJ',exchange='BSE'),
    dict(ts_code='200001.SZ'), dict(curr_type='USD'),dict(list_status='D'),
    dict(delist_date=date(2026,1,1)),dict(list_date=date(2022,1,1)),dict(list_date=None)])
def test_excluded_identity(changes):
    value=stock(); value.update(changes)
    assert not study.eligible(value)


def test_evidence_fingerprint_and_size(tmp_path):
    path=tmp_path/'evidence';path.write_bytes(b'abc')
    assert study.read_checked(path,3,study.digest(b'abc'))==b'abc'
    with pytest.raises(ValueError,match='fingerprint'):
        study.read_checked(path,3,study.digest(b'abd'))
    with pytest.raises(ValueError,match='oversized'):
        study.read_checked(path,2)


def test_redirected_evidence(tmp_path):
    path=tmp_path/'source';path.write_bytes(b'abc')
    alias=tmp_path/'alias';alias.symlink_to(path)
    with pytest.raises(ValueError,match='redirected'):
        study.read_checked(alias,3)


def test_sql_rows_queries_and_external_access(monkeypatch):
    monkeypatch.setattr(study,'SPEC',replace(study.SPEC,max_rows=2,max_queries=2))
    q=study.Queries([],time.monotonic())
    try:
        assert q.run('SELECT 1 n') == [{'n':1}]
        with pytest.raises(ValueError,match='row budget'):
            q.run('SELECT range FROM range(3)')
        assert q.run("SELECT current_setting('enable_external_access') allowed")==[{'allowed':False}]
        with pytest.raises(TimeoutError):
            q.run('SELECT 1')
    finally:
        q.connection.close()


def test_parquet_budget_rejects_before_scanning(tmp_path,monkeypatch):
    path=tmp_path/'not_parquet';path.write_bytes(b'abc')
    monkeypatch.setattr(study,'SPEC',replace(study.SPEC,max_bytes=2))
    with pytest.raises(ValueError,match='parquet budget'):
        study.Queries([path],time.monotonic())


def test_existing_output_rejected_before_sources(tmp_path):
    with pytest.raises(ValueError,match='output'):
        study.execute(tmp_path)


def test_lake_audit_with_only_synthetic_parquet(tmp_path,monkeypatch):
    import duckdb

    monkeypatch.setattr(study,'SPEC',replace(study.SPEC,lake=str(tmp_path)))
    conn=duckdb.connect(':memory:')

    def parquet(relative,sql):
        path=tmp_path/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        conn.execute(f"COPY ({sql}) TO '{path}' (FORMAT PARQUET)")

    identity="SELECT '002084.SZ' ts_code,'SZSE' exchange,'主板' market,'CNY' curr_type,'L' list_status,DATE '2000-01-01' list_date,NULL::DATE delist_date"
    parquet('silver/basic/stock_basic/full/part-000.parquet',identity)
    parquet('silver/basic/stock_lifecycle/full/part-000.parquet',identity)
    parquet('silver/calendar/trade_calendar/full/part-000.parquet',
            "SELECT 'SSE' exchange, DATE '2021-09-09'+CAST(range AS INTEGER) trade_date,true is_open FROM range(251)")
    for i in range(190,250):
        day=date(2021,9,9)+timedelta(days=i)
        daily=f"SELECT '002084.SZ' ts_code,DATE '{day}' trade_date,120.0 amount"
        suspension=f"SELECT '002084.SZ' ts_code,DATE '{day}' trade_date,'S' suspend_type,NULL::VARCHAR suspend_timing"
        parquet(f'silver/quote/stock_daily/trade_date={day}/part-000.parquet',daily+(' WHERE false' if i==190 else ''))
        parquet(f'silver/quote/stock_suspend_daily/trade_date={day}/part-000.parquet',suspension+(' WHERE false' if i!=190 else ''))
    conn.close()
    result=study.lake_audit({'replayed':[],'selected':[],'ranked':['002084.SZ']},time.monotonic())
    assert result['days']==251
    assert result['identity_mismatches']==[]
    assert result['path_checks']==12
    assert len(result['stock_inventory'][0]['missing'])==12
    assert result['boards'][0]['never_ranked']==0
    row=result['liquidity'][0]
    assert row['full_suspend']==1
    assert row['unexplained_missing']==0
    assert row['present']==59
    assert row['mean_amount']==118.
