"""Independent M0 count audit from saved OHLC and the alternate BSP iterator."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import time

from scripts.research.index_market.chan.m0_data import REPO, SPEC, digest
from scripts.research.index_market.chan.run_m0 import verify_source


def verify(report, source):
    report = report.resolve(strict=True)
    if not report.is_relative_to(REPO / 'reports'):
        raise ValueError('only saved research reports accepted')
    manifest = json.loads((report / 'manifest.json').read_text())
    for name, expected in manifest['artifacts_sha256'].items():
        if digest((report / name).read_bytes()) != expected:
            raise ValueError(f'artifact changed: {name}')
    source_info = verify_source(source)
    if source_info != manifest['source']:
        raise ValueError('third-party source differs from recorded run')
    from ChanConfig import CChanConfig
    from Common.CEnum import KL_TYPE
    from Common.CTime import CTime
    from KLine.KLine_List import CKLine_List
    from KLine.KLine_Unit import CKLine_Unit

    with (report / 'source.csv').open() as handle:
        rows = [r for r in csv.DictReader(handle) if r['ts_code'] == SPEC.replay_code]
    if not 0 < len(rows) <= SPEC.max_bars:
        raise ValueError('saved input row budget')
    kl = CKLine_List(KL_TYPE.K_DAY, CChanConfig(SPEC.chan_config()))
    last = None
    seen, sure_seen, first = set(), set(), {}
    start = time.monotonic()
    for i, row in enumerate(rows):
        if time.monotonic()-start > SPEC.replay_seconds:
            raise TimeoutError('independent audit budget')
        year, month, day = map(int, row['date'].split('-'))
        unit = CKLine_Unit(dict(time_key=CTime(year, month, day, 0, 0),
                               **{k: float(row[k]) for k in ('open', 'high', 'low', 'close')}))
        unit.set_idx(i)
        unit.kl_type = KL_TYPE.K_DAY
        if last is not None:
            unit.set_pre_klu(last)
        kl.add_single_klu(unit)
        last = unit
        # Unlike the production adapter, traverse type/direction stores.
        points = kl.bs_point_lst.getSortedBspList()
        iterator_indices = {p.bi.idx for p in points}
        if iterator_indices != set(kl.bs_point_lst.bsp_store_flat_dict):
            raise ValueError('BSP iterators disagree')
        for p in points:
            begin = rows[p.bi.get_begin_klu().idx]['date']
            prefix = 'B' if p.is_buy else 'S'
            for kind in {t.value for t in p.type}:
                seen.add((prefix, kind, begin))
                if p.bi.is_sure:
                    sure_seen.add((prefix, kind, begin))
            labels = {t.value for t in p.type}
            targets = [suffix for suffix, types in [('1', {'1'}), ('2', {'2'}), ('3', {'3a', '3b'})]
                       if labels & types]
            if not p.bi.is_sure:
                continue
            for target in targets:
                key = (prefix+target, begin)
                first.setdefault(key, (row['date'], rows[p.klu.idx]['date']))
    saved = [json.loads(line) for line in (report / 'events.jsonl').read_text().splitlines()]
    expected = {(e['group'], e['start_date']): (e['signal_date'], e['anchor_date']) for e in saved}
    if len(saved) != len(expected) or expected != first:
        raise ValueError('alternate iterator first-signal mismatch')
    raw_counts = Counter(prefix+kind for prefix, kind, _ in seen)
    sure_counts = Counter(prefix+kind for prefix, kind, _ in sure_seen)
    b3 = [dict(group=g, start=b, signal=d, anchor=a) for (g, b), (d, a) in first.items()
          if g == 'B3' and d >= SPEC.evaluation_start]
    return dict(alternate_iterator_all_days_equal=True, independently_rebuilt_events=len(first),
                raw_type_candidates=dict(sorted(raw_counts.items())),
                ever_sure_type_candidates=dict(sorted(sure_counts.items())),
                b3_evaluation_events=b3, seconds=time.monotonic()-start,
                source='Saved source.csv; no Lake/DB/API access',
                caveat='Counts by type may overlap; same fixed Chan implementation, not an independent theory implementation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--chan-source', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.report, args.chan_source), ensure_ascii=False, indent=2))
