"""Bounded, read-only G2a input gates; not a general stock-history loader."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from threading import Timer
import time

from scripts.research.index_market.chan.m0_data import digest
from scripts.research.index_market.chan.minute_data import slots
from scripts.research.index_market.chan.stock_chan_rank import LAKE, connection


@dataclass(frozen=True)
class StockReplaySpec:
    variant: str = 'stock-chan-G2a-fixed-pilot'
    rank_report: str = 'reports/stock_chan_shsz_r1_surviving_20260912'
    rank_manifest: str = 'fed8bd835ddbe8fa4955b9c62f90b9d33a9c01fbfdf939067d12eaf0fe4fef31'
    a_report: str = 'reports/chan_minute_variant_a_20260909'
    a_manifest: str = '631e7cecffc4df6bf7784d11b81c5a13c4dc0af114e042d83500f9a0cd7ef089'
    pilot_selection: str = 'minimum_code_across_actual_G1_seats'
    start: str = '2021-09-09'
    end: str = '2026-09-08'
    universe_asof: str = '2026-09-12'
    frequency: int = 30
    calendar_exchange: str = 'SSE'
    history_days: int = 250
    max_seats: int = 300
    max_stocks: int = 300
    max_files: int = 2000
    max_bytes: int = 2 * 1024**3
    max_bars: int = 10000
    query_seconds: int = 60
    pilot_seconds: int = 180
    total_seconds: int = 1800
    max_output_bytes: int = 128 * 1024**2
    memory: str = '1GiB'
    threads: int = 4
    basis_tolerance: float = 1e-8


SPEC = StockReplaySpec()


class Reader:
    def __init__(self, spec=SPEC):
        self.spec, self.hashes, self.queries = spec, {}, []
        self.started = time.monotonic()

    def check_time(self):
        if time.monotonic() - self.started > self.spec.pilot_seconds:
            raise TimeoutError('pilot total time budget')

    def read(self, paths, sql, parameters, limit):
        self.check_time()
        paths = [Path(p) for p in paths]
        union = set(paths) | {Path(p) for p in self.hashes}
        if (len(union) > self.spec.max_files or any(
                not p.is_file() or p.resolve() != p or not p.is_relative_to(LAKE) for p in union)
                or sum(p.stat().st_size for p in union) > self.spec.max_bytes):
            raise ValueError('Lake path/file/byte budget')
        for p in paths:
            if str(p) not in self.hashes:
                self.hashes[str(p)] = digest(p.read_bytes())
        started = time.monotonic()
        with connection(paths, self.spec) as c:
            timer = Timer(min(self.spec.query_seconds,
                              self.spec.pilot_seconds - (started - self.started)), c.interrupt)
            timer.start()
            try:
                cursor = c.execute(sql, parameters)
                names = [col[0] for col in cursor.description]
                rows = cursor.fetchmany(limit + 1)
            finally:
                timer.cancel()
        self.queries.append(dict(sql=sql, parameters=parameters, row_count=len(rows),
                                 seconds=time.monotonic()-started))
        if len(rows) > limit:
            raise ValueError('query return row budget')
        self.check_time()
        return [dict(zip(names, row)) for row in rows]

    def verify_unchanged(self):
        changed = [p for p, expected in self.hashes.items() if digest(Path(p).read_bytes()) != expected]
        if changed:
            raise ValueError(f'input changed during replay: {changed}')
        return dict(files=len(self.hashes), bytes=sum(Path(p).stat().st_size for p in self.hashes),
                    source_hashes_unchanged=True)


def gold_paths(code, end, spec=SPEC):
    return sorted(p for year in range(int(spec.start[:4]), int(end[:4])+1)
                  for p in (LAKE/f'gold/quote/stk_mins_qfq/freq=30/ts_code={code}/year={year}').glob('part-000.parquet'))


def validate_lifecycle(seats, life, spec=SPEC):
    codes = {s['code'] for s in seats}
    by_code = {r['ts_code']: r for r in life}
    if len(by_code) != len(life) or set(by_code) != codes:
        raise ValueError('lifecycle identities missing or duplicated')
    for s in seats:
        r = by_code[s['code']]
        exchange = r['exchange']
        suffix = {'SSE': '.SH', 'SZSE': '.SZ'}.get(exchange)
        if (not r['is_cny_stock'] or suffix is None or not s['code'].endswith(suffix)
                or not r['list_date'] or r['list_date'] > s['window_id']
                or (r['delist_date'] and r['delist_date'] <= max(spec.universe_asof, s['window_id']))):
            raise ValueError('out-of-scope or delisted stock')
    return by_code


def validate_rows(rows, days, code, listed, end, observation_start, spec=SPEC):
    if not 0 < len(rows) <= spec.max_bars or days != sorted(set(days)):
        raise ValueError('input/calendar budget or order')
    times = [r['time'] for r in rows]
    if times != sorted(set(times)):
        raise ValueError('duplicate or unsorted bars')
    expected = {f'{day} {slot}' for day in days for slot in slots(spec.frequency)
                if day >= max(spec.start, listed) and f'{day} {slot}' <= end}
    missing, extra = sorted(expected - set(times)), sorted(set(times) - expected)
    if missing or extra:
        raise ValueError(f'unreconciled minute grid: missing={len(missing)} extra={len(extra)} '
                         f'samples={missing[:8]}/{extra[:8]}; suspension audit required, no fill')
    for r in rows:
        values = [r[k] for k in ('open', 'high', 'low', 'close', 'vol', 'amount')]
        if (r['code'] != code or r['frequency'] != spec.frequency or r['date'] != r['time'][:10]
                or r['exchange'] != (('SSE' if code.endswith('.SH') else 'SZSE'))
                or not all(v is not None and math.isfinite(v) for v in values)
                or not 0 < r['low'] <= min(r['open'], r['close'])
                or not max(r['open'], r['close']) <= r['high']
                or r['vol'] <= 0 or r['amount'] <= 0):
            raise ValueError('invalid price/volume/identity; zero-trade bars require separate audit')
    history = len({r['date'] for r in rows if r['date'] < observation_start})
    if history < spec.history_days:
        raise ValueError(f'insufficient structure history: {history} < {spec.history_days}')
    return dict(bars=len(rows), trading_days=len({r['date'] for r in rows}),
                history_days_before_observation=history, missing_bars=0, unexpected_bars=0,
                first_bar=times[0], last_bar=times[-1])


def validate_basis(anchors, raw, spec=SPEC):
    if len(raw) != len(anchors) or {r['time'] for r in raw} != set(anchors):
        raise ValueError('missing or duplicate source anchors')
    bases = []
    for r in raw:
        values = [r['raw_close'], r['adj_factor'], anchors[r['time']]]
        if not all(v is not None and math.isfinite(v) and v > 0 for v in values):
            raise ValueError('invalid source basis')
        bases.append(dict(**r, gold_close=anchors[r['time']],
                          implied_base=r['raw_close']*r['adj_factor']/anchors[r['time']]))
    if not bases or any(not math.isclose(r['implied_base'], bases[0]['implied_base'],
                       rel_tol=spec.basis_tolerance, abs_tol=0) for r in bases):
        raise ValueError('inconsistent cross-year price basis')
    return dict(method='first_and_last_bar_of_each_year_close_vs_Silver5_times_adj_factor',
                scope='sampled_cross_year_anchors_not_all_bar_derivation', anchors=bases)


def load_pilot(reader, seats, code, window):
    spec = reader.spec
    life_path = LAKE/'silver/basic/stock_lifecycle/full/part-000.parquet'
    calendar = LAKE/'silver/calendar/trade_calendar/full/part-000.parquet'
    life = reader.read([life_path], """SELECT ts_code,name,exchange,is_cny_stock,
        CAST(list_date AS VARCHAR) list_date,CAST(delist_date AS VARCHAR) delist_date
        FROM read_parquet(?,hive_partitioning=false) WHERE ts_code IN (SELECT unnest(?))""",
        [str(life_path), sorted({s['code'] for s in seats})], spec.max_stocks)
    identities = validate_lifecycle(seats, life, spec)
    cal = reader.read([calendar], """SELECT exchange,CAST(trade_date AS VARCHAR) AS calendar_day
        FROM read_parquet(?,hive_partitioning=false) WHERE exchange=? AND is_open
        AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) ORDER BY exchange,trade_date""",
        [str(calendar), spec.calendar_exchange, spec.start, window['exit_bar_end'][:10]], 2000)
    days = [r['calendar_day'] for r in cal]
    if not days:
        raise ValueError('empty canonical trading calendar')
    paths = gold_paths(code, window['exit_bar_end'], spec)
    rows = reader.read(paths, """SELECT ts_code code,freq frequency,exchange,
        CAST(trade_date AS VARCHAR) AS date,CAST(trade_time AS VARCHAR) AS time,
        open,high,low,close,vol,amount FROM read_parquet(?,hive_partitioning=false)
        WHERE trade_time BETWEEN CAST(? AS TIMESTAMP) AND CAST(? AS TIMESTAMP) ORDER BY trade_time""",
        [[str(p) for p in paths], spec.start, window['exit_bar_end']], spec.max_bars)
    quality = validate_rows(rows, days, code, identities[code]['list_date'],
                            window['exit_bar_end'], window['prior_days'][0], spec)
    anchors = {}
    for year in sorted({r['date'][:4] for r in rows}):
        batch = [r for r in rows if r['date'].startswith(year)]
        for r in (batch[0], batch[-1]):
            anchors[r['time']] = r['close']
    dates = sorted({t[:10] for t in anchors})
    silver = [LAKE/f'silver/quote/stk_mins/freq=5/trade_date={d}/part-000.parquet' for d in dates]
    factors = [LAKE/f'silver/quote/adj_factor/trade_date={d}/part-000.parquet' for d in dates]
    raw = reader.read(silver+factors, """SELECT CAST(s.trade_time AS VARCHAR) AS time,
        CAST(s.close AS DOUBLE) AS raw_close,CAST(f.adj_factor AS DOUBLE) AS adj_factor
        FROM read_parquet(?,hive_partitioning=false) s
        JOIN read_parquet(?,hive_partitioning=false) f USING(ts_code,trade_date)
        WHERE s.ts_code=? AND s.freq=5 AND s.trade_time IN (SELECT CAST(unnest(?) AS TIMESTAMP))
        ORDER BY s.trade_time""",
        [[str(p) for p in silver], [str(p) for p in factors], code, sorted(anchors)], len(anchors))
    return rows, days, life, quality, validate_basis(anchors, raw, spec)
