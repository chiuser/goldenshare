"""Retrospective reference-extrema audit; preserves earlier evidence files.

Local pivots are explicitly defined in reference_extrema_candidate.py. Results
cannot rule out other swing/pivot algorithms or claim blind software accuracy.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from audit_turn_filters import labels50
from audit_narrated_thresholds import next_dif_line
from reference_extrema_candidate import last_pivot, replay
from replay import read_rows
from replay_color_flip import replay as original
from validate_stage2 import CASES

ROOT = Path(__file__).resolve().parent
GATES = (.75, 1, 1.2)
VARIANTS = [('whole', ('price', 'dif'))] + [
    (mode, fields) for mode in ('last_interior', 'last_boundary')
    for fields in (('price',), ('dif',), ('price', 'dif'))]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(rows, mode, fields, gate, diagnostics=False):
    return replay(rows, gate, historical_extrema=mode, reference_fields=fields,
                  diagnostics=diagnostics, reference_policy='strongest_eligible')


def compact(row):
    return {k: row[k] for k in ('time', 'event', 'state', 'event_route',
        'event_ref_start', 'event_ref_dif', 'event_ref_price', 'dif', 'close')}


def logical_checks():
    rows = [dict(time=f't{i:02}', close=c, dif=d, hist=h) for i, (c, d, h)
            in enumerate([(100, 10, 1), (120, 20, 1), (110, 18, 1),
                (115, 19, 1), (105, 17, 1), (90, 12, -1),
                (121, 15, 1), (122, 16, 1), (123, 19.5, 1)])]
    whole = run(rows, 'whole', ('dif',), 1)
    local = run(rows, 'last_interior', ('dif',), 1)
    assert whole[-1]['event'] == 'NONE' and local[-1]['event'] == 'CANCEL'
    assert whole[7]['event_ref_dif'] == 20 and local[7]['event_ref_dif'] == 19
    plateau = [dict(time=str(i), dif=d) for i, d in enumerate([10, 12, 12, 11])]
    assert last_pivot(plateau, 'dif', 1)['pivot_time'] == '2'
    assert last_pivot(plateau[:3], 'dif', 1) is None
    monotonic = [dict(time=str(i), dif=d) for i, d in enumerate([10, 12, 13])]
    boundary = dict(time='3', dif=11)
    assert last_pivot(monotonic, 'dif', 1) is None
    assert last_pivot(monotonic, 'dif', 1, boundary)['value'] == 13
    assert last_pivot(monotonic, 'dif', 1, boundary)['confirmed_at'] == '3'
    mirrored = [dict(time=r['time'], close=250-r['close'], dif=-r['dif'], hist=-r['hist'])
                for r in rows]
    prefix_checks = 0
    for mode, fields in VARIANTS:
        top, bottom = run(rows, mode, fields, 1, True), run(mirrored, mode, fields, 1, True)
        assert [(r['event'], r['state']) for r in top] == [(r['event'], r['state']) for r in bottom]
        for source, output in ((rows, top), (mirrored, bottom)):
            for i, row in enumerate(output):
                assert run(source[:i+1], mode, fields, 1, True)[-1] == row
                prefix_checks += 1
    return dict(prefix_checks=prefix_checks, mirrored=True, plateau=True,
                boundary_confirmation=True, different_cancel_paths=True,
                note='Logical illustration, not an EMA-consistent market observation')


def main():
    names = {'reference_extrema_candidate.py', Path(__file__).name, 'reference_extrema_audit.json'}
    protected = {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob('*')
                 if p.is_file() and p.suffix in {'.py', '.json', '.csv', '.png'}
                 and p.name not in names and '__pycache__' not in p.parts}
    assert sha(ROOT/'replay_color_flip.py') == 'f472817f85fa8b152501ad659a4afcefe8f903f5b19f8db6bb62403c6ce301ba'
    labels = labels50()
    data = {case: read_rows(filename) for case, filename in CASES.items()}
    summaries, checks, outputs = [], [], {}
    for mode, fields in VARIANTS:
        for gate in GATES:
            key = (mode, fields, gate)
            outputs[key] = {case: {r['time']: r for r in run(rows, mode, fields, gate, True)}
                            for case, rows in data.items()}
            failures = []
            for label in labels:
                row = outputs[key][label['case']][label['time']]
                prefix = [r for r in data[label['case']] if r['time'] <= label['time']]
                assert run(prefix, mode, fields, gate, True)[-1] == row
                check = dict(**label, mode=mode, fields=fields, gate=gate,
                             actual=row['event'], matched=row['event'] == label['expected'],
                             prefix_matched=True, result=compact(row),
                             diagnostics=row['historical_extrema'])
                checks.append(check)
                if not check['matched']:
                    failures.append(check)
            summaries.append(dict(mode=mode, fields=fields, gate=gate, points=50,
                direct_failures=sum(r['confidence']=='direct' for r in failures),
                mapped_failures=sum(r['confidence']=='mapped' for r in failures), failures=failures))
    scope, parity_runs, parity_rows = [], 0, 0
    for path in sorted((ROOT/'inputs').glob('*.csv')):
        rows = read_rows(path.name)
        for gate in GATES:
            baseline = run(rows, 'whole', ('price', 'dif'), gate)
            assert baseline == original(rows, gate, reference_policy='strongest_eligible')
            parity_runs += 1
            parity_rows += len(rows)
            for mode, fields in VARIANTS[1:]:
                alternative = run(rows, mode, fields, gate)
                event_changes, reference_changes = [], []
                for a, b in zip(baseline, alternative):
                    pair = dict(time=a['time'], baseline=compact(a), alternative=compact(b))
                    if (a['event'], a['state'], a['event_route']) != (b['event'], b['state'], b['event_route']):
                        event_changes.append(pair)
                    if (a['event_ref_start'], a['event_ref_dif'], a['event_ref_price']) != (b['event_ref_start'], b['event_ref_dif'], b['event_ref_price']):
                        reference_changes.append(pair)
                scope.append(dict(input=path.name, gate=gate, mode=mode, fields=fields,
                    rows=len(rows), event_changes=event_changes, reference_changes=reference_changes,
                    note='Unlabelled changes are screening candidates, not software failures'))
    # Inspect already observed discriminatory/reference cases without adding labels.
    focal = []
    for case, times in {
        'daily_2025': ['2025-11-06', '2025-11-07', '2025-11-10', '2025-11-11'],
        'bottom_daily': ['2026-09-24'],
        'aug_120': ['2025-07-21 15:00:00', '2025-07-23 11:30:00',
                    '2025-10-16 15:00:00', '2025-08-18 15:00:00'],
    }.items():
        for time in times:
            focal.append(dict(case=case, time=time, candidates=[
                dict(mode=mode, fields=fields, result=outputs[mode, fields, 1][case][time])
                for mode, fields in VARIANTS]))
    # Freeze numerical interval candidates before requesting another transcript.
    minute_rows = data['aug_120']
    index = next(i for i, row in enumerate(minute_rows) if row['time'] == '2025-07-22 15:00:00')
    slope, intercept = next_dif_line(minute_rows[index-1], minute_rows[index])
    actual_next = minute_rows[index+1]
    residual = actual_next['dif'] - (slope*actual_next['close'] + intercept)
    assert abs(residual) < 1e-8
    range_probe = dict(period='2025-07-22 close to 2025-07-23 morning', frequency='120',
        whole_reference=27.208300610376682, last_local_reference=26.62301931837783,
        previous_dif=minute_rows[index]['dif'], next_dif_slope=slope,
        next_dif_intercept=intercept, next_actual_residual=residual,
        whole_next_close_equality_boundary=(27.208300610376682-intercept)/slope,
        local_next_close_equality_boundary=(26.62301931837783-intercept)/slope,
        note='Both references predict the observed July 23 morning cancellation; need an explicit reference or next-bar cancellation-price statement, not the same endpoint again.')
    logical = logical_checks()
    assert all(sha(ROOT/name) == digest for name, digest in protected.items())
    report = dict(as_of=datetime.now(timezone.utc).isoformat(),
        scope='Only historical reference extrema changed; retrospective comparison, no new software labels.',
        fixed_rules=dict(reference_policy='strongest_eligible', max_refs=2, min_bars=2,
                         current_extrema='whole', turn='single_bar_pct', cancellation='strict raw DIF'),
        variants=[dict(mode=m, fields=f) for m, f in VARIANTS], gates=GATES,
        labels=dict(total=50, direct=19, mapped=31, newly_added=0),
        parity=dict(runs=parity_runs, rows=parity_rows, exact=True),
        causal_prefix_checks=len(checks), summaries=summaries, checks=checks,
        scope_comparisons=scope, focal=focal, frozen_range_probe=range_probe,
        logical_checks=logical, protected_files=protected, protected_files_unchanged=True,
        candidate_sha256=sha(ROOT/'reference_extrema_candidate.py'), audit_sha256=sha(Path(__file__)))
    (ROOT/'reference_extrema_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(parity=report['parity'], prefix_checks=len(checks),
        summaries=[{k:r[k] for k in ('mode','fields','gate','direct_failures','mapped_failures')} for r in summaries],
        dif_only_scope=[dict(input=r['input'], mode=r['mode'], event_changes=len(r['event_changes']),
                            reference_changes=len(r['reference_changes'])) for r in scope if r['fields']==('dif',) and r['gate']==1],
        logical=logical, protected_files=len(protected)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
