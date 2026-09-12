"""G2a: one deterministic stock replay before any batch or efficacy claim."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import time

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_data import slots
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.minute_roundtrip import opening_time
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A, verify_variant_source
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_chan_rank import PLAN, SPEC as RANK_SPEC
from scripts.research.index_market.chan.stock_chan_replay_data import SPEC, Reader, gold_paths, load_pilot


def authenticated_manifest(folder, expected):
    raw = (folder/'manifest.json').read_bytes()
    if digest(raw) != expected:
        raise ValueError('reference manifest changed')
    manifest = json.loads(raw)
    artifacts = manifest['artifacts_sha256']
    paths = [(folder/name).resolve(strict=True) for name in artifacts]
    if (len(paths) > 100 or any(not p.is_relative_to(folder.resolve()) for p in paths)
            or sum(p.stat().st_size for p in paths) > SPEC.max_output_bytes):
        raise ValueError('reference artifact budget/path')
    for name, expected_hash in artifacts.items():
        if digest((folder/name).read_bytes()) != expected_hash:
            raise ValueError(f'reference artifact changed: {name}')
    return manifest


def freeze_samples(folder, manifest, spec=SPEC):
    if manifest['status'] != 'rank_complete' or manifest['spec'] != json.loads(json.dumps(asdict(RANK_SPEC))):
        raise ValueError('G1 incomplete or different scope')
    if digest((Path(__file__).parent/'stock_chan_rank.py').read_bytes()) != manifest['code_sha256']:
        raise ValueError('G1 code changed')
    windows = json.loads((folder/'windows.json').read_text())
    if len(windows) != 3 or len({w['window_id'] for w in windows}) != 3:
        raise ValueError('window scope')
    seats, unmatched = [], []
    for w in windows:
        prefix = folder/w['window_id']
        leaders = json.loads((prefix/'top50.json').read_text())
        pairs = json.loads((prefix/'pairs.json').read_text())
        winner_codes = {r['ts_code'] for r in leaders}
        if len(leaders) != 50 or len(winner_codes) != 50 or len(pairs) != 50:
            raise ValueError('G1 winner/pair count')
        if {p['winner'] for p in pairs} != winner_codes:
            raise ValueError('G1 pair winner mismatch')
        controls = [p['control'] for p in pairs if p['control']]
        if len(set(controls)) != len(controls) or winner_codes.intersection(controls):
            raise ValueError('G1 duplicate/overlapping controls')
        seats.extend(dict(window_id=w['window_id'], code=r['ts_code'], group='winner') for r in leaders)
        seats.extend(dict(window_id=w['window_id'], code=c, group='control') for c in controls)
        unmatched.extend(dict(window_id=w['window_id'], **p) for p in pairs if not p['control'])
    codes = sorted({s['code'] for s in seats})
    if not 0 < len(seats) <= spec.max_seats or len(codes) > spec.max_stocks:
        raise ValueError('sample budget')
    return windows, sorted(seats, key=lambda s: (s['window_id'], s['group'], s['code'])), codes, unmatched


def adapter(code, remaining_seconds=SPEC.pilot_seconds):
    # Only identity/frequency/resource scope changes; the original A entry remains frozen.
    result = replace(VARIANT_A, codes=(code,), frequencies=(SPEC.frequency,), replay_seconds=remaining_seconds)
    allowed = {'codes', 'frequencies', 'replay_seconds'}
    if any(value != asdict(VARIANT_A)[key] for key, value in asdict(result).items() if key not in allowed):
        raise ValueError('A algorithm settings changed')
    if result.chan_config() != VARIANT_A.chan_config():
        raise ValueError('A Chan configuration changed')
    return result


def event_signature(events, start='', end='9999'):
    # Array indexes shift with a shorter initialization history; semantic times do not.
    omit = {'signal_index', 'start_index', 'end_index', 'anchor_index', 'bi_index'}
    return [{k: v for k, v in event.items() if k not in omit}
            for event in events if start <= event['signal_time'] <= end]


def diagnose_window(rows, events, window, days):
    times = [r['time'] for r in rows]
    a, b = times.index(window['entry_bar_end']), times.index(window['exit_bar_end'])
    if a >= b or opening_time(rows[a]) != window['start'] or opening_time(rows[b]) != window['end']:
        raise ValueError('stock/index endpoint mismatch')
    grid = [f'{day} {slot}' for day in days for slot in slots(30)]
    index_pos = grid.index(window['signal_time'])
    found = []
    for event in events:
        t = event['signal_time']
        if not event['group'].startswith('B') or not window['prior_days'][0] <= t < window['end']:
            continue
        single = bisect_right(times, t)
        action = bisect_right(times, max(t, window['signal_time']))
        item = dict(event=event, relative_market_bars=grid.index(t)-index_pos,
                    timing='before' if t < window['signal_time'] else 'same_bar' if t == window['signal_time'] else 'after',
                    stock_next_open_time=opening_time(rows[single]) if single < len(rows) else None,
                    action_time=opening_time(rows[action]) if action < len(rows) else None,
                    actionable=a <= action < b)
        if item['actionable']:
            p0, ps, pe = rows[a]['open'], rows[action]['open'], rows[b]['open']
            elapsed, remaining = ps/p0-1, pe/ps-1
            if not math.isclose((1+elapsed)*(1+remaining), pe/p0, rel_tol=1e-12):
                raise ValueError('return compounding identity')
            highs = [r['high'] for r in rows[action:b]]+[pe]
            lows = [r['low'] for r in rows[action:b]]+[pe]
            item.update(action_price=ps, elapsed_change=elapsed, remaining_change=remaining,
                        mfe=max(highs)/ps-1, mae=min(lows)/ps-1)
        else:
            item['reason'] = 'no_action_before_index_exit'
        found.append(item)
    first = {}
    for item in found:
        first.setdefault(item['event']['group'], item)
    return dict(window=window, entry_price=rows[a]['open'], exit_price=rows[b]['open'],
                interval_change=rows[b]['open']/rows[a]['open']-1,
                interval_mfe=max([r['high'] for r in rows[a:b]]+[rows[b]['open']])/rows[a]['open']-1,
                interval_mae=min([r['low'] for r in rows[a:b]]+[rows[b]['open']])/rows[a]['open']-1,
                observation_buy_count=len(found), first_by_group=first, all_observation_buys=found)


def run_checks(rows, code, window, reader, output):
    # Never feed the exit bar's later high/low/close into the executable observation period.
    main_rows = rows[:-1]
    duration, results = {}, {}

    def one(name, data, keep_changes=False):
        reader.check_time()
        print(f'{code}: {name} start, {len(data)} bars', flush=True)
        started = time.monotonic()
        changes = []
        remaining = reader.spec.pilot_seconds - (started-reader.started)
        events = replay(data, code, SPEC.frequency, adapter(code, remaining),
                        sink=changes.extend if keep_changes else None)
        duration[name] = time.monotonic()-started
        save(output/f'{name}_events.json', events)
        if keep_changes:
            save(output/'changes.json', changes)
        save(output/f'{name}_checkpoint.json', dict(bars=len(data), events=len(events), seconds=duration[name]))
        reader.check_time()
        return events

    events = one('full', main_rows, True)
    cutoff = window['signal_time']
    prefix = one('prefix', [r for r in main_rows if r['time'] <= cutoff])
    results['prefix_equal'] = event_signature(events, end=cutoff) == event_signature(prefix)
    future = deepcopy(main_rows)
    for row in future:
        if row['time'] > cutoff:
            for key in ('open', 'high', 'low', 'close'):
                row[key] *= 1.5
    future_events = one('future_perturbed', future)
    results['future_isolation_equal'] = event_signature(events, end=cutoff) == event_signature(future_events, end=cutoff)
    scaled = [dict(r, **{k: r[k]*2 for k in ('open', 'high', 'low', 'close')}) for r in main_rows]
    results['uniform_scaling_equal'] = event_signature(events) == event_signature(one('scaled', scaled))
    actual_days = sorted({r['date'] for r in main_rows})
    shorter = [r for r in main_rows if r['date'] >= actual_days[SPEC.history_days]]
    shorter_events = one('shorter_history', shorter)
    start = window['prior_days'][0]
    results['shorter_initialization_observation_equal'] = (
        event_signature(events, start=start) == event_signature(shorter_events, start=start))
    return events, dict(**results, all_passed=all(results.values()), seconds_by_replay=duration,
                        future_cutoff=cutoff, shorter_start=shorter[0]['time'])


def execute(output, spec=SPEC):
    if asdict(spec) != asdict(SPEC):
        raise ValueError('unapproved G2a specification')
    output = safe_output(output)
    if shutil.disk_usage(REPO).free < 2*spec.max_output_bytes:
        raise ValueError('report disk reserve')
    g1_folder = REPO/spec.rank_report
    g1 = authenticated_manifest(g1_folder, spec.rank_manifest)
    windows, seats, codes, unmatched = freeze_samples(g1_folder, g1, spec)
    pilot = codes[0]
    pilot_seats = [s for s in seats if s['code'] == pilot]
    # Pilot only: use its first chronological seat, with the choice saved before replay.
    w = next(w for w in windows if w['window_id'] == pilot_seats[0]['window_id'])
    a = authenticated_manifest(REPO/spec.a_report, spec.a_manifest)
    for name, expected in a['code_sha256'].items():
        if digest((Path(__file__).parent/name).read_bytes()) != expected:
            raise ValueError(f'frozen A code changed: {name}')
    source = verify_variant_source(Path(a['source']['path']))
    if source != a['source']:
        raise ValueError('third-party source or expanded A configuration changed')
    inventory = sorted({p for code in codes for p in gold_paths(code, spec.end, spec)})
    if len(inventory) > spec.max_files or sum(p.stat().st_size for p in inventory) > spec.max_bytes:
        raise ValueError('whole sample Gold inventory budget')
    output.mkdir(parents=True, exist_ok=False)
    reader = Reader(spec)
    manifest = dict(status='running', spec=asdict(spec), created_at_utc=datetime.now(timezone.utc).isoformat(),
                    plan_sha256=digest(PLAN.read_bytes()), source=source,
                    code_sha256={name: digest((Path(__file__).parent/name).read_bytes()) for name in
                                 ('stock_chan_replay.py', 'stock_chan_replay_data.py', 'stock_chan_rank.py',
                                  'minute_replay.py', 'minute_variant_a.py', 'minute_data.py', 'minute_roundtrip.py',
                                  'm0_data.py', 'event_ledger.py', 'run_m0.py')})
    sample = dict(seats=seats, unmatched_controls=unmatched, unique_codes=codes,
                  counts=dict(Counter(s['group'] for s in seats)), pilot_code=pilot, pilot_seat=pilot_seats[0],
                  inventory_files=len(inventory), inventory_bytes=sum(p.stat().st_size for p in inventory),
                  inventory_scope='Gold metadata only, not whole-sample quality acceptance')
    save(output/'samples.json', sample)
    save(output/'gold_inventory.json', [dict(path=str(p), bytes=p.stat().st_size) for p in inventory])
    save(output/'window.json', w)
    try:
        rows, days, life, quality, basis = load_pilot(reader, seats, pilot, w)
        # The selected Gold2026, calendar and lifecycle must still match G1's ranking snapshot.
        g1_hashes = json.loads((g1_folder/'source_hashes.json').read_text())
        for path, value in reader.hashes.items():
            if path in g1_hashes and g1_hashes[path] != value:
                raise ValueError(f'G1 source changed: {path}')
        save(output/'input.json', rows)
        save(output/'calendar.json', days)
        save(output/'selected_lifecycle.json', life)
        save(output/'quality.json', quality)
        save(output/'basis.json', basis)
        events, checks = run_checks(rows, pilot, w, reader, output)
        diagnostics = diagnose_window(rows, events, w, days)
        ranking = json.loads((g1_folder/w['window_id']/'ranking.json').read_text())
        ranked = next(r for r in ranking if r['ts_code'] == pilot)
        if not math.isclose(diagnostics['interval_change'], ranked['gross_change'], rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError('pilot endpoint returns no longer match frozen G1')
        checks['g1_return_equal'] = True
        checks['read_audit'] = reader.verify_unchanged()
        full_seconds = checks['seconds_by_replay']['full']
        checks['rough_batch_engine_seconds'] = full_seconds/(len(rows)-1)*spec.max_bars*len(codes)
        checks['estimate_method'] = 'pilot seconds per bar times 10000 bars times 289 stocks; excludes I/O and repeat checks'
        checks['batch_engine_estimate_within_total_budget'] = checks['rough_batch_engine_seconds'] <= spec.total_seconds
        save(output/'checks.json', checks)
        save(output/'diagnostics.json', diagnostics)
        manifest.update(status='pilot_complete' if checks['all_passed'] else 'pilot_stability_failed',
                        pilot=pilot, full_events=len(events), observation_buys=diagnostics['observation_buy_count'],
                        batch_executed=False)
    except Exception as exc:
        manifest.update(status='blocked', error_type=type(exc).__name__, error=str(exc), batch_executed=False)
        raise
    finally:
        save(output/'queries.json', reader.queries)
        save(output/'source_hashes.json', reader.hashes)
        manifest['seconds'] = time.monotonic()-reader.started
        paths = sorted(p for p in output.rglob('*') if p.is_file())
        size = sum(p.stat().st_size for p in paths)
        if size > spec.max_output_bytes:
            manifest.update(status='output_budget_exceeded')
        manifest['output_bytes_before_manifest'] = size
        manifest['artifacts_sha256'] = {str(p.relative_to(output)): digest(p.read_bytes()) for p in paths}
        save(output/'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.output)
    print(json.dumps({k: result.get(k) for k in ('status', 'pilot', 'full_events', 'observation_buys', 'seconds')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
