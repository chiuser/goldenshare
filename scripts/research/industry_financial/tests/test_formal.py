"""Fixed authorized limits, genuine batch boundaries, and shared financial policy."""
from dataclasses import replace
from decimal import Decimal as D
import pytest
from scripts.research.industry_financial.spec import SPEC,TRIAL_SCOPE,FORMAL_SCOPE,ExecutionScope
from scripts.research.industry_financial.formal import batches,identity_query,tree_query,validate_identity
from scripts.research.industry_financial.extract import financial_query,mapping_query,validate_rows,resolve_mapping
from scripts.research.industry_financial.storage import RunStore,atomic_json


def test_formal_scope_does_not_silently_change_trial():
    assert TRIAL_SCOPE.digest()==SPEC.digest()
    assert FORMAL_SCOPE.max_codes==5571 and FORMAL_SCOPE.max_rows==245124
    assert FORMAL_SCOPE.db_seconds==900 and TRIAL_SCOPE.db_seconds==180
    assert FORMAL_SCOPE.digest()!=SPEC.digest()
    with pytest.raises(ValueError):ExecutionScope('all')
    codes=[f'{i:06d}.SZ' for i in range(5571)]
    parts=batches(codes,2000)
    assert list(map(len,parts))==[2000,2000,1571]
    assert [c for p in parts for c in p]==codes
    with pytest.raises(ValueError):batches(codes+['999999.SZ'],2000)
    with pytest.raises(ValueError):batches(codes,5571)


def test_financial_chart_exclusion_and_named_score_tooltip():
    import json
    from scripts.research.industry_financial.charts import chart_rows
    groups=[{'identity':{'sector_code':'bank','sector_name':'银行','root':'bank','financial':True}},
            {'identity':{'sector_code':'industry','sector_name':'测试行业','root':'industry','financial':False}}]
    scores={'1':[{'sector_code':'industry','score_available':True,'dimensions':list(map(D,[20,30,40,50])),
        'raw':list(map(D,['.1','.2','.3','.4','.5','.6','.7'])),'n':5,'candidate_n':6,
        'sample_id':'literal_sample','coverage_current':{'value':D(1)},'coverage_previous':{'value':D('.95')}}]}
    rows,missing,bx,by=chart_rows(groups,scores,1,5)
    assert len(rows)==1 and missing==[{'sector_code':'bank','reason':'financial_industry_observation_only'}]
    assert (rows[0]['x'],rows[0]['y'],bx,by)==(30,20,50,50)
    raw=json.loads(rows[0]['raw_values'])
    assert raw['forecast_earnings_yield']=='0.1' and raw['model_downside']=='0.7'
    assert rows[0]['样本数']==5 and rows[0]['候选数']==6


def test_formal_2000_code_query_and_report_type_boundary():
    codes=[f'{i:06d}.SZ' for i in range(2000)]
    q=financial_query('income','2026-09-30',codes,2000,industrial_only=False)
    assert q.limit==2000 and len(q.codes)==2000
    validate_rows(q,[{'ts_code':codes[0],'end_date':'2026-09-30','report_type':'1','comp_type':'2'}])
    with pytest.raises(ValueError):financial_query('income','2026-09-30',codes)
    with pytest.raises(ValueError):financial_query('income','2026-09-30',codes+['999999.SZ'],2000)
    with pytest.raises(ValueError):financial_query('income','2023-12-31',codes,2000)
    with pytest.raises(ValueError):validate_rows(q,[{'ts_code':codes[0],'end_date':'2026-09-30','report_type':'2'}])
    mq=replace(mapping_query(codes[:500],500,2000),name='mapping_b00')
    validate_rows(mq,[{'con_code':codes[0],'trade_date':'2026-10-30'},{'con_code':codes[0],'trade_date':'2026-10-30'}])
    with pytest.raises(ValueError):mapping_query(codes[:500],500,25000)
    assert 'LIMIT 2000' in identity_query(1,'100000.SZ').select
    with pytest.raises(ValueError):identity_query(3,'100000.SZ')
    assert tree_query().limit==496


def test_formal_store_aliases_resume_and_scope_guard(tmp_path,monkeypatch):
    from scripts.research.industry_financial import storage
    monkeypatch.setattr(storage,'OUTPUT_ROOT',tmp_path)
    s=RunStore(tmp_path/'formal_example',scope=FORMAL_SCOPE)
    for name,value in [('batch0',1),('batch1',2)]:
        part=s.path/'inputs'/f'{name}.part';part.write_text('{"value":'+str(value)+'}\n');s.seal(name,part,1,{'n':1})
    atomic_json(s.path/'evidence/input_parts.json',{'logical':['batch0','batch1']})
    assert list(s.rows('logical'))==[{'value':1},{'value':2}]
    resumed=RunStore(s.path,True,FORMAL_SCOPE)
    assert resumed.completed('batch0')['sha256']==s.completed('batch0')['sha256']
    with pytest.raises(ValueError):RunStore(s.path,True)
    with pytest.raises(ValueError):RunStore(tmp_path/'trial_wrong',scope=FORMAL_SCOPE)
    atomic_json(s.path/'evidence/input_parts.json',{'logical':['batch0','missing']})
    with pytest.raises(ValueError):list(s.rows('logical'))


def test_full_mapping_without_preselected_root_stays_unique():
    sample=[{'ts_code':'000001.SZ'}]
    leaf={'con_code':'000001.SZ','sector_code':'leaf','industry_level':3,'root_sector_code':'root','root_sector_name':'行业','parent_sector_code':'parent','parent_sector_name':'二级'}
    assert resolve_mapping(sample,[leaf])[0]['root']=='root'
    with pytest.raises(ValueError):resolve_mapping(sample,[leaf,dict(leaf,root_sector_code='other')])
