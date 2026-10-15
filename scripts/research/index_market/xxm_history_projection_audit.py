"""Compare complete minute history with its XXM field projection, read-only.

Run from the repository root. Reads the formal Lake, never writes source files;
all output goes to a new explicitly selected report directory.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import time

from src.foundation.clients.local_lake.major_index_mins_contract import FORMAL_LAKE_ROOT
from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteReadRequest, MajorIndexMinsLakeReader


def digest(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--through', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    records = []
    for freq in (60, 90, 120):
        reader = MajorIndexMinsLakeReader(FORMAL_LAKE_ROOT)
        request = IndexMinuteReadRequest('000001.SH', freq, None, args.through, 1000, None)
        expected_pages = []
        for dataset, values in (('bars', ('close',)), ('indicators', ('macd_dif', 'macd_dea', 'macd'))):
            fields = ('ts_code', 'freq', 'trade_date', 'trade_time', *values)
            signature = reader.history_source_signature(request, dataset=dataset)
            started = time.perf_counter()
            full = reader.read_complete_history(request, dataset=dataset, timeout_seconds=4)
            full_seconds = time.perf_counter() - started
            refreshed = reader.history_source_signature(request, dataset=dataset)
            assert signature == refreshed, 'Source changed during parity audit; compare a new snapshot'
            started = time.perf_counter()
            projected = reader.read_complete_history(request, dataset=dataset, timeout_seconds=4, value_columns=values)
            projection_seconds = time.perf_counter() - started
            assert signature == reader.history_source_signature(request, dataset=dataset)
            expected = tuple({key: row[key] for key in fields} for row in full.rows)
            assert expected == projected.rows
            expected_pages.append(expected)
            assert full.count == projected.count and full.scanned_file_count == projected.scanned_file_count
            assert projected.next_cursor is None and not projected.has_more
            record = dict(freq=freq, dataset=dataset, count=projected.count, files=projected.scanned_file_count,
                          first=str(projected.rows[0]['trade_time']), last=str(projected.rows[-1]['trade_time']),
                          signature=digest(signature), values=digest(expected), fullSeconds=full_seconds,
                          projectionSeconds=projection_seconds)
            records.append(record)
            (out/'parity.json').write_text(json.dumps(dict(status='PASS', through=str(args.through), records=records), indent=2)+'\n')
            print(json.dumps(record), flush=True)

        started = time.perf_counter()
        paired = reader.read_complete_history_pair(request, timeout_seconds=4,
            bar_value_columns=('close',), indicator_value_columns=('macd_dif', 'macd_dea', 'macd'))
        assert [page.rows for page in paired] == expected_pages
        records.append(dict(freq=freq, dataset='pair', counts=[page.count for page in paired],
                            pairSeconds=time.perf_counter()-started, values=[digest(page.rows) for page in paired]))
        (out/'parity.json').write_text(json.dumps(dict(status='PASS', through=str(args.through), records=records), indent=2)+'\n')


if __name__ == '__main__':
    main()
