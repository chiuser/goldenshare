"""Literal income fixtures match frozen income columns; expectations hand calculated."""
from copy import deepcopy
from decimal import Decimal as D
import json
import pytest
from scripts.research.industry_financial.history_publication import (
    HS, Book, panel, profit_change, reconcile_panels, income_projection,
)
from scripts.research.industry_financial.publication import PublicationRun, FrozenSource
from scripts.research.industry_financial.storage import atomic_json, digest

I={'sector_name':'测试','level':1}

def records(code='a', missing=()):
    # Single quarters 10,20,30,40; cumulative 10,30,60,100.
    return [{'ts_code':code,'end_date':date,'report_type':'1','revenue':r,'n_income_attr_p':D(r)/10}
            for date,r in zip(HS.periods,[10,30,60,100,11,33,66,110,12,36,72]) if date not in missing]


def test_quarter_differences_and_annual_identities_with_independent_literals():
    result=panel(Book({'income':records()}),['a'],I,'测试',quarter=True)
    assert [r['营业收入（亿元）'] for r in result['rows'][:4]]==[1e-7,2e-7,3e-7,4e-7]
    assert all(r['收入同比（%）'] is None for r in result['rows'][:4])
    assert result['rows'][4]['收入同比（%）']==10
    assert len(result['rows'])==11 and result['rows'][-1]['报告期']=='2026-09-30'
    assert set(result['audit']['quarter_residuals'].values())=={D(0)}


def test_missing_q1_does_not_contaminate_q2_and_nine_month_cohort_is_separate():
    b=records('b',('2024-03-31',));b[0]['revenue']=100
    book=Book({'income':records()+b})
    q=panel(book,['a','b'],I,'测试',quarter=True)
    assert q['audit']['codes']==('a',) and q['rows'][1]['营业收入（亿元）']==2e-7
    n=panel(book,['a','b'],I,'测试')
    assert n['audit']['codes']==('a','b') and n['rows'][0]['营业收入（亿元）']==1.2e-6
    assert q['audit']['excluded'][0]['missing'][0]['period']=='2024-03-31'


@pytest.mark.parametrize('current,previous,revenue,growth,state',[
    ('12','10','100',D(20),'增加'),('0','10','100',D(-100),'减少'),
    ('5','-10','100',None,'扭亏'),('-5','-10','100',None,'减亏'),
    ('-15','-10','100',None,'亏损扩大'),('-1','10','100',None,'转亏'),
    ('1','0','100',None,'近零或无效基数'),('1','.01','100',None,'近零或无效基数'),
    ('.11','.1','100',D(10),'增加')])
def test_profit_growth_material_positive_base_only(current,previous,revenue,growth,state):
    assert profit_change(*map(D,(current,previous,revenue)))==(growth,state)


def test_finance_three_years_uses_total_revenue_and_no_financial_quarters():
    rows=[dict(r,total_revenue=D(r['revenue'])*10) for r in records()]
    r=panel(Book({'income':rows}),['a'],I,'金融',finance=True)
    assert [x['营业总收入（亿元）'] for x in r['rows']]==[6e-6,6.6e-6,7.2e-6]
    assert all('营业收入（亿元）' not in x for x in r['rows'])


def test_comparability_boundary_and_missing_inputs_preserved():
    book=Book({'income':records()},noncomparable={'a':{'boundary':'2025-01-01'}})
    r=panel(book,['a'],I,'测试')
    assert not r['audit']['codes'] and r['rows'][0]['营业收入（亿元）'] is None
    assert r['audit']['excluded'][0]['reason']=='known_comparability_boundary'
    rows=records();rows[-1]['n_income_attr_p']=None
    assert not panel(Book({'income':rows}),['a'],I,'测试',quarter=True)['audit']['codes']


def test_parent_child_union_and_amounts_have_independent_guards():
    book=Book({'income':records()+records('b')})
    p=panel(book,['a','b'],I,'测试',quarter=True)
    a=panel(book,['a'],I,'测试',quarter=True); b=panel(book,['b'],I,'测试',quarter=True)
    assert set(reconcile_panels(p,[a,b]).values())=={D(0)}
    with pytest.raises(ValueError,match='sets differ'):reconcile_panels(p,[a,a])
    b['audit']['exact']['2024-03-31']['profit']+=D(2)
    with pytest.raises(ValueError,match='amounts differ'):reconcile_panels(p,[a,b])


def test_income_contract_duplicate_wrong_period_and_missing_column_fail_closed(tmp_path):
    (tmp_path/'evidence').mkdir();(tmp_path/'inputs').mkdir()
    def source(rows):
        files={};parts={}
        for period in HS.periods:
            name='income_'+period; path=tmp_path/f'inputs/{name}.jsonl'
            chosen=[r for r in rows if r['end_date']==period]
            path.write_text(''.join(json.dumps(r,default=str)+'\n' for r in chosen))
            receipt=tmp_path/f'evidence/{name}.receipt.json'
            atomic_json(receipt,{'artifact':f'inputs/{name}.jsonl','sha256':digest(path)})
            files[str(path.relative_to(tmp_path))]=digest(path);files[str(receipt.relative_to(tmp_path))]=digest(receipt)
            parts[name]=[name]
        atomic_json(tmp_path/'evidence/input_parts.json',parts);files['evidence/input_parts.json']=digest(tmp_path/'evidence/input_parts.json')
        atomic_json(tmp_path/'evidence/artifact_manifest.json',{'files':files});return FrozenSource(tmp_path)
    members=[{'ts_code':'a','curr_type':'CNY','root_name':'测试'}]
    assert len(income_projection(source(records()),members)[0])==11
    with pytest.raises(ValueError,match='Duplicate historical'):income_projection(source(records()+[records()[0]]),members)
    rows=records();del rows[0]['revenue']
    with pytest.raises(ValueError,match='column absent'):income_projection(source(rows),members)
    rows=records();rows[0]['report_type']='2'
    with pytest.raises(ValueError,match='consolidation'):income_projection(source(rows),members)
    source(records())
    path=tmp_path/'inputs/income_2024-03-31.jsonl'
    wrong=json.loads(path.read_text());wrong['end_date']='2024-03-30'
    path.write_text(json.dumps(wrong)+'\n')
    receipt=tmp_path/'evidence/income_2024-03-31.receipt.json'
    atomic_json(receipt,{'artifact':str(path.relative_to(tmp_path)),'sha256':digest(path)})
    manifest=tmp_path/'evidence/artifact_manifest.json';m=json.loads(manifest.read_text())
    m['files'][str(path.relative_to(tmp_path))]=digest(path)
    m['files'][str(receipt.relative_to(tmp_path))]=digest(receipt)
    atomic_json(manifest,m)
    with pytest.raises(ValueError,match='period'):income_projection(FrozenSource(tmp_path),members)
    with pytest.raises(ValueError,match='currency'):
        income_projection(source(records()),[dict(members[0],curr_type='USD')])


def test_history_stage_resume_reuses_receipts_and_refuses_config_drift(tmp_path):
    out=tmp_path/'narrative_history';r=PublicationRun(out,{'immutable':'yes'},base_root=tmp_path,spec=HS)
    assert r.state['stage']=='history' and r.spec.calculation_seconds==600
    r.unit('one',lambda:{'amount':120}); stamp=(out/'units/one.json').stat().st_mtime_ns
    (out/'CANCEL').touch()
    with pytest.raises(InterruptedError):r.unit('two',lambda:pytest.fail('cancel ignored'))
    (out/'CANCEL').unlink();r=PublicationRun(out,{'immutable':'yes'},True,base_root=tmp_path,spec=HS)
    assert r.unit('one',lambda:pytest.fail('recomputed'))=={'amount':120}
    assert (out/'units/one.json').stat().st_mtime_ns==stamp
    with pytest.raises(ValueError,match='Source/spec'):PublicationRun(out,{'immutable':'yes'},True,base_root=tmp_path)
