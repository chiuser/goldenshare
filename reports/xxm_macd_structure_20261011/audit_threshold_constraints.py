"""Optimize research validation: parameter cells, anchor windows, local witnesses.

No candidate changes. Bounds are conditional on DG values and this candidate,
not identified software parameters. All tests are retrospective calibration.
"""
import hashlib
import itertools
import json
import math
from pathlib import Path

from active_reference_candidate import replay
from audit_turn_filters import labels50
from replay import read_rows
from validate_stage2 import CASES

ROOT = Path(__file__).resolve().parent
OUTPUT = 'threshold_constraint_audit.json'
MODES = ('locked', 'both_before', 'dull_before', 'both_after')
DOMAIN = (0., 5.)
PAIR = {('jul_120', '2025-07-09 15:00:00'), ('jul_120', '2025-07-10 11:30:00')}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(rows, gate, mode, diagnostics=False):
    return replay(rows, gate, active_policy=mode, diagnostics=diagnostics,
                  reference_policy='strongest_eligible')


def last_passing_threshold(basis, magnitude):
    """Use the actual float predicate in the candidate, not rounded percentages."""
    basis = abs(basis)
    q = 100 * magnitude / basis
    steps = 0
    while magnitude < basis * q / 100:
        q = math.nextafter(q, -math.inf); steps += 1
    while magnitude >= basis * math.nextafter(q, math.inf) / 100:
        q = math.nextafter(q, math.inf); steps += 1
    assert steps < 20
    assert magnitude >= basis * q / 100
    assert magnitude < basis * math.nextafter(q, math.inf) / 100
    return q


def match_exact(labels, outputs, indices):
    return all(outputs[l['case']][indices[l['case']][l['time']]]['event'] == l['expected']
               for l in labels)


def match_windows(labels, outputs, indices, *, explain=False):
    """Only mapped positive markers shift; NONE observations stay at their anchor.

    Assign each positive label a distinct event, in chronological order within
    its input. Direct positives stay exact. Never reuse one event for two labels.
    This is a deliberately limited timing alternative, not a relabeling.
    """
    fixed = [l for l in labels if l['confidence'] == 'direct' or l['expected'] == 'NONE']
    if not match_exact(fixed, outputs, indices): return False, []
    explanations = []
    for case in outputs:
        positives = sorted([l for l in labels if l['case'] == case and l['expected'] != 'NONE'],
                           key=lambda l: l['time'])
        states = {-1: []}
        for label in positives:
            anchor = indices[case][label['time']]
            choices = [anchor] if label['confidence'] == 'direct' else range(
                max(0, anchor - 1), min(len(outputs[case]), anchor + 2))
            next_states = {}
            for j in choices:
                if outputs[case][j]['event'] != label['expected']: continue
                predecessor = next((p for p in sorted(states) if p < j), None)
                if predecessor is not None:
                    assignment = dict(case=case, anchor=label['time'], confidence=label['confidence'],
                                      expected=label['expected'], assigned=outputs[case][j]['time'],
                                      ordinal_shift=j - anchor)
                    next_states[j] = states[predecessor] + [assignment]
            states = next_states
            if not states: return False, []
        if explain and states: explanations += states[min(states)]
    return True, explanations


def flags(labels, output, indices):
    return dict(
        direct_only=match_exact([l for l in labels if l['confidence'] == 'direct'], output, indices),
        exact_all=match_exact(labels, output, indices),
        mapped_positive_window1=match_windows(labels, output, indices)[0],
        omit_jul9=match_exact([l for l in labels if (l['case'], l['time']) != ('jul_120', '2025-07-09 15:00:00')], output, indices),
        omit_jul10=match_exact([l for l in labels if (l['case'], l['time']) != ('jul_120', '2025-07-10 11:30:00')], output, indices),
        omit_jul9_10_pair=match_exact([l for l in labels if (l['case'], l['time']) not in PAIR], output, indices),
        omit_aug8_negative=match_exact([l for l in labels if (l['case'], l['time']) != ('aug_120', '2025-08-08 15:00:00')], output, indices))


def merged_ranges(cells, criterion):
    result = []
    for cell in cells:
        if not cell['flags'][criterion]: continue
        if result and result[-1]['upper_inclusive'] == cell['lower_exclusive']:
            result[-1]['upper_inclusive'] = cell['upper_inclusive']
        else:
            result.append(dict(lower_exclusive=cell['lower_exclusive'], upper_inclusive=cell['upper_inclusive']))
    return result


def main():
    excluded = {Path(__file__).name, OUTPUT}
    protected = {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob('*')
                 if p.is_file() and p.name not in excluded and '__pycache__' not in p.parts}
    old = json.loads((ROOT / 'source_sensitivity_audit.json').read_text())
    assert old['candidate_sha256'] == sha(ROOT / 'active_reference_candidate.py')
    assert sha(ROOT / 'replay_color_flip.py') == 'f472817f85fa8b152501ad659a4afcefe8f903f5b19f8db6bb62403c6ce301ba'
    newer = json.loads((ROOT / 'holdout_20260105_pair.json').read_text())
    labels = labels50() + [dict(case='mins90', source='holdout_20260105_pair.json', **l) for l in newer['labels']]
    assert len(labels) == 52
    data = {c: [r for r in read_rows(name) if r['time'] <= max(l['time'] for l in labels if l['case'] == c)]
            for c, name in CASES.items()}
    indices = {c: {r['time']: i for i, r in enumerate(rows)} for c, rows in data.items()}
    roots = {DOMAIN[0], DOMAIN[1]}
    root_sources = {}
    for case, rows in data.items():
        for previous, current in zip(rows, rows[1:]):
            if not previous['dif']: continue
            magnitude = abs(current['dif'] - previous['dif'])
            q = 100 * magnitude / abs(previous['dif'])
            if not DOMAIN[0] < q < DOMAIN[1]: continue
            q = last_passing_threshold(previous['dif'], magnitude)
            roots.add(q)
            root_sources.setdefault(q, []).append(dict(case=case, time=current['time'],
                                                       previous_time=previous['time'],
                                                       previous_dif=previous['dif'], current_dif=current['dif']))
    roots = sorted(roots)
    cells_by_mode = {}; full_replays = 0
    endpoint_cell_checks = 0
    for mode in MODES:
        cells = []
        for lo, hi in zip(roots, roots[1:]):
            mid = lo + (hi - lo) / 2
            assert lo < mid <= hi
            outputs = {c: run(rows, mid, mode) for c, rows in data.items()}
            ends = {c: run(rows, hi, mode) for c, rows in data.items()}
            full_replays += 2 * len(data)
            fm, fe = flags(labels, outputs, indices), flags(labels, ends, indices)
            assert fm == fe, (mode, lo, hi)
            # Label output parity, not just aggregate success. The cell proof
            # follows from all same-bar threshold predicates staying fixed;
            # sign, price and cancellation conditions are threshold-independent.
            for label in labels:
                c = label['case']; i = indices[c][label['time']]
                keys = ('event', 'state', 'event_route', 'ref_start', 'event_ref_start')
                assert all(outputs[c][i][k] == ends[c][i][k] for k in keys)
            endpoint_cell_checks += 1
            assert not fm['exact_all'] or fm['mapped_positive_window1']
            cells.append(dict(lower_exclusive=lo, upper_inclusive=hi,
                              representative=mid, flags=fm))
        cells_by_mode[mode] = cells
        print(json.dumps(dict(progress=mode, cells=len(cells)), ensure_ascii=False), flush=True)

    criteria = tuple(cells_by_mode[MODES[0]][0]['flags'])
    ranges = {mode: {criterion: merged_ranges(cells, criterion) for criterion in criteria}
              for mode, cells in cells_by_mode.items()}
    boundaries = []; prefix_checks = 0
    for mode in MODES:
        for criterion in criteria:
            for interval in ranges[mode][criterion]:
                lo, hi = interval['lower_exclusive'], interval['upper_inclusive']
                probes = [('lower', lo), ('after_lower', math.nextafter(lo, math.inf)),
                          ('upper', hi), ('after_upper', math.nextafter(hi, math.inf))]
                outcomes = []
                for position, gate in probes:
                    outputs = {c: run(rows, gate, mode, True) for c, rows in data.items()}
                    full_replays += len(data)
                    passed = flags(labels, outputs, indices)[criterion]
                    exact_failures = [dict(**l, actual=outputs[l['case']][indices[l['case']][l['time']]]['event'])
                                      for l in labels if outputs[l['case']][indices[l['case']][l['time']]]['event'] != l['expected']]
                    for label in exact_failures:
                        c = label['case']; i = indices[c][label['time']]
                        assert run(data[c][:i + 1], gate, mode, True)[-1] == outputs[c][i]
                        prefix_checks += 1
                    assert passed == (position in ('after_lower', 'upper')), (mode, criterion, position)
                    outcomes.append(dict(position=position, gate=gate, criterion_passed=passed,
                                         all_label_exact_failures=exact_failures))
                boundaries.append(dict(mode=mode, criterion=criterion, interval=interval, probes=outcomes,
                                       lower_root_sources=root_sources.get(lo, []),
                                       upper_root_sources=root_sources.get(hi, [])))

    # Local sensitivity: the least equal two-value displacement required to
    # cross the 1.2% comparator, conditional on the same active state/reference.
    rows = data['jul_120']; i = indices['jul_120']['2025-07-09 15:00:00']
    p, c = rows[i - 1]['dif'], rows[i]['dif']; fraction = .012
    current_only = p * (1 - fraction) - c
    previous_only = p - c / (1 - fraction)
    joint = current_only / (2 - fraction)
    local_checks = []
    for factor in (0., .5, .999, 1.001, 2.):
        e = joint * factor
        alt = [dict(r) for r in rows]
        alt[i - 1]['dif'] -= e; alt[i]['dif'] += e
        # Preserve histogram, equivalently move DEA by the same DIF amount.
        # This is a local mixed-input witness, not a consistent EMA source path.
        assert e < old['envelopes']['120']['stress_limits']['dif']
        assert e < old['envelopes']['120']['stress_limits']['dea']
        for mode, gate in itertools.product(MODES, (.75, 1, 1.2)):
            base = run(rows, gate, mode, True)
            changed = run(alt, gate, mode, True)
            full_replays += 2
            points = []
            for t in sorted(time for case, time in PAIR):
                j = indices['jul_120'][t]
                a, b = base[j], changed[j]
                keys = ('event', 'state', 'event_route', 'ref_start')
                points.append(dict(time=t, before={k: a[k] for k in keys}, after={k: b[k] for k in keys}))
                assert run(alt[:j + 1], gate, mode, True)[-1] == b
                prefix_checks += 1
            changed_event = points[0]['before']['event'] != points[0]['after']['event']
            assert changed_event == (gate == 1.2 and factor > 1)
            local_checks.append(dict(factor=factor, per_value_shift=e, mode=mode, gate=gate,
                                     decline_pct=100 * (alt[i - 1]['dif'] - alt[i]['dif']) / abs(alt[i - 1]['dif']),
                                     first_event_changed=changed_event, points=points))

    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    result = dict(as_of='2026-10-12 Asia/Shanghai',
                  scope='Single-bar relative threshold validation only; no fitted or modified algorithm',
                  domain=dict(lower_exclusive=DOMAIN[0], upper_inclusive=DOMAIN[1], unit='percent'),
                  labels=dict(total=52, direct=20, mapped=32, mapped_positive_window_count=22, newly_added=0),
                  source_counts=dict(screenshots=37, numeric_endpoints=21, new_sources=0),
                  fixed_rules=dict(reference_policy='strongest_eligible', max_refs=2, min_bars=2,
                                   color_flip=True, flip_requires_turn=False, turn='single_bar_relative'),
                  parameter_breakpoints=roots, cells_per_mode=len(roots) - 1,
                  cell_endpoint_checks=endpoint_cell_checks, full_replays=full_replays,
                  ranges=ranges, cell_results=cells_by_mode, boundary_probes=boundaries,
                  local_sensitivity=dict(time=rows[i]['time'], previous_dif=p, current_dif=c,
                                         gate_pct=1.2, current_only_increase_infimum=current_only,
                                         previous_only_decrease_infimum=previous_only,
                                         equal_pair_linf_infimum=joint,
                                         scope='Only these two DIF/DEA values change; histograms, eligible state and reference remain conditional'),
                  local_checks=local_checks, prefix_checks=prefix_checks,
                  candidate_sha256=sha(ROOT / 'active_reference_candidate.py'), script_sha256=sha(Path(__file__)),
                  input_hashes={name: sha(ROOT / 'inputs' / name) for name in set(CASES.values())},
                  protected_files=protected, protected_files_unchanged=True,
                  limits=[
                      'All intervals use DG history and the frozen candidate; none is an identified software parameter interval.',
                      'Cell coverage is restricted to positive thresholds through 5%; state-extreme and period-specific gates are outside this audit.',
                      'Direct-only checks ignore mapped labels but still depend on inferred active-state/reference histories.',
                      'Window matching preserves mapped NONE anchors, order and unique event assignment; it tests one timing alternative only.',
                      'Local shift infima are conditional two-bar algebra, not globally minimal source perturbations or coherent EMA histories.',
                      'No new software values, markers, transcripts, DB/Lake operations or formal algorithm changes.'])
    (ROOT / OUTPUT).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(ranges=ranges, cells_per_mode=len(roots) - 1,
                          endpoint_cell_checks=endpoint_cell_checks, prefix_checks=prefix_checks,
                          local_pair_shift=joint, protected_files=len(protected)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
