"""Read-only diagnostics of truncated reference history and active-state resets.

No replay function is changed; no synthetic historical prefix is introduced.
The mapped historical markers remain separate from the candidate event stream.
"""
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from active_reference_candidate import replay
from audit_november_followup import extend_daily
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze():
    defs_path = ROOT / 'lifecycle_trace_definitions_20261012.json'
    defs = json.loads(defs_path.read_text())
    prior = json.loads((ROOT / 'july3_chart_comparison_20261012.json').read_text())
    inputs = ROOT / 'inputs/90_20250603_20260113.csv'
    candidate = ROOT / 'active_reference_candidate.py'
    assert sha(inputs) == prior['input_sha256']
    assert sha(candidate) == prior['candidate_sha256']
    rows = read_rows(inputs.name)
    times = [r['time'] for r in rows]
    assert len(times) == len(set(times)) == 459
    assert all(math.isfinite(r[k]) for r in rows for k in ('close', 'dif', 'hist'))
    assert all(r['close'] > 0 for r in rows)
    assert set(Counter(t[:10] for t in times).values()) == {3}
    assert {t[-8:] for t in times} == {'11:00:00', '14:00:00', '15:00:00'}
    root_rows = [r for r in rows if r['time'] <= '2025-06-27 15:00:00']
    variants = []
    prefix_checks = 0
    options = defs['root_variants']
    for policy in options['reference_policy']:
        for active in options['active_policy']:
            for gate in options['gate_pct']:
                for refs in options['max_refs']:
                    kwargs = dict(reference_policy=policy, active_policy=active, max_refs=refs, diagnostics=True)
                    output = replay(root_rows, gate, **kwargs)
                    by_time = {r['time']: r for r in output}
                    window = [r for r in output if r['time'] >= '2025-06-24']
                    for row in window:
                        assert replay([r for r in root_rows if r['time'] <= row['time']], gate, **kwargs)[-1] == row
                        prefix_checks += 1
                    dull = by_time['2025-06-24 14:00:00']
                    cancel = by_time['2025-06-25 14:00:00']
                    missed = by_time['2025-06-27 14:00:00']
                    pool = missed['reference_refresh']['same_sign_last_two']
                    assert dull['event'] == 'DULL' and cancel['event'] == 'CANCEL'
                    assert missed['event'] == 'NONE' and missed['state'] == 'NONE'
                    assert len(pool) == 1 and pool[0]['start'] == rows[0]['time']
                    assert pool[0]['dif'] == 10.556501856990963
                    variants.append(dict(reference_policy=policy, active_policy=active,
                        gate_pct=gate, max_refs=refs, dull=dull, cancel=cancel, missed=missed))
    by_input = {r['time']: r for r in rows}
    prev = by_input['2025-06-27 11:00:00']
    target = by_input['2025-06-27 14:00:00']
    fall_pct = (prev['dif'] - target['dif']) / abs(prev['dif']) * 100
    assert fall_pct > max(options['gate_pct'])
    # Necessary constraints if the same locked-reference/strict-break mechanism
    # was to retain a dulling reference through this saved peak. These are not
    # an invented software reference or proof that such a peak actually existed.
    constraints = dict(saved_reference_dif=10.556501856990963,
        dif_on_cancellation=by_input['2025-06-25 14:00:00']['dif'],
        maximum_dif_through_formation=prev['dif'],
        required_reference_dif_lower_bound_if_locked=prev['dif'],
        bound_inclusive=True, gate_fall_pct=fall_pct,
        missing_information=['Earlier part of the first positive wave may be missing',
            'Earlier eligible positive waves are not available in this extract',
            'Which historical peak the software actually used is unknown'],
        conclusion='Lost activation eligibility precedes the missed turn; true software root cause still unconfirmed')
    lecture_context = []
    needles = {
        '20250624': ['90分钟也一样啊', '所以90分钟 120分钟仍然是有顿化的'],
        '20250626': ['90分钟他现在目前是个低分', '90分钟 120分钟 日线现在全都有钝化'],
    }
    for date, markers in needles.items():
        path = ROOT / f'sources/{date}_vidiq_transcript.json'
        data = json.loads(path.read_text())
        text = data['response']['transcription']
        for marker in markers:
            start = text.index(marker)
            lecture_context.append(dict(date=date, source=str(path.relative_to(REPO)), sha256=sha(path),
                marker=marker, character_start=start, excerpt=text[max(0, start-50):start+260],
                no_new_source=True, raw_transcription_not_audio_verified=True))
    fixture_path = REPO / 'tests/fixtures/quote_trend_channel/000001_sh_daily_input.json'
    fixture = json.loads(fixture_path.read_text())['rows']
    seed = read_rows('daily_2025.csv')
    daily = {mode: extend_daily(seed, fixture, '2025-11-14', mode)[0]
             for mode in ('recovered_rounded_seed', 'fixture_first_close')}
    lifecycles = []
    for spec in defs['historical_observations']:
        observation_path = ROOT / spec['source']
        observation = json.loads(observation_path.read_text())
        assert observation['candidate_sha256'] == sha(candidate)
        series = {'saved90': rows} if spec['period'] == '90' else daily
        for origin, data in series.items():
            for policy in options['reference_policy']:
                for gate in options['gate_pct']:
                    clipped = [r for r in data if r['time'] <= spec['mapped_disappearance']]
                    out = replay(clipped, gate, reference_policy=policy)
                    a = next(i for i, r in enumerate(out) if r['time'] == spec['formation'])
                    b = len(out) - 1
                    anchor = out[a]
                    assert anchor['event'] == 'STRUCTURE' and anchor['event_direction'] == 1
                    reset = next(i for i in range(a, b+1) if out[i]['hist'] < 0)
                    assert out[reset]['state'] == 'NONE' and out[reset]['ref_start'] == ''
                    assert out[b]['event'] == 'NONE' and out[b]['state'] == 'NONE'
                    for i in {a, reset, b}:
                        assert replay(clipped[:i+1], gate, reference_policy=policy)[-1] == out[i]
                        prefix_checks += 1
                    lifecycles.append(dict(period=spec['period'], input_origin=origin,
                        policy=policy, gate_pct=gate, anchor=anchor, saved_negative_state_reset=out[reset],
                        mapped_disappearance=out[b], bars_after_reset=b-reset,
                        source=str(observation_path.relative_to(REPO)), source_sha256=sha(observation_path),
                        observation_conditional=True, historical_markers_not_added_to_replay=True))
    assert {x['bars_after_reset'] for x in lifecycles if x['period'] == 'daily'} == {1}
    compact = []
    for spec in defs['historical_observations']:
        group = [r for r in lifecycles if r['period'] == spec['period'] and r['anchor']['time'] == spec['formation']]
        assert len({(x['saved_negative_state_reset']['time'], x['bars_after_reset']) for x in group}) == 1
        compact.append(dict(period=spec['period'], formation=spec['formation'],
            saved_state_clear=group[0]['saved_negative_state_reset']['time'],
            mapped_green=spec['mapped_disappearance'], bars_after_clear=group[0]['bars_after_reset'],
            variants=len(group)))
    result = dict(research_date='2026-10-12', definitions_sha256=sha(defs_path),
        candidate_sha256=sha(candidate), input_sha256=sha(inputs),
        input_profile=dict(rows=len(rows), distinct_keys=len(set(times)), finite_numeric=True,
            first=times[0], last=times[-1], bars_per_saved_date=3,
            positive_at_left_boundary=rows[0]['hist'] > 0, complete_first_wave_unknown=True,
            contiguous_calendar_coverage_not_asserted=True),
        root_variants=variants, root_constraints=constraints, existing_lecture_context=lecture_context,
        lifecycle_variants=lifecycles, lifecycle_summary=compact, prefix_checks=prefix_checks,
        source_fingerprints={str(p.relative_to(REPO)): sha(p) for p in (
            inputs, candidate, ROOT / 'audit_november_followup.py', ROOT / 'inputs/daily_2025.csv', fixture_path)},
        next_research_constraints=defs['next_model_constraints'],
        next_step='Verify same-period historical reference coverage before interpreting June27 as a turn-threshold failure. Keep historical confirmation lifecycle separate in any future research model; no new withdrawal formula or source date chosen here.',
        limitations=['Direct mechanism on saved input is established; actual software historical reference is not',
            'Two possible prefix omissions are hypotheses, not verified repair instructions',
            'Mapped observations remain conditional and were already seen; this is no independent validation set',
            'Different periods and origins are not independent observations',
            'No fixed countdown, 24-bar expiry, bottom symmetry or whole-defense correction join inferred',
            'No additional labels or sources and no production/dependency/data/branch/commit/trading changes'])
    return result


def main():
    before = json.loads(Path('/private/tmp/xxm_lifecycle_trace_before_20261012.json').read_text())
    assert all(sha(REPO / name) == digest for name, digest in before.items())
    result = analyze()
    assert all(sha(REPO / name) == digest for name, digest in before.items())
    result['preserved_prior_files'] = len(before)
    (ROOT / 'lifecycle_trace_audit_20261012.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(root_variants=len(result['root_variants']), prefix_checks=result['prefix_checks'],
        fall_pct=result['root_constraints']['gate_fall_pct'], lifecycle_summary=result['lifecycle_summary'],
        preserved_prior_files=len(before)), ensure_ascii=False))


if __name__ == '__main__':
    main()
