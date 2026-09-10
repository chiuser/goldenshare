"""R1 G1: fixed SH/SZ historical universe, endpoint ranking and prior-activity controls."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Timer
import time

import duckdb

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_diagnostics import authenticated_input
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.stock_chan_reference import (
    SPEC as INDEX_SPEC, authenticate, select_windows,
)


@dataclass(frozen=True)
class StockRankSpec:
    variant: str = 'stock-chan-shsz-R1-G1-source5'
    start: str = '2021-09-09'
    end: str = '2026-09-08'
    frequency: int = 30
    source_frequency: int = 5
    exchanges: tuple[str, ...] = ('SSE', 'SZSE')
    lookback_days: int = 20
    top_n: int = 50
    max_files: int = 6000
    batch_files: int = 3000
    max_bytes: int = 512 * 1024**2
    max_stocks: int = 6000
    query_seconds: int = 60
    total_seconds: int = 600
    memory: str = '1GiB'
    threads: int = 4
    basis_tolerance: float = 1e-8


SPEC = StockRankSpec()
LAKE = Path('/Volumes/datasource/data_lake')
PLAN = REPO/'docs/product/stock-chan-index-window-research-plan-v1.md'


def historical_pool_sql():
    return """SELECT ts_code,name,exchange,list_date,delist_date FROM life
        WHERE is_cny_stock AND exchange IN ('SSE','SZSE')
        AND list_date <= CAST(? AS DATE)
        AND (delist_date IS NULL OR CAST(? AS DATE) < delist_date)"""


def endpoint_source_sql():
    # Formal Gold30 is aggregated from six Silver5 regular bars, not Silver30.
    # These fixed endpoints exclude the 10:00 auction-anchored first window.
    return """CREATE TEMP TABLE endpoint_source AS SELECT s.ts_code,
        s.trade_time+INTERVAL 25 MINUTE AS trade_time,s.open*f.adj_factor AS adjusted,
        count(*) OVER(PARTITION BY s.ts_code,s.trade_time) AS multiplicity
        FROM read_parquet(?,hive_partitioning=false) s
        JOIN read_parquet(?,hive_partitioning=false) f USING(ts_code,trade_date)
        WHERE s.freq=5 AND strftime(s.trade_time,'%H:%M:%S') IN
          ('10:05:00','10:35:00','11:05:00','13:05:00','13:35:00','14:05:00','14:35:00')"""


def match_controls(ranking, top_n=50):
    """Only pre-window amount enters distance; winners never replaced for missing history."""
    if len(ranking) < 2*top_n:
        raise ValueError('insufficient comparable stocks')
    leaders = ranking[:top_n]
    available = [r for r in ranking[top_n:] if r['prior_amount'] is not None]
    features = sorted({r['prior_amount'] for r in ranking if r['prior_amount'] is not None})
    # Average rank handles ties; relative ranks do not depend on outcome ordering.
    values = sorted(r['prior_amount'] for r in ranking if r['prior_amount'] is not None)
    from bisect import bisect_left, bisect_right
    # Compare twice-ranks as integers: floating percentile subtraction can break exact ties.
    ranks = {v: bisect_left(values, v)+bisect_right(values, v)-1 for v in features}
    pairs = []
    for leader in sorted(leaders, key=lambda r: r['ts_code']):
        value = leader['prior_amount']
        if value is None or not available:
            pairs.append(dict(winner=leader['ts_code'], control=None, reason='prior_history_unavailable'))
            continue
        chosen = min(available, key=lambda r: (abs(ranks[r['prior_amount']]-ranks[value]), r['ts_code']))
        available.remove(chosen)
        pairs.append(dict(winner=leader['ts_code'], control=chosen['ts_code'],
            rank_distance=abs(ranks[value]-ranks[chosen['prior_amount']])/2/max(len(values)-1, 1),
            winner_amount=value, control_amount=chosen['prior_amount']))
    return pairs


@contextmanager
def connection(paths, spec=SPEC):
    with duckdb.connect(':memory:', config={'memory_limit': spec.memory, 'threads': spec.threads,
            'max_temp_directory_size': '0B', 'allow_persistent_secrets': False,
            'autoinstall_known_extensions': False, 'autoload_known_extensions': False}) as con:
        con.execute('SET allowed_paths=?', [[str(p) for p in paths]])
        con.execute('SET enable_external_access=false')
        con.execute('SET lock_configuration=true')
        yield con


def execute(output, spec=SPEC):
    if asdict(spec) != asdict(SPEC):
        raise ValueError('unapproved specification')
    output = safe_output(output)
    started = time.monotonic()
    folder = REPO/INDEX_SPEC.report
    authenticate(folder, INDEX_SPEC.manifest_sha256)
    _, _, source_audit, source_rows = authenticated_input()
    index_rows = [r for r in source_rows if r['code'] == INDEX_SPEC.code and r['frequency'] == spec.frequency]
    books = json.loads((folder/f'{INDEX_SPEC.code}_{spec.frequency}/books.json').read_text())
    windows = select_windows(books['B3']['trades'], index_rows)
    if any(w[k][11:] == '10:00:00' for w in windows for k in ('entry_bar_end','exit_bar_end')):
        raise ValueError('auction-anchored endpoint needs canonical source audit')
    life = LAKE/'silver/basic/stock_lifecycle/full/part-000.parquet'
    calendar = LAKE/'silver/calendar/trade_calendar/full/part-000.parquet'
    gold = sorted(p for p in (LAKE/'gold/quote/stk_mins_qfq/freq=30').glob('ts_code=*/year=2026/part-000.parquet')
                  if p.parts[-3].endswith(('.SH', '.SZ')))
    with connection([calendar], spec) as c:
        days = [r[0] for r in c.execute("""SELECT CAST(trade_date AS VARCHAR)
            FROM read_parquet(?,hive_partitioning=false) WHERE exchange='SSE' AND is_open
            AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) ORDER BY trade_date""",
            [str(calendar), spec.start, spec.end]).fetchmany(2001)]
    if not 0 < len(days) <= 2000 or len(set(days)) != len(days):
        raise ValueError('calendar scope or duplicates')
    wanted = set()
    for w in windows:
        pos = days.index(w['signal_time'][:10])
        w['prior_days'] = days[pos-spec.lookback_days:pos]
        if len(w['prior_days']) != spec.lookback_days:
            raise ValueError('insufficient prior calendar')
        wanted.update(w['prior_days'])
        wanted.update((w['entry_bar_end'][:10], w['exit_bar_end'][:10]))
    endpoint_days = sorted({w[k][:10] for w in windows for k in ('entry_bar_end', 'exit_bar_end')})
    suspension = [LAKE/f'silver/quote/stock_suspend_daily/trade_date={d}/part-000.parquet' for d in sorted(wanted)]
    silver = [LAKE/f'silver/quote/stk_mins/freq={spec.source_frequency}/trade_date={d}/part-000.parquet' for d in endpoint_days]
    factors = [LAKE/f'silver/quote/adj_factor/trade_date={d}/part-000.parquet' for d in endpoint_days]
    paths = [life, calendar]+gold+suspension+silver+factors
    if (not gold or len(paths) > spec.max_files or any(not p.is_file() or p.resolve() != p for p in paths)
            or sum(p.stat().st_size for p in paths) > spec.max_bytes):
        raise ValueError('source path/file/byte budget')
    before = {str(p): digest(p.read_bytes()) for p in paths}
    output.mkdir(parents=True, exist_ok=False)
    save(output/'windows.json', windows)
    queries, results = [], []

    def query(c, sql, params=(), limit=None):
        if time.monotonic()-started > spec.total_seconds:
            raise TimeoutError('total budget')
        t = time.monotonic()
        timer = Timer(spec.query_seconds, c.interrupt)
        timer.daemon = True
        timer.start()
        try:
            cur = c.execute(sql, params)
            if limit is None:
                return None
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(limit+1)
            if len(rows) > limit:
                raise ValueError('result row budget')
            return [dict(zip(cols, r)) for r in rows]
        finally:
            timer.cancel()
            queries.append(dict(sql=sql, params=params, seconds=time.monotonic()-t))

    error = None
    try:
        with connection(paths, spec) as c:
            query(c, 'CREATE TEMP TABLE life AS SELECT * FROM read_parquet(?,hive_partitioning=false)', [str(life)])
            bad = query(c, """SELECT count(*)-count(DISTINCT ts_code) AS duplicates,
                count(*) FILTER(WHERE ts_code IS NULL OR list_date IS NULL OR
                    (exchange='SSE' AND NOT ends_with(ts_code,'.SH')) OR
                    (exchange='SZSE' AND NOT ends_with(ts_code,'.SZ'))) AS bad FROM life""", limit=1)[0]
            if any(bad.values()):
                raise ValueError(f'lifecycle: {bad}')
            for i in range(0, len(gold), spec.batch_files):
                verb = 'CREATE TEMP TABLE prices AS' if i == 0 else 'INSERT INTO prices'
                query(c, f"""{verb} SELECT ts_code,freq,trade_date,trade_time,open,high,low,close,vol,amount,exchange,
                    regexp_extract(filename,'ts_code=([^/]+)',1) AS path_code
                    FROM read_parquet(?,hive_partitioning=false,filename=true)
                    WHERE CAST(trade_date AS VARCHAR) IN (SELECT unnest(?))""",
                    [[str(p) for p in gold[i:i+spec.batch_files]], sorted(wanted)])
                print(f'G1 Gold files {min(i+spec.batch_files,len(gold))}/{len(gold)}', flush=True)
            bad = query(c, """SELECT count(*)-count(DISTINCT(ts_code,trade_time)) AS duplicates,
                count(*) FILTER(WHERE ts_code IS DISTINCT FROM path_code OR freq IS DISTINCT FROM 30
                    OR trade_date IS DISTINCT FROM CAST(trade_time AS DATE)
                    OR strftime(trade_time,'%H:%M:%S') NOT IN
                       ('10:00:00','10:30:00','11:00:00','11:30:00','13:30:00','14:00:00','14:30:00','15:00:00')
                    OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                    OR NOT isfinite(open) OR NOT isfinite(high) OR NOT isfinite(low) OR NOT isfinite(close)
                    OR low<=0 OR low>least(open,close) OR high<greatest(open,close)
                    OR vol IS NULL OR amount IS NULL OR NOT isfinite(vol) OR NOT isfinite(amount)
                    OR vol<0 OR amount<0) AS bad FROM prices""", limit=1)[0]
            if any(bad.values()):
                raise ValueError(f'Gold quality: {bad}')
            query(c, """CREATE TEMP TABLE daily AS SELECT ts_code,trade_date,count(*) AS bars,
                sum(amount) AS amount FROM prices GROUP BY ALL""")
            query(c, """CREATE TEMP TABLE suspended AS SELECT ts_code,trade_date,
                bool_or(suspend_type='S' AND coalesce(trim(suspend_timing),'')='')
                  AND NOT bool_or(suspend_type='R') AS full_day
                FROM read_parquet(?,hive_partitioning=false) GROUP BY ALL""", [[str(p) for p in suspension]])
            query(c, endpoint_source_sql(), [[str(p) for p in silver], [str(p) for p in factors]])
            for w in windows:
                query(c, 'CREATE OR REPLACE TEMP TABLE pool AS '+historical_pool_sql(), [w['signal_time'][:10]]*2)
                query(c, """CREATE OR REPLACE TEMP TABLE prior AS
                    SELECT p.ts_code,
                    count(*) FILTER(WHERE d.bars=8 OR (d.bars IS NULL AND s.full_day)) AS complete_days,
                    sum(CASE WHEN d.bars=8 THEN d.amount WHEN d.bars IS NULL AND s.full_day THEN 0 END)/?
                       AS prior_amount
                    FROM pool p CROSS JOIN (SELECT CAST(unnest(?) AS DATE) AS trade_date) cal
                    LEFT JOIN daily d USING(ts_code,trade_date)
                    LEFT JOIN suspended s USING(ts_code,trade_date)
                    WHERE cal.trade_date>=p.list_date GROUP BY p.ts_code""", [spec.lookback_days, w['prior_days']])
                query(c, """CREATE OR REPLACE TEMP TABLE candidates AS SELECT p.ts_code,p.name,p.exchange,
                    a.open AS entry_open,b.open AS exit_open,
                    b.open/a.open-1 AS gross_change,
                    CASE WHEN h.complete_days=? THEN h.prior_amount END AS prior_amount,
                    h.complete_days,
                    CASE WHEN a.ts_code IS NULL AND NOT coalesce(sa.full_day,false) THEN 'unexplained_entry_missing'
                         WHEN b.ts_code IS NULL AND NOT coalesce(sb.full_day,false) THEN 'unexplained_exit_missing'
                         WHEN a.ts_code IS NULL OR b.ts_code IS NULL THEN 'suspended_endpoint'
                         WHEN a.vol<=0 OR a.amount<=0 OR b.vol<=0 OR b.amount<=0 THEN 'zero_activity_endpoint'
                         WHEN x.adjusted IS NULL OR y.adjusted IS NULL OR x.multiplicity<>1 OR y.multiplicity<>1
                           OR NOT isfinite(x.adjusted) OR NOT isfinite(y.adjusted) OR x.adjusted<=0 OR y.adjusted<=0
                            THEN 'invalid_endpoint_source'
                         WHEN abs((b.open/a.open)/(y.adjusted/x.adjusted)-1)>? THEN 'inconsistent_adjustment_basis'
                         ELSE 'comparable' END AS eligibility
                    FROM pool p LEFT JOIN prices a ON p.ts_code=a.ts_code AND a.trade_time=CAST(? AS TIMESTAMP)
                    LEFT JOIN prices b ON p.ts_code=b.ts_code AND b.trade_time=CAST(? AS TIMESTAMP)
                    LEFT JOIN prior h ON p.ts_code=h.ts_code
                    LEFT JOIN suspended sa ON p.ts_code=sa.ts_code AND sa.trade_date=CAST(? AS DATE)
                    LEFT JOIN suspended sb ON p.ts_code=sb.ts_code AND sb.trade_date=CAST(? AS DATE)
                    LEFT JOIN endpoint_source x ON a.ts_code=x.ts_code AND a.trade_time=x.trade_time
                    LEFT JOIN endpoint_source y ON b.ts_code=y.ts_code AND b.trade_time=y.trade_time""",
                    [spec.lookback_days, spec.basis_tolerance, w['entry_bar_end'], w['exit_bar_end'],
                     w['entry_bar_end'][:10], w['exit_bar_end'][:10]])
                counts = query(c, 'SELECT eligibility,count(*) AS n FROM candidates GROUP BY ALL ORDER BY ALL', limit=20)
                excluded = query(c, "SELECT * FROM candidates WHERE eligibility<>'comparable' ORDER BY ts_code", limit=spec.max_stocks)
                count_pool = query(c, 'SELECT count(*) AS n FROM pool', limit=1)[0]['n']
                if count_pool > spec.max_stocks or sum(r['n'] for r in counts) != count_pool:
                    raise ValueError('pool/join count mismatch')
                window_dir = output/w['window_id']
                window_dir.mkdir()
                save(window_dir/'exclusions.json', excluded)
                blocked = any(r['eligibility'] not in ('comparable','suspended_endpoint','zero_activity_endpoint') for r in counts)
                summary = dict(window_id=w['window_id'], pool=count_pool, counts=counts, blocked=blocked)
                if not blocked:
                    ranking = query(c, """SELECT row_number() OVER(ORDER BY gross_change DESC,ts_code) AS rank,
                        ts_code,name,exchange,entry_open,exit_open,gross_change,prior_amount,complete_days
                        FROM candidates WHERE eligibility='comparable' ORDER BY rank""", limit=spec.max_stocks)
                    pairs = match_controls(ranking, spec.top_n)
                    save(window_dir/'ranking.json', ranking)
                    save(window_dir/'top50.json', ranking[:spec.top_n])
                    save(window_dir/'pairs.json', pairs)
                    summary.update(ranked=len(ranking), paired=sum(p['control'] is not None for p in pairs))
                results.append(summary)
                print('G1', summary, flush=True)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    unchanged = before == {str(p): digest(p.read_bytes()) for p in paths}
    save(output/'queries.json', queries)
    save(output/'summary.json', dict(windows=results, error=error, source_unchanged=unchanged))
    save(output/'source_hashes.json', before)
    artifacts = {str(p.relative_to(output)): digest(p.read_bytes()) for p in output.rglob('*.json')}
    complete = error is None and unchanged and len(results)==len(windows) and not any(r['blocked'] for r in results)
    manifest = dict(status='rank_complete' if complete else 'blocked_data_quality', spec=asdict(spec),
        created_at_utc=datetime.now(timezone.utc).isoformat(), seconds=time.monotonic()-started,
        files=len(paths), bytes=sum(p.stat().st_size for p in paths), source_audit=source_audit,
        plan_sha256=digest(PLAN.read_bytes()), code_sha256=digest(Path(__file__).read_bytes()),
        artifacts_sha256=artifacts, stock_replay_executed=False)
    save(output/'manifest.json', manifest)
    return dict(status=manifest['status'], seconds=manifest['seconds'], windows=results, error=error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
