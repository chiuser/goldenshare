"""Independent literal frozen-result contracts, CNY yuan; no fitted expectations."""
from copy import deepcopy
from decimal import Decimal as D
import pytest
from scripts.research.industry_financial.forecast_publication import (
    model_row,validate_model,reconcile_models,score_row,cutoff_ties,sensitivity_rows,RAW_NAMES,
)

I={'sector_name':'测试','sector_code':'r','level':1,'financial':False}

def model(kind='P',codes=('a','b')):
    # Revenue FY25=100, 9M26=90, Q4=30, FY26=120 (100 million yuan).
    # Profit FY25=8, 9M26=9, Q4=3, FY26=12; scenario FY=8..15.
    m={'available':True,'kind':kind,'n':len(codes),'codes':list(codes),'candidate_n':len(codes),
       'sample_id':'audit-only','coverage_current':{'value':'1'},'coverage_previous':{'value':'1'},
       'R25':'10000000000','R9':'9000000000','R9_previous':'8000000000',
       'R4_base':'3000000000','R4_low':'2000000000','R4_high':'4000000000',
       'R_base':'12000000000','R_low':'11000000000','R_high':'13000000000',
       'X25':'800000000','X9':'900000000','X4_base':'300000000','X4_low':'-100000000','X4_high':'600000000',
       'X_base':'1200000000','X_low':'800000000','X_high':'1500000000',
       'income_method_A':'2000000000','income_method_B':'4000000000',
       'season_weight':'.5','quarter_margin_base':'.1'}
    return m


def test_forecast_projection_preserves_actual_quarter_and_independent_growth():
    row=model_row(model(),I,'测试')
    assert row['前三季实际（亿元）']==9
    assert row['第四季度基准预测（亿元）']==3
    assert row['全年基准预测（亿元）']==12
    assert row['全年低情景（亿元）']==8 and row['全年高情景（亿元）']==15
    assert row['全年利润增长（%）']==50 and row['全年收入增长（%）']==20
    assert not {'codes','sample_id'}&row.keys()


def test_profit_and_deducted_models_keep_their_own_amounts_and_company_counts():
    p=model();d=model('D',('c',))
    for k in [x for x in d if x.startswith('X')]:d[k]=str(D(d[k])*2)
    d['quarter_margin_base']='.2'
    assert model_row(p,I,'测试')['全年基准预测（亿元）']==12
    row=model_row(d,I,'测试')
    assert row['全年基准预测（亿元）']==24 and row['可比公司数']==1
    c=model_row(model('C'),I,'测试')
    assert c['全年利润增长（%）'] is None and c['利润变化状态']=='现金流预测单列'


@pytest.mark.parametrize('key,value,message',[
 ('X_base','1300000000','annual identity'),('X_low','1300000000','annual identity'),
 ('income_method_A','1000000000','50/50'),('season_weight','.75','weight changed'),
 ('quarter_margin_base','.2','margin product'),('n',9,'company count')])
def test_frozen_forecast_contract_guards(key,value,message):
    f=model();f[key]=value
    with pytest.raises(ValueError,match=message):validate_model(f)


def test_negative_q4_and_full_year_loss_are_preserved_not_stacked_or_grown():
    f=model();f.update(X9='-100000000',X4_base='-200000000',X4_low='-300000000',X4_high='-100000000',
                       X_base='-300000000',X_low='-400000000',X_high='-200000000')
    f.pop('quarter_margin_base');r=model_row(f,I,'测试')
    assert r['全年基准预测（亿元）']==-3 and r['第四季度基准预测（亿元）']==-2
    assert r['全年利润增长（%）'] is None and r['利润变化状态']=='转亏'


def test_parent_child_amount_and_company_union_have_independent_checks():
    child={'identity':I,'forecasts':{k:model(k) for k in ('P','D','C')}}
    group=deepcopy(child);group['children']=[child]
    assert set(reconcile_models(group).values())=={D(0)}
    group['children']=[child,child]
    with pytest.raises(ValueError,match='company sets'):reconcile_models(group)
    group['children']=[deepcopy(child)]
    group['children'][0]['forecasts']['P']['X25']='800000002'
    with pytest.raises(ValueError,match='amount mismatch'):reconcile_models(group)


def literal_score():
    r=model('D',tuple('abcde'))
    r.update(sector_name='测试',sector_code='r',root='r',level=1,financial=False,
        eligible=True,score_available=True,total_score='50',dimensions=['20','40','60','80'],rank=5,
        raw=['.1','.2','.02','.1','.2','.4','.3333333333333333333333333333'],
        market_value_yuan='12000000000',deducted_ttm='1000000000',average_parent_equity='5000000000',qualification_failures=[])
    return r


def test_score_projection_uses_score_deducted_cohort_yuan_and_original_rank():
    r=score_row(literal_score(),'测试')
    assert r['综合得分']==50 and r['名次']==5
    assert r[RAW_NAMES[0]]==10 and r[RAW_NAMES[1]]==20 and r[RAW_NAMES[2]]==2
    assert r['同集市值（亿元）']==120 and r['评分同集全年扣非预测（亿元）']==12
    assert r['可比公司数']==5
    wrong=literal_score();wrong['total_score']='60'
    with pytest.raises(ValueError,match='four-dimension'):score_row(wrong,'测试')
    wrong=literal_score();wrong['raw'][0]='.2'
    with pytest.raises(ValueError,match='metrics or company'):score_row(wrong,'测试')
    wrong=literal_score();wrong['raw'][1]=None
    with pytest.raises(ValueError,match='Incomplete frozen'):score_row(wrong,'测试')


def test_unqualified_score_is_not_zero_or_an_invented_last_rank():
    r=literal_score();r.update(eligible=False,score_available=False,qualification_failures=['coverage_current_below_90pct_or_unknown'])
    row=score_row(r,'测试')
    assert row['名次'] is None and row['综合得分'] is None
    assert row['未评分原因']=='本期已知收入覆盖不足90%或未知'


def test_exact_cutoff_includes_true_ties_and_distinguishes_rounded_values():
    values=[{'name':k,'code':k,'value':D(v)} for k,v in [('a','1.004'),('b','1.003'),('c','1.004')]]
    assert [r['name'] for r in cutoff_ties(values,1)]==['a','c']


def sensitive_literal():
    row={'sector_name':'测试','sector_code':'r','root':'r','score_available':True,'rank':1,'level':1}
    alternative={'comparable_ranking':True,'peer_set_unchanged':True,'rows':[dict(row,rank=2)]}
    return [row],{'weight_sensitivity':{'available':True,'combinations':85,'rows':[{'sector_code':'r','min_rank':1,'max_rank':3,'top20_combinations':85,'top20_fraction':'1'}]},
        'model_sensitivity':{'0.25':deepcopy(alternative),'0.75':deepcopy(alternative),
          'exclude_top3':{'comparable_ranking':False,'failed_original_candidates':['r'],'original_metrics':[dict(row,
              coverage_current={'value':'.4'},coverage_previous={'value':'.5'},qualification_failures=['coverage_current_below_90pct_or_unknown'])]}}}


def test_sensitivity_frequency_is_not_probability_and_failed_set_not_reranked():
    ranks,source=sensitive_literal();w,m,h=sensitivity_rows(ranks,source,{'r':'测试'})
    assert w[0]['前20%组合占比（%）']==100 and w[0]['前20%组合数']==85
    assert m[0]['季节法50%名次']==1 and m[0]['季节法25%名次']==2
    assert h[0]['整体排名可比性']=='不可比' and h[0]['替代名次'] is None
    assert h[0]['剔除后本期已知收入覆盖（%）']==40
    source['model_sensitivity']['0.25']['rows']=[]
    with pytest.raises(ValueError,match='candidate set changed'):sensitivity_rows(ranks,source,{'r':'测试'})
