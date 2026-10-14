"""Retrospective, one-factor audit of DIF turn filters on 50 saved labels.

No new software observations, no blind test, no writes to earlier evidence.
Single/state-extreme bounds are conditional on this replay's eligible state,
reference choices and mapped-label anchors, not universal software parameters.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from replay import read_rows
from replay_color_flip import replay as original
from screen_reference_retirement import all_labels
from turn_filter_candidate import replay
from validate_stage2 import CASES

ROOT = Path(__file__).resolve().parent
GATES = (.75, 1, 1.2)
VARIANTS = [(mode, gate) for mode in ('single_bar', 'state_extreme', 'display_3dp')
            for gate in GATES] + [('integer_trunc', 0), ('integer_round', 0), ('single_bar', 0)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(rows, mode, gate, diagnostics=False):
    return replay(rows, gate, reference_policy='strongest_eligible',
                  turn_measure=mode, diagnostics=diagnostics)


def labels50():
    labels = all_labels()
    for label in json.loads((ROOT / 'holdout_20250723_120.json').read_text())['labels']:
        labels.append(dict(case='aug_120', time=label['time'], expected=label['expected_event'],
                           confidence=label['confidence'], source='holdout_20250723_120.json'))
    assert len(labels) == len({(r['case'], r['time']) for r in labels}) == 50
    return labels


def conditional_bounds(labels, outputs, modes):
    result = []
    for mode in modes:
        upper, lower = [], []
        for label in labels:
            row = outputs[mode, 1][label['case']][label['time']]
            diag = row['filter_diagnostics']
            if not diag or not diag['evaluated_basis']:
                continue
            is_turn = diag['state_before'] == 'DULL' and diag['delta'] < 0
            is_return = diag['state_before'] == 'STRUCTURE' and diag['delta'] > 0
            if not (is_turn or is_return):
                continue
            evidence = dict(**label, **diag, actual_route=row['event_route'])
            if label['expected'] == ('STRUCTURE' if is_turn else 'DULL'):
                upper.append(evidence)
            elif label['expected'] == 'NONE':
                lower.append(evidence)
        lower.sort(key=lambda r: r['magnitude_pct'], reverse=True)
        upper.sort(key=lambda r: r['magnitude_pct'])
        result.append(dict(mode=mode, lower_exclusive=lower[0]['magnitude_pct'] if lower else None,
                           upper_inclusive=upper[0]['magnitude_pct'] if upper else None,
                           lower_constraints=lower, upper_constraints=upper,
                           caveat='Conditional on active state, references, sign-wave split and mapped anchors; not global parameter identification.'))
    return result


def main():
    names = {Path(__file__).name, 'turn_filter_candidate.py', 'turn_filter_audit.json'}
    protected = {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob('*')
                 if p.is_file() and p.suffix in {'.py', '.json', '.csv', '.png'}
                 and p.name not in names and '__pycache__' not in p.parts}
    assert sha(ROOT / 'replay_color_flip.py') == 'f472817f85fa8b152501ad659a4afcefe8f903f5b19f8db6bb62403c6ce301ba'
    labels = labels50()
    data = {case: read_rows(filename) for case, filename in CASES.items()}
    parity_runs, parity_rows = 0, 0
    for path in sorted((ROOT / 'inputs').glob('*.csv')):
        rows = read_rows(path.name)
        for gate in GATES:
            assert run(rows, 'single_bar', gate) == original(rows, gate, reference_policy='strongest_eligible')
            parity_runs += 1
            parity_rows += len(rows)
    scope_screen = []
    for path in sorted((ROOT / 'inputs').glob('*.csv')):
        rows = read_rows(path.name)
        for gate in GATES:
            base = run(rows, 'single_bar', gate)
            for mode in ('state_extreme', 'display_3dp'):
                alternative = run(rows, mode, gate)
                changed = [dict(time=a['time'], baseline=a, alternative=b)
                           for a, b in zip(base, alternative)
                           if (a['event'], a['state'], a['event_route'], a['event_ref_start'])
                           != (b['event'], b['state'], b['event_route'], b['event_ref_start'])]
                scope_screen.append(dict(input=path.name, mode=mode, gate=gate,
                                         rows=len(rows), differences=changed,
                                         observation='UNLABELLED BARS ARE NOT SOFTWARE OBSERVATIONS'))
    outputs, summaries, checks, differences = {}, [], [], []
    physical_labels = {(120 if '120' in r['case'] else r['case'], r['time']): r for r in labels}
    for mode, gate in VARIANTS:
        outputs[mode, gate] = {case: {r['time']: r for r in run(rows, mode, gate, True)}
                               for case, rows in data.items()}
        failures = []
        for label in labels:
            row = outputs[mode, gate][label['case']][label['time']]
            prefix = [r for r in data[label['case']] if r['time'] <= label['time']]
            assert run(prefix, mode, gate, True)[-1] == row
            check = dict(**label, mode=mode, gate=gate, actual=row['event'],
                         matched=label['expected'] == row['event'], prefix_matched=True,
                         route=row['event_route'], reference=row['event_ref_start'],
                         diagnostics=row['filter_diagnostics'])
            checks.append(check)
            if not check['matched']:
                failures.append(check)
        summaries.append(dict(mode=mode, gate=gate, points=len(labels),
                              direct_failures=sum(r['confidence'] == 'direct' for r in failures),
                              mapped_failures=sum(r['confidence'] == 'mapped' for r in failures),
                              failures=failures))
        base_gate = gate if gate in GATES else 1
        for case in ('aug_120', 'may_120', 'daily_2025', 'bottom_daily', 'mins60', 'mins90'):
            for time, row in outputs[mode, gate][case].items():
                base = outputs['single_bar', base_gate][case][time]
                if (row['event'], row['event_ref_start']) != (base['event'], base['event_ref_start']):
                    label = physical_labels.get((120 if '120' in case else case, time))
                    differences.append(dict(case=case, time=time, mode=mode, gate=gate,
                                            baseline=base, alternative=row,
                                            observation=label if label else 'NOT_OBSERVED'))
    # Illustrative state-machine path, not a claimed EMA-consistent price series.
    synthetic = [dict(time=f't{i:02d}', close=c, dif=d, hist=h)
                 for i, (c, d, h) in enumerate([(100, 10, 1), (101, 12, 1), (95, 9, -1),
                    (102, 9, 1), (103, 9.5, 1), (104, 10, 1),
                    (104, 9.96, 1), (104, 9.92, 1), (104, 9.88, 1),
                    (104, 9.84, 1), (104, 9.88, 1), (104, 9.92, 1), (104, 9.96, 1)])]
    a, b = run(synthetic, 'single_bar', 1), run(synthetic, 'state_extreme', 1)
    assert a[8]['event'] == 'NONE' and b[8]['event'] == 'STRUCTURE'
    assert a[-1]['event'] == 'NONE' and b[-1]['event'] == 'DULL'
    mirrored = [dict(time=r['time'], close=200-r['close'], dif=-r['dif'], hist=-r['hist'])
                for r in synthetic]
    synthetic_checks = []
    for mode in ('single_bar', 'state_extreme', 'display_3dp', 'integer_trunc', 'integer_round'):
        gate = 0 if mode.startswith('integer') else 1
        top, bottom = run(synthetic, mode, gate), run(mirrored, mode, gate)
        assert [(r['event'], r['state']) for r in top] == [(r['event'], r['state']) for r in bottom]
        for rows, full in ((synthetic, top), (mirrored, bottom)):
            for i, row in enumerate(full):
                assert run(rows[:i+1], mode, gate)[-1] == row
        synthetic_checks.append(dict(mode=mode, mirrored_events_match=True,
                                     prefix_checks=2*len(synthetic)))
    bounds = conditional_bounds(labels, outputs, ('single_bar', 'state_extreme'))
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    report = dict(as_of=datetime.now(timezone.utc).isoformat(),
                  scope='Retrospective one-factor comparison; no new labels or blind accuracy claim.',
                  fixed_rules=dict(reference_policy='strongest_eligible', max_refs=2, min_bars=2,
                                   color_flip=True, flip_requires_turn=False, cancel='strict raw DIF break'),
                  variants=[dict(mode=m, gate=g) for m, g in VARIANTS],
                  labels=dict(total=50, direct=19, mapped=31, newly_added=0),
                  baseline_parity=dict(runs=parity_runs, rows=parity_rows, exact_match=True),
                  causal_prefix_checks=len(checks), summaries=summaries, checks=checks,
                  conditional_bounds=bounds, candidate_differences=differences,
                  all_input_screen=scope_screen,
                  synthetic=dict(inputs=synthetic, single=a, cumulative=b, checks=synthetic_checks,
                                 note='State-machine illustration only; symmetry is not software evidence'),
                  protected_files=protected, protected_files_unchanged=True,
                  candidate_sha256=sha(ROOT / 'turn_filter_candidate.py'),
                  audit_script_sha256=sha(Path(__file__)))
    (ROOT / 'turn_filter_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(parity=report['baseline_parity'], checks=len(checks),
                         summaries=[{k: r[k] for k in ('mode', 'gate', 'direct_failures', 'mapped_failures')}
                                    for r in summaries],
                         bounds=[{k: r[k] for k in ('mode', 'lower_exclusive', 'upper_inclusive')}
                                 for r in bounds], differences=len(differences),
                         protected_files=len(protected)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
