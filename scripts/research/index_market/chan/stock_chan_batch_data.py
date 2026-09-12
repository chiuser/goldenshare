"""G2b set-based preflight and final-Silver suspension classification."""
from __future__ import annotations

from dataclasses import dataclass

from scripts.research.index_market.chan.minute_data import slots
from scripts.research.index_market.chan.stock_chan_rank import LAKE
from scripts.research.index_market.chan.stock_chan_replay_data import (
    StockReplaySpec, gold_paths, validate_basis, validate_lifecycle, validate_rows,
)


@dataclass(frozen=True)
class StockBatchSpec(StockReplaySpec):
    variant: str = 'stock-chan-G2b-first-batch'
    batch_size: int = 10
    batch_index: int = 0
    pilot_report: str = 'reports/stock_chan_g2a_replay_20260912'
    pilot_manifest: str = 'ac7758b69090b47ae4663a1d5a1d963370975632803e904004ac2997a8f67f64'
    max_batch_rows: int = 100000
    max_aggregate_rows: int = 10000


SPEC = StockBatchSpec()


def select_batch(seats, codes, spec=SPEC):
    selected = codes[:spec.batch_size]
    return selected, sorted((s for s in seats if s['code'] in selected),
                            key=lambda s: (s['code'], s['window_id']))


def classify_gaps(gaps, suspension, code):
    """Only a missing whole day explained by final S/no timing/no R is excused."""
    facts = {}
    for row in suspension:
        if row['ts_code'] == code:
            facts.setdefault(row['trade_date'], []).append(row)
    classified = []
    for gap in gaps:
        if gap['code'] != code:
            continue
        rows = facts.get(gap['trade_date'], [])
        full = (any(r['suspend_type'] == 'S' and not (r['suspend_timing'] or '').strip() for r in rows)
                and not any(r['suspend_type'] == 'R' for r in rows))
        reason = ('confirmed_full_day_suspension' if full and gap['missing_bars'] == 8
                  else 'partial_missing_bars' if gap['missing_bars'] != 8
                  else 'no_final_suspension_fact' if not rows else 'non_full_day_or_conflicting_suspension')
        classified.append(dict(**gap, reason=reason, final_facts=rows))
    return classified


def load_batch(reader, windows, seats, codes, spec=SPEC):
    by_window = {w['window_id']: w for w in windows}
    ends = {c: max(by_window[s['window_id']]['exit_bar_end'] for s in seats if s['code'] == c) for c in codes}
    paths = sorted({p for c in codes for p in gold_paths(c, ends[c], spec)})
    life_path = LAKE/'silver/basic/stock_lifecycle/full/part-000.parquet'
    calendar_path = LAKE/'silver/calendar/trade_calendar/full/part-000.parquet'
    life = reader.read([life_path], """SELECT ts_code,name,exchange,is_cny_stock,
        CAST(list_date AS VARCHAR) AS list_date,CAST(delist_date AS VARCHAR) AS delist_date
        FROM read_parquet(?,hive_partitioning=false) WHERE ts_code IN (SELECT unnest(?))""",
        [str(life_path), codes], spec.max_stocks)
    identities = validate_lifecycle(seats, life, spec)
    calendar = reader.read([calendar_path], """SELECT CAST(trade_date AS VARCHAR) AS trade_date
        FROM read_parquet(?,hive_partitioning=false) WHERE exchange=? AND is_open
        AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) ORDER BY trade_date""",
        [str(calendar_path), spec.calendar_exchange, spec.start, spec.end], 2000)
    days = [r['trade_date'] for r in calendar]
    if not days or days != sorted(set(days)):
        raise ValueError('invalid canonical calendar')
    profile = reader.read(paths, """WITH limits AS (
        SELECT unnest(?) AS code,CAST(unnest(?) AS TIMESTAMP) AS until)
        SELECT p.ts_code,year(p.trade_time) AS year,count(*) AS bars,
          CAST(min(p.trade_time) AS VARCHAR) AS first_bar,CAST(max(p.trade_time) AS VARCHAR) AS last_bar
        FROM read_parquet(?,hive_partitioning=false) p JOIN limits l ON p.ts_code=l.code
        WHERE p.trade_time BETWEEN CAST(? AS TIMESTAMP) AND l.until GROUP BY ALL ORDER BY 1,2""",
        [codes, [ends[c] for c in codes], [str(p) for p in paths], spec.start], 2000)
    gaps = reader.read(paths+[calendar_path, life_path], """WITH limits AS (
        SELECT unnest(?) AS code,CAST(unnest(?) AS TIMESTAMP) AS until),
        days AS (SELECT trade_date FROM read_parquet(?,hive_partitioning=false)
          WHERE exchange=? AND is_open AND trade_date>=CAST(? AS DATE)),
        grid AS (SELECT code,CAST(CAST(d.trade_date AS VARCHAR)||' '||s.slot AS TIMESTAMP) AS t
          FROM limits l JOIN read_parquet(?,hive_partitioning=false) i ON i.ts_code=l.code
          CROSS JOIN days d CROSS JOIN (SELECT unnest(?) AS slot) s
          WHERE d.trade_date>=i.list_date AND t<=l.until),
        prices AS (SELECT ts_code,trade_time FROM read_parquet(?,hive_partitioning=false))
        SELECT code,CAST(CAST(t AS DATE) AS VARCHAR) AS trade_date,count(*) AS missing_bars
        FROM grid g ANTI JOIN prices p ON g.code=p.ts_code AND g.t=p.trade_time
        GROUP BY ALL ORDER BY 1,2""",
        [codes, [ends[c] for c in codes], str(calendar_path), spec.calendar_exchange,
         spec.start, str(life_path), list(slots(spec.frequency)), [str(p) for p in paths]], spec.max_aggregate_rows)
    selected, batch_seats = select_batch(seats, codes, spec)
    batch_paths = sorted({p for c in selected for p in gold_paths(c, ends[c], spec)})
    prices = reader.read(batch_paths, """WITH limits AS (
        SELECT unnest(?) AS code,CAST(unnest(?) AS TIMESTAMP) AS until)
        SELECT p.ts_code AS code,p.freq AS frequency,p.exchange,
        CAST(p.trade_date AS VARCHAR) AS date,CAST(p.trade_time AS VARCHAR) AS time,
        p.open,p.high,p.low,p.close,p.vol,p.amount,
        regexp_extract(filename,'ts_code=([^/]+)',1) AS path_code
        FROM read_parquet(?,hive_partitioning=false,filename=true) p
        JOIN limits l ON regexp_extract(filename,'ts_code=([^/]+)',1)=l.code
        WHERE p.trade_time BETWEEN CAST(? AS TIMESTAMP) AND l.until ORDER BY code,time""",
        [selected, [ends[c] for c in selected], [str(p) for p in batch_paths], spec.start], spec.max_batch_rows)
    if any(r['path_code'] != r['code'] for r in prices):
        raise ValueError('Gold file/row identity mismatch')
    batch_gaps = [g for g in gaps if g['code'] in selected]
    suspend_paths = [LAKE/f'silver/quote/stock_suspend_daily/trade_date={d}/part-000.parquet'
                     for d in sorted({g['trade_date'] for g in batch_gaps})]
    suspension = reader.read(suspend_paths, """SELECT ts_code,CAST(trade_date AS VARCHAR) AS trade_date,
        suspend_type,suspend_timing FROM read_parquet(?,hive_partitioning=false)
        WHERE ts_code IN (SELECT unnest(?)) ORDER BY 1,2""",
        [[str(p) for p in suspend_paths], selected], spec.max_aggregate_rows) if suspend_paths else []
    # Each seat needs its own endpoint anchor, including repeated stocks' earlier windows.
    anchor_keys = set()
    for seat in batch_seats:
        end = by_window[seat['window_id']]['exit_bar_end']
        seq = [r for r in prices if r['code'] == seat['code'] and r['time'] <= end]
        for yr in sorted({r['date'][:4] for r in seq}):
            chunk = [r for r in seq if r['date'].startswith(yr)]
            anchor_keys.update((seat['code'], r['time']) for r in (chunk[0], chunk[-1]))
    anchor_dates = sorted({t[:10] for _, t in anchor_keys})
    silver = [LAKE/f'silver/quote/stk_mins/freq=5/trade_date={d}/part-000.parquet' for d in anchor_dates]
    factors = [LAKE/f'silver/quote/adj_factor/trade_date={d}/part-000.parquet' for d in anchor_dates]
    anchors = reader.read(silver+factors, """WITH targets AS (
        SELECT unnest(?) AS code,CAST(unnest(?) AS TIMESTAMP) AS t)
        SELECT s.ts_code AS code,CAST(s.trade_time AS VARCHAR) AS time,
          CAST(s.close AS DOUBLE) AS raw_close,CAST(f.adj_factor AS DOUBLE) AS adj_factor
        FROM read_parquet(?,hive_partitioning=false) s
        JOIN read_parquet(?,hive_partitioning=false) f USING(ts_code,trade_date)
        JOIN targets t ON s.ts_code=t.code AND s.trade_time=t.t
        WHERE s.freq=5 ORDER BY 1,2""",
        [[c for c,t in sorted(anchor_keys)], [t for c,t in sorted(anchor_keys)],
         [str(p) for p in silver], [str(p) for p in factors]], spec.max_aggregate_rows)
    global_dates = {row[k][:10] for row in profile for k in ('first_bar', 'last_bar')}
    # Earlier window endpoints are already among the frozen three exit dates; account explicitly.
    global_dates.update(w['exit_bar_end'][:10] for w in windows)
    global_susp_dates = {g['trade_date'] for g in gaps}
    global_sources = set(paths+[life_path, calendar_path])
    global_sources.update(LAKE/f'silver/quote/{kind}/trade_date={d}/part-000.parquet'
                          for d in global_dates for kind in ('stk_mins/freq=5', 'adj_factor'))
    global_sources.update(LAKE/f'silver/quote/stock_suspend_daily/trade_date={d}/part-000.parquet'
                          for d in global_susp_dates)
    budget = dict(global_planned_files=len(global_sources), global_max_files=spec.max_files,
                  global_file_budget_passed=len(global_sources) <= spec.max_files,
                  global_metadata_bytes=sum(p.stat().st_size for p in global_sources if p.is_file()),
                  global_missing_files=[str(p) for p in sorted(global_sources) if not p.is_file()],
                  gold_files=len(paths), anchor_dates=len(global_dates), suspension_dates=len(global_susp_dates),
                  gap_stock_days=len(gaps), gap_bars=sum(g['missing_bars'] for g in gaps))
    return dict(seats=batch_seats, selected=selected, prices=prices, life=life, identities=identities,
                days=days, profile=profile, gaps=gaps, suspension=suspension, anchors=anchors, budget=budget)


def seat_input(batch, seat, window, spec=SPEC):
    code, end = seat['code'], window['exit_bar_end']
    rows = [r for r in batch['prices'] if r['code'] == code and r['time'] <= end]
    gaps = [g for g in batch['gaps'] if g['code'] == code and g['trade_date'] <= end[:10]]
    classified = classify_gaps(gaps, batch['suspension'], code)
    bad = [g for g in classified if g['reason'] != 'confirmed_full_day_suspension']
    if bad:
        return rows, dict(status='data_blocked', reasons=bad, gaps=classified)
    removed = {g['trade_date'] for g in classified}
    days = [d for d in batch['days'] if d not in removed]
    history = len({r['date'] for r in rows if r['date'] < window['prior_days'][0]})
    if history < spec.history_days:
        return rows, dict(status='insufficient_history', actual_history_days=history, gaps=classified)
    quality = validate_rows(rows, days, code, batch['identities'][code]['list_date'],
                            end, window['prior_days'][0], spec)
    anchors = {}
    for yr in sorted({r['date'][:4] for r in rows}):
        chunk = [r for r in rows if r['date'].startswith(yr)]
        for r in (chunk[0], chunk[-1]):
            anchors[r['time']] = r['close']
    raw = [{k:v for k,v in r.items() if k != 'code'} for r in batch['anchors']
           if r['code'] == code and r['time'] in anchors]
    basis = validate_basis(anchors, raw, spec)
    return rows, dict(status='ready', quality=quality, basis=basis, gaps=classified)
