"""Fixtures follow the current models/Serving ordering read in preflight."""
from dataclasses import replace
from pathlib import Path
import json
import pytest
from scripts.research.industry_financial.spec import SPEC,FIELDS
from scripts.research.industry_financial.extract import financial_query,selection_query,wrap,resolve_mapping,validate_rows,Query
from scripts.research.industry_financial.storage import RunStore,Cancelled,atomic_json


def test_fixed_scope_and_source_projection():
    assert len(SPEC.dates)==11 and SPEC.dates[0]=='2024-03-31' and SPEC.dates[-1]=='2026-09-30'
    for kwargs in [{'per_root':21},{'max_codes':101},{'dates':('2023-12-31',)}]:
        with pytest.raises(ValueError):replace(SPEC,**kwargs)
    flat={x for fields in FIELDS.values() for x in fields}
    assert not flat&{'cip','cip_total','roic','daa','depr_fa_coga_dpba'}
    query=selection_query().select
    assert 'LIMIT 20' in query and 'ORDER BY s.ts_code' in query
    assert all(c in query for c in SPEC.excluded)


def test_sql_rejects_scope_and_writes():
    for value in ['SELECT 1; DELETE FROM x','DELETE FROM x','SELECT 1 -- comment','SELECT 1 INTO x']:
        with pytest.raises(ValueError):wrap(value)
    with pytest.raises(ValueError):financial_query('income','2023-12-31',['000001.SZ'])
    with pytest.raises(ValueError):financial_query('income','2024-03-31',["000001.SZ'); DROP TABLE x"])
    q=financial_query('fina_indicator','2024-03-31',['000001.SZ'])
    assert "CASE update_flag WHEN '1' THEN 0 ELSE 1 END" in q.select
    assert 'COALESCE' not in q.select
    assert wrap(q.select).startswith('BEGIN READ ONLY;')


def test_mapping_direct_and_fallback_conflict():
    sample=[{'ts_code':'000001.SZ','selected_root':'BK0438.DC'}]
    leaf={'con_code':'000001.SZ','sector_code':'L3','industry_level':3,'root_sector_code':'BK0438.DC','root_sector_name':'食品饮料','parent_sector_code':'L2','parent_sector_name':'饮料'}
    mapped=resolve_mapping(sample,[leaf])
    assert mapped[0]['parent']=='L2' and mapped[0]['parent_name']=='饮料'
    direct=dict(leaf,industry_level=2,sector_code='L2',sector_name='饮料')
    assert resolve_mapping(sample,[leaf,direct])[0]['parent']=='L2'
    with pytest.raises(ValueError):resolve_mapping(sample,[leaf,dict(direct,sector_code='OTHER')])


def test_duplicates_and_report_type_are_rejected():
    q=Query('income_2024-03-31','SELECT 1',100,'SELECT 1')
    row={'ts_code':'000001.SZ','end_date':'2024-03-31','report_type':'1'}
    validate_rows(q,[row])
    for rows in [[row,row],[dict(row,report_type='2')],[dict(row,end_date='2023-12-31')]]:
        with pytest.raises(ValueError):validate_rows(q,rows)


def test_receipt_survives_state_failure_and_resume(tmp_path,monkeypatch):
    from scripts.research.industry_financial import storage
    monkeypatch.setattr(storage,'OUTPUT_ROOT',tmp_path)
    store=RunStore(tmp_path/'trial_test')
    part=store.path/'inputs/one.part';part.write_text('{"amount":null}\n')
    monkeypatch.setattr(store,'save',lambda **kw:(_ for _ in ()).throw(OSError('state failure')))
    with pytest.raises(OSError):store.seal('one',part,1,{'n':1})
    resumed=RunStore(store.path,resume=True)
    assert resumed.completed('one')['rows']==1
    assert list(resumed.rows('one'))==[{'amount':None}]
    (store.path/'CANCEL').write_text('cancel')
    with pytest.raises(Cancelled):resumed.check()
    with pytest.raises(ValueError):RunStore(tmp_path/'unrelated')
    target=store.path/'inputs/one.jsonl';target.write_text('changed')
    with pytest.raises(ValueError):resumed.completed('one')


def test_source_change_stops_resume_before_read(tmp_path,monkeypatch):
    from scripts.research.industry_financial import storage,extract
    monkeypatch.setattr(storage,'OUTPUT_ROOT',tmp_path)
    store=RunStore(tmp_path/'trial_source_change')
    part=store.path/'inputs/unit.part';part.write_text('{"value":1}\n')
    store.seal('unit',part,1,{'n':1,'fetched_at':'2026-11-01T10:00:00'})
    q=Query('unit','SELECT 1',1,'SELECT 1')
    monkeypatch.setattr(extract,'fingerprint',lambda *args:{'n':1,'fetched_at':'2026-11-01T10:01:00'})
    with pytest.raises(ValueError,match='Source changed'):extract.run_unit(store,q)
    # A process exit before sealing leaves a .part, never a completed unit.
    (store.path/'inputs/unfinished.jsonl.part').write_text('{"value":2}\n')
    assert store.completed('unfinished') is None


def test_nonfinite_values_and_changed_scope_rejected():
    from scripts.research.industry_financial.metrics import dec
    from decimal import Decimal
    assert dec('0')==Decimal(0) and dec(None) is None
    with pytest.raises(ValueError):dec('NaN')
    with pytest.raises(ValueError):replace(SPEC,roots=('BK0001.DC',)+SPEC.roots[1:])
    with pytest.raises(ValueError):replace(SPEC,excluded=())


def test_exact_query_scope_not_only_allowed_study_dates():
    q=financial_query('income','2024-03-31',['000001.SZ'])
    good={'ts_code':'000001.SZ','end_date':'2024-03-31','report_type':'1'}
    validate_rows(q,[good])
    for bad in [dict(good,ts_code='000002.SZ'),dict(good,end_date='2024-06-30')]:
        with pytest.raises(ValueError):validate_rows(q,[bad])


def test_actual_process_exit_does_not_seal_partial_unit(tmp_path,monkeypatch):
    import subprocess,sys
    from scripts.research.industry_financial import storage
    monkeypatch.setattr(storage,'OUTPUT_ROOT',tmp_path)
    store=RunStore(tmp_path/'trial_exit')
    part=store.path/'inputs/one.part';part.write_text('{"value":1}\n')
    store.seal('one',part,1,{'n':1})
    sha=store.completed('one')['sha256']
    target=store.path/'inputs/unfinished.jsonl.part'
    # A separate process physically exits before a receipt can be written.
    child=subprocess.run([sys.executable,'-c',"import pathlib,os,sys; pathlib.Path(sys.argv[1]).write_text('{\"value\":2}'); os._exit(17)",str(target)],capture_output=True)
    assert child.returncode==17 and target.exists()
    resumed=RunStore(store.path,True)
    assert resumed.completed('unfinished') is None
    assert resumed.completed('one')['sha256']==sha
    assert list(resumed.rows('one'))==[{'value':1}]


def test_cli_rejects_global_scope_options():
    from scripts.research.industry_financial.run import main
    with pytest.raises(SystemExit):main(['--output','/tmp/trial_wrong','--all-market'])
    with pytest.raises(SystemExit):main(['--output','/tmp/trial_wrong','--offline'])


def test_no_adoption_of_unowned_nonempty_output(tmp_path,monkeypatch):
    from scripts.research.industry_financial import storage
    monkeypatch.setattr(storage,'OUTPUT_ROOT',tmp_path)
    path=tmp_path/'trial_existing';path.mkdir();(path/'unrelated.txt').write_text('keep')
    with pytest.raises(ValueError,match='Nonempty'):RunStore(path)
    assert (path/'unrelated.txt').read_text()=='keep'
