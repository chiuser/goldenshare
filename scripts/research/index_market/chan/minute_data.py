"""Frozen five-year minute experiment; bounded Gold reads, no Lake writes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import threading
import time

import duckdb

from scripts.research.index_market.chan.m0_data import LAKE, SPEC, file_facts


@dataclass(frozen=True)
class MinuteSpec:
    codes: tuple[str, ...] = SPEC.codes
    frequencies: tuple[int, ...] = (30, 60)
    start: str = '2021-09-09'
    end: str = '2026-09-08'
    evaluation_start: str = '2022-01-01'
    commit: str = SPEC.commit
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20)
    cooldown_days: int = 20
    blocks: tuple[int, ...] = (60, 20, 120)
    repetitions: int = 10000
    seed: int = 20260909
    main_comparisons: int = 12
    min_events: int = 50
    min_years: int = 5
    max_files: int = 2600
    max_bytes: int = 32 * 1024**2
    max_rows: int = 50000
    max_calendar_rows: int = 2000
    max_bars: int = 10000
    max_points: int = 5000
    max_events: int = 10000
    max_changes: int = 100000
    query_seconds: int = 60
    replay_seconds: int = 180
    total_seconds: int = 600
    max_output_bytes: int = 128 * 1024**2
    reserve_bytes: int = 256 * 1024**2

    def chan_config(self):
        return SPEC.chan_config()


MINUTE = MinuteSpec()


def slots(frequency):
    if frequency == 30:
        return ('10:00:00', '10:30:00', '11:00:00', '11:30:00',
                '13:30:00', '14:00:00', '14:30:00', '15:00:00')
    if frequency == 60:
        return ('10:30:00', '11:30:00', '14:00:00', '15:00:00')
    raise ValueError('unapproved frequency')


def discover(spec=MINUTE, lake=LAKE):
    paths = []
    for freq in spec.frequencies:
        root = lake / f'gold/quote/major_index_mins/freq={freq}'
        paths.extend(sorted(p / 'part-000.parquet' for p in root.iterdir()
                            if f'trade_date={spec.start}' <= p.name <= f'trade_date={spec.end}'))
    calendar = lake / 'silver/calendar/trade_calendar/full/part-000.parquet'
    all_paths = paths + [calendar]
    if not paths or len(all_paths) > spec.max_files:
        raise ValueError('file budget or empty source')
    if any(p.resolve() != p or not p.is_file() for p in all_paths):
        raise ValueError('missing or redirected source')
    facts = file_facts(all_paths)
    if sum(p['bytes'] for p in facts) > spec.max_bytes:
        raise ValueError('input byte budget')
    return paths, calendar, facts


def validate(con, spec=MINUTE):
    """Set-based exact grid audit, independent of formal Dagster checks."""
    count = con.execute('SELECT count(*) FROM prices').fetchone()[0]
    cal = con.execute('SELECT CAST(trade_date AS VARCHAR), is_open FROM calendar ORDER BY trade_date').fetchmany(spec.max_calendar_rows+1)
    begin, end = date.fromisoformat(spec.start), date.fromisoformat(spec.end)
    natural = [(begin+timedelta(days=i)).isoformat() for i in range((end-begin).days+1)]
    if [r[0] for r in cal] != natural or any(type(r[1]) is not bool for r in cal):
        raise ValueError('calendar missing, duplicated or invalid')
    if not 0 < count <= spec.max_rows or len(cal) > spec.max_calendar_rows:
        raise ValueError('row budget')
    con.execute('CREATE TEMP TABLE grid(freq INTEGER, slot VARCHAR)')
    # Tiny constant relation: twelve allowed session slots, not per-price inserts.
    con.execute('INSERT INTO grid SELECT unnest(?), unnest(?)',
                [[f for f in spec.frequencies for _ in slots(f)],
                 [s for f in spec.frequencies for s in slots(f)]])
    con.execute('''CREATE TEMP TABLE expected AS SELECT code AS ts_code, freq,
        CAST(CAST(trade_date AS VARCHAR)||' '||slot AS TIMESTAMP) AS trade_time
        FROM calendar CROSS JOIN grid CROSS JOIN (SELECT unnest(?) AS code)
        WHERE is_open''', [list(spec.codes)])
    issues = {}
    issues['missing'] = con.execute('SELECT count(*) FROM expected ANTI JOIN prices USING(ts_code,freq,trade_time)').fetchone()[0]
    issues['unexpected'] = con.execute('SELECT count(*) FROM prices ANTI JOIN expected USING(ts_code,freq,trade_time)').fetchone()[0]
    issues['duplicates'] = con.execute('SELECT count(*)-count(DISTINCT (ts_code,freq,trade_time)) FROM prices').fetchone()[0]
    issues['identity'] = con.execute('''SELECT count(*) FROM prices WHERE
        trade_date IS NULL OR trade_date != CAST(trade_time AS DATE)
        OR CAST(trade_date AS VARCHAR) != partition_date OR freq != partition_freq
        OR exchange IS NULL OR exchange NOT IN ('SSE','XSHG')''').fetchone()[0]
    invalid = ' OR '.join(f'{k} IS NULL OR NOT isfinite({k}) OR {k} {"<=" if k in ("open","high","low","close") else "<"} 0'
                          for k in ('open','high','low','close','vol','amount'))
    issues['values'] = con.execute(f'''SELECT count(*) FROM prices WHERE {invalid}
        OR low>high OR open<low OR open>high OR close<low OR close>high''').fetchone()[0]
    if any(issues.values()):
        raise ValueError(f'minute quality failed: {issues}')
    return dict(rows=count, natural_days=len(cal), open_days=sum(r[1] for r in cal),
                issues=issues, formal_dagster_checks_executed=False,
                historical_revisions_available=False), [d for d, o in cal if o]


def load_input(spec=MINUTE, lake=LAKE):
    paths, calendar, before = discover(spec, lake)
    started = time.monotonic()
    with duckdb.connect(':memory:', config={'threads':4, 'memory_limit':'1GiB',
            'max_temp_directory_size':'0B', 'allow_persistent_secrets':False,
            'autoinstall_known_extensions':False, 'autoload_known_extensions':False}) as con:
        con.execute('SET allowed_paths = ?', [[x['path'] for x in before]])
        con.execute('SET enable_external_access=false')
        con.execute('SET lock_configuration=true')
        timer = threading.Timer(spec.query_seconds, con.interrupt)
        timer.daemon = True
        timer.start()
        try:
            con.execute('''CREATE TEMP TABLE prices AS SELECT ts_code, freq, trade_date,
                trade_time, open, high, low, close, vol, amount, exchange,
                regexp_extract(filename,'trade_date=([0-9-]+)',1) AS partition_date,
                CAST(regexp_extract(filename,'/freq=([0-9]+)/',1) AS INTEGER) AS partition_freq
                FROM read_parquet(?, hive_partitioning=false, filename=true)
                WHERE ts_code IN (SELECT unnest(?))''', [[str(p) for p in paths], list(spec.codes)])
            con.execute('''CREATE TEMP TABLE calendar AS SELECT trade_date,is_open
                FROM read_parquet(?,hive_partitioning=false) WHERE exchange='SSE'
                AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)''',
                        [str(calendar), spec.start, spec.end])
            schema = dict((r[0],r[1]) for r in con.execute('DESCRIBE prices').fetchmany(20))
            if schema.get('trade_date') != 'DATE' or schema.get('trade_time') != 'TIMESTAMP':
                raise ValueError('Gold timestamp/date schema drift')
            quality, days = validate(con, spec)
            names = ('code','frequency','date','time','open','high','low','close','vol','amount')
            rows = [dict(zip(names, r)) for r in con.execute('''SELECT ts_code,freq,
                CAST(trade_date AS VARCHAR),CAST(trade_time AS VARCHAR),open,high,low,close,vol,amount
                FROM prices ORDER BY ts_code,freq,trade_time''').fetchmany(spec.max_rows+1)]
        finally:
            timer.cancel()
    if file_facts([Path(x['path']) for x in before]) != before:
        raise ValueError('source changed during read')
    quality.update(seconds=time.monotonic()-started, files=len(before),
                   bytes=sum(x['bytes'] for x in before), schema=schema)
    return rows, days, before, quality
