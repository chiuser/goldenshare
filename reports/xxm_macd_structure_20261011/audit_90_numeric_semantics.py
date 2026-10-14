"""Bounded offline audit of 90-minute MACD and software numeric differences.

Reads saved CSVs, four previously supplied pictures, and pure window contracts.
Does not import assets/resources, access Lake/DB, or alter candidate rules.
The fixed-seed and rounding controls isolate hypotheses; neither is a vendor
implementation. Previously read pictures make this a retrospective analysis.
"""
import csv
import hashlib
import json
import runpy
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
FAST, SLOW, SIGNAL = 2 / 13, 2 / 27, 2 / 10
BF, BS = 1 - FAST, 1 - SLOW
SOFTWARE = [
    dict(date='2025-08-06', image='IMG_0374.PNG', dif=12.244, dea=7.817,
         hist=8.855, open=3628.43, high=3634.31, low=3628.27, close=3633.99),
    dict(date='2025-08-12', image='IMG_0359.PNG', dif=18.704, dea=16.557,
         hist=4.293, open=3666.15, high=3668.71, low=3661.13, close=3665.92),
    dict(date='2025-08-14', image='IMG_0315.PNG', dif=20.435, dea=20.109,
         hist=.652, open=3677.24, high=3686.49, low=3666.44, close=3666.44),
    dict(date='2026-01-13', image='IMG_0369.PNG', dif=45.344, dea=44.449,
         hist=1.790, open=4163.98, high=4164.19, low=4126.23, close=4138.76),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name):
    with (ROOT / 'inputs' / name).open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) <= 3000
    return [{key: value if key == 'trade_time' else float(value)
             for key, value in row.items()} for row in rows]


def ema(rows, *, initial=None, price_round=False):
    if initial is None:
        fast = slow = rows[0]['close']
        dea = 0.0
        first = 0
        output = []
    else:
        fast, slow, dea = initial
        first = 1
        output = [dict(trade_time=rows[0]['trade_time'], close=rows[0]['close'],
                       dif=fast-slow, dea=dea, hist=2*(fast-slow-dea))]
    for row in rows[first:]:
        close = round(row['close'], 2) if price_round else row['close']
        fast = BF * fast + FAST * close
        slow = BS * slow + SLOW * close
        dif = fast - slow
        dea = (1 - SIGNAL) * dea + SIGNAL * dif
        output.append(dict(trade_time=row['trade_time'], close=close,
                           dif=dif, dea=dea, hist=2*(dif-dea)))
    return output


def main():
    protected = json.loads(Path('/private/tmp/xxm_90_numeric_before_20261011.json').read_text())
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    name = '90_20250603_20260113.csv'
    rows = load(name)
    thirty = load('30_20250603_20261009.csv')
    overlap = load('90_20250701_20250814.csv')
    assert len(rows) == 459 and len(overlap) == 99
    by_time = {row['trade_time']: row for row in rows}
    assert all(all(row[key] == by_time[row['trade_time']][key]
                   for key in ('close', 'dif', 'dea', 'hist')) for row in overlap)

    contract_path = REPO / 'lake_console/orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py'
    contract = runpy.run_path(str(contract_path))
    windows = contract['canonical_gold_minute_windows'](90)
    ends = tuple(window.target_time for window in windows)
    assert ends == ('11:00:00', '14:00:00', '15:00:00')
    days = defaultdict(dict)
    for row in thirty:
        if row['trade_time'] <= rows[-1]['trade_time']:
            days[row['trade_time'][:10]][row['trade_time'][11:]] = row
    derived = []
    for date, bars in sorted(days.items()):
        for window in windows:
            assert all(time in bars for time in window.regular_source_times)
            derived.append(bars[window.target_time])
    assert len(derived) == len(rows)
    assert all(a['trade_time'] == b['trade_time'] and a['close'] == b['close']
               for a, b in zip(derived, rows))

    # Recover first-bar fast/slow states from D0, D1 and C1. Subsequent rows
    # are independent recurrence checks, not a seed refit at each observation.
    slow = rows[1]['close'] + (BF*rows[0]['dif'] - rows[1]['dif']) / (FAST-SLOW)
    fast = slow + rows[0]['dif']
    initial = (fast, slow, rows[0]['dea'])
    reconstructed = ema(rows, initial=initial)
    residuals = {key: max(abs(a[key]-b[key]) for a, b in zip(rows[2:], reconstructed[2:]))
                 for key in ('dif', 'dea', 'hist')}
    assert max(residuals.values()) < 1e-8
    rounded = ema(rows, initial=initial, price_round=True)
    assert max(abs(a['dif']-b['dif']) for a, b in zip(rounded, reconstructed)) < .01
    alternate = [bars[time] for _, bars in sorted(days.items())
                 for time in ('11:00:00', '11:30:00', '14:30:00', '15:00:00')]
    alternate_ema = {row['trade_time']: row for row in ema(alternate)}

    manifest = {entry['file']: entry for entry in
                json.loads((ROOT / 'screenshot_manifest.json').read_text())}
    observations = []
    for observation in SOFTWARE:
        image_path = Path(manifest[observation['image']]['original_path'])
        assert sha(image_path) == manifest[observation['image']]['sha256']
        time = observation['date'] + ' 15:00:00'
        i = next(i for i, row in enumerate(rows) if row['trade_time'] == time)
        dg = rows[i]
        price_difference = {key: observation[key]-dg[key]
                            for key in ('open', 'high', 'low', 'close')}
        previous_close_error = observation['open'] - rows[i-1]['close']
        assert abs(previous_close_error) <= .0051
        assert all(abs(price_difference[key]) <= .0051 for key in ('high', 'low', 'close'))
        dif_difference = observation['dif']-dg['dif']
        # EMA is a convex filter: rounding each close to nearest .01 produces
        # <=.005 error in each EMA, <=.01 in DIF; allow .001 for DIF display.
        assert abs(dif_difference) > .011
        observations.append(dict(software=observation, dg=dg, index=i,
            software_minus_dg={key: observation[key]-dg[key] for key in ('dif', 'dea', 'hist')},
            ohlc_software_minus_dg=price_difference,
            software_open_minus_previous_close=previous_close_error,
            rounded_price_dif=rounded[i]['dif'],
            session_restart_dif=alternate_ema[time]['dif'],
            image_sha256=sha(image_path)))

    # Isolate a SINGLE fixed initialization difference with common prices and
    # exact 12/26 EMA coefficients: delta D(k)=A*BF**k+B*BS**k.
    first, second = observations[:2]
    origin = first['index']
    m = second['index']-origin
    e0 = first['software_minus_dg']['dif']
    e1 = second['software_minus_dg']['dif']
    coefficient_a = (e1-e0*BS**m)/(BF**m-BS**m)
    coefficient_b = e0-coefficient_a
    seed_checks = []
    for observation in observations:
        k = observation['index']-origin
        w1 = (BS**k-BF**k)/(BS**m-BF**m)
        w0 = BF**k-w1*BF**m
        predicted = coefficient_a*BF**k+coefficient_b*BS**k
        actual = observation['software_minus_dg']['dif']
        allowance = .001*(1+abs(w0)+abs(w1))
        seed_checks.append(dict(date=observation['software']['date'], bars_after_anchor=k,
            predicted_difference=predicted, observed_difference=actual,
            residual=actual-predicted, conservative_display_allowance=allowance,
            compatible=abs(actual-predicted) <= allowance))
    assert all(check['compatible'] for check in seed_checks[:2])
    assert not any(check['compatible'] for check in seed_checks[2:])

    # Prefix invariance checks use recovered states, so no later value decides
    # a focal output after the two-row seed identification.
    focal = [item['index'] for item in observations]
    focal += [i for i, row in enumerate(rows) if row['trade_time'].startswith('2025-12-16')]
    for i in focal:
        assert ema(rows[:i+1], initial=initial)[-1] == reconstructed[i]
    source_paths = [contract_path,
        REPO/'lake_console/orchestrator/src/orchestrator/defs/run_contracts/major_index_mins.py',
        REPO/'lake_console/orchestrator/src/orchestrator/defs/run_contracts/major_index_mins_technical.py',
        REPO/'lake_console/orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py']
    result = dict(as_of=datetime.now(timezone.utc).isoformat(),
        source_code=[dict(path=str(path), sha256=sha(path)) for path in source_paths],
        inputs={n: sha(ROOT/'inputs'/n) for n in (name, '90_20250701_20250814.csv',
                                                 '30_20250603_20261009.csv')},
        rows=459, overlapping_rows_unchanged=99,
        windows=[dict(target_time=w.target_time, source_times=w.regular_source_times,
                      auction_anchor_time=w.auction_anchor_time) for w in windows],
        endpoint_close_matches=459, derived_price_limit='Saved 30-minute CSV has no OHLC/auction row; only close/endpoint reconstruction is verified',
        recovered_first_bar_state=dict(fast=fast, slow=slow, dea=initial[2]),
        independent_recurrence_checks=len(rows)-2, maximum_residual=residuals,
        rounding_control='Same state and coefficients, round subsequent closes to nearest .01; isolated upper bound .01 DIF plus .001 display',
        observations=observations,
        fixed_initialization_only=dict(anchor_dates=['2025-08-06','2025-08-12'],
                                      coefficient_a=coefficient_a, coefficient_b=coefficient_b,
                                      checks=seed_checks,
                                      exclusions='Does not exclude per-chart reseeding, combined source differences or different recurrence precision'),
        session_restart_control='Specific alternative: restart 90-minute grouping after lunch, with four bars per day. Cold seeded on June 3; large mismatch, not an exhaustive bin search',
        december16=[dict(saved=row, recomputed=reconstructed[i]) for i, row in enumerate(rows)
                    if row['trade_time'].startswith('2025-12-16')],
        focal_prefix_checks=len(focal), software_marker_labels_added=0,
        conclusion='DG export is internally consistent; nearest-price rounding alone and a single fixed initial-state offset alone cannot explain software differences. Vendor calculation/input history remains unresolved',
        browser_probe='CUA video-tab creation and subsequent state query timed out; no video frame obtained; no further retry',
        protected_files=protected, protected_files_unchanged=True,
        script_sha256=sha(Path(__file__)),
        limits=['No new 90-minute December 16 software image or numeric reading',
                'Matching terminal highs/lows/closes does not prove all intraday historical closes agree',
                'Previous-close opening is an observed alignment, not a verified vendor-wide rule',
                'Do not apply a constant DIF correction or modify frozen candidates to make screenshots fit',
                'No formal Dagster execution, Lake/DB reads or writes, dependency installation or trading actions'])
    assert all(sha(ROOT/name) == digest for name, digest in protected.items())
    (ROOT/'numeric_90_semantics_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(close_matches=459, overlap_matches=99,
                          recurrence_residuals=residuals, seed_only_rejected=2,
                          prefix_checks=len(focal), protected_files=len(protected)),ensure_ascii=False))


if __name__ == '__main__':
    main()
