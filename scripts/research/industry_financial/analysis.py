"""Process one root at a time; freeze tables before building charts."""
from collections import defaultdict
from decimal import Decimal as D
from .spec import SPEC
from .storage import atomic_json,load,digest
from .metrics import Book,R,DED,CURRENT,PRIOR,facts,fact_series,sample_id,descriptor
from .forecast import forecast_group,aggregate_forecasts,model_sample
from .ranking import EXTRA,raw_score,score_level,weight_sensitivity,compare_alternative


def top_three(book,codes):
    valid=book.common(codes,[(R,'2025-12-31')])
    return sorted(valid,key=lambda c:(-book.get(R,c,'2025-12-31'),c))[:3]


def group_output(book,codes,meta,kind_models):
    return {'identity':meta,'facts':facts(book,codes),'series':fact_series(book,codes),'forecasts':kind_models,
            'model_sample_fingerprint':{k:f.get('sample_id') for k,f in kind_models.items()}}


def analyze(store):
    store.check();store.save(status='CALCULATING')
    samples=load(store.path/'calculations/sample.json')
    quality=load(store.path/'evidence/quality.json')
    semantic=quality.get('semantic_pass',False)
    raw_levels={1:[],2:[]};groups=[];alternatives={str(w):{1:[],2:[]} for w in SPEC.model_weights if w!='0.5'}
    alternatives['exclude_top3']={1:[],2:[]};checks=[]
    tree=list(store.rows('tree')) if store.scope.name=='formal' else []
    roots=sorted(r['sector_code'] for r in tree if r['industry_level']==1) if tree else SPEC.roots
    for root in roots:
        store.check()
        members=[r for r in samples if r['root']==root];universe=[r['ts_code'] for r in members]
        book=Book.from_run(store,universe)
        parents=sorted(r['sector_code'] for r in tree if r['industry_level']==2 and r['root_sector_code']==root) if tree else sorted({r['parent'] for r in members})
        children=[];score_children=[]
        child_models={k:[] for k in ('P','D','C')}
        root_name=next(r['sector_name'] for r in tree if r['sector_code']==root) if tree else members[0]['root_name']
        financial=root_name in ('银行','非银金融')
        root_meta={'sector_code':root,'sector_name':root_name,'level':1,'root':root,'financial':financial}
        def model(codes,kind,**kwargs):
            if financial:return dict(available=False,reason='financial_industry_observation_only',kind=kind,**descriptor(book,(),codes))
            return forecast_group(book,codes,kind,**kwargs)
        for parent in parents:
            subset=[r['ts_code'] for r in members if r['parent']==parent]
            meta={'sector_code':parent,'sector_name':next(r['sector_name'] for r in tree if r['sector_code']==parent) if tree else next(r['parent_name'] for r in members if r['parent']==parent),'level':2,'root':root,'financial':financial}
            models={k:model(subset,k) for k in ('P','D','C')}
            for k,f in models.items():child_models[k].append(f)
            score_forecast=model(subset,'D',extra=EXTRA);score_children.append(score_forecast)
            raw_levels[2].append(dict(raw_score(book,subset,score_forecast,semantic),**meta))
            children.append(group_output(book,subset,meta,models))
            for weight in alternatives:
                if weight=='exclude_top3':
                    remaining=sorted(set(subset)-set(top_three(book,subset)))
                    f=model(remaining,'D',extra=EXTRA)
                    if f['available']:
                        # Qualification remains relative to the original trial universe.
                        f.update(descriptor(book,f['codes'],subset))
                else:f=model(subset,'D',extra=EXTRA,season_weight=weight)
                alternatives[weight][2].append(dict(raw_score(book,subset,f,semantic),**meta))
        models={k:aggregate_forecasts(book,universe,values,k) for k,values in child_models.items()}
        root_group=group_output(book,universe,root_meta,models)
        score_forecast=aggregate_forecasts(book,universe,score_children,'D')
        raw_levels[1].append(dict(raw_score(book,universe,score_forecast,semantic),**root_meta))
        for weight in alternatives:
            removed=set(top_three(book,universe)) if weight=='exclude_top3' else set()
            fs=[]
            for parent in parents:
                subset=[r['ts_code'] for r in members if r['parent']==parent and r['ts_code'] not in removed]
                fs.append(model(subset,'D',extra=EXTRA,season_weight=None if weight=='exclude_top3' else weight))
            f=aggregate_forecasts(book,universe,fs,'D')
            alternatives[weight][1].append(dict(raw_score(book,universe,f,semantic),**root_meta))
        for k,f in models.items():
            if not f['available']:continue
            field={'P':('income','n_income_attr_p'),'D':('fina_indicator','profit_dedt'),'C':('cashflow','n_cashflow_act')}[k]
            direct=book.total(field,f['codes'],CURRENT)
            checks.append({'root':root,'kind':k,'unique_codes':len(f['codes'])==len(set(f['codes'])),
                           'actual_9m_difference':f['X9']-direct,
                           'actual_9m_matches_independent_sum':abs(f['X9']-direct)<=D(SPEC.amount_tolerance),
                           'full_year_difference':f['X_base']-(f['X9']+f['X4_base']),
                           'full_year_identity':abs(f['X_base']-(f['X9']+f['X4_base']))<=D(SPEC.amount_tolerance),
                           'range_contains_base':f['X_low']<=f['X_base']<=f['X_high']})
        root_group['children']=children
        root_group['observed_deducted_quarter_conflicts']=[{'code':c,'period':d,'reason':reason} for (c,d),reason in book.invalid_quarters.items()]
        atomic_json(store.path/'calculations'/f'{root}.json',root_group)
        groups.append(root_group)
        print('CALCULATED',root_meta['sector_name'],'children',len(children),flush=True)
        del book
    ranked={str(level):score_level(rows) for level,rows in raw_levels.items()}
    sensitive={str(level):{'weight_sensitivity':weight_sensitivity(ranked[str(level)]),
        'model_sensitivity':{w:compare_alternative(ranked[str(level)],a[level]) for w,a in alternatives.items()}}
        for level in (1,2)}
    passed=all(all(check[key] for key in ('unique_codes','actual_9m_matches_independent_sum','full_year_identity','range_contains_base')) for check in checks)
    atomic_json(store.path/'evidence/reconciliation.json',{'checks':checks,'all_pass':passed,'tolerance_yuan':SPEC.amount_tolerance,'basis':'raw input sum and annual identity, with residuals preserved'})
    if not passed:raise AssertionError('Ledger reconciliation failed')
    atomic_json(store.path/'calculations/ranking.json',ranked)
    atomic_json(store.path/'calculations/sensitivity.json',sensitive)
    atomic_json(store.path/'calculations/groups.json',groups)
    store.save(status='CALCULATIONS_SAVED')
    return groups,ranked
