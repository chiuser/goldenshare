"""Fixed seven metrics, complete candidates, average ranks and exact ties."""
from decimal import Decimal as D
from itertools import product
from math import ceil
from fractions import Fraction as F
from .metrics import R,DED,C,E,A,L,CURRENT,PRIOR,ratio,descriptor
from .spec import SPEC

EXTRA=((C,CURRENT),(E,PRIOR),(E,CURRENT),(A,CURRENT),(L,CURRENT),
       (('valuation','total_mv'),SPEC.snapshot),(('valuation','close'),SPEC.snapshot),(('valuation','total_share'),SPEC.snapshot))


def raw_score(book,universe,f,semantic_pass=True):
    result=dict(f)
    failures=[]
    if not f['available']:
        return dict(result,eligible=False,qualification_failures=[f['reason']],raw=None)
    sample=f['codes']; get=lambda field,date:book.total(field,sample,date)
    if not semantic_pass:failures.append('deducted_attribution_unverified')
    if len(sample)<SPEC.min_companies:failures.append('fewer_than_5_companies')
    for key in ('coverage_current','coverage_previous'):
        c=f[key]
        if not c['valid'] or c['value']<D(SPEC.min_coverage):failures.append(key+'_below_90pct_or_unknown')
    if any(book.get(R,c,CURRENT) is None and book.get(R,c,PRIOR) is None for c in universe):failures.append('both_revenue_periods_unknown')
    if f['X_base']<=0:failures.append('nonpositive_forecast_deducted_profit')
    ep,ec=get(E,PRIOR),get(E,CURRENT)
    equity=None if ep is None or ec is None else (ep+ec)/2
    assets=get(A,CURRENT);mv=get(('valuation','total_mv'),SPEC.snapshot)
    if mv is not None:mv*=10000
    if any(x is None or x<=0 for x in (equity,ec,assets,mv,f['R25'],f['R_base'])):failures.append('nonpositive_or_missing_denominator')
    if any(book.get(field,c,SPEC.snapshot) is None or book.get(field,c,SPEC.snapshot)<=0
           for c in sample for field in (('valuation','close'),('valuation','total_share'),('valuation','total_mv'))):failures.append('invalid_quote')
    dttm=get(DED,'2025-12-31')+get(DED,CURRENT)-get(DED,PRIOR)
    raw=[ratio(f['X_base'],mv),ratio(f['R_base'],f['R25']),
         None if ratio(f['X_base'],f['R_base']) is None or ratio(f['X25'],f['R25']) is None else f['X_base']/f['R_base']-f['X25']/f['R25'],
         ratio(get(C,CURRENT),get(R,CURRENT)),ratio(dttm,equity),ratio(get(L,CURRENT),assets),
         ratio(f['X_base']-f['X_low'],f['X_base'])]
    if raw[1] is not None:raw[1]-=1
    if any(x is None for x in raw):failures.append('incomplete_metric')
    result.update(eligible=not failures,qualification_failures=failures,raw=raw,
                  market_value_yuan=mv,deducted_ttm=dttm,average_parent_equity=equity,
                  negative_equity_companies=sum(book.get(E,c,CURRENT)<0 for c in sample))
    return result


def percentile_fractions(values,lower_better=False):
    if len(values)<SPEC.min_peers:return None
    if any(v is None for v in values):raise ValueError('Missing metric cannot be reweighted')
    n=len(values);out=[]
    for value in values:
        less=sum(x<value for x in values);equal=sum(x==value for x in values)
        rank=F(less)+F(equal+1,2)
        p=100*(rank-1)/(n-1)
        out.append(100-p if lower_better else p)
    return out


def decimal(value):return D(value.numerator)/D(value.denominator)


def percentiles(values,lower_better=False):
    values=percentile_fractions(values,lower_better)
    return None if values is None else list(map(decimal,values))


def dimension_fractions(rows):
    columns=[percentile_fractions([r['raw'][k] for r in rows],k in (5,6)) for k in range(7)]
    return [[p[0],(p[1]+p[2])/2,(p[3]+p[4])/2,(p[5]+p[6])/2]
            for p in zip(*columns)],columns


def competition(values):return [1+sum(other>value for other in values) for value in values]


def score_level(rows,weights=None):
    result=[dict(row) for row in rows]
    eligible=[r for r in result if r.get('eligible')]
    if len(eligible)<SPEC.min_peers:
        for r in result:r.update(score_available=False,score_reason='fewer_than_5_qualified_industries' if r.get('eligible') else 'qualification_failed')
        return result
    exact_dimensions,metric_scores=dimension_fractions(eligible)
    weights=tuple(F(w) for w in (weights or SPEC.dimension_weights));exact_totals=[]
    for i,row in enumerate(eligible):
        p=[column[i] for column in metric_scores]
        dimensions=exact_dimensions[i]
        total=sum((w*v for w,v in zip(weights,dimensions)),F(0));exact_totals.append(total)
        row.update(score_available=True,metric_percentiles=list(map(decimal,p)),dimensions=list(map(decimal,dimensions)),
                   total_score=decimal(total))
    ranks=competition(exact_totals)
    for row,rank in zip(eligible,ranks):row['rank']=rank
    for r in result:
        if not r.get('eligible'):r.update(score_available=False,score_reason='qualification_failed')
    return sorted(result,key=lambda r:(not r.get('score_available'),-r.get('total_score',D(0)),r['sector_code']))


def weight_sensitivity(rows):
    candidates=[r for r in rows if r.get('score_available')]
    if len(candidates)<SPEC.min_peers:return {'available':False,'reason':'small_complete_peer_group'}
    weights=[w for w in product(map(D,SPEC.sensitivity_weights),repeat=4) if sum(w)==1]
    exact_dimensions,_=dimension_fractions(candidates)
    positions={r['sector_code']:[] for r in candidates};k=ceil(D('.2')*len(candidates));top={key:0 for key in positions}
    for ws in weights:
        values=[sum((F(w)*x for w,x in zip(ws,dimensions)),F(0)) for dimensions in exact_dimensions]
        ranks=competition(values)
        for row,rank in zip(candidates,ranks):
            key=row['sector_code'];positions[key].append(rank);top[key]+=rank<=k
    return {'available':True,'combinations':len(weights),'top20_boundary_ties':'all included',
            'rows':[{'sector_code':key,'min_rank':min(rs),'max_rank':max(rs),'top20_combinations':top[key],'top20_fraction':D(top[key])/len(weights)} for key,rs in positions.items()]}


def compare_alternative(original,alternative):
    original_candidates={r['sector_code'] for r in original if r.get('eligible')}
    changed={r['sector_code']:r for r in alternative}
    failed=sorted(key for key in original_candidates if key not in changed or not changed[key].get('eligible'))
    if failed or len(original_candidates)<SPEC.min_peers:
        return {'comparable_ranking':False,'failed_original_candidates':failed,'reason':'original_peer_group_not_complete_or_small',
                'original_metrics':alternative}
    scored=score_level([changed[key] for key in sorted(original_candidates)])
    return {'comparable_ranking':True,'rows':scored,'peer_set_unchanged':True}
