"""Trading-day labels, slot/year baselines and paired day-block uncertainty."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from scripts.research.index_market.chan.minute_data import MINUTE


def label_rows(rows, days, horizon, spec=MINUTE):
    day_number = {d:i for i,d in enumerate(days)}
    ends = {r['date']:i for i,r in enumerate(rows)}
    labels = {}
    for i, row in enumerate(rows):
        target = day_number[row['date']]+horizon
        if row['date']<spec.evaluation_start or target>=len(days) or i+1>=len(rows):
            continue
        end = ends[days[target]]
        entry = rows[i+1]['open']
        r = rows[end]['close']/row['close']-1
        q = rows[end]['close']/entry-1
        path = rows[i+1:end+1]
        labels[i] = dict(index=i,day=day_number[row['date']],date=row['date'],
            stratum=row['time'][:4]+'|'+row['time'][11:],signal_time=row['time'],
            entry_bar_end=rows[i+1]['time'],entry=entry,target_time=rows[end]['time'],
            r=r,q=q,up=float(r>0),q_up=float(q>0),
            mae=min(x['low'] for x in path)/entry-1,
            mfe=max(x['high'] for x in path)/entry-1)
    return labels


def select_events(events, days, group, cooldown, spec=MINUTE):
    day_number = {d:i for i,d in enumerate(days)}
    result, previous = [], -10**9
    for e in events:
        if not e['evaluation'] or e['group']!=group:
            continue
        day = day_number[e['signal_time'][:10]]
        if cooldown and day-previous<spec.cooldown_days:
            continue
        result.append(e)
        previous = day
    return result


def summarize(events, labels):
    strata = defaultdict(list)
    for label in labels.values():
        strata[label['stratum']].append(label)
    baseline = {s:{k:float(np.mean([r[k] for r in rr])) for k in ('up','q')}
                for s,rr in strata.items()}
    scored = []
    for e in events:
        label = labels.get(e['signal_index'])
        if label is not None:
            b = baseline[label['stratum']]
            scored.append(dict(event_id=e['event_id'],**label,
                baseline_up=b['up'],baseline_q=b['q'],lift_up=label['up']-b['up'],lift_q=label['q']-b['q']))
    result = dict(signals=len(events),n=len(scored),tail_excluded=len(events)-len(scored))
    for k in ('up','q_up','r','q','mae','mfe','baseline_up','baseline_q','lift_up','lift_q'):
        result[k] = float(np.mean([r[k] for r in scored])) if scored else None
    result['median_q'] = float(np.median([r['q'] for r in scored])) if scored else None
    result['year_counts'] = {year:sum(r['date'][:4]==year for r in scored)
                             for year in sorted({r['date'][:4] for r in scored})}
    result['yearly'] = {year:dict(n=sum(r['date'][:4]==year for r in scored),
        q=float(np.mean([r['q'] for r in scored if r['date'][:4]==year])),
        lift_q=float(np.mean([r['lift_q'] for r in scored if r['date'][:4]==year])))
        for year in result['year_counts']}
    return result,scored


def block_intervals(scored, labels, days, spec=MINUTE):
    """Resample signal and all-slot outcomes jointly, rebuilding matched baselines."""
    if not scored:
        return {}
    strata = sorted({r['stratum'] for r in labels.values()})
    sindex = {s:i for i,s in enumerate(strata)}
    shape = (len(days),len(strata))
    bn,sn,bu,bq,su,sq = [np.zeros(shape) for _ in range(6)]
    for r in labels.values():
        d,s = r['day'],sindex[r['stratum']]
        bn[d,s]+=1
        bu[d,s]+=r['up']
        bq[d,s]+=r['q']
    for r in scored:
        d,s = r['day'],sindex[r['stratum']]
        sn[d,s]+=1
        su[d,s]+=r['up']
        sq[d,s]+=r['q']
    valid_days = sorted({r['day'] for r in labels.values()})
    year_days = [[i for i in valid_days if days[i][:4]==y]
                 for y in sorted({days[i][:4] for i in valid_days})]
    results = {}
    for block in spec.blocks:
        rng = np.random.default_rng(spec.seed)
        diffs = []
        for start in range(0,spec.repetitions,100):
            size = min(100,spec.repetitions-start)
            weights = np.zeros((size,len(days)))
            for yy in year_days:
                n = len(yy)
                length = min(block,n)
                starts = rng.integers(0,n-length+1,size=(size,(n+length-1)//length))
                indices = (starts[:,:,None]+np.arange(length)).reshape(size,-1)[:,:n]
                for j in range(size):
                    weights[j,np.asarray(yy)] = np.bincount(indices[j],minlength=n)
            bcount,scount = weights@bn, weights@sn
            n_events = scount.sum(axis=1)
            for k,(base,signal) in enumerate(((bu,su),(bq,sq))):
                bm = np.divide(weights@base,bcount,out=np.zeros_like(bcount),where=bcount>0)
                numerator = (weights@signal-bm*scount).sum(axis=1)
                delta = np.divide(numerator,n_events,out=np.full(size,np.nan),where=n_events>0)
                if k==0:
                    pair = np.zeros((size,2))
                pair[:,k] = delta
            diffs.append(pair)
        values = np.concatenate(diffs)
        valid = values[np.isfinite(values).all(axis=1)]
        alpha = .05/spec.main_comparisons
        results[str(block)] = dict(valid_repetitions=len(valid),empty_repetitions=len(values)-len(valid))
        for i,k in enumerate(('lift_up','lift_q')):
            results[str(block)][k] = (dict(ci95=np.quantile(valid[:,i],[.025,.975]).tolist(),
                simultaneous=np.quantile(valid[:,i],[alpha/2,1-alpha/2]).tolist())
                if len(valid)>=spec.repetitions*.9 else None)
    return results
