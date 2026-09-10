"""Explain frozen variant-A events without changing signals or fitting filters."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.verify_minute import audit


@dataclass(frozen=True)
class DiagnosticSpec:
    report: str = 'reports/chan_minute_variant_a_20260909'
    manifest_sha256: str = '631e7cecffc4df6bf7784d11b81c5a13c4dc0af114e042d83500f9a0cd7ef089'
    lookback_days: int = 20
    max_files: int = 100
    max_bytes: int = 128 * 1024**2
    max_rows: int = 50000
    max_events: int = 1000


SPEC = DiagnosticSpec()
FEATURES = ('return20', 'drawdown20', 'amount_ratio', 'anchor_rebound')
PLAN = REPO/'docs/product/chan-signal-prediction-and-profit-experiment-plan-v1.md'


def features(rows, event, lookback=SPEC.lookback_days):
    """Only the prefix can affect features, including the current day's amount."""
    i, a = event['signal_index'], event['anchor_index']
    if not 0 <= a <= i < len(rows) or rows[i]['time'] != event['signal_time']:
        raise ValueError('invalid event index/time/anchor')
    prefix = rows[:i+1]
    now = prefix[-1]
    days = sorted({r['date'] for r in prefix})
    if len(days) <= lookback:
        raise ValueError('insufficient completed history')
    previous = days[-lookback-1:-1]
    history = [r for r in prefix if r['date'] in previous]
    today = [r for r in prefix if r['date'] == now['date']]
    base_close = [r['close'] for r in history if r['date'] == previous[0]][-1]
    prior_amount = sum(r['amount'] for r in history if r['time'][11:] <= now['time'][11:])/lookback
    return dict(
        return20=now['close']/base_close-1,
        drawdown20=now['close']/max(r['high'] for r in history+today)-1,
        amount_ratio=sum(r['amount'] for r in today)/prior_amount if prior_amount else None,
        anchor_rebound=now['close']/prefix[a]['low']-1,
    )


def distribution(values):
    valid = [v for v in values if v is not None]
    return dict(n=len(valid), missing=len(values)-len(valid),
                median=median(valid) if valid else None,
                minimum=min(valid) if valid else None, maximum=max(valid) if valid else None)


def sensitivity(records):
    """Deletion is an influence diagnostic, never an altered strategy result."""
    if not records:
        raise ValueError('empty diagnostic group')
    q = [r['q'] for r in records]
    best = max(records, key=lambda r: r['q'])
    removed = {}
    for unit, field in (('date', 'date'), ('year', 'year')):
        removed[unit] = []
        for value in sorted({r[field] for r in records}):
            remain = [r for r in records if r[field] != value]
            removed[unit].append(dict(removed=value, removed_n=len(records)-len(remain),
                                     remaining_n=len(remain), q=mean(r['q'] for r in remain) if remain else None))
    return dict(n=len(q), signal_dates=len({r['date'] for r in records}), q=mean(q),
                median_q=median(q), q_positive=sum(x > 0 for x in q)/len(q),
                best=best['event_id'], best_q=best['q'],
                without_best_q=(sum(q)-max(q))/(len(q)-1) if len(q)>1 else None,
                deletion=removed,
                outcome_features={label: {k: distribution([r[k] for r in records if (r['q']>0)==positive])
                                         for k in FEATURES}
                                  for label, positive in (('positive', True), ('nonpositive', False))})


def validate_record(rows, event, scored, actual):
    """Independent daily grouping and direct path arithmetic, not scorer reuse."""
    i = event['signal_index']
    prefix = rows[:i+1]
    grouped = defaultdict(list)
    for row in prefix:
        grouped[row['date']].append(row)
    dates = sorted(grouped)
    previous = dates[-SPEC.lookback_days-1:-1]
    slot = rows[i]['time'][11:]
    amounts = [sum(r['amount'] for r in grouped[d] if r['time'][11:] <= slot) for d in previous]
    denom = mean(amounts)
    expected = dict(return20=rows[i]['close']/grouped[previous[0]][-1]['close']-1,
                    drawdown20=rows[i]['close']/max(max(r['high'] for r in grouped[d]) for d in previous+[dates[-1]])-1,
                    amount_ratio=sum(r['amount'] for r in grouped[dates[-1]])/denom if denom else None,
                    anchor_rebound=rows[i]['close']/rows[event['anchor_index']]['low']-1)
    for k in FEATURES:
        if expected[k] is None or actual[k] is None:
            assert expected[k] is actual[k]
        else:
            assert abs(expected[k]-actual[k]) < 1e-12, k
    assert features(prefix, event) == actual
    changed = prefix + [{**r, **{k: r[k]*1.7 for k in ('open','high','low','close','amount')}} for r in rows[i+1:]]
    assert features(changed, event) == actual
    target = next(j for j, r in enumerate(rows) if r['time'] == scored['target_time'])
    all_days = sorted({r['date'] for r in rows})
    assert rows[target]['date'] == all_days[all_days.index(rows[i]['date'])+1]
    assert rows[target]['time'].endswith('15:00:00')
    path = rows[i+1:target+1]
    entry = path[0]['open']
    assert scored['entry_bar_end'] == path[0]['time'] and scored['entry'] == entry
    expected_q = rows[target]['close']/entry-1
    for k, v in dict(q=expected_q, r=rows[target]['close']/rows[i]['close']-1,
                     mae=min(r['low'] for r in path)/entry-1,
                     mfe=max(r['high'] for r in path)/entry-1).items():
        assert abs(v-scored[k]) < 1e-12, k


def authenticated_input():
    folder = REPO/SPEC.report
    manifest_bytes = (folder/'manifest.json').read_bytes()
    if digest(manifest_bytes) != SPEC.manifest_sha256:
        raise ValueError('variant-A manifest changed')
    manifest = json.loads(manifest_bytes)
    paths = [(folder/name).resolve(strict=True) for name in manifest['artifacts_sha256']]
    if len(paths)>SPEC.max_files or any(not p.is_relative_to(folder.resolve()) for p in paths):
        raise ValueError('invalid artifact paths/count')
    if sum(p.stat().st_size for p in paths)>SPEC.max_bytes:
        raise ValueError('input byte budget exceeded')
    check = audit(folder)
    source = json.loads((folder/'source.json').read_bytes())
    if len(source)>SPEC.max_rows:
        raise ValueError('row budget exceeded')
    return folder, manifest, check, source


def execute(output):
    output = safe_output(output)
    folder, manifest, check, source = authenticated_input()
    days = json.loads((folder/'calendar.json').read_bytes())
    cells, records = {}, []
    for code in manifest['spec']['codes']:
        for frequency in manifest['spec']['frequencies']:
            cell = f'{code}_{frequency}'
            rows = [r for r in source if r['code']==code and r['frequency']==frequency]
            events = [e for e in json.loads((folder/cell/'events.json').read_bytes()) if e['evaluation'] and e['group']=='B3']
            if len(records)+len(events)>SPEC.max_events:
                raise ValueError('event budget exceeded')
            scored = [r for r in json.loads((folder/cell/'next_day_scored.json').read_bytes()) if r['group']=='B3']
            raw = {r['event_id']:r for r in scored if r['mode']=='raw'}
            cooled = {r['event_id'] for r in scored if r['mode']=='cooldown'}
            assert set(raw)=={e['event_id'] for e in events}, 'unscored or extra B3 events'
            assert len(raw)==len(events) and cooled <= set(raw)
            assert len(scored)==len(raw)+len(cooled), 'duplicate scoring rows'
            expected_cooled, last_day = set(), -10**9
            for e in events:
                day = days.index(e['signal_time'][:10])
                if day-last_day >= manifest['spec']['cooldown_days']:
                    expected_cooled.add(e['event_id'])
                    last_day = day
            assert cooled==expected_cooled
            for r in scored:
                assert {k:v for k,v in r.items() if k!='mode'} == {k:v for k,v in raw[r['event_id']].items() if k!='mode'}
            for e in events:
                f = features(rows, e)
                validate_record(rows, e, raw[e['event_id']], f)
                records.append(dict(**raw[e['event_id']], **f, code=code, frequency=frequency, cell=cell,
                                    year=e['signal_time'][:4], cooled=e['event_id'] in cooled,
                                    anchor_time=e['anchor_time'], lag_bars=e['lag_bars']))
            selected = [r for r in records if r['cell']==cell]
            cells[cell] = {mode:sensitivity([r for r in selected if mode=='raw' or r['cooled']]) for mode in ('raw','cooldown')}
            print(f'{cell}: validated {len(events)} events', flush=True)
    clusters = defaultdict(list)
    for r in records:
        if r['cooled']:
            clusters[r['date']].append({k:r[k] for k in ('event_id','cell','signal_time','q',*FEATURES)})
    output.mkdir(parents=True, exist_ok=False)
    save(output/'events.json', records)
    save(output/'diagnostics.json', dict(cells=cells, date_clusters=dict(sorted(clusters.items())),
                                       raw_n=len(records), cooled_n=sum(r['cooled'] for r in records),
                                       unique_cooled_signal_dates=len(clusters)))
    save(output/'validation.json', dict(source_audit=check, independently_recomputed_events=len(records),
                                      prefix_and_future_perturbation_events=len(records),
                                      source_sha256=manifest['artifacts_sha256']['source.json']))
    save(output/'manifest.json', dict(status='complete', created_at_utc=datetime.now(timezone.utc).isoformat(),
                                     spec=asdict(SPEC), plan_sha256_before_run=digest(PLAN.read_bytes()),
                                     code_sha256={p.name:digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')},
                                     artifacts_sha256={p.name:digest(p.read_bytes()) for p in output.iterdir()}))
    return dict(output=str(output), raw=len(records), cooled=sum(r['cooled'] for r in records), dates=len(clusters))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
