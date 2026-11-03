"""Only the approved revenue/margin formulas; second-level first, then sum."""
from decimal import Decimal as D
from .metrics import R,P,DED,C,CURRENT,PRIOR,ratio,sample_id,descriptor
from .spec import SPEC

HISTORY=('2024-06-30','2024-09-30','2024-12-31','2025-06-30','2025-09-30','2025-12-31','2026-06-30','2026-09-30')
KINDS={'P':P,'D':DED,'C':C}


def model_requirements(kind,extra=()):
    field=KINDS[kind]
    periods=HISTORY if kind!='C' else ('2024-09-30','2024-12-31','2025-09-30','2025-12-31','2026-09-30')
    return [(R,d) for d in HISTORY]+[(field,d) for d in periods]+list(extra)


def model_sample(book,universe,kind,extra=()):
    sample=book.common(universe,model_requirements(kind,extra))
    if kind=='D':sample=tuple(c for c in sample if all(book.flow(DED,c,f'{y}-12-31') is not None for y in (2024,2025)))
    return sample


def corner(revenue_low,revenue_high,margin_low,margin_high,base):
    values=[r*m for r in (revenue_low,revenue_high) for m in (margin_low,margin_high)]+[base]
    return min(values),max(values)


def forecast_group(book,universe,kind,extra=(),season_weight=None):
    sample=model_sample(book,universe,kind,extra)
    if not sample:return {'available':False,'reason':'incomplete_model_history','kind':kind,**descriptor(book,sample,universe)}
    field=KINDS[kind]
    get=lambda f,d:book.total(f,sample,d)
    quarter=lambda f,d:book.total(f,sample,d,quarter=True)
    r9={y:get(R,f'{y}-09-30') for y in (2024,2025,2026)}
    r3={y:quarter(R,f'{y}-09-30') for y in (2024,2025,2026)}
    r4={y:quarter(R,f'{y}-12-31') for y in (2024,2025)}
    if any(x is None or x<=0 for x in list(r9.values())+list(r3.values())+list(r4.values())):
        return {'available':False,'reason':'nonpositive_revenue_model_input','kind':kind,**descriptor(book,sample,universe)}
    weight=D(SPEC.revenue_season_weight) if season_weight is None else D(season_weight)
    a=r9[2026]*(r4[2024]/r9[2024]+r4[2025]/r9[2025])/2
    b=r4[2025]*r3[2026]/r3[2025]
    rb=weight*a+(1-weight)*b;rl,rh=min(a,b),max(a,b)
    if kind=='C':
        current=get(C,CURRENT)/r9[2026]
        deltas=[quarter(C,f'{y}-12-31')/r4[y]-get(C,f'{y}-09-30')/r9[y] for y in (2024,2025)]
    else:
        current=quarter(field,CURRENT)/r3[2026]
        deltas=[quarter(field,f'{y}-12-31')/r4[y]-quarter(field,f'{y}-09-30')/r3[y] for y in (2024,2025)]
    margin=current+sum(deltas,D(0))/2
    paths=[current+d for d in deltas]+[margin]
    xb=rb*margin;xl,xh=corner(rl,rh,min(paths),max(paths),xb)
    x9=get(field,CURRENT)
    result={'available':True,'kind':kind,**descriptor(book,sample,universe),'sample_losses':book.explain(universe,model_requirements(kind,extra),sample),
       'R9':r9[2026],'R9_previous':r9[2025],'X9':x9,'R25':get(R,'2025-12-31'),'X25':get(field,'2025-12-31'),
       'R4_base':rb,'R4_low':rl,'R4_high':rh,'X4_base':xb,'X4_low':xl,'X4_high':xh,
       'R_base':r9[2026]+rb,'R_low':r9[2026]+rl,'R_high':r9[2026]+rh,
       'X_base':x9+xb,'X_low':x9+xl,'X_high':x9+xh,
       'income_method_A':a,'income_method_B':b,'quarter_margin_base':margin,
       'quarter_margin_paths':paths,'season_weight':weight,'scope':book.scope_label+'_forecast'}
    if not result['X_low']<=result['X_base']<=result['X_high']:raise AssertionError('Scenario does not contain base')
    return result


SUM_KEYS=('R9','R9_previous','X9','R25','X25','R4_base','R4_low','R4_high','X4_base','X4_low','X4_high','R_base','R_low','R_high','X_base','X_low','X_high','income_method_A','income_method_B')

def aggregate_forecasts(book,universe,children,kind):
    valid=[c for c in children if c['available']]
    sample=tuple(sorted(c for child in valid for c in child['codes']))
    if len(sample)!=len(set(sample)):raise ValueError('Duplicate companies between second-level industries')
    if not valid:return {'available':False,'kind':kind,'reason':'no_valid_child_forecast',**descriptor(book,(),universe)}
    result={key:sum((c[key] for c in valid),D(0)) for key in SUM_KEYS}
    result.update(available=True,kind=kind,**descriptor(book,sample,universe),
                  scope=book.scope_label+'_child_amounts_sum',child_count=len(valid),low_high_meaning='simultaneous_child_model_bounds_not_probability',
                  sample_losses=[{'code':code,'reason':'excluded_or_invalid_child_model','details':[loss for child in children for loss in child.get('sample_losses',[]) if loss['code']==code]} for code in sorted(set(universe)-set(sample))])
    return result
