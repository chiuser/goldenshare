"""Independent hand-calculated artificial money examples, not market forecasts."""
from decimal import Decimal as D
import pytest
from scripts.research.industry_financial.metrics import Book,R,P,DED,C,shift_quarter,facts
from scripts.research.industry_financial.forecast import forecast_group,corner,aggregate_forecasts
from scripts.research.industry_financial.ranking import percentiles,competition,score_level,compare_alternative


def fixture(code='000001.SZ'):
    # Literal YTD source-like records; units CNY yuan, report_type 1 per current contracts.
    dates=('2024-06-30','2024-09-30','2024-12-31','2025-06-30','2025-09-30','2025-12-31','2026-06-30','2026-09-30')
    revenues=(200,300,400,220,330,440,260,390)
    profits=('20','30','35','22','33','38.5','26','39')
    cash=('10','15','45','11','16.5','49.5','13','19.5')
    result={k:[] for k in ('income','fina_indicator','cashflow','balancesheet')}
    for date,r,p,c in zip(dates,revenues,profits,cash):
        result['income'].append({'ts_code':code,'end_date':date,'report_type':'1','revenue':str(r),'n_income_attr_p':p,'n_income':p})
        result['fina_indicator'].append({'ts_code':code,'end_date':date,'profit_dedt':p,'q_dtprofit':None})
        result['cashflow'].append({'ts_code':code,'end_date':date,'report_type':'1','n_cashflow_act':c})
    return result


def test_literal_forecast_and_cashflow():
    b=Book(fixture());codes=['000001.SZ']
    forecast=forecast_group(b,codes,'D')
    assert forecast['income_method_A']==D(130) and forecast['income_method_B']==D(130)
    assert forecast['R_base']==D(520)
    assert forecast['quarter_margin_base']==D('.05')
    assert forecast['X4_base']==D('6.5') and forecast['X_base']==D('45.5')
    assert forecast_group(b,codes,'C')['X_base']==D('58.5')
    assert b.flow(DED,codes[0],'2024-12-31')==D(5)
    assert b.ttm(DED,codes[0])==D('44.5')
    assert b.ttm(DED,codes[0],'2024-09-30') is None
    assert shift_quarter('2025-03-31',-1)=='2024-12-31'


def test_negative_corner_and_missing_history_not_filled():
    # With a negative margin, high revenue may be the worst profit.
    assert corner(D(100),D(200),D('-.3'),D('-.1'),D(-30))==(D(-60),D(-10))
    rows=fixture();rows['fina_indicator'][0]['profit_dedt']=None
    assert not forecast_group(Book(rows),['000001.SZ'],'D')['available']
    rows=fixture();rows['fina_indicator'][2]['q_dtprofit']='999'
    assert Book(rows).flow(DED,'000001.SZ','2024-12-31') is None
    assert not forecast_group(Book(rows),['000001.SZ'],'D')['available']


def test_parent_sum_not_independent_fit():
    rows=fixture();other=fixture('000002.SZ')
    for key in rows:rows[key]+=other[key]
    book=Book(rows)
    children=[forecast_group(book,[c],'D') for c in ('000001.SZ','000002.SZ')]
    parent=aggregate_forecasts(book,['000001.SZ','000002.SZ'],children,'D')
    assert parent['R_base']==D(1040) and parent['X_base']==D(91)
    with pytest.raises(ValueError):aggregate_forecasts(book,['000001.SZ'],[children[0],children[0]],'D')


def test_common_sample_and_restatement_do_not_change_absolute_fact():
    b=Book(fixture(),noncomparable=['000001.SZ'])
    assert b.get(R,'000001.SZ','2024-12-31')==D(400)
    assert b.common(['000001.SZ'],[(R,'2026-09-30'),(R,'2025-09-30')])==()
    assert not forecast_group(b,['000001.SZ'],'D')['available']
    rows=fixture();rows['income'][1]['revenue']=None
    b=Book(rows)
    assert not forecast_group(b,['000001.SZ'],'D')['available']
    assert b.get(DED,'000001.SZ','2024-09-30')==D(30)


def test_percentiles_ties_small_sets_and_fixed_candidates():
    assert percentiles(list(map(D,[1,2,3,4,5])))==list(map(D,[0,25,50,75,100]))
    assert percentiles([D(1)]*5)==[D(50)]*5
    assert percentiles(list(map(D,[1,2,3,4,5])),True)==list(map(D,[100,75,50,25,0]))
    assert percentiles([D(1)]*4) is None
    assert competition([D(8),D(8),D(7)])==[1,1,3]
    rows=[{'sector_code':str(i),'eligible':True,'raw':[D(i+1)]*7} for i in range(5)]
    scored=score_level(rows)
    assert all(r['score_available'] for r in scored)
    altered=[dict(r,eligible=r['sector_code']!='2') for r in rows]
    assert not compare_alternative(scored,altered)['comparable_ranking']
    assert not score_level(rows[:4])[0]['score_available']


def test_repeating_percentile_totals_keep_mathematical_ties():
    # Artificial ordinal inputs. Average-rank step=100/6; four equal dimensions.
    # Rows 1 and 4 both have weighted ordinal sum 21/8, hence 43.75 exactly.
    matrix=[[6,6,2,0,3,6,5],[3,2,1,5,2,4,3],[5,3,0,6,4,2,0],
            [0,5,6,2,1,0,6],[1,4,3,1,5,5,1],[2,0,4,4,6,3,4],[4,1,5,3,0,1,2]]
    result={r['sector_code']:r for r in score_level([
        {'sector_code':str(i),'eligible':True,'raw':list(map(D,values))} for i,values in enumerate(matrix)])}
    assert result['1']['total_score']==result['4']['total_score']==D('43.75')
    assert result['1']['rank']==result['4']['rank']==5
    assert result['3']['rank']==7


def test_fact_axes_handle_losses_and_zero():
    rows=fixture();rows['income'][-1]['n_income_attr_p']='-10';rows['income'][4]['n_income_attr_p']='-20'
    book=Book(rows)
    f=facts(book,['000001.SZ'])['plots'][1]
    assert f['available'] and f['x']>0 and f['y']>0 # loss shrinks; denominator is revenue
    assert f['raw']['parent_profit']==D(-10)


def test_targeted_restatement_preserves_good_periods():
    rows=fixture()
    rows['income'] += [{'ts_code':'000001.SZ','end_date':'2025-03-31','revenue':'100'},
                       {'ts_code':'000001.SZ','end_date':'2026-03-31','revenue':'120'}]
    book=Book(rows,noncomparable={'000001.SZ':{'boundary':'2025-01-01','unrestated_periods':['2025-03-31']}})
    code=['000001.SZ']
    assert book.common(code,[(R,'2025-09-30'),(R,'2026-09-30')])==tuple(code)
    assert book.common(code,[(R,'2024-09-30'),(R,'2025-09-30')])==()
    assert book.common(code,[(R,'2025-06-30','quarter'),(R,'2026-06-30','quarter')])==()
    assert book.get(R,code[0],'2025-03-31')==D(100)


def test_negative_equity_company_kept_but_aggregate_must_be_positive():
    from scripts.research.industry_financial.ranking import raw_score
    from scripts.research.industry_financial.metrics import CURRENT,PRIOR
    class LiteralBook:
        def get(self,field,code,date):
            if field[0]=='valuation':return D(1)
            if field[1]=='total_hldr_eqy_exc_min_int':return D(-2) if code=='a' else D(10)
            if field[1]=='total_assets':return D(10)
            return D(1)
        def total(self,field,codes,date):return sum(self.get(field,c,date) for c in codes)
    b=LiteralBook();codes=list('abcde')
    f={'available':True,'codes':codes,'X_base':D(5),'X25':D(4),'R25':D(10),'R_base':D(12),'X_low':D(3),
       'coverage_current':{'valid':True,'value':D(1)},'coverage_previous':{'valid':True,'value':D(1)}}
    result=raw_score(b,codes,f)
    assert result['eligible'] and result['negative_equity_companies']==1
    assert result['average_parent_equity']==D(38)
    assert result['market_value_yuan']==D(50000)
    original=b.get
    b.get=lambda field,code,date: D(-10) if field[1]=='total_hldr_eqy_exc_min_int' else original(field,code,date)
    assert 'nonpositive_or_missing_denominator' in raw_score(b,codes,f)['qualification_failures']
    f['coverage_current']={'valid':True,'value':D('.8999')}
    assert not raw_score(LiteralBook(),codes,f)['eligible']


def test_joint_coverage_does_not_drop_large_missing_comparator():
    rows=fixture();other=fixture('000002.SZ')
    # A large company has known sales, but missing prior profit; joint analysis
    # must expose its lost revenue rather than using only the smaller denominator.
    for r in other['income']:r['revenue']='10000'
    other['fina_indicator'][4]['profit_dedt']=None
    for key in rows:rows[key]+=other[key]
    plot=facts(Book(rows),['000001.SZ','000002.SZ'])['plots'][3]
    assert plot['codes']==['000001.SZ']
    assert plot['coverage_current']['value']<D('.04')


def test_average_receivable_and_270_day_basis_not_end_balance():
    rows=fixture()
    for date,balance in [('2024-12-31','10'),('2025-09-30','14'),('2025-12-31','20'),('2026-09-30','30')]:
        rows['balancesheet'].append({'ts_code':'000001.SZ','end_date':date,'accounts_receiv':balance})
    plot=facts(Book(rows),['000001.SZ'])['plots'][7]
    # (20+30)/2 /390 *270 =225/13; prior (10+14)/2 /330 *270=108/11.
    assert plot['available']
    assert abs(plot['raw']['current_days']-D(225)/13)<D('1e-20')
    assert abs(plot['raw']['prior_days']-D(108)/11)<D('1e-20')
    assert abs(plot['y']-D(1071)/143)<D('1e-20')
    assert not facts(Book(rows),['000001.SZ'],'2025-09-30')['plots'][7]['available']


def test_company_median_and_two_year_cagr_not_ratio_average():
    rows=fixture();other=fixture('000002.SZ')
    other['income'][4]['revenue']='100'
    other['income'][-1]['revenue']='200'
    for key in rows:rows[key]+=other[key]
    metrics={m['metric']:m for m in facts(Book(rows),['000001.SZ','000002.SZ'])['metrics']}
    expected=(D(390)/330-1+D(1))/2
    assert abs(metrics['company_median_revenue_yoy']['value']-expected)<D('1e-20')
    expected_cagr=(D(590)/600).sqrt()-1
    assert metrics['revenue_two_year_cagr']['value']==expected_cagr
    assert metrics['revenue_improved_fraction']['value']==D(1)
    assert metrics['parent_current_performance']['value']['label']=='增收增利'
