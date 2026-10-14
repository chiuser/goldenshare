"""Read-only historical coverage audit; preserves the frozen candidate and CSV.

Predeclared comparison: Apr 1-Jul 3 vs Jun 3-Jul 3, locked references,
two existing reference policies, 0.75/1/1.2 percent gates. No EMA recompute,
synthetic references, software labels, or formal Lake writes.
"""
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from active_reference_candidate import replay

ROOT = Path(__file__).resolve().parent
LAKE = Path('/Volumes/datasource/data_lake/gold')
START, END = '2025-04-01', '2025-07-03'
OLD = ROOT / 'inputs/90_20250603_20260113.csv'
TARGETS = ['2025-06-24 14:00:00', '2025-06-25 14:00:00',
           '2025-06-27 14:00:00', '2025-07-01 14:00:00',
           '2025-07-02 14:00:00', '2025-07-03 14:00:00']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = ROOT / 'history_prefix_audit_20261012.json'
    protected = {str(p.relative_to(ROOT)): digest(p) for p in ROOT.rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p != output}
    sources = {}
    for kind, subdir in [('indicator', 'indicator/major_index_mins_technical'),
                         ('quote', 'quote/major_index_mins')]:
        sources[kind] = sorted(
            p for p in (LAKE / subdir / 'freq=90').glob('trade_date=*/part-000.parquet')
            if START <= p.parent.name.removeprefix('trade_date=') <= END)
    assert sources['indicator'] and sources['quote']
    assert [p.parent.name for p in sources['indicator']] == [
        p.parent.name for p in sources['quote']]
    provenance = [dict(kind=k, path=str(p), bytes=p.stat().st_size,
                       sha256=digest(p)) for k, paths in sources.items() for p in paths]
    con = duckdb.connect(':memory:')
    con.execute('SET allowed_paths=' + repr([p['path'] for p in provenance]))
    con.execute('SET enable_external_access=false')
    con.execute('SET allow_persistent_secrets=false')
    con.execute('SET lock_configuration=true')
    fields = {'indicator': 'trade_time,macd_dif,macd_dea,macd,params_key',
              'quote': 'trade_time,open,high,low,close'}
    records = {}
    for kind, paths in sources.items():
        records[kind] = con.execute(
            f'SELECT {fields[kind]} FROM read_parquet(?,hive_partitioning=false) '
            "WHERE ts_code='000001.SH' AND freq=90 ORDER BY trade_time",
            [[str(p) for p in paths]]).fetchall()
        times = [r[0] for r in records[kind]]
        assert times == sorted(set(times))
    con.close()
    assert [r[0] for r in records['indicator']] == [r[0] for r in records['quote']]
    params = sorted({r[4] for r in records['indicator']})
    assert len(params) == 1 and '__macd_12_26_9__' in params[0]
    exported = []
    for t, q in zip(records['indicator'], records['quote']):
        assert all(math.isfinite(v) for v in (*t[1:4], *q[1:]))
        assert abs(t[3] - 2 * (t[1] - t[2])) < 1e-9
        exported.append(dict(trade_time=str(t[0]), open=q[1], high=q[2], low=q[3],
                             close=q[4], dif=t[1], dea=t[2], hist=t[3]))
    assert 0 < len(exported) <= 210
    with OLD.open(newline='') as handle:
        old = list(csv.DictReader(handle))
    old_overlap = [r for r in old if r['trade_time'] <= END + ' 15:00:00']
    by_time = {r['trade_time']: r for r in exported}
    assert old_overlap
    for row in old_overlap:
        assert row['trade_time'] in by_time
        assert set(row) == set(by_time[row['trade_time']])
        assert all(float(row[k]) == by_time[row['trade_time']][k]
                   for k in row if k != 'trade_time'), row['trade_time']
    rows = [dict(time=r['trade_time'], **{k: r[k] for k in ('close', 'dif', 'hist')})
            for r in exported]
    truncated = [r for r in rows if r['time'] >= old[0]['trade_time']]
    old_all = [dict(time=r['trade_time'], **{k: float(r[k]) for k in ('close', 'dif', 'hist')})
               for r in old]
    extended_all = [r for r in rows if r['time'] < old[0]['trade_time']] + old_all
    # Follow-up sensitivity check: only history differs; the saved future is unchanged.
    assert len(extended_all) <= 600
    segments = []
    for row in rows:
        sign = (row['hist'] > 0) - (row['hist'] < 0)
        if not segments or segments[-1]['sign'] != sign:
            segments.append(dict(sign=sign, rows=[]))
        segments[-1]['rows'].append(row)
    prior_positive_waves = []
    for index, segment in enumerate(segments):
        wave_rows = segment['rows']
        if segment['sign'] == 1 and wave_rows[-1]['time'] < '2025-06-24':
            price_peak = max(wave_rows, key=lambda r: r['close'])
            dif_peak = max(wave_rows, key=lambda r: r['dif'])
            prior_positive_waves.append(dict(
                start=wave_rows[0]['time'], end=wave_rows[-1]['time'], bars=len(wave_rows),
                price_peak=price_peak['close'], price_peak_time=price_peak['time'],
                dif_peak=dif_peak['dif'], dif_peak_time=dif_peak['time'],
                left_boundary_observed=index > 0, right_boundary_observed=index < len(segments)-1))
    comparisons, prefix_checks = [], 0
    for policy in ('nearest_qualifying', 'strongest_eligible'):
        for gate in (0.75, 1.0, 1.2):
            options = dict(active_policy='locked', reference_policy=policy,
                           max_refs=2, min_bars=2, diagnostics=True)
            extended = replay(rows, gate, **options)
            short = replay(truncated, gate, **options)
            extended_map, short_map = ({r['time']: r for r in rs}
                                       for rs in (extended, short))
            for time in TARGETS:
                idx = next(i for i, r in enumerate(rows) if r['time'] == time)
                assert replay(rows[:idx+1], gate, **options) == extended[:idx+1]
                prefix_checks += 1
            old_future, extended_future = (replay(rs, gate, **options)
                                           for rs in (old_all, extended_all))
            future_map = {r['time']: r for r in extended_future}
            semantic_keys = ('event', 'state', 'event_direction', 'event_route',
                             'event_ref_dif', 'event_ref_price')
            changed = [dict(time=r['time'], before={k: r[k] for k in semantic_keys},
                            after={k: future_map[r['time']][k] for k in semantic_keys})
                       for r in old_future if any(r[k] != future_map[r['time']][k]
                                                  for k in semantic_keys)]
            later = [r for r in old_future if r['time'] >= '2025-07-01']
            assert all(all(r[k] == future_map[r['time']][k] for k in semantic_keys)
                       for r in later)
            comparisons.append(dict(
                reference_policy=policy, gate_pct=gate,
                saved_future_bars=len(old_future), extended_context_bars=len(extended_future),
                semantic_changes=changed, july_onward_bars_unchanged=len(later),
                targets=[dict(time=t, truncated=short_map[t], extended=extended_map[t])
                         for t in TARGETS],
                extended_events=[r for r in extended
                                 if '2025-06-24' <= r['time'] and r['event'] != 'NONE']))
    target = ROOT / 'inputs/90_20250401_20250703.csv'
    if target.exists():
        with target.open(newline='') as handle:
            saved = list(csv.DictReader(handle))
        assert len(saved) == len(exported)
        assert all(s['trade_time'] == e['trade_time'] and
                   all(float(s[k]) == e[k] for k in e if k != 'trade_time')
                   for s, e in zip(saved, exported)), 'do not overwrite research evidence'
    else:
        with target.open('x', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(exported[0]))
            writer.writeheader()
            writer.writerows(exported)
    assert all(digest(Path(p['path'])) == p['sha256'] for p in provenance)
    assert all(digest(ROOT / name) == sha for name, sha in protected.items())
    result = dict(
        audited_at_utc=datetime.now(timezone.utc).isoformat(),
        question='Does real same-frequency history before June 3 restore June 27 structure eligibility?',
        interpretation='DG historical inputs, not verified software reference readings; retrospective diagnosis',
        requested_start=START, requested_end=END, rows=len(rows),
        prefix_rows_added=len(rows)-len(truncated), overlap_rows_exact=len(old_overlap),
        first_time=rows[0]['time'], last_time=rows[-1]['time'],
        first_hist=rows[0]['hist'], params_key=params[0],
        csv_sha256=digest(target), frozen_csv_sha256=digest(OLD),
        candidate_sha256=digest(ROOT / 'active_reference_candidate.py'),
        duckdb_version=duckdb.__version__, prefix_checks=prefix_checks,
        protected_existing_files_unchanged=len(protected),
        prior_positive_waves=prior_positive_waves,
        source_files=provenance, comparisons=comparisons)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ('source_files', 'comparisons', 'prior_positive_waves')},
                     ensure_ascii=False))
    for comparison in comparisons:
        print(json.dumps(dict(policy=comparison['reference_policy'], gate=comparison['gate_pct'],
                              semantic_changes=len(comparison['semantic_changes']),
                              july_onward_bars_unchanged=comparison['july_onward_bars_unchanged'],
                              targets=[dict(time=t['time'], old=t['truncated']['event'],
                                            new=t['extended']['event'], state=t['extended']['state'],
                                            reference=t['extended']['reference_refresh']['active_reference'],
                                            event_reference=t['extended']['reference_refresh']['event_reference'])
                                       for t in comparison['targets']]), ensure_ascii=False))


if __name__ == '__main__':
    main()
