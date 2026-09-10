"""Frozen F1: skip variant-A B3 when high-to-close drawdown exceeds 2 daily ATRs."""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from statistics import mean, median
import time

import numpy as np

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_data import MinuteSpec
from scripts.research.index_market.chan.minute_diagnostics import authenticated_input, PLAN
from scripts.research.index_market.chan.minute_score import label_rows, select_events, summarize
from scripts.research.index_market.chan.run_m0 import save


@dataclass(frozen=True)
class BackgroundSpec(MinuteSpec):
    variant: str = 'F1-drawdown-2-ATR20'
    lookback_days: int = 20
    max_drawdown_atr: float = 2.0
    omit_year: str = '2024'
    omit_signal_date: str = '2024-10-10'


SPEC = BackgroundSpec()


def background(rows, spec=SPEC):
    """Forward-only daily accumulation; current day cannot enter ATR."""
    completed = deque(maxlen=spec.lookback_days+1)
    current, previous_time, result = None, '', []
    for row in rows:
        if row['time'] <= previous_time:
            raise ValueError('rows must be strictly time ordered')
        previous_time = row['time']
        if current is None or row['date'] != current['date']:
            if current is not None:
                prev_close = completed[-1]['close'] if completed else None
                tr = (max(current['high']-current['low'], abs(current['high']-prev_close),
                          abs(current['low']-prev_close)) if prev_close is not None else None)
                completed.append(dict(current, tr=tr))
            current = dict(date=row['date'], high=row['high'], low=row['low'], close=row['close'])
        else:
            current.update(high=max(current['high'], row['high']), low=min(current['low'], row['low']), close=row['close'])
        atr, high, distance = None, None, None
        if len(completed) >= spec.lookback_days+1:
            history = list(completed)[-spec.lookback_days:]
            atr = mean(r['tr'] for r in history)
            high = max(current['high'], max(r['high'] for r in history))
            if atr > 0:
                distance = (high-row['close'])/atr
        result.append(dict(time=row['time'], atr20=atr, reference_high=high, drawdown_atr=distance,
                           keep=distance is not None and distance <= spec.max_drawdown_atr))
    return result


def independent_background(rows, index, spec=SPEC):
    """Batch prefix aggregation: independent of forward daily state/deque."""
    prefix = rows[:index+1]
    days = sorted({r['date'] for r in prefix})
    if len(days) < spec.lookback_days+2:
        return None
    daily = []
    for day in days[-spec.lookback_days-2:]:
        rr = [r for r in prefix if r['date']==day]
        daily.append(dict(high=max(r['high'] for r in rr), low=min(r['low'] for r in rr), close=rr[-1]['close']))
    tr = [max(daily[j]['high']-daily[j]['low'], abs(daily[j]['high']-daily[j-1]['close']),
              abs(daily[j]['low']-daily[j-1]['close'])) for j in range(1, len(daily)-1)]
    atr = sum(tr)/spec.lookback_days
    high = max(r['high'] for r in daily[1:])
    return dict(atr20=atr, reference_high=high, drawdown_atr=(high-prefix[-1]['close'])/atr if atr else None)


def split_events(events, contexts):
    kept, removed = [], []
    for e in events:
        context = contexts[e['signal_index']]
        if context['time'] != e['signal_time'] or context['drawdown_atr'] is None:
            raise ValueError('event has missing/mismatched background')
        (kept if context['keep'] else removed).append(e)
    return kept, removed


def comparison(records):
    def stats(rr):
        return dict(n=len(rr), q=mean(r['q'] for r in rr) if rr else None,
                    median_q=median(r['q'] for r in rr) if rr else None,
                    positive=sum(r['q']>0 for r in rr), negative=sum(r['q']<0 for r in rr),
                    flat=sum(r['q']==0 for r in rr))
    kept = [r for r in records if r['keep']]
    removed = [r for r in records if not r['keep']]
    before, after = stats(records), stats(kept)
    fixed_q = sum(r['q'] for r in kept)/len(records) if records else None
    return dict(before=before, after=after, removed=stats(removed),
                missed_positive_q_sum=sum(r['q'] for r in removed if r['q']>0),
                avoided_negative_q_sum=-sum(r['q'] for r in removed if r['q']<0),
                fixed_opportunity_q=fixed_q,
                fixed_opportunity_delta=fixed_q-before['q'] if records else None,
                conditional_mean_delta=after['q']-before['q'] if kept else None)


def block_weights(year_days, n_days, block, size, rng):
    """year_days contains ALL scorable trading days, not only eligible dates."""
    weights = np.zeros((size, n_days))
    for yy in year_days:
        n = len(yy)
        length = min(block, n)
        starts = rng.integers(0, n-length+1, size=(size, (n+length-1)//length))
        indices = (starts[:, :, None]+np.arange(length)).reshape(size, -1)[:, :n]
        for j in range(size):
            weights[j, np.asarray(yy)] = np.bincount(indices[j], minlength=n)
    return weights


def background_intervals(scored, eligible_labels, all_labels, days, spec=SPEC):
    """Matched-background lift only; no CI claim for before/after mean change."""
    if not scored:
        return {}
    strata = sorted({r['stratum'] for r in all_labels.values()})
    sindex = {s:i for i,s in enumerate(strata)}
    bn, sn, bu, bq, su, sq = [np.zeros((len(days),len(strata))) for _ in range(6)]
    for r in eligible_labels.values():
        d, s = r['day'], sindex[r['stratum']]
        bn[d,s] += 1
        bu[d,s] += r['up']
        bq[d,s] += r['q']
    for r in scored:
        d, s = r['day'], sindex[r['stratum']]
        sn[d,s] += 1
        su[d,s] += r['up']
        sq[d,s] += r['q']
    # Critical: filtering must not compress calendar gaps before drawing blocks.
    valid_days = sorted({r['day'] for r in all_labels.values()})
    year_days = [[d for d in valid_days if days[d][:4]==year] for year in sorted({days[d][:4] for d in valid_days})]
    result = {}
    for block in spec.blocks:
        rng, draws = np.random.default_rng(spec.seed), []
        for start in range(0, spec.repetitions, 100):
            size = min(100, spec.repetitions-start)
            w = block_weights(year_days, len(days), block, size, rng)
            bc, sc = w@bn, w@sn
            n = sc.sum(axis=1)
            pair = []
            for base, signal in ((bu,su),(bq,sq)):
                bm = np.divide(w@base, bc, out=np.zeros_like(bc), where=bc>0)
                numerator = (w@signal-bm*sc).sum(axis=1)
                pair.append(np.divide(numerator, n, out=np.full(size,np.nan), where=n>0))
            draws.append(np.stack(pair, axis=1))
        samples = np.concatenate(draws)
        valid = samples[np.isfinite(samples).all(axis=1)]
        alpha = .05/spec.main_comparisons
        result[str(block)] = dict(valid_repetitions=len(valid), empty_repetitions=len(samples)-len(valid),
                                 full_calendar_days=len(valid_days), eligible_days=len({r['day'] for r in eligible_labels.values()}))
        for i, key in enumerate(('lift_up','lift_q')):
            result[str(block)][key] = (dict(ci95=np.quantile(valid[:,i],[.025,.975]).tolist(),
                                           simultaneous=np.quantile(valid[:,i],[alpha/2,1-alpha/2]).tolist())
                                      if len(valid)>=spec.repetitions*.9 else None)
    return result


def validate_contexts(rows, events, contexts, spec=SPEC):
    for e in events:
        i = e['signal_index']
        expected = independent_background(rows, i, spec)
        assert expected is not None
        for key, value in expected.items():
            assert value is not None and abs(value-contexts[i][key]) < 1e-10, key
        assert background(rows[:i+1], spec)[-1] == contexts[i]
    checks = []
    for cutoff in ('2022-12-31', '2024-12-31'):
        count = sum(r['date'] <= cutoff for r in rows)
        assert background(rows[:count], spec) == contexts[:count]
        perturbed = rows[:count]+[{**r, **{k:r[k]*1.7 for k in ('open','high','low','close')}} for r in rows[count:]]
        assert background(perturbed, spec)[:count] == contexts[:count]
        checks.append(dict(cutoff=cutoff, bars=count, unchanged=True))
    return dict(independent_events=len(events), per_event_prefix=len(events), whole_prefix_checks=checks)


def evaluate(events, all_labels, eligible_labels, contexts, spec=SPEC):
    before, original = summarize(events, all_labels)
    kept, removed = split_events(events, contexts)
    after, scored = summarize(kept, eligible_labels)
    assert before['tail_excluded']==after['tail_excluded']==0
    records = [dict(r, keep=contexts[r['index']]['keep'], **{k:contexts[r['index']][k] for k in ('atr20','reference_high','drawdown_atr')}) for r in original]
    overview = comparison(records)
    assert before['n']==len(kept)+len(removed) and after['n']==len(kept)
    annual = {year:comparison([r for r in records if r['date'][:4]==year]) for year in sorted({r['date'][:4] for r in records})}
    without_date = {day:comparison([r for r in records if r['date']!=day]) for day in sorted({r['date'] for r in records})}
    best = max(records, key=lambda r:r['q']) if records else None
    result = dict(before=before, after=after, effect=overview, yearly=annual,
                  without_2024=comparison([r for r in records if r['date'][:4]!=spec.omit_year]),
                  without_known_failure_date=comparison([r for r in records if r['date']!=spec.omit_signal_date]),
                  leave_date_out=without_date, original_best=best,
                  sample_gate=after['n']>=spec.min_events and len(after['year_counts'])>=spec.min_years)
    return result, records, scored


def execute(output, spec=SPEC):
    if asdict(spec)!=asdict(SPEC):
        raise ValueError('unapproved background specification')
    started = time.monotonic()
    output = safe_output(output)
    folder, manifest, source_audit, source = authenticated_input()
    for name in ('minute_score.py','minute_data.py','m0_data.py','run_m0.py','verify_minute.py'):
        if digest((Path(__file__).parent/name).read_bytes())!=manifest['code_sha256'][name]:
            raise ValueError(f'reused source changed: {name}')
    days = json.loads((folder/'calendar.json').read_bytes())
    if shutil.disk_usage(REPO/'reports').free < spec.reserve_bytes+spec.max_output_bytes:
        raise ValueError('insufficient report disk budget')
    output.mkdir(parents=True, exist_ok=False)
    metadata = dict(spec=asdict(spec), source_report=str(folder), source_manifest_sha256=digest((folder/'manifest.json').read_bytes()),
                    source_sha256=manifest['artifacts_sha256']['source.json'], source_audit=source_audit,
                    plan_sha256_before_run=digest(PLAN.read_bytes()), created_at_utc=datetime.now(timezone.utc).isoformat(),
                    code_sha256={p.name:digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')})
    save(output/'started.json', metadata)
    cells = []
    for code in spec.codes:
        for frequency in spec.frequencies:
            cell = f'{code}_{frequency}'
            prices = [r for r in source if r['code']==code and r['frequency']==frequency]
            contexts = background(prices, spec)
            labels = label_rows(prices, days, 1, spec)
            if any(contexts[i]['drawdown_atr'] is None for i in labels):
                raise ValueError('missing background in evaluation bars')
            eligible = {i:r for i,r in labels.items() if contexts[i]['keep']}
            all_events = json.loads((folder/cell/'events.json').read_bytes())
            saved_scored = json.loads((folder/cell/'next_day_scored.json').read_bytes())
            raw_events = select_events(all_events, days, 'B3', False, spec)
            verification = validate_contexts(prices, raw_events, contexts, spec)
            result = dict(code=code, frequency=frequency, all_bars=len(labels), eligible_bars=len(eligible), modes={})
            event_rows = []
            for mode in ('raw','cooldown'):
                events = select_events(all_events, days, 'B3', mode=='cooldown', spec)
                stats, records, scored = evaluate(events, labels, eligible, contexts, spec)
                expected = {r['event_id']:r for r in saved_scored if r['group']=='B3' and r['mode']==mode}
                assert {r['event_id'] for r in records}==set(expected)
                for r in records:
                    for key, value in expected[r['event_id']].items():
                        if key not in ('group','mode'):
                            assert r[key]==value, (cell, key)
                result['modes'][mode] = stats
                event_rows.extend(dict(mode=mode, **r) for r in records)
                if mode=='cooldown':
                    print(f'{cell}: {len(events)} -> {len(scored)}, computing full-calendar intervals', flush=True)
                    result['intervals'] = background_intervals(scored, eligible, labels, days, spec)
            cell_dir = output/cell
            cell_dir.mkdir()
            save(cell_dir/'metrics.json', result)
            save(cell_dir/'events.json', event_rows)
            save(cell_dir/'background.json', contexts)
            save(cell_dir/'verification.json', verification)
            cells.append(result)
            if time.monotonic()-started>spec.total_seconds or sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>spec.max_output_bytes:
                raise ValueError('execution/output budget exceeded')
            print(f'{cell}: saved and verified', flush=True)
    save(output/'metrics.json', cells)
    save(output/'manifest.json', dict(metadata, status='complete', seconds=time.monotonic()-started,
                                     artifacts_sha256={str(p.relative_to(output)):digest(p.read_bytes()) for p in output.rglob('*') if p.is_file()}))
    return dict(output=str(output), cells=len(cells), seconds=time.monotonic()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.output), ensure_ascii=False))


if __name__=='__main__':
    main()
