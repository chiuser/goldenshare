"""Offline P0 source-coverage check. No API/Lake reads, sampling or returns."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile


def profile(rows: list[dict], inventory: list[dict], suspensions: list[dict], day: str) -> dict:
    """Keep missing caps visible; three equal-count bins are feasibility only."""
    caps = {}
    for row in rows:
        code, value = row['ts_code'], row['total_mv']
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code):
            raise ValueError('invalid source code')
        if code in caps or row['trade_date'] != day:
            raise ValueError('duplicate code or wrong date')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('invalid total_mv')
        caps[code] = value
    codes = [r['code'] for r in inventory]
    if len(set(codes)) != len(codes) or any(not re.fullmatch(r'\d{6}\.(SH|SZ)', c) for c in codes):
        raise ValueError('invalid research universe')
    if any(type(r['seen']) is not bool for r in inventory):
        raise ValueError('invalid exposure flag')
    if any(r['trade_date'] != day for r in suspensions):
        raise ValueError('wrong suspension date')
    full_day = {r['ts_code'] for r in suspensions
                if r['suspend_type'] == 'S' and not (r['suspend_timing'] or '').strip()}
    full_day -= {r['ts_code'] for r in suspensions if r['suspend_type'] == 'R'}
    missing = [{'code': r['code'], 'board': r['board'], 'seen': r['seen'],
                'full_day_suspension': r['code'] in full_day}
               for r in inventory if r['code'] not in caps]
    boards = []
    for board in sorted({r['board'] for r in inventory}):
        pool = [r for r in inventory if r['board'] == board and not r['seen']]
        covered = sorted((r for r in pool if r['code'] in caps), key=lambda r: (caps[r['code']], r['code']))
        quotient, remainder = divmod(len(covered), 3)
        boards.append({'board': board, 'not_selected': len(pool), 'covered': len(covered),
                       'missing': len(pool) - len(covered),
                       'illustrative_small_mid_large': [quotient + (i < remainder) for i in range(3)]})
    return {'source_rows': len(rows), 'eligible': len(inventory),
            'covered': len(inventory) - len(missing), 'missing': missing,
            'not_selected': sum(not r['seen'] for r in inventory),
            'not_selected_covered': sum(not r['seen'] and r['code'] in caps for r in inventory),
            'outside_universe': len(set(caps) - set(codes)), 'boards': boards,
            'status': 'source_feasibility_only_no_sampling_no_imputation'}


def audit(evidence: dict, root: Path) -> dict:
    path = root / evidence['p0_archive']
    if hashlib.sha256(path.read_bytes()).hexdigest() != evidence['p0_sha256']:
        raise ValueError('P0 source fingerprint mismatch')
    with zipfile.ZipFile(path) as z:
        lake = json.loads(z.read('lake_audit.json'))
    day = lake['size_date'].replace('-', '')
    calls = evidence['calls']
    full = next(c for c in calls if c['label'] == 'full_date')
    if full['args'] != {'trade_date': day, 'fields': ['ts_code', 'trade_date', 'total_mv']}:
        raise ValueError('full-date request mismatch')
    result = profile(full['rows'], lake['stock_inventory'],
                     next(c for c in calls if c['label'] == 'suspend_default')['rows'], day)
    probe = [next(c for c in calls if c['label'] == f'probe_{i}')['rows'][0] for i in range(3)]
    for row in probe:
        if row['trade_date'] != day or row['ts_code'] != '002245.SZ' or row['total_mv'] != probe[0]['total_mv']:
            raise ValueError('field-mode mismatch')
    if any(probe[0].get(key) != value for row in probe[1:] for key, value in row.items()):
        raise ValueError('explicit projection mismatch')
    full_probe = next(r for r in full['rows'] if r['ts_code'] == probe[0]['ts_code'])
    if full_probe['total_mv'] != probe[0]['total_mv']:
        raise ValueError('single-stock vs full-date mismatch')
    suspension_rows = next(c for c in calls if c['label'] == 'suspend_default')['rows']
    normalize = lambda rows: sorted(json.dumps(r, sort_keys=True) for r in rows)
    for label in ('suspend_explicit_1', 'suspend_explicit_2'):
        if normalize(next(c for c in calls if c['label'] == label)['rows']) != normalize(suspension_rows):
            raise ValueError('suspension projection mismatch')
    result['probe_price_times_shares_minus_total_mv_wanyuan'] = round(
        probe[0]['close'] * probe[0]['total_share'] - probe[0]['total_mv'], 8)
    for item in result['missing']:
        call = next(c for c in calls if c['label'] == 'missing_' + item['code'])
        if call['rows'] or call['args']['trade_date'] != day or call['args']['ts_code'] != item['code']:
            raise ValueError('missing-code probe mismatch')
    if result != evidence['summary']:
        raise ValueError('stored summary does not reproduce')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path, help='Saved source evidence JSON; read only')
    args = parser.parse_args()
    print(json.dumps(audit(json.loads(args.evidence.read_text()), Path(__file__).resolve().parents[4]),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
