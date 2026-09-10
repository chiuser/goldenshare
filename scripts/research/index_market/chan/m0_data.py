"""Frozen M0 scope and bounded, read-only Lake input. No signal scoring."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import hashlib
import time

import duckdb

REPO = Path(__file__).resolve().parents[4]
LAKE = Path('/Volumes/datasource/data_lake')


@dataclass(frozen=True)
class M0Spec:
    codes: tuple[str, ...] = ('000001.SH', '000300.SH', '000905.SH')
    replay_code: str = '000300.SH'
    start: str = '2010-01-04'
    end: str = '2026-09-07'
    evaluation_start: str = '2011-01-01'
    frequency: str = 'K_DAY'
    commit: str = '429d6ed3043e27c93a003ba2b10e70a05575e1f5'
    prefix_dates: tuple[str, ...] = (
        '2011-12-30', '2015-12-31', '2020-12-31', '2025-12-31', '2026-09-07')
    max_files: int = 4501
    max_bytes: int = 256 * 1024**2
    max_rows: int = 15000
    max_calendar_rows: int = 6500
    max_bars: int = 4500
    max_points: int = 2000
    max_events: int = 20000
    max_changes: int = 100000
    query_seconds: int = 60
    replay_seconds: int = 180
    total_seconds: int = 600
    max_output_bytes: int = 64 * 1024**2
    reserve_bytes: int = 128 * 1024**2

    def __post_init__(self):
        if not (self.start < self.evaluation_start <= self.end):
            raise ValueError('initialization/evaluation window invalid')
        if self.replay_code not in self.codes or len(set(self.codes)) != len(self.codes):
            raise ValueError('code scope invalid')

    def chan_config(self):
        return dict(trigger_step=True, bi_algo='normal', bi_strict=True,
                    bi_fx_check='strict', gap_as_kl=False, bi_end_is_peak=True,
                    bi_allow_sub_peak=True, seg_algo='chan', left_seg_method='peak',
                    zs_algo='normal', zs_combine=True, zs_combine_mode='zs',
                    one_bi_zs=False, divergence_rate=1.0, macd_algo='peak',
                    max_bs2_rate=0.9999)


SPEC = M0Spec()


def safe_output(path: Path) -> Path:
    path = path.resolve()
    parent = (REPO / 'reports').resolve()
    if path == parent or not path.is_relative_to(parent) or path.exists():
        raise ValueError('output must be a new child of repository reports')
    return path


def file_facts(paths):
    return [dict(path=str(p), bytes=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns)
            for p in paths]


def discover(spec=SPEC):
    daily = LAKE / 'silver/index_daily'
    paths = sorted(p / 'part-000.parquet' for p in daily.iterdir()
                   if p.is_dir() and f'trade_date={spec.start}' <= p.name <= f'trade_date={spec.end}')
    calendar = LAKE / 'silver/calendar/trade_calendar/full/part-000.parquet'
    all_paths = paths + [calendar]
    if not paths or len(all_paths) > spec.max_files:
        raise ValueError('source file count budget')
    if any(p.resolve() != p or not p.is_file() for p in all_paths):
        raise ValueError('missing or redirected source file')
    facts = file_facts(all_paths)
    if sum(p['bytes'] for p in facts) > spec.max_bytes:
        raise ValueError('source byte budget')
    return paths, calendar, facts


def validate(rows, calendar, spec=SPEC):
    """Validate only research OHLC/date scope, not formal Dagster readiness."""
    import math

    if not rows or len(rows) > spec.max_rows or len(calendar) > spec.max_calendar_rows:
        raise ValueError('input row budget or empty input')
    start, end = date.fromisoformat(spec.start), date.fromisoformat(spec.end)
    expected_days = {(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)}
    cal_dates = [r['date'] for r in calendar]
    if len(set(cal_dates)) != len(cal_dates) or set(cal_dates) != expected_days:
        raise ValueError('calendar missing, duplicate or out-of-window natural day')
    if any(type(r['is_open']) is not bool for r in calendar):
        raise ValueError('invalid calendar open flag')
    expected = {r['date'] for r in calendar if r['is_open']}
    seen = set()
    by_code = {c: set() for c in spec.codes}
    for r in rows:
        c, d = r['ts_code'], r['date']
        if c not in by_code or d not in expected or d != r['partition_date']:
            raise ValueError('code/date/partition scope mismatch')
        if (c, d) in seen:
            raise ValueError('duplicate index/date')
        seen.add((c, d))
        by_code[c].add(d)
        prices = [r[k] for k in ('open', 'high', 'low', 'close')]
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in prices):
            raise ValueError('invalid OHLC value')
        if not r['low'] <= min(r['open'], r['close']) <= max(r['open'], r['close']) <= r['high']:
            raise ValueError('invalid OHLC ordering')
    for c, days in by_code.items():
        if days != expected:
            raise ValueError(f'calendar coverage mismatch {c}: missing={sorted(expected-days)[:5]}')
    return dict(open_days=len(expected), natural_days=len(calendar), rows=len(rows),
                rows_by_code={c: len(d) for c, d in by_code.items()},
                missing=0, duplicates=0, invalid_ohlc=0, partition_mismatch=0,
                formal_dagster_checks_executed=False, historical_revisions_available=False)


def load_input(spec=SPEC):
    import threading

    paths, calendar_path, before = discover(spec)
    start = time.monotonic()
    with duckdb.connect(':memory:', config={
        'threads': 4, 'memory_limit': '1GiB', 'max_temp_directory_size': '0B',
        'allow_persistent_secrets': False, 'autoinstall_known_extensions': False,
        'autoload_known_extensions': False,
    }) as con:
        con.execute('SET allowed_paths = ?', [[p['path'] for p in before]])
        con.execute('SET enable_external_access = false')
        con.execute('SET lock_configuration = true')
        timer = threading.Timer(spec.query_seconds, con.interrupt)
        timer.daemon = True
        timer.start()
        try:
            con.execute('''CREATE TEMP TABLE prices AS
                SELECT ts_code, trade_date, open, high, low, close,
                       regexp_extract(filename, 'trade_date=([0-9-]+)', 1) AS partition_date
                FROM read_parquet(?, hive_partitioning=false, filename=true)
                WHERE ts_code IN (SELECT unnest(?))''', [[str(p) for p in paths], list(spec.codes)])
            con.execute('''CREATE TEMP TABLE calendar AS
                SELECT trade_date, is_open FROM read_parquet(?, hive_partitioning=false)
                WHERE exchange='SSE' AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)''',
                        [str(calendar_path), spec.start, spec.end])
            if con.execute('SELECT count(*) FROM prices').fetchone()[0] > spec.max_rows:
                raise ValueError('filtered price row budget')
            if con.execute('SELECT count(*) FROM calendar').fetchone()[0] > spec.max_calendar_rows:
                raise ValueError('calendar row budget')
            schema = con.execute('DESCRIBE prices').fetchall()
            cal_schema = con.execute('DESCRIBE calendar').fetchall()
            if dict((r[0], r[1]) for r in schema).get('trade_date') != 'DATE':
                raise ValueError('Silver price date must be DATE')
            if dict((r[0], r[1]) for r in cal_schema) != {'trade_date': 'DATE', 'is_open': 'BOOLEAN'}:
                raise ValueError('Silver calendar schema changed')
            names = ('ts_code', 'date', 'open', 'high', 'low', 'close', 'partition_date')
            rows = [dict(zip(names, r)) for r in con.execute('''
                SELECT ts_code, CAST(trade_date AS VARCHAR), open, high, low, close, partition_date
                FROM prices ORDER BY ts_code, trade_date''').fetchall()]
            calendar = [dict(date=d, is_open=o) for d, o in con.execute('''
                SELECT CAST(trade_date AS VARCHAR), is_open FROM calendar ORDER BY trade_date''').fetchall()]
        finally:
            timer.cancel()
            timer.join()
    if time.monotonic()-start > spec.query_seconds:
        raise TimeoutError('input read time budget')
    quality = validate(rows, calendar, spec)
    if file_facts(paths + [calendar_path]) != before:
        raise ValueError('source changed during read')
    quality.update(file_count=len(before), source_bytes=sum(f['bytes'] for f in before),
                   read_seconds=time.monotonic()-start, price_schema=schema, calendar_schema=cal_schema,
                   parquet_scan_queries=2)
    return rows, calendar, before, quality


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
