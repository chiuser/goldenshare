"""B0 feasibility only: frozen first-observable buys paired with new sells."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
from statistics import median
import time

import duckdb
import pandas as pd

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_diagnostics import PLAN, authenticated_input
from scripts.research.index_market.chan.run_m0 import save


@dataclass(frozen=True)
class RoundTripSpec:
    variant: str = 'B0-roundtrip-feasibility'
    source_report: str = 'reports/chan_minute_variant_a_20260909'
    source_manifest: str = '631e7cecffc4df6bf7784d11b81c5a13c4dc0af114e042d83500f9a0cd7ef089'
    codes: tuple = ('000001.SH', '000300.SH', '000905.SH')
    frequencies: tuple = (30, 60)
    buy_groups: tuple = ('B1', 'B2', 'B3')
    sell_groups: tuple = ('S1', 'S2', 'S3')
    start: str = '2021-09-09'
    end: str = '2026-09-08'
    evaluation_start: str = '2022-01-01'
    execution: str = 'next_actual_bar_open'
    cases: str = 'earliest_B3_natural_and_earliest_terminal_per_cell'
    min_exits: int = 30
    min_years: int = 5
    prefix_dates: tuple = ('2022-12-31', '2024-12-31')
    max_rows: int = 50000
    max_bars: int = 10000
    max_events: int = 1000
    total_seconds: int = 600
    max_output_bytes: int = 64 * 1024**2
    reserve_bytes: int = 128 * 1024**2


SPEC = RoundTripSpec()


def validate_cell(rows, events, code, frequency, spec=SPEC):
    if not 0 < len(rows) <= spec.max_bars or len(events) > spec.max_events:
        raise ValueError('cell budget')
    times = [r['time'] for r in rows]
    if times != sorted(set(times)):
        raise ValueError('price order or duplicate')
    if any(r['code'] != code or r['frequency'] != frequency or r['date'] != r['time'][:10]
           for r in rows):
        raise ValueError('mixed price identity')
    seen, previous = set(), -1
    for e in events:
        i = e['signal_index']
        if (e['event_id'] in seen or not previous <= i < len(rows) or i < 0
                or e['signal_time'] != times[i] or e['code'] != code or e['frequency'] != frequency
                or e['group'] not in spec.buy_groups + spec.sell_groups
                or e['evaluation'] != (times[i][:10] >= spec.evaluation_start)
                or not e['sure'] or e['buy'] != e['group'].startswith('B')
                or not 0 <= e['start_index'] <= e['anchor_index'] <= e['end_index'] <= i
                or e['anchor_time'] != times[e['anchor_index']]):
            raise ValueError('invalid event identity/order/first-time/anchor')
        seen.add(e['event_id'])
        previous = i


def pair_events(events, bar_count, group, spec=SPEC):
    """State transitions use only first-observable event indexes, never prices."""
    if group not in spec.buy_groups or bar_count <= 0:
        raise ValueError('invalid group or bar count')
    by_bar = defaultdict(list)
    seen, previous = set(), -1
    for e in events:
        i = e['signal_index']
        if e['event_id'] in seen or not 0 <= i < bar_count or i < previous:
            raise ValueError('invalid event order/identity')
        seen.add(e['event_id'])
        previous = i
        if e['evaluation']:
            by_bar[i].append(e)
    trades, decisions = [], []
    position, order = None, None
    for i in range(bar_count):
        if order is not None:
            if order['side'] == 'buy':
                position = dict(buy_event=order['event'], entry_index=i,
                                sell_events=[], exit_index=None, status='terminal_mark')
                trades.append(position)
            else:
                position.update(exit_index=i, status='natural_exit')
                position = None
            order = None
        buys = sorted((e for e in by_bar[i] if e['group'] == group), key=lambda e: e['event_id'])
        sells = sorted((e for e in by_bar[i] if e['group'] in spec.sell_groups), key=lambda e: e['event_id'])
        if position is not None:
            decisions.extend(dict(event_id=e['event_id'], reason='holding') for e in buys)
            if sells:
                position['sell_events'] = sells
                if i+1 < bar_count:
                    order = dict(side='sell')
                else:
                    position['pending_exit'] = True
        elif buys:
            if sells:
                decisions.extend(dict(event_id=e['event_id'], reason='conflict') for e in buys)
            else:
                decisions.append(dict(event_id=buys[0]['event_id'],
                                      reason='entered' if i+1 < bar_count else 'pending_entry'))
                decisions.extend(dict(event_id=e['event_id'], reason='duplicate_bar') for e in buys[1:])
                if i+1 < bar_count:
                    order = dict(side='buy', event=buys[0])
    return trades, decisions


def verify_pairs(events, bar_count, group, actual):
    """Independent interval search, not the bar-by-bar order state machine."""
    buys = sorted((e for e in events if e['evaluation'] and e['group'] == group),
                  key=lambda e: (e['signal_index'], e['event_id']))
    sells = [e for e in events if e['evaluation'] and e['group'] in SPEC.sell_groups]
    available, expected = 0, []
    for buy in buys:
        i = buy['signal_index']
        if i < available or any(e['signal_index'] == i for e in sells):
            continue
        if i+1 == bar_count:
            break
        after = [e for e in sells if e['signal_index'] > i]
        end_signal = min((e['signal_index'] for e in after), default=None)
        exit_index = end_signal+1 if end_signal is not None and end_signal+1 < bar_count else None
        identities = sorted(e['event_id'] for e in after if e['signal_index'] == end_signal)
        expected.append((buy['event_id'], i+1, exit_index, identities))
        available = exit_index if exit_index is not None else bar_count
    observed = [(t['buy_event']['event_id'], t['entry_index'], t['exit_index'],
                 sorted(e['event_id'] for e in t['sell_events'])) for t in actual]
    assert observed == expected, 'independent interval pairing mismatch'
    return len(expected)


def opening_time(row):
    return (datetime.fromisoformat(row['time']) - timedelta(minutes=row['frequency'])).isoformat(sep=' ')


def enrich(rows, trade):
    a, b = trade['entry_index'], trade['exit_index']
    path = rows[a:b] if b is not None else rows[a:]
    entry, exit_price = rows[a]['open'], rows[b]['open'] if b is not None else rows[-1]['close']
    minimum = min([entry, exit_price] + [r['low'] for r in path])
    maximum = max([entry, exit_price] + [r['high'] for r in path])
    return dict(**trade, entry_time=opening_time(rows[a]), entry_price=entry,
                exit_time=opening_time(rows[b]) if b is not None else rows[-1]['time'],
                exit_price=exit_price, gross_change=exit_price/entry-1,
                mae=minimum/entry-1, mfe=maximum/entry-1, holding_bars=len(path),
                holding_trade_dates=len({r['date'] for r in path} | ({rows[b]['date']} if b is not None else set())),
                price_path=path,
                exit_open_row=rows[b] if b is not None else None)


def verify_prices(rows, trades):
    """Recompute all entry/exit/path fields using independent DuckDB aggregation."""
    frame = pd.DataFrame([dict(idx=i, **r) for i, r in enumerate(rows)])
    with duckdb.connect(':memory:', config={'threads': 2, 'memory_limit': '256MiB',
            'max_temp_directory_size': '0B', 'enable_external_access': False,
            'allow_persistent_secrets': False, 'autoinstall_known_extensions': False,
            'autoload_known_extensions': False}) as con:
        con.register('bars', frame)
        for t in trades:
            a, b = t['entry_index'], t['exit_index']
            stop = b if b is not None else len(rows)
            price, ts = con.execute('SELECT open, CAST(time AS TIMESTAMP) - frequency * INTERVAL 1 MINUTE FROM bars WHERE idx=?', [a]).fetchone()
            end_price, end_time, end_date = con.execute(
                'SELECT '+('open, CAST(time AS TIMESTAMP) - frequency * INTERVAL 1 MINUTE' if b is not None else 'close, CAST(time AS TIMESTAMP)')
                + ', date FROM bars WHERE idx=?', [b if b is not None else len(rows)-1]).fetchone()
            low, high, count, dates = con.execute('SELECT min(low), max(high), count(*), list(DISTINCT date) FROM bars WHERE idx>=? AND idx<?', [a, stop]).fetchone()
            assert t['entry_time'] == str(ts) and t['exit_time'] == str(end_time)
            assert t['entry_price'] == price and t['exit_price'] == end_price
            assert t['holding_bars'] == count and t['holding_trade_dates'] == len(set(dates) | {end_date})
            for key, value in dict(gross_change=end_price/price-1,
                                   mae=min(price, end_price, low)/price-1,
                                   mfe=max(price, end_price, high)/price-1).items():
                assert abs(t[key]-value) < 1e-12, key
    return len(trades)


def summarize(events, group, trades, decisions, spec=SPEC):
    counts = Counter(d['reason'] for d in decisions)
    raw = sum(e['evaluation'] and e['group'] == group for e in events)
    natural = [t for t in trades if t['status'] == 'natural_exit']
    years = dict(sorted(Counter(t['exit_time'][:4] for t in natural).items()))
    assert raw == sum(counts.values()) == len({d['event_id'] for d in decisions})
    assert counts['entered'] == len(trades)
    terminal = len(trades)-len(natural)
    assert terminal <= 1
    lengths = [t['holding_bars'] for t in trades]
    return dict(raw_buys=raw, entries=len(trades), natural_exits=len(natural),
                terminal_marks=terminal, pending_entries=counts['pending_entry'],
                pending_exits=sum(t.get('pending_exit', False) for t in trades),
                dispositions=dict(counts), exit_year_counts=years,
                min_holding_bars=min(lengths) if lengths else None,
                median_holding_bars=median(lengths) if lengths else None,
                max_holding_bars=max(lengths) if lengths else None,
                sample_gate=len(natural) >= spec.min_exits and len(years) >= spec.min_years)


def select_cases(trades):
    # Input is chronological; selection is independent of returns and risk metrics.
    natural = next((t for t in trades if t['status'] == 'natural_exit'), None)
    terminal = next((t for t in trades if t['status'] == 'terminal_mark'), None)
    return [t for t in (natural, terminal) if t is not None]


def execute(output, spec=SPEC):
    if asdict(spec) != asdict(SPEC):
        raise ValueError('unapproved roundtrip specification')
    output = safe_output(output)
    started = time.monotonic()
    if digest((REPO/spec.source_report/'manifest.json').read_bytes()) != spec.source_manifest:
        raise ValueError('source manifest changed')
    folder, source_manifest, audit, source = authenticated_input()
    if folder != REPO/spec.source_report or len(source) > spec.max_rows:
        raise ValueError('source identity/budget')
    saved_spec = source_manifest['spec']
    for key in ('codes', 'frequencies', 'start', 'end', 'evaluation_start'):
        assert saved_spec[key] == json.loads(json.dumps(asdict(spec)[key])), key
    hashes = {p.name: digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')}
    if shutil.disk_usage(REPO/'reports').free < spec.reserve_bytes+spec.max_output_bytes:
        raise ValueError('insufficient research output space')
    output.mkdir(parents=True, exist_ok=False)
    metadata = dict(spec=asdict(spec), source_audit=audit,
                    source_sha256=source_manifest['artifacts_sha256']['source.json'],
                    code_sha256=hashes, plan_sha256_before_run=digest(PLAN.read_bytes()),
                    created_at_utc=datetime.now(timezone.utc).isoformat())
    save(output/'started.json', metadata)
    summary, selected_cases, verification, total_events = {}, {}, {}, 0
    for code in spec.codes:
        for freq in spec.frequencies:
            if time.monotonic()-started > spec.total_seconds:
                raise TimeoutError('roundtrip budget')
            cell = f'{code}_{freq}'
            rows = [r for r in source if r['code'] == code and r['frequency'] == freq]
            events = json.loads((folder/cell/'events.json').read_bytes())
            total_events += len(events)
            if total_events > spec.max_events:
                raise ValueError('combined event budget')
            validate_cell(rows, events, code, freq, spec)
            cell_folder = output/cell
            cell_folder.mkdir()
            summary[cell], books, checks = {}, {}, {}
            for group in spec.buy_groups:
                trades, decisions = pair_events(events, len(rows), group, spec)
                independent = verify_pairs(events, len(rows), group, trades)
                enriched = [enrich(rows, t) for t in trades]
                sql_n = verify_prices(rows, enriched)
                prefixes = {}
                for date in spec.prefix_dates:
                    n = sum(r['date'] <= date for r in rows)
                    prefix_events = [e for e in events if e['signal_index'] < n]
                    pp, _ = pair_events(prefix_events, n, group, spec)
                    natural = [t for t in pp if t['exit_index'] is not None]
                    assert natural == [t for t in trades if t['exit_index'] is not None and t['exit_index'] < n]
                    prefixes[date] = len(natural)
                summary[cell][group] = summarize(events, group, enriched, decisions, spec)
                books[group] = dict(trades=enriched, decisions=decisions)
                checks[group] = dict(independent_pairs=independent, sql_prices=sql_n,
                                     prefix_natural_exits=prefixes, reconciled=True)
            selected_cases[cell] = select_cases(books['B3']['trades'])
            verification[cell] = checks
            save(cell_folder/'books.json', books)
            save(cell_folder/'summary.json', summary[cell])
            save(cell_folder/'verification.json', checks)
            print(f'{cell}: '+', '.join(f'{g} raw={s["raw_buys"]} entry={s["entries"]} exit={s["natural_exits"]} tail={s["terminal_marks"]}' for g, s in summary[cell].items()), flush=True)
            if sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) > spec.max_output_bytes:
                raise ValueError('output budget')
    _, end_manifest, end_audit, _ = authenticated_input()
    assert end_manifest == source_manifest and end_audit == audit
    assert hashes == {p.name: digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')}
    save(output/'summary.json', summary)
    save(output/'cases.json', selected_cases)
    save(output/'verification.json', dict(cells=verification, input_unchanged=True,
                                         code_unchanged=True, total_source_events=total_events))
    artifacts = {str(p.relative_to(output)): digest(p.read_bytes()) for p in output.rglob('*.json')}
    save(output/'manifest.json', dict(**metadata, status='complete', seconds=time.monotonic()-started,
                                      artifacts_sha256=artifacts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    execute(parser.parse_args().output)


if __name__ == '__main__':
    main()
