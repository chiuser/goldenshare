"""Diagnose frozen sell exits without changing signals or backtesting a new policy."""
import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time

from scripts.research.index_market.chan import stock_exit_study as old
from scripts.research.index_market.chan import stock_opportunity as base
from scripts.research.index_market.chan.stock_calendar_opportunity import grid
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_research_store import StockResearchStore


@dataclass(frozen=True)
class AuditSpec:
    exits: str = 'exits'
    calendar: str = 'calendar'
    dates: str = 'initial/source.json'
    plan: str = 'docs/product/stock-chan-share-position-backtest-plan-v1.md'
    cases_per_category: int = 2
    input_bytes: int = 20 * 1024**2
    output_bytes: int = 16 * 1024**2
    seconds: int = 180


SPEC = AuditSpec()


def blocks(times, rows, entry, j):
    reasons = []
    if times[j][:10] <= times[entry][:10]:
        reasons.append('T+1')
    if rows[j] is None:
        reasons.append('missing_bar')
    elif rows[j]['vol'] <= 0 or rows[j]['amount'] <= 0:
        reasons.append('zero_turnover')
    return reasons


def executable(times, rows, entry, trigger, end):
    waiting = Counter()
    for j in range(trigger + 1, end + 1):
        reasons = blocks(times, rows, entry, j)
        if not reasons:
            return dict(index=j, bar_end=times[j], open=rows[j]['open'],
                        waiting_slots=j-trigger-1, blocked_slots=dict(waiting))
        waiting.update(reasons)
    return dict(index=None, bar_end=None, open=None, waiting_slots=end-trigger,
                blocked_slots=dict(waiting))


def validate_events(events, structure, code):
    ids = set()
    for e in events:
        i, a = e['signal_index'], e['anchor_index']
        if (e['event_id'] in ids or e['code'] != code or e['frequency'] != 60
                or e['group'] not in ('B1', 'B2', 'B3', 'S1', 'S2', 'S3')
                or e['buy'] is not e['group'].startswith('B') or e['sure'] is not True
                or not 0 <= a <= i < len(structure)
                or structure[i]['time'] != e['signal_time']
                or structure[a]['time'] != e['anchor_time']):
            raise ValueError('event identity or future anchor')
        ids.add(e['event_id'])


def diagnose(case, events, structure, times, rows, max_slots):
    """Independent event-first reconstruction, not a call to old.simulate."""
    entry = case['signal_index'] + 1
    deadline = case['signal_index'] + max_slots
    if deadline >= len(rows):
        raise ValueError('incomplete opportunity')
    if rows[entry] is None or rows[entry]['vol'] <= 0 or rows[entry]['amount'] <= 0:
        raise ValueError('untradable entry')
    indices = {t: i for i, t in enumerate(times)}
    eligible_types = {'S'+g[1:] for g in case['types']}
    observed = case['arms']['sell']
    candidates = []
    for e in events:
        if not e['group'].startswith('S'):
            continue
        k = indices[e['signal_time']]
        if not entry <= k <= deadline:
            continue
        candidates.append(dict(event_id=e['event_id'], group=e['group'], index=k,
            signal_time=e['signal_time'], anchor_time=e['anchor_time'],
            confirm_close=structure[e['signal_index']]['close'],
            matches=e['group'] in eligible_types, before_deadline=k < deadline,
            while_original_holding=k < observed['exit_index'] or
                (k == observed['exit_index'] and observed['exit_phase'] == 'close'),
            execution=executable(times, rows, entry, k, deadline)))
    candidates.sort(key=lambda x: (x['index'], x['group'], x['event_id']))
    in_window = [x for x in candidates if x['before_deadline']]
    matched = [x for x in in_window if x['matches']]
    first = matched[0] if matched else None
    if first:
        execution = executable(times, rows, entry, first['index'], len(rows)-1)
        expected = (dict(exit_index=execution['index'], exit_time=execution['bar_end'],
                         exit_price=execution['open'], exit_phase='open', reason='sell',
                         trigger_time=first['signal_time']) if execution['index'] is not None else None)
    else:
        j = next((j for j in range(deadline, len(rows)) if not blocks(times, rows, entry, j)), None)
        expected = (dict(exit_index=j, exit_time=times[j],
                         exit_price=rows[j]['close'] if j == deadline else rows[j]['open'],
                         exit_phase='close' if j == deadline else 'open', reason='timeout',
                         trigger_time=None) if j is not None else None)
    differences = {}
    if expected is None:
        differences['status'] = dict(expected='unclosed', observed=observed['status'])
    else:
        expected.update(entry_index=entry, entry_price=rows[entry]['open'],
                        deadline=times[deadline], return_value=expected['exit_price']/rows[entry]['open']-1)
        differences = {k: dict(expected=v, observed=observed.get(k)) for k, v in expected.items()
                       if v != observed.get(k)}
    if observed['reason'] == 'sell':
        category = 'matched_sell_exit'
    elif matched:
        category = 'matched_but_unexecuted_or_inconsistent'
    elif in_window:
        category = 'nonmatching_only'
    else:
        category = 'no_sell_in_trigger_window'
    actionable_other = [x for x in in_window if not x['matches']
        and x['execution']['index'] is not None
        and (x['execution']['index'] < observed['exit_index'] or
             (x['execution']['index'] == observed['exit_index'] and observed['exit_phase'] == 'close'))]
    return dict(code=case['code'], signal_time=case['signal_time'], types=case['types'],
                entry_bar=times[entry], entry_price=rows[entry]['open'], deadline=times[deadline],
                category=category, recorded_exit=observed, independent_exit=expected,
                differences=differences, sellers=candidates,
                actionable_other_before_exit=len(actionable_other),
                first_actionable_other=actionable_other[0] if actionable_other else None)


def execute(output):
    output = base.safe_output(output)
    store = StockResearchStore()
    source = store.root_key(SPEC.exits)
    calendar = store.root_key(SPEC.calendar)
    inputs = {}

    def read(path, expected=None):
        if store.size(path) > SPEC.input_bytes:
            raise ValueError('input budget')
        h = store.sha(path)
        if expected is not None and h != expected:
            raise ValueError(f'input hash: {path}')
        inputs[str(path)] = h
        return store.read(path)

    m = read(source/'manifest.json')
    if m['status'] != 'complete':
        raise ValueError('incomplete source')
    setup = read(source/'setup.json', m['setup_sha256'])
    previous = read(source/'aggregate.json', m['aggregate_sha256'])
    expected_spec = asdict(old.SPEC)
    expected_spec['source'] = store.original_path(old.SPEC.source)
    if setup['spec'] != json.loads(json.dumps(expected_spec)):
        raise ValueError('exit spec changed')
    for p, h in setup['code_sha256'].items():
        store.verify_code(p, h)
    origin = read(calendar/'source.json', setup['source_sha256'])
    for p, h in origin['code_sha256'].items():
        store.verify_code(p, h)
    days = read(SPEC.dates, origin['previous_source_sha256'])['days']
    statuses = read(calendar/'status_10.json')
    if (len(statuses) != 10 or {s['code'] for s in statuses} != set(origin['codes'])
            or any(not s['code'].endswith(('.SH', '.SZ')) for s in statuses)):
        raise ValueError('frozen cohort changed')
    lo, hi = setup['periods']['full']
    max_slots = setup['spec']['max_days'] * setup['spec']['bars_day']
    output.mkdir()
    started = time.monotonic()
    save(output/'setup.json', dict(spec=asdict(SPEC), exit_spec=setup['spec'], input_store=store.receipt,
        plan_sha256=base.sha(base.REPO/SPEC.plan),
        code_sha256={str(p):base.sha(p) for p in (Path(__file__), Path(old.__file__), Path(base.__file__))}))
    summaries, examples = [], {}
    for st in sorted(statuses, key=lambda x: x['code']):
        if time.monotonic()-started > SPEC.seconds:
            raise TimeoutError('audit budget')
        code = st['code']
        folder = source/code
        cm = read(folder/'manifest.json')
        data_manifest = read(calendar/code/'manifest.json', cm['source_manifest_sha256'])
        if cm['status'] != 'complete' or data_manifest['status'] != 'complete':
            raise ValueError('incomplete stock')
        paths = [calendar/code/n for n in ('input_30.json', 'input_60.json', 'full_events.json')]
        if sum(store.size(p) for p in paths)+store.size(folder/'cases.json') > SPEC.input_bytes:
            raise ValueError('stock input budget')
        obs, structure, events = [read(p, data_manifest['artifacts_sha256'][p.name]) for p in paths]
        cases = read(folder/'cases.json', cm['artifacts_sha256']['cases.json'])
        validate_events(events, structure, code)
        event_map = {e['event_id']:e for e in events}
        times, rows = grid(obs, days)
        common = [c for c in cases if lo <= c['signal_time'][:10] <= hi and
                  len(c['arms']) == 4 and all(a['status'] == 'closed' and a['exit_time'][:10] <= hi for a in c['arms'].values())]
        diagnostics = []
        for c in common:
            es = [event_map[eid] for eid in c['event_ids']]
            if (c['code'] != code or times[c['signal_index']] != c['signal_time']
                    or any(e['signal_time'] != c['signal_time'] or not e['buy'] for e in es)
                    or c['types'] != sorted({e['group'] for e in es})):
                raise ValueError('buy identity mismatch')
            diagnostics.append(diagnose(c, events, structure, times, rows, max_slots))
        counts = Counter(x['category'] for x in diagnostics)
        timeouts = [x for x in diagnostics if x['recorded_exit']['reason'] == 'timeout']
        unique_sells = {x['event_id'] for d in diagnostics for x in d['sellers'] if x['before_deadline']}
        summary = dict(code=code, name=st['name'], total=len(cases), common=len(common),
            categories=dict(counts), unique_sells_in_windows=len(unique_sells),
            timeout_with_actionable_other=sum(x['actionable_other_before_exit'] > 0 for x in timeouts),
            all_with_actionable_other=sum(x['actionable_other_before_exit'] > 0 for x in diagnostics),
            boundary_cases=sum(any(not s['before_deadline'] for s in x['sellers']) for x in diagnostics),
            cases_with_execution_wait=sum(any(s['before_deadline'] and s['execution']['blocked_slots'] for s in x['sellers']) for x in diagnostics),
            mismatches=sum(bool(x['differences']) for x in diagnostics))
        for d in sorted(diagnostics, key=lambda x:x['signal_time']):
            chosen = examples.setdefault(d['category'], [])
            if len(chosen) < SPEC.cases_per_category:
                chosen.append(dict(code=code, signal_time=d['signal_time']))
        target = output/code
        target.mkdir()
        save(target/'diagnostics.json', diagnostics)
        save(target/'summary.json', summary)
        save(target/'manifest.json', dict(status='complete', artifacts_sha256={p.name:base.sha(p) for p in target.iterdir()}))
        summaries.append(summary)
        print(f'{len(summaries)}/{len(statuses)} {code}: {dict(counts)}', flush=True)
    counts = Counter()
    for s in summaries:
        counts.update(s['categories'])
    n = sum(s['common'] for s in summaries)
    expected_n = next(x['n'] for x in previous if x['period'] == 'full' and x['mode'] == 'sell')
    if n != expected_n:
        raise ValueError('common denominator changed')
    for path, h in inputs.items():
        if store.sha(path) != h:
            raise ValueError('input mutated during audit')
    store.verify_unchanged()
    aggregate = dict(common=n, categories=dict(counts), stocks=summaries, examples=examples,
        **{k:sum(s[k] for s in summaries) for k in ('timeout_with_actionable_other', 'all_with_actionable_other',
            'boundary_cases', 'cases_with_execution_wait', 'mismatches')})
    save(output/'aggregate.json', aggregate)
    save(output/'sources.json', inputs)
    if sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) > SPEC.output_bytes:
        raise ValueError('output budget')
    save(output/'manifest.json', dict(status='complete' if not aggregate['mismatches'] else 'needs_review',
        seconds=time.monotonic()-started, files_checked=len(inputs), all_inputs_unchanged=True,
        artifacts_sha256={str(p.relative_to(output)):base.sha(p) for p in output.rglob('*') if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    execute(parser.parse_args().output)
