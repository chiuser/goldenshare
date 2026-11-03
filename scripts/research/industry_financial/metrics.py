"""Decimal facts and joint samples, per methodology 1.3/3/4."""
from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
import json
from statistics import median
from .spec import SPEC,FIELDS

D=Decimal
CURRENT='2026-09-30'; PRIOR='2025-09-30'
R=('income','revenue');P=('income','n_income_attr_p');N=('income','n_income')
DED=('fina_indicator','profit_dedt');C=('cashflow','n_cashflow_act')
E=('balancesheet','total_hldr_eqy_exc_min_int')
A=('balancesheet','total_assets');L=('balancesheet','total_liab')
AR=('balancesheet','accounts_receiv');INV=('balancesheet','inventories')
FA=('balancesheet','fix_assets_total');COST=('income','oper_cost')


def dec(value):
    if value is None:return None
    number=D(str(value))
    if not number.is_finite():raise ValueError('Non-finite monetary value')
    return number
def ratio(a,b):return None if a is None or b is None or b<=0 else a/b

def prior_year(date):return str(int(date[:4])-1)+date[4:]

def shift_quarter(date,offset):
    year,month=int(date[:4]),int(date[5:7]);ordinal=year*4+month//3-1+offset
    year,q=divmod(ordinal,4)
    return f'{year}-{((q+1)*3):02d}-{30 if q in (1,2) else 31:02d}'

def sample_id(codes):return sha256(','.join(sorted(codes)).encode()).hexdigest()[:16]

class Book:
    def __init__(self,records,valuation=(),noncomparable=(),scope_label="trial_selected_codes_only"):
        self.scope_label=scope_label
        self.noncomparable=dict(noncomparable) if isinstance(noncomparable,dict) else {c:{'all_multi_period':True} for c in noncomparable}
        self.data={k:{} for k in FIELDS}
        for kind,rows in records.items():
            for row in rows:
                key=(row['ts_code'],row.get('end_date',row.get('trade_date')))
                if key in self.data[kind]:raise ValueError('Duplicate book key')
                if 'report_type' in row and row['report_type']!='1':raise ValueError('Wrong consolidated type')
                self.data[kind][key]=row
        for row in valuation:self.data['valuation'][(row['ts_code'],row['trade_date'])]=row
        self.invalid_quarters={}
        for (code,date),row in self.data['fina_indicator'].items():
            if date.endswith('12-31'):
                ytd=self.get(DED,code,date[:4]+'-09-30');full=self.get(DED,code,date)
                direct=dec(row.get('q_dtprofit'))
                if None not in (ytd,full,direct) and abs(direct-(full-ytd))>D(SPEC.amount_tolerance):
                    self.invalid_quarters[(code,date)]='direct_q4_differs_from_cumulative'

    @classmethod
    def from_run(cls,store,codes):
        codes=set(codes)
        records={kind:[r for date in SPEC.dates for r in store.rows(kind+'_'+date) if r['ts_code'] in codes]
                 for kind in ('income','balancesheet','cashflow','fina_indicator')}
        from .storage import load
        quality=load(store.path/'evidence/quality.json') if (store.path/'evidence/quality.json').exists() else {}
        return cls(records,[r for r in store.rows('valuation') if r['ts_code'] in codes],quality.get('noncomparable_codes',{}),'current_candidate_industry_known_revenue' if store.scope.name=='formal' else 'trial_selected_codes_only')

    def get(self,field,code,date):
        if date not in SPEC.dates and field[0]!='valuation':return None
        return dec(self.data[field[0]].get((code,date),{}).get(field[1]))

    def flow(self,field,code,date):
        current=self.get(field,code,date)
        if date.endswith('03-31'):return current
        if field==DED and (code,date) in self.invalid_quarters:return None
        prior=self.get(field,code,shift_quarter(date,-1))
        return None if current is None or prior is None else current-prior

    def ttm(self,field,code,date=CURRENT):
        values=[self.get(field,code,x) for x in (f'{int(date[:4])-1}-12-31',date,prior_year(date))]
        return None if any(v is None for v in values) else values[0]+values[1]-values[2]

    def common(self,codes,requirements):
        def value(code,req):
            field,date,*mode=req
            return self.flow(field,code,date) if mode and mode[0]=='quarter' else self.get(field,code,date)
        periods={r[1] for r in requirements if r[0][0]!='valuation'}
        if any(len(r)>2 and r[2]=='quarter' and not r[1].endswith('03-31') for r in requirements):
            periods.update(shift_quarter(r[1],-1) for r in requirements if len(r)>2 and r[2]=='quarter' and not r[1].endswith('03-31'))
        def comparable(code):
            rule=self.noncomparable.get(code)
            if not rule or len(periods)<=1:return True
            if rule.get('all_multi_period'):return False
            boundary=rule.get('boundary')
            if boundary and min(periods)<boundary<=max(periods):return False
            return not set(rule.get('unrestated_periods',[]))&periods
        return tuple(sorted(c for c in codes if comparable(c) and all(value(c,r) is not None for r in requirements)))

    def explain(self,universe,requirements,sample):
        result=[]
        for code in sorted(set(universe)-set(sample)):
            missing=[]
            for field,date,*mode in requirements:
                value=self.flow(field,code,date) if mode and mode[0]=='quarter' else self.get(field,code,date)
                if value is None:missing.append({'dataset':field[0],'field':field[1],'period':date,'basis':mode[0] if mode else 'reported'})
            reason=self.noncomparable.get(code) if not missing and code in self.noncomparable else None
            result.append({'code':code,'missing':missing,'comparability':reason,'reason':'missing_or_invalid_inputs' if missing else 'known_comparability_boundary' if reason else 'quarter_conflict_or_model_input'})
        return result

    def total(self,field,codes,date,quarter=False):
        values=[self.flow(field,c,date) if quarter else self.get(field,c,date) for c in codes]
        if not values or any(v is None for v in values):return None
        return sum(values,D(0))

    def coverage(self,codes,universe,date):
        known=self.common(universe,[(R,date)])
        numerator=self.total(R,codes,date);denominator=self.total(R,known,date)
        value=ratio(numerator,denominator)
        return {'value':value,'known_companies':len(known),'candidate_companies':len(universe),
                'scope':self.scope_label,'valid':value is not None and 0<=value<=1}


def descriptor(book,codes,universe,date=CURRENT):
    return {'codes':list(codes),'sample_id':sample_id(codes),'n':len(codes),'candidate_n':len(universe),
            'coverage_current':book.coverage(codes,universe,date),
            'coverage_previous':book.coverage(codes,universe,prior_year(date))}


def facts(book,universe,date=CURRENT):
    prior=prior_year(date);plots={};tables=[]
    def plot(number,requirements,calculate):
        codes=book.common(universe,requirements)
        row={'chart':number,**descriptor(book,codes,universe,date),'period':date,'kind':'observed','sample_losses':book.explain(universe,requirements,codes)}
        try:
            x,y,raw=calculate(codes)
            if x is None or y is None:raise ValueError('nonpositive_denominator')
            row.update(x=x,y=y,raw=raw,available=True)
        except (ValueError,ZeroDivisionError,TypeError):row.update(x=None,y=None,available=False,reason='missing_inputs_or_invalid_denominator')
        plots[number]=row
    total=lambda f,s,t,**kw:book.total(f,s,t,**kw)
    req=lambda fs,ds:[(f,d) for f in fs for d in ds]
    def operating(s):
        rt,r0,pt,p0=[total(f,s,d) for f,d in ((R,date),(R,prior),(P,date),(P,prior))]
        return (ratio(rt,r0)-1 if ratio(rt,r0) is not None else None)*100,(ratio(pt-p0,r0)*100 if ratio(pt-p0,r0) is not None else None),{'revenue':rt,'prior_revenue':r0,'parent_profit':pt,'prior_parent_profit':p0}
    plot(1,req((R,P),(date,prior)),operating)
    last=shift_quarter(date,-1)
    def momentum(s):
        vals=[total(R,s,d,quarter=True) for d in (date,prior,last,prior_year(last))]
        g,g0=ratio(vals[0],vals[1]),ratio(vals[2],vals[3])
        return (g-1)*100,(g-g0)*100,{'growth':g-1,'previous_quarter_growth':g0-1,'current_quarter_revenue':vals[0],'prior_year_quarter_revenue':vals[1],'previous_quarter_revenue':vals[2],'prior_year_previous_quarter_revenue':vals[3]}
    plot(2,[(R,d,'quarter') for d in (date,prior,last,prior_year(last))],momentum)
    def rates(s):
        rt,r0=total(R,s,date),total(R,s,prior)
        mt,m0=ratio(total(DED,s,date),rt),ratio(total(DED,s,prior),r0)
        ct,c0=ratio(total(C,s,date),rt),ratio(total(C,s,prior),r0)
        return (mt-m0)*100,(ct-c0)*100,{'deducted_margin':mt,'cashflow_margin':ct,'prior_deducted_margin':m0,'prior_cashflow_margin':c0,'revenue':rt,'prior_revenue':r0,'deducted_profit':total(DED,s,date),'prior_deducted_profit':total(DED,s,prior),'operating_cashflow':total(C,s,date),'prior_operating_cashflow':total(C,s,prior)}
    plot(3,req((R,DED,C),(date,prior)),rates)
    def breadth(s):
        x=(ratio(total(DED,s,date),total(R,s,date))-ratio(total(DED,s,prior),total(R,s,prior)))*100
        improved=sum(book.get(DED,c,date)>book.get(DED,c,prior) for c in s)
        return x,D(improved)/D(len(s))*100,{'improved_companies':improved,'total_companies':len(s),'revenue':total(R,s,date),'prior_revenue':total(R,s,prior),'deducted_profit':total(DED,s,date),'prior_deducted_profit':total(DED,s,prior),'deducted_margin':ratio(total(DED,s,date),total(R,s,date))}
    plot(4,req((R,DED),(date,prior)),breadth)
    beginning=f'{int(date[:4])-1}-12-31';prior_beginning=f'{int(date[:4])-2}-12-31'
    for number,asset,denom in ((7,AR,R),(8,INV,COST)):
        def turnover(s,asset=asset,denom=denom):
            rt,r0=total(R,s,date),total(R,s,prior)
            current_balance=(total(asset,s,beginning)+total(asset,s,date))/2
            old_balance=(total(asset,s,prior_beginning)+total(asset,s,prior))/2
            days=D(int(date[5:7]))*30
            current_days=ratio(current_balance,total(denom,s,date))*days
            old_days=ratio(old_balance,total(denom,s,prior))*days
            return (ratio(rt,r0)-1)*100,current_days-old_days,{'current_days':current_days,'prior_days':old_days,'current_average_balance':current_balance,'prior_average_balance':old_balance,'revenue':rt,'prior_revenue':r0,'current_denominator':total(denom,s,date),'prior_denominator':total(denom,s,prior)}
        plot(number,req((R,denom),(date,prior))+req((asset,),(date,prior,beginning,prior_beginning)),turnover)
    def fixed(s):
        r=ratio(total(R,s,date),total(R,s,prior));f=ratio(total(FA,s,date),total(FA,s,prior))
        return (r-1)*100,(f-1)*100,{'fixed_assets':total(FA,s,date),'prior_fixed_assets':total(FA,s,prior),'revenue':total(R,s,date),'prior_revenue':total(R,s,prior)}
    plot(9,req((R,FA),(date,prior)),fixed)
    # Independent fact metrics each carry their actual joint sample.
    metric_specs=[('cashflow_rate',[(C,date),(R,date)],lambda s:ratio(total(C,s,date),total(R,s,date))),
      ('sales_cash_rate',[(('cashflow','c_fr_sale_sg'),date),(R,date)],lambda s:ratio(total(('cashflow','c_fr_sale_sg'),s,date),total(R,s,date))),
      ('gross_margin',[(R,date),(COST,date)],lambda s:ratio(total(R,s,date)-total(COST,s,date),total(R,s,date))),
      ('operating_margin',[(('income','operate_profit'),date),(R,date)],lambda s:ratio(total(('income','operate_profit'),s,date),total(R,s,date))),
      ('liabilities_assets',[(L,date),(A,date)],lambda s:ratio(total(L,s,date),total(A,s,date))),
      ('cash_surplus',[(C,date),(('cashflow','c_pay_acq_const_fiolta'),date)],lambda s:total(C,s,date)-total(('cashflow','c_pay_acq_const_fiolta'),s,date)),
      ('partial_working_capital',[(AR,date),(INV,date),(('balancesheet','accounts_pay'),date)],lambda s:total(AR,s,date)+total(INV,s,date)-total(('balancesheet','accounts_pay'),s,date)),
      ('fixed_assets_assets',[(FA,date),(A,date)],lambda s:ratio(total(FA,s,date),total(A,s,date)))]
    for name,requirements,calculate in metric_specs:
        codes=book.common(universe,requirements)
        value=calculate(codes) if codes else None
        tables.append({'metric':name,'value':value,**descriptor(book,codes,universe,date)})
    return {'plots':plots,'metrics':tables+extra_facts(book,universe,date),'trend':trend(book,universe,date)}


def trend(book,codes,date):
    periods=[shift_quarter(date,-i) for i in range(3)]
    req=[(f,d,'quarter') for d in periods+[prior_year(d) for d in periods] for f in (R,DED)]
    sample=book.common(codes,req)
    if not sample:return {'label':'资料不足','n':0}
    def level(d):
        rt=book.total(R,sample,d,quarter=True);r0=book.total(R,sample,prior_year(d),quarter=True)
        g=ratio(rt,r0);m=ratio(book.total(DED,sample,d,quarter=True),rt)
        m0=ratio(book.total(DED,sample,prior_year(d),quarter=True),r0)
        b=D(sum(book.flow(DED,c,d)>book.flow(DED,c,prior_year(d)) for c in sample))/len(sample)
        if None in (g,m,m0):raise ValueError('nonpositive trend revenue')
        return g-1,m-m0,b
    try:now,previous,earlier=[level(d) for d in periods]
    except ValueError:return {'label':'资料不足','n':len(sample)}
    sign=lambda x:(x>0)-(x<0)
    def direction(a,b):
        signals=[sign(a[0]-b[0]),sign(a[1]),sign(a[2]-b[2])]
        return (1 if signals.count(1)>=2 else -1 if signals.count(-1)>=2 else 0),signals
    current,signals=direction(now,previous);old,_=direction(previous,earlier)
    label=('景气上升' if old==1 else '边际改善') if current==1 else ('景气下降' if old==-1 else '边际转弱') if current==-1 else '震荡分化'
    return {'label':label,'n':len(sample),'sample_id':sample_id(sample),'signals':signals,'magnitudes':now}


def fact_series(book,universe):
    fields={'revenue':R,'parent_profit':P,'deducted_profit':DED,'cashflow':C,'accounts_receivable':AR,'inventory':INV,'fixed_assets':FA,'assets':A}
    rows=[]
    for date in SPEC.dates:
        for name,field in fields.items():
            sample=book.common(universe,[(field,date)])
            old=prior_year(date);same=book.common(universe,[(field,date),(field,old)])
            a,b=book.total(field,same,date),book.total(field,same,old)
            growth=ratio(a,b)
            if field in (P,DED):
                same=book.common(same,[(R,old)])
                a,b=book.total(field,same,date),book.total(field,same,old)
                growth=ratio(a,b)
                base_revenue=book.total(R,same,old)
                if b is None or b<=0 or base_revenue is None or base_revenue<=0 or abs(b)/base_revenue<D(SPEC.near_zero_profit) or (a is not None and a<0):growth=None
            rows.append({'metric':name,'period':date,'basis':'period_end' if field[0]=='balancesheet' else 'year_to_date',
                         'amount':book.total(field,sample,date),'n':len(sample),'sample_id':sample_id(sample),
                         'comparison_n':len(same),'comparison_current':a,'comparison_previous':b,'yoy':None if growth is None else growth-1})
    return rows


def extra_facts(book,universe,date=CURRENT):
    prior=prior_year(date);previous_fy=f'{int(date[:4])-1}-12-31'
    rows=[]
    def add(name,requirements,fn):
        sample=book.common(universe,requirements)
        value=None
        if sample:
            try:value=fn(sample)
            except (TypeError,ZeroDivisionError):pass
        rows.append({'metric':name,'value':value,**descriptor(book,sample,universe,date)})
    t=lambda f,s,d:book.total(f,s,d)
    for field,name in ((P,'parent_margin'),(DED,'deducted_margin'),(N,'consolidated_margin')):
        add(name,[(field,date),(R,date)],lambda s,f=field:ratio(t(f,s,date),t(R,s,date)))
    older=prior_year(prior)
    add('revenue_two_year_cagr',[(R,date),(R,older)],lambda s:
        None if t(R,s,date)<=0 or t(R,s,older)<=0 else (t(R,s,date)/t(R,s,older)).sqrt()-1)
    for field,name in ((('balancesheet','contract_assets'),'contract_assets_yoy'),
                       (('balancesheet','contract_liab'),'contract_liabilities_yoy')):
        add(name,[(field,date),(field,prior)],lambda s,f=field:
            None if ratio(t(f,s,date),t(f,s,prior)) is None else t(f,s,date)/t(f,s,prior)-1)
    add('receivable_growth_less_revenue_growth',[(f,d) for f in (AR,R) for d in (date,prior)],lambda s:
        None if ratio(t(AR,s,date),t(AR,s,prior)) is None or ratio(t(R,s,date),t(R,s,prior)) is None
        else t(AR,s,date)/t(AR,s,prior)-t(R,s,date)/t(R,s,prior))
    # Company medians use valid individual denominators. Invalid companies remain
    # in amount aggregates, and the lost median sample is explicitly recorded.
    for name,requirements,individual in (
        ('company_median_revenue_yoy',[(R,date),(R,prior)],lambda c:
         None if book.get(R,c,prior)<=0 else book.get(R,c,date)/book.get(R,c,prior)-1),
        ('company_median_deducted_margin_change',[(f,d) for f in (R,DED) for d in (date,prior)],lambda c:
         None if min(book.get(R,c,date),book.get(R,c,prior))<=0 else book.get(DED,c,date)/book.get(R,c,date)-book.get(DED,c,prior)/book.get(R,c,prior))):
        complete=book.common(universe,requirements)
        values={c:individual(c) for c in complete};sample=tuple(c for c in complete if values[c] is not None)
        rows.append({'metric':name,'value':median(values[c] for c in sample) if sample else None,
                     'invalid_individual_denominators':sorted(set(complete)-set(sample)),**descriptor(book,sample,universe,date)})
    for field,label in ((R,'revenue_improved_fraction'),(DED,'deducted_profit_improved_fraction')):
        add(label,[(field,date),(field,prior)],lambda s,f=field:D(sum(book.get(f,c,date)>book.get(f,c,prior) for c in s))/len(s))
    for field,label in ((P,'parent_current_performance'),(DED,'deducted_current_performance')):
        def performance(s,f=field):
            dr=t(R,s,date)-t(R,s,prior);dp=t(f,s,date)-t(f,s,prior)
            return {'revenue_change':dr,'profit_change':dp,'label':'持平' if dr==0 or dp==0 else
                    '增收增利' if dr>0 and dp>0 else '增收不增利' if dr>0 else '减收增利' if dp>0 else '收入利润双降'}
        add(label,[(f,d) for f in (R,field) for d in (date,prior)],performance)
    add('profit_cash_conversion',[(C,date),(N,date)],lambda s:ratio(t(C,s,date),t(N,s,date)))
    for field,name in ((('cashflow','c_pay_acq_const_fiolta'),'capital_expenditure'),(('balancesheet','contract_assets'),'contract_assets'),(('balancesheet','contract_liab'),'contract_liabilities')):
        add(name,[(field,date)],lambda s,f=field:t(f,s,date))
    for asset,denominator,name in ((AR,R,'receivable_days'),(INV,COST,'inventory_days')):
        add(name,[(asset,previous_fy),(asset,date),(denominator,date)],lambda s,a=asset,d=denominator:ratio((t(a,s,previous_fy)+t(a,s,date))/2,t(d,s,date))*D(int(date[5:7])*30))
    flow_dates=(previous_fy,date,prior)
    def ttm(field,s):return t(field,s,previous_fy)+t(field,s,date)-t(field,s,prior)
    add('asset_turnover_ttm',[(R,d) for d in flow_dates]+[(A,d) for d in (prior,date)],lambda s:ratio(ttm(R,s),(t(A,s,date)+t(A,s,prior))/2))
    for field,name in ((P,'parent_roe_ttm'),(DED,'deducted_roe_ttm')):
        add(name,[(field,d) for d in flow_dates]+[(E,d) for d in (prior,date)],lambda s,f=field:ratio(ttm(f,s),(t(E,s,date)+t(E,s,prior))/2))
    ec=('balancesheet','total_hldr_eqy_inc_min_int')
    def dupont(s):
        n,r=ttm(N,s),ttm(R,s);a=(t(A,s,date)+t(A,s,prior))/2;e=(t(ec,s,date)+t(ec,s,prior))/2
        ratios=(ratio(n,r),ratio(r,a),ratio(a,e))
        if any(v is None for v in ratios):return None
        return {'consolidated_margin_ttm':ratios[0],'asset_turnover_ttm':ratios[1],'equity_multiplier':ratios[2],
                'product':ratios[0]*ratios[1]*ratios[2],'direct_consolidated_roe':n/e}
    add('consolidated_dupont',[(f,d) for f in (N,R) for d in flow_dates]+[(f,d) for f in (A,ec) for d in (prior,date)],dupont)
    for field,label in ((P,'parent_profit_change_decomposition'),(DED,'deducted_profit_change_decomposition')):
        def decompose(s,f=field):
            r1,r0=t(R,s,date),t(R,s,prior);x1,x0=t(f,s,date),t(f,s,prior)
            m1,m0=ratio(x1,r1),ratio(x0,r0)
            if m1 is None or m0 is None:return None
            contribution_r=(r1-r0)*(m1+m0)/2;contribution_m=(m1-m0)*(r1+r0)/2
            return {'revenue_contribution':contribution_r,'margin_contribution':contribution_m,'total_change':x1-x0,'residual':x1-x0-contribution_r-contribution_m}
        add(label,[(f,d) for f in (R,field) for d in (date,prior)],decompose)
    for field,label in ((P,'parent_loss_fraction'),(DED,'deducted_loss_fraction')):
        add(label,[(field,date)],lambda s,f=field:D(sum(book.get(f,c,date)<0 for c in s))/len(s))
    sample=book.common(universe,[(f,d) for f in (R,P) for d in (date,prior)])
    top=sorted(sample,key=lambda c:(-book.get(R,c,prior),c))[:3]
    rows.append({'metric':'prior_revenue_top3_parent_profit_contribution','value':[
        {'code':c,'base_revenue':book.get(R,c,prior),'profit_change':book.get(P,c,date)-book.get(P,c,prior)} for c in top],**descriptor(book,sample,universe,date)})
    return rows
