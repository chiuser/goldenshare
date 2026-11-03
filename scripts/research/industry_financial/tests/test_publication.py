"""Independent literal samples follow frozen input/aggregate contracts in §10.12."""
from copy import deepcopy
from decimal import Decimal as D
import json
from pathlib import Path
import pytest

from scripts.research.industry_financial.publication import (
    FrozenSource, PublicationRun, financial_projection, profit_parts, reconcile_parent,
    current_projection, SPEC, safe_relative, pack_heat_groups,
    top_company_names, receivable_balance, reconcile_receivable,
)
from scripts.research.industry_financial.metrics import Book
from scripts.research.industry_financial.storage import atomic_json, digest


def meta():
    return {'n': 3, 'candidate_n': 4, 'codes': ['a', 'b', 'c'], 'sample_id': 'private',
            'coverage_current': {'value': '1'}, 'coverage_previous': {'value': '.9'}, 'available': True}


def literal_group():
    # Income 100->120; parent10->18; deducted5->9.6; operating cash2->12.
    p1 = dict(meta(), x='20', raw={'revenue':'120','prior_revenue':'100','parent_profit':'18','prior_parent_profit':'10'})
    p3 = dict(meta(), x='3', y='8', raw={'deducted_margin':'.08','cashflow_margin':'.10'})
    p4 = dict(meta(), x='3', raw={'revenue':'120','prior_revenue':'100','deducted_profit':'9.6','prior_deducted_profit':'5','improved_companies':2,'total_companies':3})
    turn = dict(meta(), x='20', y='-3', raw={'current_days':'27','prior_days':'30'})
    metric = dict(meta(), metric='cash_surplus', value='-2')
    top = dict(meta(), metric='prior_revenue_top3_parent_profit_contribution', value=[{'profit_change':'10','code':'a'},{'profit_change':'-1','code':'b'},{'profit_change':'-3','code':'c'}])
    return {'identity': {'sector_code':'test','sector_name':'测试行业','level':1,'financial':False},
            'facts':{'plots':{'1':p1,'3':p3,'4':p4,'7':turn,'8':deepcopy(turn),'9':dict(meta(), x='20', y='10', raw={})},'metrics':[metric,top]}}


def test_projected_money_signs_and_same_company_rates():
    r = current_projection(literal_group(), '测试行业')['queries']
    assert r['quadrant']['收入增长（%）'] == 20
    assert r['quadrant']['利润率变化（百分点）'] == 3
    assert r['quality']['经营现金流率变化（百分点）'] == 8
    assert r['profit']['归母利润增减（亿元）'] == 8e-8
    assert r['profit']['前三大收入公司贡献（亿元）'] == 6e-8
    assert r['profit']['其余公司贡献（亿元）'] == 2e-8
    assert r['receivable']['周转天数变化（天）'] == -3
    assert r['capex']['现金流扣除资本开支（亿元）'] == -2e-8
    assert r['breadth']['利润改善公司比例（%）'] == pytest.approx(200/3)
    assert 'sample_id' not in r['quality']


def test_concentration_rejects_mixed_company_sets_and_keeps_offsetting_losses():
    g = literal_group();plot=g['facts']['plots']['1'];top=g['facts']['metrics'][1]
    assert profit_parts(plot,top) == (D(8), D(6), D(2))
    top['codes']=['a','b']
    with pytest.raises(ValueError,match='different company'): profit_parts(plot,top)


def test_missing_fact_remains_missing_not_zero():
    g=literal_group();g['facts']['plots']['7']['available']=False
    row=current_projection(g,'测试行业')['queries']['receivable']
    assert row['可用状态']=='缺少可比数据'
    assert row.get('周转天数变化（天）') is None


def test_finance_uses_total_revenue_two_periods_and_preserves_loss():
    # Nonfinancial revenue is intentionally unrelated; company b lacks prior income.
    records=[{'ts_code':'a','end_date':'2025-09-30','revenue':'7','total_revenue':'1000','n_income_attr_p':'100'},
             {'ts_code':'a','end_date':'2026-09-30','revenue':'99','total_revenue':'1200','n_income_attr_p':'-10'},
             {'ts_code':'b','end_date':'2026-09-30','total_revenue':'300','n_income_attr_p':'30'}]
    book=Book({'income':records});identity={'sector_name':'测试金融','level':1}
    r=financial_projection(book,['a','b'],identity,'测试金融')
    assert r['codes']==('a',)
    assert [x['营业总收入（亿元）'] for x in r['rows']] == [1e-5,1.2e-5]
    assert r['rows'][1]['归母净利润（亿元）']==-1e-7
    assert r['rows'][1]['已知营业总收入覆盖（%）']==80
    assert r['rows'][0]['可比公司数']==1
    # A normal value change must not be mistaken for a version conflict.
    records[1]['total_revenue']='1250'
    changed=financial_projection(Book({'income':records}),['a'],identity,'测试金融')
    assert changed['rows'][1]['营业总收入（亿元）']==1.25e-5


def test_finance_known_comparability_boundary_and_null_are_not_imputed():
    records=[{'ts_code':'a','end_date':d,'total_revenue':100,'n_income_attr_p':10} for d in SPEC.periods]
    book=Book({'income':records},noncomparable={'a':{'boundary':'2026-01-01'}})
    r=financial_projection(book,['a'],{'sector_name':'金融','level':2},'金融')
    assert r['rows'][0]['可比公司数']==0 and r['rows'][0]['营业总收入（亿元）'] is None
    records[1]['total_revenue']=None
    assert not financial_projection(Book({'income':records}),['a'],{'sector_name':'金融','level':2},'金融')['codes']


def test_independent_parent_child_reconciliation_and_duplicate_rejection():
    parent={'codes':['a','b'],'raw':{'revenue':'30','prior_revenue':'20','parent_profit':'3','prior_parent_profit':'2'}}
    def child(code,r,p): return {'facts':{'plots':{'1':{'available':True,'codes':[code],'raw':{'revenue':r,'prior_revenue':'10','parent_profit':p,'prior_parent_profit':'1'}}}}}
    group={'facts':{'plots':{'1':parent}},'children':[child('a','10','1'),child('b','20','2')]}
    assert set(reconcile_parent(group).values()) == {D(0)}
    group['children'][1]['facts']['plots']['1']['codes']=['a']
    with pytest.raises(ValueError,match='sets differ'):reconcile_parent(group)


def test_frozen_source_hash_and_path_guards(tmp_path):
    (tmp_path/'evidence').mkdir();atomic_json(tmp_path/'value.json',{'reviewed':1})
    atomic_json(tmp_path/'evidence/artifact_manifest.json',{'files':{'value.json':digest(tmp_path/'value.json')}})
    source=FrozenSource(tmp_path)
    assert source.json('value.json')=={'reviewed':1}
    with pytest.raises(ValueError,match='outside'):safe_relative(tmp_path,'../escape.json')
    atomic_json(tmp_path/'value.json',{'reviewed':2})
    with pytest.raises(ValueError,match='hash mismatch'):source.json('value.json')
    with pytest.raises(ValueError,match='manifest changed'):FrozenSource(tmp_path,'not-an-authorized-hash')


def test_current_units_cancel_resume_and_immutable_receipts(tmp_path):
    out=tmp_path/'narrative_test';run=PublicationRun(out,{'frozen':'abc'},base_root=tmp_path)
    run.unit('one',lambda:{'independent_literal':120})
    stamp=(out/'units/one.json').stat().st_mtime_ns
    (out/'CANCEL').write_text('stop')
    with pytest.raises(InterruptedError):run.unit('two',lambda:{'should_not_run':1})
    assert not (out/'units/two.json').exists()
    (out/'CANCEL').unlink()
    resumed=PublicationRun(out,{'frozen':'abc'},True,base_root=tmp_path)
    assert resumed.unit('one',lambda:pytest.fail('committed unit recomputed'))=={'independent_literal':120}
    assert (out/'units/one.json').stat().st_mtime_ns==stamp
    resumed.unit('two',lambda:{'independent_literal':20})
    with pytest.raises(ValueError,match='Source/spec'):PublicationRun(out,{'frozen':'changed'},True,base_root=tmp_path)
    with pytest.raises(ValueError,match='explicit resume'):PublicationRun(out,{'frozen':'abc'},False,base_root=tmp_path)
    with pytest.raises(ValueError,match='direct narrative'):PublicationRun(tmp_path/'formal_bad',{},base_root=tmp_path)


def test_grouping_keeps_all_secondary_rows_visible_and_bounded():
    roots=[{'identity':{'sector_name':name},'children':[{'queries':{'quadrant':{'行业':f'{name}{i}'}}} for i in range(n)]} for name,n in [('甲',10),('乙',9),('丙',2)]]
    groups=pack_heat_groups(roots)
    assert [len(g['industries']) for g in groups]==[10,11]
    assert sum(len(g['industries']) for g in groups)==21
    assert all(len(g['industries'])<=16 for g in groups)


def test_top_company_names_follow_frozen_order_and_reject_unknown_identity():
    metric={'codes':['a','b','c'],'value':[{'code':'c'},{'code':'a'},{'code':'b'}]}
    members=[{'ts_code':'a','name':'甲公司'},{'ts_code':'b','name':'乙公司'},{'ts_code':'c','name':'丙公司'}]
    assert top_company_names(metric,members)=='丙公司、甲公司、乙公司'
    with pytest.raises(ValueError,match='Missing frozen'):top_company_names(metric,members[:2])
    with pytest.raises(ValueError,match='Duplicate'):top_company_names(metric,members+[members[0]])
    metric['value']=[{'code':'a'},{'code':'a'}]
    with pytest.raises(ValueError,match='Invalid frozen'):top_company_names(metric,members)


def ar_group(now='120',prior='100',n=2,all_current='999'):
    # The full current population has 999; only the comparable companies have 120.
    return {'identity':{'sector_name':'测试'},'facts':{'plots':{'1':{'candidate_n':3}}},
            'series':[{'metric':'accounts_receivable','period':'2026-09-30','comparison_n':n,
                       'comparison_current':now,'comparison_previous':prior,'amount':all_current}]}


def test_receivables_use_comparable_period_end_balances_not_all_current_amount():
    row=receivable_balance(ar_group(),'测试一级')
    assert row['2026年9月末应收账款（亿元）']==1.2e-6
    assert row['2025年9月末应收账款（亿元）']==1e-6
    assert row['应收账款增减（亿元）']==2e-7
    assert row['应收账款同比（%）']==20
    assert row['可比公司数']==2
    zero=receivable_balance(ar_group('10','0'),'测试一级')
    assert zero['应收账款同比（%）'] is None and zero['应收账款增减（亿元）']==1e-7
    missing=receivable_balance(ar_group(None,None,0),'测试一级')
    assert missing['应收账款增减（亿元）'] is None and missing['可用状态']=='缺少两期可比数据'
    with pytest.raises(ValueError,match='Inconsistent'):receivable_balance(ar_group(None,'100'),'测试一级')


def test_receivable_parent_child_amount_and_count_reconciliation():
    parent=ar_group();parent['children']=[ar_group('40','50',1),ar_group('80','50',1)]
    assert set(reconcile_receivable(parent).values())=={D(0)}
    parent['children'][0]['series'][0]['comparison_current']='41'
    # Two yuan catches the stated one-yuan tolerance.
    parent['children'][1]['series'][0]['comparison_current']='81'
    with pytest.raises(ValueError,match='amounts differ'):reconcile_receivable(parent)
    parent['children']=[ar_group('40','50',2),ar_group('80','50',1)]
    with pytest.raises(ValueError,match='counts differ'):reconcile_receivable(parent)
