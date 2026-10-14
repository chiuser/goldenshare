"""Bounded read-only Lake export for IMG_0369; no formal dataset writes.

Run with the existing orchestrator environment. Two file sets are read
separately, then reconciled by timestamp, avoiding the local DuckDB CLI's
Parquet join statistics assertion. No extensions, installs or network calls.
"""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
LAKE = Path('/Volumes/datasource/data_lake/gold')


def main():
    sources = {}
    for kind, subdir in [('indicator', 'indicator/major_index_mins_technical'),
                         ('quote', 'quote/major_index_mins')]:
        sources[kind] = sorted(p for p in (LAKE / subdir / 'freq=90').glob('trade_date=*/part-000.parquet')
                               if '2025-06-03' <= p.parent.name.removeprefix('trade_date=') <= '2026-01-13')
    assert sources['indicator'] and sources['quote']
    assert [p.parent.name for p in sources['indicator']] == [p.parent.name for p in sources['quote']]
    con = duckdb.connect(':memory:')
    all_paths = [str(p) for paths in sources.values() for p in paths]
    con.execute('SET allowed_paths=' + repr(all_paths))
    con.execute('SET enable_external_access=false')
    con.execute('SET allow_persistent_secrets=false')
    con.execute('SET lock_configuration=true')
    fields = {'indicator': 'trade_time,macd_dif,macd_dea,macd,params_key',
              'quote': 'trade_time,open,high,low,close'}
    records = {}
    for kind, paths in sources.items():
        records[kind] = con.execute(
            f"SELECT {fields[kind]} FROM read_parquet(?,hive_partitioning=false) "
            "WHERE ts_code='000001.SH' AND freq=90 ORDER BY trade_time",
            [[str(p) for p in paths]]).fetchall()
        times = [r[0] for r in records[kind]]
        assert times == sorted(set(times)), (kind, 'duplicate timestamps')
    assert [r[0] for r in records['indicator']] == [r[0] for r in records['quote']]
    params = sorted({r[4] for r in records['indicator']})
    assert len(params) == 1 and '__macd_12_26_9__' in params[0]
    rows = []
    for t, q in zip(records['indicator'], records['quote']):
        assert abs(t[3] - 2 * (t[1] - t[2])) < 1e-9
        rows.append(dict(trade_time=str(t[0]),open=q[1],high=q[2],low=q[3],close=q[4],
                         dif=t[1],dea=t[2],hist=t[3]))
    assert len(rows) <= 600, 'bounded research export exceeded planned size'
    target = ROOT / 'inputs/90_20250603_20260113.csv'
    with target.open('w', newline='') as handle:
        writer = csv.DictWriter(handle,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    meta = dict(exported_at_utc=datetime.now(timezone.utc).isoformat(),ts_code='000001.SH',freq=90,
                requested_start='2025-06-03',requested_end='2026-01-13',rows=len(rows),
                first_time=rows[0]['trade_time'],last_time=rows[-1]['trade_time'],params_key=params[0],
                output=target.name,output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                reconciliation='quote and indicator timestamps unique and identical; histogram equals 2*(DIF-DEA)',
                duckdb_version=duckdb.__version__,
                source_files=[dict(kind=k,path=str(p),bytes=p.stat().st_size,
                                   sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                              for k, paths in sources.items() for p in paths])
    (ROOT / 'export_90_jan13.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in meta.items() if k!='source_files'},ensure_ascii=False))


if __name__ == '__main__':
    main()
