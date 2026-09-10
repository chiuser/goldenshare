"""C1: frozen breakout/retest versus A B3; research projections only."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_background import block_weights
from scripts.research.index_market.chan.minute_data import MinuteSpec, slots
from scripts.research.index_market.chan.minute_diagnostics import PLAN, authenticated_input
from scripts.research.index_market.chan.minute_score import label_rows, select_events, summarize
from scripts.research.index_market.chan.run_m0 import save


@dataclass(frozen=True)
class ComparisonSpec(MinuteSpec):
    variant: str = 'C1-breakout-retest-vs-A'
    breakout_days: int = 5
    wait_days: int = 1
    atr_days: int = 20
    tolerance_atr: float = 0.25
    trend_days: int = 20
    volatility_days: int = 60
    min_baseline_bars: int = 20
    main_comparisons: int = 36
    match_days: int = 1
    prefix_dates: tuple[str, ...] = ('2022-12-31', '2024-12-31')
    omit_year: str = '2024'
    common_weight: str = 'pooled_signal_counts_fixed'
    comparison_epsilon: float = 1e-12


SPEC = ComparisonSpec()


def contexts(rows, spec=SPEC):
    """Only completed days enter history; returned dictionaries are value snapshots."""
    history = deque(maxlen=max(spec.volatility_days, spec.trend_days, spec.atr_days)+1)
    current, result, previous_time = None, [], ''
    for row in rows:
        if row['time'] <= previous_time:
            raise ValueError('rows must be strictly time ordered')
        previous_time = row['time']
        if current is None or current['date'] != row['date']:
            if current is not None:
                prev = history[-1]['close'] if history else None
                tr = max(current['high']-current['low'], abs(current['high']-prev),
                         abs(current['low']-prev)) if prev else None
                history.append(dict(current, tr=tr, tr_pct=tr/prev if prev else None))
            current = dict(date=row['date'], high=row['high'], low=row['low'], close=row['close'])
        else:
            current.update(high=max(current['high'], row['high']), low=min(current['low'], row['low']), close=row['close'])
        hh = list(history)
        level = max(r['high'] for r in hh[-spec.breakout_days:]) if len(hh)>=spec.breakout_days else None
        atr = float(np.mean([r['tr'] for r in hh[-spec.atr_days:]])) if len(hh)>spec.atr_days else None
        trend = row['close']/hh[-spec.trend_days]['close']-1 if len(hh)>=spec.trend_days else None
        vol = None
        if len(hh)>spec.volatility_days:
            denom = float(np.mean([r['tr_pct'] for r in hh[-spec.volatility_days:]]))
            if denom>0:
                vol = float(np.mean([r['tr_pct'] for r in hh[-spec.atr_days:]]))/denom
        suffix = (f'{int(trend>=0 or math.isclose(trend,0,abs_tol=spec.comparison_epsilon))}|'
                  f'{int(vol>=1 or math.isclose(vol,1,rel_tol=spec.comparison_epsilon,abs_tol=spec.comparison_epsilon))}'
                  if trend is not None and vol is not None else None)
        result.append(dict(time=row['time'], level=level, atr20=atr, trend_return=trend,
                           volatility_ratio=vol, background=suffix))
    return result


def simple_signals(rows, context, frequency, spec=SPEC):
    """One active candidate, at most one start per day; no retrospective low fills."""
    if len(rows)!=len(context) or any(r['time']!=c['time'] for r,c in zip(rows,context)):
        raise ValueError('context alignment')
    window = len(slots(frequency))*spec.wait_days
    events, candidates, active, started_day = [], [], None, None
    for i, (row, ctx) in enumerate(zip(rows, context)):
        if active is not None:
            elapsed = i-active['breakout_index']
            level, tolerance = active['level'], active['tolerance']
            reason = None
            if row['close']<=level or row['low']<level-tolerance:
                reason = 'failed'
            elif abs(row['low']-level)<=tolerance and row['close']<rows[i-1]['close']:
                reason = 'triggered'
                events.append(dict(event_id=f"simple|{row['time']}", group='B3',
                    evaluation=row['date']>=spec.evaluation_start, signal_index=i,
                    signal_time=row['time'], breakout_index=active['breakout_index'],
                    breakout_time=active['breakout_time'], level=level, tolerance=tolerance))
            elif elapsed>=window:
                reason = 'expired'
            if reason:
                active.update(status=reason, end_index=i, end_time=row['time'])
                active = None
            continue
        if i==0 or started_day==row['date'] or ctx['level'] is None or ctx['atr20'] is None or ctx['atr20']<=0:
            continue
        if rows[i-1]['close']<=ctx['level']<row['close']:
            active = dict(breakout_index=i, breakout_time=row['time'], level=ctx['level'],
                          tolerance=spec.tolerance_atr*ctx['atr20'], status='pending_at_end',
                          end_index=None, end_time=None)
            candidates.append(active)
            started_day = row['date']
    return events, candidates


def matched_labels(labels, context):
    result = {}
    for i, label in labels.items():
        if context[i]['background'] is None:
            raise ValueError('missing evaluation background')
        result[i] = dict(label, stratum=label['stratum']+'|'+context[i]['background'])
    return result


def grouped(records):
    result = defaultdict(list)
    for r in records:
        result[r['stratum']].append(r)
    return result


def common_comparison(simple, chan, spec=SPEC, target_weights=None):
    ss, cc = grouped(simple), grouped(chan)
    common = sorted(ss.keys() & cc.keys())
    sn, cn = sum(len(ss[s]) for s in common), sum(len(cc[s]) for s in common)
    weights = {s:(len(ss[s])+len(cc[s]))/(sn+cn) for s in common} if target_weights is None else target_weights
    missing = sorted(set(weights)-set(common))
    result = dict(strata=len(common), weights=weights, missing_target_strata=missing, simple_n=sn, chan_n=cn,
                  simple_coverage=sn/len(simple) if simple else None,
                  chan_coverage=cn/len(chan) if chan else None,
                  sample_gate=not missing and sn>=spec.min_events and cn>=spec.min_events
                  and len({r['date'][:4] for s in common for r in ss[s]})>=spec.min_years
                  and len({r['date'][:4] for s in common for r in cc[s]})>=spec.min_years)
    for key in ('up', 'q'):
        for method, gr in (('simple',ss), ('chan',cc)):
            result[f'{method}_{key}'] = sum(weights[s]*float(np.mean([r[key] for r in gr[s]])) for s in weights) if weights and not missing else None
        result[f'delta_{key}'] = result[f'chan_{key}']-result[f'simple_{key}'] if weights and not missing else None
    return result


def evaluate(events_by_method, labels, spec=SPEC, target_weights=None):
    counts = {s:len(rr) for s,rr in grouped(labels.values()).items()}
    supported_labels = {i:r for i,r in labels.items() if counts[r['stratum']]>=spec.min_baseline_bars}
    result, records = {}, {}
    for method, events in events_by_method.items():
        all_stats, all_records = summarize(events, labels)
        supported_events = [e for e in events if e['signal_index'] in supported_labels]
        supported, scored = summarize(supported_events, supported_labels)
        records[method] = scored
        result[method] = dict(all=all_stats, supported=supported,
            unsupported_scored=all_stats['n']-supported['n'], signal_dates=len({r['date'] for r in all_records}),
            sample_gate=supported['n']>=spec.min_events and len(supported['year_counts'])>=spec.min_years)
    result['direct'] = common_comparison(records['simple'], records['chan'], spec, target_weights)
    return result, records, supported_labels


def intervals(records, eligible, all_labels, days, spec=SPEC):
    strata = sorted({r['stratum'] for r in eligible.values()})
    si = {s:i for i,s in enumerate(strata)}
    arrays = np.zeros((3, 3, len(days), len(strata)))
    for method, rr in enumerate((eligible.values(), records['simple'], records['chan'])):
        for r in rr:
            arrays[method, :, r['day'], si[r['stratum']]] += (1, r['up'], r['q'])
    common = common_comparison(records['simple'], records['chan'], spec)['weights']
    columns = [si[s] for s in common]
    target_w = np.asarray(list(common.values()))
    valid_days = sorted({r['day'] for r in all_labels.values()})
    years = [[d for d in valid_days if days[d][:4]==year] for year in sorted({days[d][:4] for d in valid_days})]
    result = {}
    for block in spec.blocks:
        rng, samples = np.random.default_rng(spec.seed), []
        for start in range(0, spec.repetitions, 100):
            size = min(100, spec.repetitions-start)
            w = block_weights(years, len(days), block, size, rng)
            totals = [[w@arrays[m,k] for k in range(3)] for m in range(3)]
            draw = np.full((size,3,2), np.nan)
            bn = totals[0][0]
            for m in (1,2):
                sn = totals[m][0]
                n = sn.sum(axis=1)
                valid = (n>0) & np.all((sn==0)|(bn>0), axis=1)
                for k in (1,2):
                    bm = np.divide(totals[0][k], bn, out=np.zeros_like(bn), where=bn>0)
                    numerator = (totals[m][k]-bm*sn).sum(axis=1)
                    draw[:,m-1,k-1] = np.divide(numerator,n,out=np.full(size,np.nan),where=valid)
            if columns:
                ns, nc = totals[1][0][:,columns], totals[2][0][:,columns]
                valid = np.all((ns>0)&(nc>0), axis=1)
                for k in (1,2):
                    sm = np.divide(totals[1][k][:,columns],ns,out=np.zeros_like(ns),where=ns>0)
                    cm = np.divide(totals[2][k][:,columns],nc,out=np.zeros_like(nc),where=nc>0)
                    draw[valid,2,k-1] = ((cm-sm)@target_w)[valid]
            samples.append(draw)
        values, summaries = np.concatenate(samples), {}
        alpha = .05/spec.main_comparisons
        for m, method in enumerate(('simple','chan','direct')):
            valid = values[:,m][np.isfinite(values[:,m]).all(axis=1)]
            out = dict(valid_repetitions=len(valid), missing_repetitions=len(values)-len(valid))
            for k, key in enumerate(('up','q')):
                out[key] = dict(ci95=np.quantile(valid[:,k],[.025,.975]).tolist(),
                    simultaneous=np.quantile(valid[:,k],[alpha/2,1-alpha/2]).tolist()) if len(valid)>=.9*spec.repetitions else None
            summaries[method] = out
        result[str(block)] = dict(full_calendar_days=len(valid_days), comparisons=summaries)
    return result


def nearest_pairs(simple, chan, rows, frequency, spec=SPEC):
    available = {e['event_id']:e for e in simple}
    pairs, unmatched = [], []
    for c in sorted(chan, key=lambda e:e['signal_index']):
        options = [s for s in available.values() if abs(s['signal_index']-c['signal_index'])<=len(slots(frequency))*spec.match_days]
        if not options:
            unmatched.append(c['event_id'])
            continue
        s = min(options,key=lambda e:(abs(e['signal_index']-c['signal_index']), e['signal_index']))
        del available[s['event_id']]
        si, ci = s['signal_index'], c['signal_index']
        pairs.append(dict(simple_id=s['event_id'], chan_id=c['event_id'], simple_time=s['signal_time'],
            chan_time=c['signal_time'], chan_minus_simple_bars=ci-si,
            signal_price_change=rows[ci]['close']/rows[si]['close']-1,
            entry_price_change=rows[ci+1]['open']/rows[si+1]['open']-1 if max(ci,si)+1<len(rows) else None))
    return dict(pairs=pairs, unmatched_chan=unmatched, unmatched_simple=sorted(available))


def sensitivity(events, labels, spec=SPEC):
    """Keep original cooldown identities; remove the same dates from the baseline."""
    result = {}
    original, _, _ = evaluate(events,labels,spec)
    target_weights = original['direct']['weights']
    dates = sorted({e['signal_time'][:10] for ee in events.values() for e in ee if e['signal_index'] in labels})
    for kind, exclusions in (('year',{y:{d for d in dates if d[:4]==y} for y in sorted({d[:4] for d in dates})}),
                             ('date',{d:{d} for d in dates})):
        result[kind] = {}
        for value, excluded in exclusions.items():
            ll = {i:r for i,r in labels.items() if (r['date'][:4]!=value if kind=='year' else r['date'] not in excluded)}
            ee = {m:[e for e in ev if e['signal_index'] in ll] for m,ev in events.items()}
            stats, _, _ = evaluate(ee,ll,spec,target_weights)
            result[kind][value] = stats
    result['without_best'] = {}
    for m, ee in events.items():
        valid = [e for e in ee if e['signal_index'] in labels]
        if valid:
            best = max(valid, key=lambda e:labels[e['signal_index']]['q'])
            rest = [labels[e['signal_index']]['q'] for e in valid if e['event_id']!=best['event_id']]
            result['without_best'][m] = dict(event_id=best['event_id'], best_q=labels[best['signal_index']]['q'],
                                            remaining_n=len(rest), q=float(np.mean(rest)) if rest else None)
    return result


def execute(output, spec=SPEC):
    if asdict(spec)!=asdict(SPEC):
        raise ValueError('unapproved comparison specification')
    from scripts.research.index_market.chan.verify_comparison import verify_cell

    started = time.monotonic()
    output = safe_output(output)
    folder, manifest, source_audit, source = authenticated_input()
    for name in ('minute_score.py','minute_data.py','m0_data.py','run_m0.py','verify_minute.py'):
        if digest((Path(__file__).parent/name).read_bytes())!=manifest['code_sha256'][name]:
            raise ValueError(f'reused source changed: {name}')
    days = json.loads((folder/'calendar.json').read_bytes())
    if shutil.disk_usage(REPO/'reports').free<spec.reserve_bytes+spec.max_output_bytes:
        raise ValueError('insufficient report disk budget')
    output.mkdir(parents=True, exist_ok=False)
    metadata = dict(spec=asdict(spec), source_report=str(folder), source_audit=source_audit,
        source_manifest_sha256=digest((folder/'manifest.json').read_bytes()),
        source_sha256=manifest['artifacts_sha256']['source.json'],
        plan_sha256_before_run=digest(PLAN.read_bytes()), created_at_utc=datetime.now(timezone.utc).isoformat(),
        code_sha256={p.name:digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')})
    save(output/'started.json',metadata)
    cells = []
    for code in spec.codes:
        for frequency in spec.frequencies:
            cell = f'{code}_{frequency}'
            print(f'{cell}: computing fixed shapes and backgrounds',flush=True)
            rows = [r for r in source if r['code']==code and r['frequency']==frequency]
            ctx = contexts(rows,spec)
            simple, candidates = simple_signals(rows,ctx,frequency,spec)
            if len(candidates)>spec.max_events or len(simple)>spec.max_events:
                raise ValueError('candidate/event budget exceeded')
            labels = label_rows(rows,days,1,spec)
            matched = matched_labels(labels,ctx)
            chan = json.loads((folder/cell/'events.json').read_bytes())
            old_scores = json.loads((folder/cell/'next_day_scored.json').read_bytes())
            stats, saved_events, methods = dict(code=code,frequency=frequency,modes={}), [], {}
            for mode in ('raw','cooldown'):
                methods = {m:select_events(ee,days,'B3',mode=='cooldown',spec) for m,ee in (('simple',simple),('chan',chan))}
                _, original = summarize(methods['chan'],labels)
                expected = {r['event_id']:{k:v for k,v in r.items() if k not in ('group','mode')}
                            for r in old_scores if r['group']=='B3' and r['mode']==mode}
                if {r['event_id']:r for r in original}!=expected:
                    raise ValueError('original A scoring changed')
                metrics, records, eligible = evaluate(methods,matched,spec)
                stats['modes'][mode] = metrics
                for method, ee in methods.items():
                    for e in ee:
                        label = matched.get(e['signal_index'])
                        saved_events.append(dict(method=method,mode=mode,event=e,label=label,
                                                 supported=label is not None and e['signal_index'] in eligible))
                if mode=='cooldown':
                    print(f'{cell}: simple={metrics["simple"]["all"]["n"]}, A={metrics["chan"]["all"]["n"]}; intervals',flush=True)
                    stats['intervals'] = intervals(records,eligible,matched,days,spec)
            stats['sensitivity'] = sensitivity(methods,matched,spec)
            stats['yearly'] = {}
            for year in sorted({r['date'][:4] for r in matched.values()}):
                ll = {i:r for i,r in matched.items() if r['date'][:4]==year}
                ee = {m:[e for e in ev if e['signal_index'] in ll] for m,ev in methods.items()}
                stats['yearly'][year] = evaluate(ee,ll,spec)[0]
            raw_s = select_events(simple,days,'B3',False,spec)
            raw_c = select_events(chan,days,'B3',False,spec)
            pairs = nearest_pairs(raw_s,raw_c,rows,frequency,spec)
            by_id = {e['event_id']:e for e in raw_s+raw_c}
            for pair in pairs['pairs']:
                for method in ('simple','chan'):
                    label = labels.get(by_id[pair[method+'_id']]['signal_index'])
                    pair[method+'_q'] = label['q'] if label else None
            verification = verify_cell(rows,days,ctx,simple,candidates,matched,methods,stats,frequency,spec)
            cell_dir = output/cell
            cell_dir.mkdir()
            for name,data in (('metrics',stats),('events',saved_events),('candidates',candidates),
                              ('contexts',ctx),('labels',list(matched.values())),('pairs',pairs),('verification',verification)):
                save(cell_dir/f'{name}.json',data)
            cells.append(stats)
            if time.monotonic()-started>spec.total_seconds or sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>spec.max_output_bytes:
                raise ValueError('execution/output budget exceeded')
            print(f'{cell}: independent verification passed; saved',flush=True)
    _, _, after_audit, _ = authenticated_input()
    if source_audit!=after_audit or any(digest((Path(__file__).parent/name).read_bytes())!=sha for name,sha in metadata['code_sha256'].items()):
        raise ValueError('source changed during run')
    save(output/'metrics.json',cells)
    save(output/'manifest.json',dict(metadata,status='complete',seconds=time.monotonic()-started,
        source_unchanged=True,artifacts_sha256={str(p.relative_to(output)):digest(p.read_bytes()) for p in output.rglob('*') if p.is_file()}))
    return dict(output=str(output),cells=len(cells),seconds=time.monotonic()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.output),ensure_ascii=False))


if __name__=='__main__':
    main()
