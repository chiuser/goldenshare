"""Exact-prefix reuse for the frozen first-batch performance experiment."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import resource
import sys
import time

from scripts.research.index_market.chan.m0_data import digest
from scripts.research.index_market.chan.minute_replay import replay
from scripts.research.index_market.chan.minute_variant_a import verify_variant_source
from scripts.research.index_market.chan.stock_chan_batch import fingerprint
from scripts.research.index_market.chan.stock_chan_replay import adapter, diagnose_window, event_signature


@dataclass(frozen=True)
class ParallelSpec:
    report: str = 'reports/stock_chan_g2b_first10_20260912'
    manifest: str = '9672ef5ebb51e5c8c41e2d4e87008822549998823f58b3484398940a4d2198d7'
    worker_counts: tuple[int, ...] = (1, 2, 4)
    stocks: int = 10
    seats: int = 11
    max_bars: int = 10000
    history_days: int = 250
    stock_seconds: int = 180
    total_seconds: int = 600
    max_bytes: int = 128 * 1024**2
    worker_rss_bytes: int = 512 * 1024**2
    total_rss_bytes: int = 2 * 1024**3
    progress_seconds: int = 15


SPEC = ParallelSpec()
MODES = ('full', 'prefix', 'future_perturbed', 'scaled', 'shorter_history')
_cancel = None
_deadline = None


def rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value * 1024)


def initialize(source, cancel, deadline):
    global _cancel, _deadline
    _cancel, _deadline = cancel, deadline
    if verify_variant_source(Path(source['path'])) != source:
        raise ValueError('frozen third-party source/configuration changed')


def check_budget(started, spec=SPEC):
    if _cancel is not None and _cancel.is_set():
        raise InterruptedError('benchmark cancelled')
    if time.monotonic()-started > spec.stock_seconds or (_deadline is not None and time.monotonic() > _deadline):
        raise TimeoutError('benchmark time budget')
    if rss_bytes() > spec.worker_rss_bytes:
        raise MemoryError('worker RSS budget')


def read_verified(path, expected):
    raw = Path(path).read_bytes()
    if digest(raw) != expected:
        raise ValueError(f'frozen input changed: {path}')
    return json.loads(raw)


def shared_histories(seats, spec=SPEC):
    """The exit row is not replay input; every other field must match exactly."""
    histories = [s['rows'][:-1] for s in seats]
    if not histories or any(not 0 < len(h) <= spec.max_bars for h in histories):
        raise ValueError('bar budget')
    longest = max(histories, key=len)
    shorter_starts = []
    for history in histories:
        if history != longest[:len(history)]:
            raise ValueError('same-stock inputs are not identical prefixes')
        days = sorted({r['date'] for r in history})
        if len(days) <= spec.history_days:
            raise ValueError('short initialization unavailable')
        shorter_starts.append(days[spec.history_days])
    if len(set(shorter_starts)) != 1:
        raise ValueError('short initialization start mismatch')
    return longest, shorter_starts[0]


def compute(seats, code, days, one, spec=SPEC):
    """one(name, rows, keep_changes) is injectable for isolated equality tests."""
    longest, short_start = shared_histories(seats, spec)
    full, changes = one('full', longest, True)
    scaled, _ = one('scaled', [dict(r, **{k: r[k]*2 for k in ('open', 'high', 'low', 'close')}) for r in longest], False)
    short, _ = one('shorter_history', [r for r in longest if r['date'] >= short_start], False)
    outputs = []
    for seat in seats:
        rows, window = seat['rows'], seat['window']
        history, cutoff = rows[:-1], window['signal_time']
        end = history[-1]['time']
        modes = {
            'full': [e for e in full if e['signal_time'] <= end],
            'scaled': [e for e in scaled if e['signal_time'] <= end],
            'shorter_history': [e for e in short if e['signal_time'] <= end],
        }
        modes['prefix'], _ = one('prefix', [r for r in history if r['time'] <= cutoff], False)
        future = deepcopy(history)
        for row in future:
            if row['time'] > cutoff:
                for key in ('open', 'high', 'low', 'close'):
                    row[key] *= 1.5
        modes['future_perturbed'], _ = one('future_perturbed', future, False)
        prefix_sig = event_signature(modes['full'], end=cutoff)
        start = window['prior_days'][0]
        checks = dict(
            prefix_equal=prefix_sig == event_signature(modes['prefix']),
            future_isolation_equal=prefix_sig == event_signature(modes['future_perturbed'], end=cutoff),
            uniform_scaling_equal=event_signature(modes['full']) == event_signature(modes['scaled']),
            shorter_initialization_observation_equal=event_signature(modes['full'], start=start) == event_signature(modes['shorter_history'], start=start),
        )
        actual = {f'{name}_events': events for name, events in modes.items()}
        actual['changes'] = [c for c in changes if c['time'] <= end]
        actual['diagnostics'] = diagnose_window(rows, modes['full'], window, days)
        hashes = {name: fingerprint(value) for name, value in actual.items()}
        equality = {name: value == seat['expected'][name] for name, value in hashes.items()}
        if not all(equality.values()) or not all(checks.values()):
            raise ValueError(f"non-equivalent replay {seat['unit_id']}: equality={equality}, checks={checks}")
        outputs.append(dict(unit_id=seat['unit_id'], bars=len(history),
                            events=len(modes['full']), observation_buys=actual['diagnostics']['observation_buy_count'],
                            expected_sha256=seat['expected'], actual_sha256=hashes,
                            exact_equal=equality, stability_checks=checks))
    return outputs


def run_stock(job):
    started = time.monotonic()
    check_budget(started)
    seats = []
    for seat in job['seats']:
        rows = read_verified(seat['input_path'], seat['input_sha256'])
        window = read_verified(seat['window_path'], seat['window_sha256'])
        if any(r['code'] != job['code'] or r['frequency'] != 30 for r in rows):
            raise ValueError('stock identity/frequency mismatch')
        seats.append(dict(seat, rows=rows, window=window))
    calls = []

    def one(name, data, keep_changes):
        check_budget(started)
        changes, count = [], 0
        t0 = time.monotonic()

        def sink(items):
            nonlocal count
            count += 1
            if keep_changes:
                changes.extend(items)
            if count % 256 == 0:
                check_budget(started)

        remaining = min(SPEC.stock_seconds-(t0-started), _deadline-t0)
        events = replay(data, job['code'], 30, adapter(job['code'], remaining), sink=sink)
        check_budget(started)
        calls.append(dict(mode=name, bars=len(data), seconds=time.monotonic()-t0))
        return events, changes

    result = compute(seats, job['code'], job['days'], one)
    check_budget(started)
    return dict(code=job['code'], pid=os.getpid(), status='equivalent',
                seconds=time.monotonic()-started, rss_peak_bytes=rss_bytes(),
                engine_calls=calls, units=result)
