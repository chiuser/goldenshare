from copy import deepcopy
from decimal import Decimal as D
import pytest
from scripts.research.industry_financial.sample_chapters import classification,quadrant_row,history_rows,STATES


def literal_group():
    # Independently calculable common-company aggregates: revenue100->120,
    # deducted5->9.6 => revenue+20%, profit margin5%->8% (+3pp).
    return {'identity':{'sector_name':'测试行业'},'facts':{'plots':{'4':{'available':True,'x':'3','n':3,'candidate_n':4,
      'sample_id':'private-evidence','codes':['a','b','c'],'coverage_current':{'value':'1'},'coverage_previous':{'value':'.95'},
      'raw':{'prior_revenue':'100','revenue':'120','prior_deducted_profit':'5','deducted_profit':'9.6'}}}}}


def test_quadrant_is_joint_money_ratio_not_average_or_other_chart():
    row,audit=quadrant_row(literal_group())
    assert row['收入增长（%）']==20 and row['利润率变化（百分点）']==3
    assert row['经营状态']==STATES[0] and row['可比公司数']==3
    assert 'sample_id' not in row and audit['sample_id']=='private-evidence'
    bad=literal_group();bad['facts']['plots']['4']['x']='99'
    with pytest.raises(ValueError):quadrant_row(bad)


def test_negative_profit_and_unrounded_quadrant_boundary():
    g=literal_group();p=g['facts']['plots']['4'];p['raw'].update(prior_deducted_profit='-10',deducted_profit='-6');p['x']='5'
    row,_=quadrant_row(g)
    assert row['利润率变化（百分点）']==5 and row['盈亏情况']=='亏损收窄'
    assert classification(D('20'),D('-.00001'))==STATES[1]
    assert classification(D('0'),D('1'))==STATES[4]
    assert classification(D('-1'),D('-1'))==STATES[3]


def test_missing_denominator_and_financial_are_not_silently_drawn():
    g=literal_group();g['facts']['plots']['4']['raw']['prior_revenue']='0'
    with pytest.raises(ValueError):quadrant_row(g)
    g=literal_group();g['identity']['sector_name']='银行'
    assert quadrant_row(g) is None
    g=literal_group();g['facts']['plots']['4']['available']=False
    with pytest.raises(ValueError):quadrant_row(g)


def test_three_year_bar_values_keep_losses_and_same_population():
    dates=['2024-09-30','2025-09-30','2026-09-30'];profit=[10,-2,-1]
    p={'sector_rows':[{'行业':'测试行业','报告期':d,'收入亿元':100+i*10,'归母利润亿元':profit[i],'共同公司数':3} for i,d in enumerate(dates)],
       'overall_exact':{d:{'n':3,'revenue':str((100+i*10)*100000000),'parent_profit':str(profit[i]*100000000)} for i,d in enumerate(dates)}}
    rows=history_rows(p)
    assert [r['归母净利润（亿元）'] for r in rows[:3]]==[10,-2,-1]
    bad=deepcopy(p);bad['sector_rows'][1]['共同公司数']=2
    with pytest.raises(ValueError):history_rows(bad)
    bad=deepcopy(p);bad['sector_rows'][0]['收入亿元']=999
    with pytest.raises(ValueError):history_rows(bad)
