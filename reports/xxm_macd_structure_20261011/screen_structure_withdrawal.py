"""Offline distinction screen; diagnostic monitors are not software signals.

Definitions precede this run. Preserve the candidate and every old observation.
Each confirmed top is a separate diagnostic anchor, not a trading episode.
"""
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from active_reference_candidate import replay
from audit_november_followup import extend_daily
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
DEFS = ROOT / 'structure_withdrawal_definitions_20261012.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan(output, gate):
    anchors = [i for i, r in enumerate(output)
               if r['event'] == 'STRUCTURE' and r['event_direction'] == 1]
    records = []
    for n, start in enumerate(anchors):
        end = anchors[n+1] if n+1 < len(anchors) else len(output)
        anchor = output[start]
        firsts = {k: None for k in ('dif_rise_any', 'dif_rise_after_negative',
                                    'histogram_return_positive', 'raw_reference_break', 'new_dull')}
        seen_negative = anchor['hist'] < 0
        first_negative = anchor['time'] if seen_negative else None
        for i in range(start+1, end):
            row, previous = output[i], output[i-1]
            if row['hist'] < 0:
                seen_negative = True
                if first_negative is None:
                    first_negative = row['time']
            rise = (row['dif'] > previous['dif'] and previous['dif'] != 0
                    and row['dif']-previous['dif'] >= abs(previous['dif'])*gate/100)
            predicates = dict(dif_rise_any=rise,
                              dif_rise_after_negative=rise and seen_negative,
                              histogram_return_positive=row['hist'] > 0 and seen_negative,
                              raw_reference_break=row['dif'] > anchor['event_ref_dif'],
                              new_dull=row['event'] == 'DULL' and row['event_direction'] == 1)
            for key, satisfied in predicates.items():
                if satisfied and firsts[key] is None:
                    firsts[key] = row['time']
        any_hit = firsts['dif_rise_any']
        phase_hit = firsts['dif_rise_after_negative']
        color_hit = firsts['histogram_return_positive']
        # Missing outcomes are right-censored, not known forever-absent events.
        distinct = phase_hit is not None and color_hit is not None and phase_hit != color_hit
        later = max(phase_hit, color_hit) if distinct else None
        raw = firsts['raw_reference_break']
        dull = firsts['new_dull']
        clean = distinct and (raw is None or raw > later) and (dull is None or dull > later)
        records.append(dict(anchor_time=anchor['time'], anchor_dif=anchor['dif'],
                            anchor_hist=anchor['hist'], reference_dif=anchor['event_ref_dif'],
                            reference_start=anchor['event_ref_start'], first_negative=first_negative,
                            firsts=firsts, next_top_structure=output[end]['time'] if end < len(output) else None,
                            censor_time=output[end-1]['time'], phase_distinct=distinct,
                            clean_phase_distinct=clean,
                            any_phase_distinct=any_hit is not None and color_hit is not None and any_hit != color_hit,
                            endpoints={key: dict(output[next(i for i in range(start+1, end)
                                                                if output[i]['time'] == time)])
                                       for key, time in firsts.items() if time is not None}))
    return records


def main():
    defs = json.loads(DEFS.read_text())
    for spec in defs['inputs'].values():
        assert sha(REPO / spec['path']) == spec['sha256']
    series = {'60': read_rows('60_20250603_20261009.csv'),
              '90': read_rows('90_20250603_20260113.csv')}
    with (ROOT / 'discrimination_screen_20261012/derived_120.csv').open() as handle:
        series['120'] = [dict(time=r['time'], **{k: float(r[k]) for k in ('close', 'dif', 'hist')})
                         for r in csv.DictReader(handle)]
    seed = read_rows('daily_2025.csv')
    fixture = json.loads((REPO / defs['inputs']['daily_fixture']['path']).read_text())['rows']
    daily_end = min(fixture[-1]['trade_date'], series['60'][-1]['time'][:10])
    minute_closes = {r['time'][:10]: r['close'] for r in series['60'] if r['time'].endswith('15:00:00')}
    derivations = []
    for origin in defs['daily_close_origins']:
        closes = [dict(r) for r in fixture]
        if origin == 'minute60_daily_endpoint':
            for r in closes:
                if seed[-1]['time'] < r['trade_date'] <= daily_end:
                    r['close'] = str(minute_closes[r['trade_date']])
        for mode in defs['daily_initializations']:
            name = 'daily:' + origin + ':' + mode
            rows, derivation = extend_daily(seed, closes, daily_end, mode)
            series[name] = rows
            derivations.append(dict(name=name, **derivation))
    # Existing labels certify only their original observations, not new monitors.
    old = json.loads((ROOT / 'validation_stage2.json').read_text())
    observed = {'daily': {'2025-11-11', '2025-10-13'},
                '120': {'2025-06-27 15:00:00', '2025-07-07 11:30:00',
                        '2025-07-09 15:00:00', '2025-10-10 15:00:00', '2025-10-14 15:00:00'},
                '90': {'2025-11-11 11:00:00'}, '60': set()}
    assert old['labels'] == 39  # This earlier snapshot is not the current total.
    groups = defaultdict(list)
    per_series = []
    prefix_checks = 0
    for name, rows in series.items():
        period = 'daily' if name.startswith('daily:') else name
        for gate in defs['gate_pct']:
            for policy in defs['reference_policy']:
                output = replay(rows, gate, reference_policy=policy)
                episodes = scan(output, gate)
                # Every candidate or monitor endpoint is re-evaluated without
                # later input. Ranking is retrospective; no predictive score.
                times = {e['anchor_time'] for e in episodes}
                times.update(t for e in episodes for t in e['firsts'].values() if t is not None)
                by_time = {r['time']: i for i, r in enumerate(output)}
                for time in sorted(times):
                    i = by_time[time]
                    partial = replay(rows[:i+1], gate, reference_policy=policy)
                    assert partial[-1] == output[i]
                    prefix_episodes = scan(partial, gate)
                    full_anchors = {e['anchor_time']: e for e in episodes if e['anchor_time'] <= time}
                    for e in prefix_episodes:
                        full = full_anchors[e['anchor_time']]
                        for key, actual in e['firsts'].items():
                            wanted = full['firsts'][key]
                            assert actual == (wanted if wanted is not None and wanted <= time else None)
                    prefix_checks += 1
                per_series.append(dict(series=name, period=period, gate_pct=gate, policy=policy,
                                       rows=len(rows), top_anchors=len(episodes),
                                       clean_phase_distinct=sum(e['clean_phase_distinct'] for e in episodes),
                                       phase_distinct=sum(e['phase_distinct'] for e in episodes)))
                for e in episodes:
                    e.update(series=name, period=period, gate_pct=gate, policy=policy,
                             existing_observed_anchor=e['anchor_time'] in observed[period])
                    groups[(period, e['anchor_time'])].append(e)
    expected_count = {'60': 6, '90': 6, '120': 6, 'daily': 24}
    ranked = []
    for (period, time), records in groups.items():
        signatures = {(r['firsts']['dif_rise_after_negative'], r['firsts']['histogram_return_positive'])
                      for r in records}
        stable = len(records) == expected_count[period] and len(signatures) == 1
        robust_clean = stable and all(r['clean_phase_distinct'] for r in records)
        robust_any = (len(records) == expected_count[period] and all(r['any_phase_distinct'] for r in records)
                      and len({(r['firsts']['dif_rise_any'], r['firsts']['histogram_return_positive']) for r in records}) == 1)
        if not robust_clean and not robust_any:
            continue
        base = records[0]
        ranked.append(dict(period=period, anchor_time=time, variants=len(records),
                           existing_observed_anchor=base['existing_observed_anchor'],
                           stable_phase_dates=stable, robust_clean_phase_distinction=robust_clean,
                           robust_any_phase_distinction=robust_any,
                           baseline=base, all_variant_firsts=[dict(series=r['series'], gate_pct=r['gate_pct'],
                                                                 policy=r['policy'], firsts=r['firsts']) for r in records]))
    ranked.sort(key=lambda r: (not r['robust_clean_phase_distinction'],
                              not r['existing_observed_anchor'],
                              r['period'] not in ('daily', '120'),
                              r['period'] != 'daily', r['anchor_time']))
    nov = groups[('daily', '2025-11-11')]
    assert len(nov) == 24
    assert all(r['firsts']['dif_rise_after_negative'] == r['firsts']['histogram_return_positive'] == '2025-11-13' for r in nov)
    result = dict(research_date=defs['research_date'], status='FROZEN_SCREEN_NO_NEW_SOFTWARE_EVIDENCE',
                  definitions_sha256=sha(DEFS), candidate_sha256=sha(ROOT / 'active_reference_candidate.py'),
                  input_fingerprints=defs['inputs'], series_summary=per_series, daily_derivations=derivations,
                  groups=len(groups), prefix_checks=prefix_checks,
                  robust_clean_candidates=sum(r['robust_clean_phase_distinction'] for r in ranked),
                  ranked_candidates=ranked, nov11_anchor_checks=len(nov),
                  all_episodes={period+'|'+time: records for (period, time), records in groups.items()},
                  limitations=['All anchors outside saved observations are candidate predictions only',
                               'Competing-event censoring and independent anchor monitors are diagnostic definitions, not software lifetime rules',
                               'DIF return may mean STRUCTURE->DULL rather than structure disappearance; phase filter does not settle identity',
                               '60/90 software history discrepancies remain; daily tail and120 extension are derived inputs',
                               'No candidate changed, no source fetched, no label added, no automatic expiry or trade inference'])
    target = ROOT / 'structure_withdrawal_screen_20261012.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(groups=len(groups), prefix_checks=prefix_checks,
                         robust_clean=result['robust_clean_candidates'], ranked=len(ranked),
                         first_candidates=[dict(period=r['period'], anchor=r['anchor_time'],
                                                known=r['existing_observed_anchor'], clean=r['robust_clean_phase_distinction'],
                                                firsts=r['baseline']['firsts']) for r in ranked[:12]]),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
