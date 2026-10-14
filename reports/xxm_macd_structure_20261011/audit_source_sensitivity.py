"""Research-only source sensitivity, with frozen rule candidates.

Terminal substitutions are mixed-source local diagnostics, not reconstructed
software histories. Bounded stress paths need not obey an EMA recurrence and
are not observed software data. Finite successes are not robustness proofs.
"""
import hashlib
import itertools
import json
import math
from pathlib import Path

from active_reference_candidate import replay
from audit_turn_filters import labels50
from audit_software_numeric_history import read, simulate
from replay import read_rows
from validate_stage2 import CASES

ROOT = Path(__file__).resolve().parent
MODES = ('locked', 'both_before', 'dull_before', 'both_after')
GATES = (.75, 1, 1.2)
OUTPUT = 'source_sensitivity_audit.json'
KEYS = ('event', 'state', 'event_route', 'ref_start', 'event_ref_start')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(rows, mode, gate, diagnostics=False):
    return replay(rows, gate, reference_policy='strongest_eligible',
                  active_policy=mode, diagnostics=diagnostics)


def compact(row):
    return {k: row[k] for k in KEYS}


def freq_for(case):
    return 60 if case == 'mins60' else 90 if case == 'mins90' else 120


def observations():
    saved = json.loads((ROOT / 'software_numeric_history_audit.json').read_text())
    result = list(saved['observations'])
    newer = json.loads((ROOT / 'holdout_20260105_pair.json').read_text())
    for row, source in zip(newer['comparisons'], newer['sources']):
        result.append(dict(freq=row['freq'], time='2026-01-05 15:00:00',
                           input=row['input'], image=source['saved_path'],
                           image_sha256=source['sha256'], software=row['software'],
                           dg=row['dg']))
    assert len(result) == 21
    for row in result:
        assert sha(Path(row['image'])) == row['image_sha256']
    return result


def envelopes(obs):
    result = {}
    for freq in (60, 90, 120):
        group = [r for r in obs if r['freq'] == freq]
        maxima = {k: max(abs(r['software'][k] - r['dg'][k])
                         for r in group if r['software'].get(k) is not None)
                  for k in ('close', 'dif', 'dea', 'hist')}
        # Extra display allowance; ceil to a visible audit scale. These are
        # chosen stress envelopes, not inferred all-history source bounds.
        limits = {k: math.ceil((v + (.001 if k != 'close' else .0005)) * 1000) / 1000
                  for k, v in maxima.items()}
        result[freq] = dict(observation_count=len(group), observed_max_abs=maxima,
                            stress_limits=limits,
                            status='RETROSPECTIVE_STRESS_ENVELOPE_NOT_SOFTWARE_BOUND')
    return result


def bounded_change(row, limits, dc, dd, da):
    """DIF/DEA shifts imply histogram shift; project onto its separate bound."""
    dc *= limits['close']; dd *= limits['dif']; da *= limits['dea']
    dh = 2 * (dd - da)
    if abs(dh) > limits['hist']:
        scale = limits['hist'] / abs(dh)
        dd *= scale; da *= scale; dh = 2 * (dd - da)
    assert abs(dc) <= limits['close'] + 1e-10
    assert abs(dd) <= limits['dif'] + 1e-10
    assert abs(da) <= limits['dea'] + 1e-10
    assert abs(dh) <= limits['hist'] + 1e-10
    return dict(row, close=row['close'] + dc, dif=row['dif'] + dd,
                hist=row['hist'] + dh)


def scenarios(rows, limits):
    result = []
    for dc, dd, da in itertools.product((-1, 1), repeat=3):
        result.append((f'constant_c{dc}_d{dd}_a{da}',
                       [bounded_change(r, limits, dc, dd, da) for r in rows]))
    for period in (8, 32, 128):
        for phase in range(4):
            output = []
            for i, r in enumerate(rows):
                angle = 2 * math.pi * i / period + phase * math.pi / 2
                output.append(bounded_change(r, limits, math.sin(angle),
                                              math.sin(angle), math.cos(angle)))
            result.append((f'smooth_period{period}_phase{phase}', output))
    for orientation in (-1, 1):
        result.append((f'alternating_{orientation}',
                       [bounded_change(r, limits, orientation * (-1) ** i,
                                       orientation * (-1) ** i,
                                       -orientation * (-1) ** i)
                        for i, r in enumerate(rows)]))
    assert len(result) == 22
    return result


def single_sign_flip(rows, i, limits):
    r = rows[i]
    sign = 1 if r['hist'] > 0 else -1
    # Cross zero by a tiny amount while keeping D/A/H within the envelope.
    dh = -sign * (abs(r['hist']) + 1e-9)
    total = limits['dif'] + limits['dea']
    dd = dh / 2 * limits['dif'] / total
    da = -dh / 2 * limits['dea'] / total
    assert abs(dh) <= limits['hist'] + 1e-10
    assert abs(dd) <= limits['dif'] + 1e-10
    assert abs(da) <= limits['dea'] + 1e-10
    alt = [dict(x) for x in rows]
    alt[i].update(dif=r['dif'] + dd, hist=r['hist'] + dh)
    assert (alt[i]['hist'] > 0) != (r['hist'] > 0)
    return alt, dict(time=r['time'], original_hist=r['hist'], alternate_hist=alt[i]['hist'],
                     dif_shift=dd, dea_shift=da, hist_shift=dh)


def main():
    excluded = {Path(__file__).name, OUTPUT}
    protected = {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob('*')
                 if p.is_file() and p.name not in excluded and '__pycache__' not in p.parts}
    assert sha(ROOT / 'replay_color_flip.py') == 'f472817f85fa8b152501ad659a4afcefe8f903f5b19f8db6bb62403c6ce301ba'
    obs = observations(); limits = envelopes(obs)
    jan = json.loads((ROOT / 'holdout_20260105_pair.json').read_text())
    labels = labels50() + [dict(case='mins90', source='holdout_20260105_pair.json', **r)
                           for r in jan['labels']]
    assert len(labels) == 52 and sum(r['confidence'] == 'direct' for r in labels) == 20
    assert len({(r['case'], r['time']) for r in labels}) == 52
    minute_labels = [r for r in labels if 'daily' not in r['case']]
    # All existing labels remain calibration/conditional source observations.
    data = {case: read_rows(name) for case, name in CASES.items()}
    baseline = {}
    baseline_checks = 0
    baseline_prefix_checks = 0
    for case, rows in data.items():
        for mode, gate in itertools.product(MODES, GATES):
            baseline[case, mode, gate] = {r['time']: r for r in run(rows, mode, gate, True)}
    for label in labels:
        for mode, gate in itertools.product(MODES, GATES):
            assert baseline[label['case'], mode, gate][label['time']]['event'] == label['expected']
            prefix = [r for r in data[label['case']] if r['time'] <= label['time']]
            assert run(prefix, mode, gate, True)[-1] == baseline[label['case'], mode, gate][label['time']]
            baseline_checks += 1
            baseline_prefix_checks += 1

    continuous_checks = []; continuous_changes = []; continuous_margins = []
    continuous_prefix_checks = 0
    for case, filename in CASES.items():
        group = [r for r in minute_labels if r['case'] == case]
        if not group: continue
        raw = read(filename)
        for precision, digits in (('standard', None), ('close_round', 2),
                                 ('float32_state', None), ('float32_all', None)):
            values = simulate(raw, precision, digits)
            rows = [dict(time=r['trade_time'],
                         close=round(r['close'], 2) if precision == 'close_round' else r['close'],
                         dif=v['dif'], hist=v['hist']) for r, v in zip(raw, values)]
            for mode, gate in itertools.product(MODES, GATES):
                out = {r['time']: r for r in run(rows, mode, gate, True)}
                for label in group:
                    b = out[label['time']]; a = baseline[case, mode, gate][label['time']]
                    c = dict(**label, precision=precision, mode=mode, gate=gate,
                             baseline=compact(a), alternate=compact(b),
                             changed=compact(a) != compact(b), matched=b['event'] == label['expected'])
                    continuous_checks.append(c)
                    if c['changed']: continuous_changes.append(c)
                    prefix = [r for r in rows if r['time'] <= label['time']]
                    assert run(prefix, mode, gate, True)[-1] == b
                    continuous_prefix_checks += 1
            if case == 'jul_120':
                i = next(i for i, r in enumerate(rows) if r['time'] == '2025-07-09 15:00:00')
                previous, current = rows[i - 1]['dif'], rows[i]['dif']
                continuous_margins.append(dict(precision=precision, time=rows[i]['time'],
                                                previous_dif=previous, current_dif=current,
                                                decline_pct=100 * (previous - current) / abs(previous)))

    endpoint_checks = []; endpoint_changes = []
    prefix_checks = 0
    for ob in obs:
        rows = [r for r in read_rows(ob['input']) if r['time'] <= ob['time']]
        assert rows[-1]['time'] == ob['time']
        alt = [dict(r) for r in rows]
        alt[-1].update({k: v for k, v in ob['software'].items()
                        if k in ('close', 'dif', 'hist') and v is not None})
        for mode, gate in itertools.product(MODES, GATES):
            a = run(rows, mode, gate)[-1]; b = run(alt, mode, gate)[-1]
            c = dict(freq=ob['freq'], time=ob['time'], mode=mode, gate=gate,
                     before=compact(a), after=compact(b), changed=compact(a) != compact(b),
                     missing_hist_retained_from_dg=ob['software']['hist'] is None,
                     scope='ONLY_CURRENT_TERMINAL_REPLACED_MIXED_SOURCE_LOCAL_DIAGNOSTIC')
            endpoint_checks.append(c)
            if c['changed']: endpoint_changes.append(c)

    critical_rows = data['jul_120']
    ci = next(i for i, r in enumerate(critical_rows) if r['time'] == '2025-07-09 15:00:00')
    cp, cc = critical_rows[ci - 1]['dif'], critical_rows[ci]['dif']
    ce = limits[120]['stress_limits']['dif']
    critical_point = dict(case='jul_120', time=critical_rows[ci]['time'],
                          previous_dif=cp, current_dif=cc,
                          decline_pct=100 * (cp - cc) / abs(cp),
                          gate_pct=1.2,
                          conditional_independent_dif_interval_pct=[
                              100 * (1 - (cc + ce) / (cp - ce)),
                              100 * (1 - (cc - ce) / (cp + ce))],
                          assumption='Only the two DIF values vary independently; same eligible state/reference and positive preceding DIF')
    critical_point['stress_examples'] = []
    for name, alt in scenarios(critical_rows, limits[120]['stress_limits']):
        if name in ('smooth_period8_phase2', 'alternating_-1'):
            p, c = alt[ci - 1], alt[ci]
            critical_point['stress_examples'].append(dict(scenario=name, previous=p, current=c,
                                                          decline_pct=100 * (p['dif'] - c['dif']) / abs(p['dif'])))

    stress_checks = []; changes = []; sign_witnesses = []; region_checks = []
    unobserved_checks = []
    weak_summary = []
    stress_series_count = 0
    path_summaries = []
    for case, source in data.items():
        group = [r for r in minute_labels if r['case'] == case]
        if not group: continue
        last = max(r['time'] for r in group)
        rows = [r for r in source if r['time'] <= last]
        freq = freq_for(case); envelope = limits[freq]['stress_limits']
        weak = [i for i, r in enumerate(rows) if 0 < abs(r['hist']) < envelope['hist']]
        weak_summary.append(dict(case=case, freq=freq, through=last,
                                 eligible_sign_flip_bars=[dict(time=rows[i]['time'], hist=rows[i]['hist']) for i in weak],
                                 minimum_abs_hist=min(abs(r['hist']) for r in rows),
                                 all_prefix_signs_invariant_if_bound_holds=all(abs(r['hist']) > envelope['hist'] for r in rows),
                                 guarantee='Only sign invariance if this hypothetical histogram bound held for every historical bar'))
        variants = [(name, alt, None) for name, alt in scenarios(rows, envelope)]
        for i in weak:
            alt, witness = single_sign_flip(rows, i, envelope)
            variants.append((f'single_sign_flip_{rows[i]["time"]}', alt, witness))
        for name, alt, sign_witness in variants:
            stress_series_count += 1
            # Every altered path is generated from only row and ordinal index;
            # no future prices or future wave extrema are used by the replay.
            for mode, gate in itertools.product(MODES, GATES):
                output = run(alt, mode, gate, True)
                by_time = {r['time']: r for r in output}
                index = {r['time']: i for i, r in enumerate(alt)}
                path_keys = KEYS + ('wave_sign', 'wave_count')
                path_changed = [dict(time=b['time'],
                                     baseline={k: baseline[case, mode, gate][b['time']][k] for k in path_keys},
                                     alternate={k: b[k] for k in path_keys}) for b in output
                                if any(b[k] != baseline[case, mode, gate][b['time']][k] for k in path_keys)]
                path_summaries.append(dict(case=case, scenario=name, mode=mode, gate=gate,
                                           changed_bars=len(path_changed), first_changes=path_changed[:3],
                                           software_observation='UNLABELLED_BAR_CHANGES_ARE_NOT_SOFTWARE_FAILURES'))
                for label in group:
                    a = baseline[case, mode, gate][label['time']]; b = by_time[label['time']]
                    changed = compact(a) != compact(b)
                    c = dict(**label, mode=mode, gate=gate, scenario=name,
                             baseline=compact(a), alternate=compact(b), changed=changed,
                             event_changed=a['event'] != b['event'], sign_witness=sign_witness)
                    stress_checks.append(c)
                    if changed:
                        changes.append(c)
                        assert run(alt[:index[label['time']] + 1], mode, gate, True)[-1] == b
                        prefix_checks += 1
                        if sign_witness is not None: sign_witnesses.append(c)
                if case == 'mins60':
                    t = '2026-01-05 15:00:00'
                    region_checks.append(dict(mode=mode, gate=gate, scenario=name,
                                              time=t, expected_regional_state='DULL',
                                              alternate=compact(by_time[t]),
                                              state_changed=by_time[t]['state'] != 'DULL',
                                              exact_event_label=False))
                if case == 'mins90':
                    for t in ('2025-12-16 11:00:00', '2025-12-16 14:00:00', '2025-12-16 15:00:00'):
                        a = baseline[case, mode, gate][t]; b = by_time[t]
                        unobserved_checks.append(dict(time=t, mode=mode, gate=gate,
                                                       scenario=name, baseline=compact(a),
                                                       alternate=compact(b), changed=compact(a) != compact(b),
                                                       software_observation='NOT_OBSERVED'))
            if sign_witness is not None:
                i = next(i for i, r in enumerate(alt) if r['time'] == sign_witness['time'])
                assert run(alt[:i + 1], 'locked', 1, True)[-1] == run(alt, 'locked', 1, True)[i]
                prefix_checks += 1

    changed_labels = []
    for label in minute_labels:
        related = [c for c in changes if c['case'] == label['case'] and c['time'] == label['time']]
        if related:
            changed_labels.append(dict(**label, changed_comparisons=len(related),
                                       event_changed_comparisons=sum(c['event_changed'] for c in related),
                                       witness=related[0]))
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    result = dict(as_of='2026-10-12 Asia/Shanghai',
                  method='Frozen candidate replay; local endpoint substitutions plus finite bounded source-stress paths',
                  labels=dict(total=52, direct=20, mapped=32, minute_stress_labels=len(minute_labels), newly_added=0),
                  source_counts=dict(screenshots=37, numeric_endpoints=21, new_sources=0),
                  source_hashes={r['image']: r['image_sha256'] for r in obs},
                  input_hashes={name: sha(ROOT / 'inputs' / name) for name in set(CASES.values())},
                  envelopes=limits, modes=MODES, gates=GATES,
                  baseline_checks=baseline_checks,
                  baseline_prefix_checks=baseline_prefix_checks,
                  continuous_precision_checks=continuous_checks,
                  continuous_precision_changes=continuous_changes,
                  continuous_jul9_margins=continuous_margins,
                  critical_turn_point=critical_point,
                  continuous_prefix_checks=continuous_prefix_checks,
                  endpoint_checks=endpoint_checks, endpoint_changes=endpoint_changes,
                  finite_stress_series=stress_series_count,
                  stress_comparisons=len(stress_checks), stress_changed_comparisons=len(changes),
                  stress_event_changed_comparisons=sum(c['event_changed'] for c in changes),
                  changed_labels=changed_labels, changes=changes,
                  single_sign_flip_witnesses=sign_witnesses, weak_boundary_summary=weak_summary,
                  path_summaries=path_summaries,
                  regional_checks=region_checks,
                  unobserved_dec16_checks=unobserved_checks,
                  prefix_checks=prefix_checks,
                  total_prefix_checks=prefix_checks + continuous_prefix_checks + baseline_prefix_checks,
                  protected_files=protected, protected_files_unchanged=True,
                  candidate_sha256=sha(ROOT / 'active_reference_candidate.py'), script_sha256=sha(Path(__file__)),
                  limits=[
                      'Endpoint displayed values are local replacements only; unknown software history remains DG.',
                      'Apr20 60-minute histogram is unreadable and remains DG; this is not a three-field substitution.',
                      'Envelopes use only observed terminal differences plus a display allowance; they are not established all-history bounds.',
                      'Stresses satisfy bounded price/DIF/DEA/histogram shifts and the histogram delta identity, but need not satisfy EMA recursion.',
                      'Continuous precision controls recur from DG-derived initial states; they do not reconstruct software history or identify its mechanism.',
                      'Finite no-change results cannot certify all perturbations or original software accuracy.',
                      'Sign witnesses establish sensitivity of this frozen model under the stated hypothetical envelope, not software mislabeling.',
                      'No new software labels, transcripts, sources, network/DB/Lake operations or formal indicator changes.'])
    (ROOT / OUTPUT).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(baseline_checks=baseline_checks, endpoint_checks=len(endpoint_checks),
                          endpoint_changes=len(endpoint_changes), finite_stress_series=stress_series_count,
                          continuous_checks=len(continuous_checks), continuous_changes=len(continuous_changes),
                          stress_comparisons=len(stress_checks), changed_comparisons=len(changes),
                          event_changed_comparisons=result['stress_event_changed_comparisons'],
                          changed_labels=[{k: r[k] for k in ('case', 'time', 'expected', 'confidence', 'changed_comparisons', 'event_changed_comparisons')} for r in changed_labels],
                          single_sign_witnesses=len(sign_witnesses), prefix_checks=result['total_prefix_checks'],
                          protected_files=len(protected)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
