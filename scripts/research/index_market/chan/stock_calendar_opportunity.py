"""Market-calendar observation without fabricated suspension prices."""
from collections import Counter, defaultdict
from statistics import mean

from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.chan.minute_data import slots


def tradable(row):
    return row is not None and row['vol'] > 0 and row['amount'] > 0


def grid(rows, days):
    lookup = {r['time']: r for r in rows}
    if len(lookup) != len(rows):
        raise ValueError('duplicate rows')
    times = [f'{d} {s}' for d in days for s in slots(30)]
    if set(lookup)-set(times):
        raise ValueError('unexpected timestamp')
    return times, [lookup.get(t) for t in times]


def outcome(times, rows, i, bars):
    start, end = i+1, i+bars
    if end >= len(rows):
        return None, 'tail'
    if not tradable(rows[start]):
        return None, 'entry_untradable'
    if not tradable(rows[end]):
        return None, 'exit_untradable'
    price = rows[start]['open']
    window = [r for r in rows[start:end+1] if tradable(r)]
    first = 'neither'
    for r in window:
        up, down = r['high'] >= price*(1+base.SPEC.barrier), r['low'] <= price*(1-base.SPEC.barrier)
        if up or down:
            first = 'ambiguous' if up and down else 'up' if up else 'down'
            break
    return dict(index=i,entry_index=start,exit_index=end,signal_time=times[i],
        entry_bar=times[start],exit_time=times[end],entry_price=price,
        return_value=rows[end]['close']/price-1,
        favorable=max(0,max(r['high'] for r in window)/price-1),
        adverse=min(0,min(r['low'] for r in window)/price-1),first=first), None


def evaluate(rows, days, events):
    times, data = grid(rows, days)
    lookup = {t:i for i,t in enumerate(times)}
    start = base.SPEC.warmup_days*8
    groups = {g:set() for g in ('B1','B2','B3','ALL')}
    for e in events:
        if e['group'] not in ('B1','B2','B3'):
            continue
        i = lookup[e['signal_time']]
        if not e['buy'] or not e['sure'] or data[i] is None:
            raise ValueError('invalid event')
        if i >= start:
            groups[e['group']].add(i)
            groups['ALL'].add(i)
    summaries, details = [], []
    for horizon in base.SPEC.horizons:
        observations = {i:outcome(times,data,i,horizon*8) for i in range(start,len(data)) if data[i] is not None}
        ordinary = [x for x,reason in observations.values() if x is not None]
        pools = defaultdict(list)
        for x in ordinary:
            pools[(x['signal_time'][:4],x['signal_time'][11:])].append(x)
        stats = {k:base.aggregate(v) for k,v in pools.items()}
        def comparison(items):
            a = base.aggregate(items)
            if not items:
                return dict(signals=a,matched_mean=None,excess=None,without_best=None)
            b = mean(stats[(x['signal_time'][:4],x['signal_time'][11:])]['mean'] for x in items)
            values = sorted(x['return_value'] for x in items)
            return dict(signals=a,matched_mean=b,excess=a['mean']-b,without_best=mean(values[:-1]) if len(values)>1 else None)
        for group,indices in groups.items():
            items=[dict(observations[i][0],group=group,horizon=horizon) for i in sorted(indices) if observations[i][0] is not None]
            matched=[stats[(x['signal_time'][:4],x['signal_time'][11:])] for x in items]
            summaries.append(dict(group=group,horizon=horizon,total=len(indices),censored=len(indices)-len(items),
                censor_reasons=dict(Counter(observations[i][1] for i in indices if observations[i][0] is None)),
                signals=base.aggregate(items),ordinary=base.aggregate(ordinary),
                matched={k:mean(x[k] for x in matched) for k in matched[0] if k!='n'} if matched else {},
                nonoverlap=base.aggregate(base.nonoverlap(items)),nonoverlap_comparison=comparison(base.nonoverlap(items)),
                without_best=comparison(items)['without_best'],
                annual={y:comparison([x for x in items if x['signal_time'][:4]==y]) for y in sorted({d[:4] for d in days[base.SPEC.warmup_days:]})}))
            details.extend(items)
    available=sorted(i+1 for i in groups['ALL'] if i+1<len(data) and tradable(data[i+1]))
    candidates=[]
    for i in range(start+8,len(data),8):
        x,_=outcome(times,data,i-1,base.SPEC.rally_days*8)
        if x is None:
            continue
        early=[j for j in available if abs(j//8-i//8)<=base.SPEC.early_days]
        during=[j for j in available if i<=j<=x['exit_index']]
        first=during[0] if during else None
        x.update(early=bool(early),early_bars=[times[j] for j in early],
            first_signal_bar=times[first] if first is not None else None,
            delay_days=first//8-i//8 if first is not None else None,
            already_risen=data[first]['open']/data[i]['open']-1 if first is not None else None)
        candidates.append(x)
    rallies=base.nonoverlap([x for x in candidates if x['return_value']>=base.SPEC.rally_return])
    return dict(summary=summaries,events=details,eligible_start=times[start],
        recall=dict(n=len(rallies),early_count=sum(x['early'] for x in rallies),ordinary_dates=len(candidates),
            ordinary_early_rate=mean(x['early'] for x in candidates) if candidates else None,rallies=rallies))
