"""Bounded offline date selection for two SZ indices; never product results.

Source contract: IndexFactorPro / TradeCalendar, audited 2026-10-18 in
reports/xxm_cross_index_daily_20261018_01/source_precheck.json. SSE calendar
is shared by Shanghai/Shenzhen A shares, as explicitly confirmed in AGENTS.
Only the existing selector hypotheses are reused; no calculation is copied.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import time

from .bottom_history_acceptance import readonly_session
from .top_daily_ambiguity import ReferenceGateCalculator
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar

ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class ResearchSpec:
    codes: tuple[str, ...] = ('399006.SZ', '399001.SZ')
    start: str = '2020-01-01'
    candidate_start: str = '2022-09-13'
    end: str = '2024-08-30'
    alternate_start: str = '2021-01-01'
    calendar_exchange: str = 'SSE'
    variants: tuple[str, ...] = ('BASE', 'ZC', 'ZR')
    batch: int = 500
    max_rows: int = 1200
    max_calendar: int = 2000
    max_bytes: int = 20_000_000
    phase_seconds: int = 60
    total_seconds: int = 240
    query_seconds: int = 15
    connection_seconds: int = 5


SPEC = ResearchSpec()
CODE_PATHS = (
    'scripts/research/index_market/xxm/cross_index_daily.py',
    'scripts/research/index_market/xxm/top_daily_ambiguity.py',
    'scripts/research/index_market/xxm/bottom_history_acceptance.py',
    'src/biz/services/wealth/market/index_detail_xxm/calculator.py',
    'src/biz/services/wealth/market/index_detail_xxm/types.py',
    'src/biz/services/wealth/market/index_detail_xxm/spec.py',
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity():
    return dict(spec=json.loads(json.dumps(asdict(SPEC))),
                code={p: sha(ROOT / p) for p in CODE_PATHS})


def save(path, value):
    """Atomic completion; callers refuse overwriting completed units."""
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if len(data.encode()) > SPEC.max_bytes:
        raise ValueError('Research unit exceeds memory/file budget')
    partial = path.with_suffix(path.suffix + '.partial')
    partial.write_text(data)
    os.replace(partial, path)


def seal(out, name, value):
    path = out / (name + '.json')
    marker = out / (name + '.complete.json')
    if path.exists() or marker.exists():
        raise ValueError('Refusing to overwrite prior unit: ' + name)
    save(path, value)
    save(marker, dict(sha256=sha(path)))


def read_unit(out, name):
    path = out / (name + '.json')
    marker = out / (name + '.complete.json')
    if not path.exists() and not marker.exists():
        return None
    if not path.is_file() or not marker.is_file() or path.stat().st_size > SPEC.max_bytes:
        raise ValueError('Incomplete or oversized research unit: ' + name)
    if sha(path) != json.loads(marker.read_text())['sha256']:
        raise ValueError('Changed completed research unit: ' + name)
    return json.loads(path.read_text())


def check_time(deadline):
    if time.perf_counter() > deadline:
        raise TimeoutError('Research phase budget exceeded')


def validate_calendar(rows):
    if not rows or len(rows) > SPEC.max_calendar:
        raise ValueError('Calendar empty or over limit')
    dates = [date.fromisoformat(r['trade_date']) for r in rows]
    if dates[0].isoformat() != SPEC.start or dates[-1].isoformat() != SPEC.end:
        raise ValueError('Calendar bounds differ')
    if any(b - a != timedelta(days=1) for a, b in zip(dates, dates[1:])):
        raise ValueError('Calendar missing/duplicate/unordered dates')
    if any(type(r['is_open']) is not bool for r in rows):
        raise ValueError('Calendar flags must be boolean')
    return tuple(r['trade_date'] for r in rows if r['is_open'])


def validate_rows(code, rows, calendar):
    if code not in SPEC.codes or not rows or len(rows) > SPEC.max_rows:
        raise ValueError('Unknown/empty/oversized source')
    expected = validate_calendar(calendar)
    if tuple(r['trade_date'] for r in rows) != expected:
        raise ValueError('Missing/duplicate/unordered/out-of-range daily rows')
    bars = []
    for row in rows:
        if row['ts_code'] != code:
            raise ValueError('Source identity mismatch')
        values = [row[k] for k in ('close', 'macd_dif_bfq', 'macd_dea_bfq', 'macd_bfq')]
        if any(v is None or isinstance(v, bool) for v in values):
            raise ValueError('NULL or boolean price/indicator')
        bar = XxmBar(row['trade_date'], *(float(v) for v in values))
        bar.validate('day')
        bars.append(bar)
    return tuple(bars)


def capture_source(out, deadline):
    """Read only six audited fields, two fixed codes and the shared calendar."""
    from sqlalchemy import select, text
    from src.foundation.models.core.index_factor_pro import IndexFactorPro as I
    from src.foundation.models.core.trade_calendar import TradeCalendar as C
    os.environ.setdefault('PGCONNECT_TIMEOUT', str(SPEC.connection_seconds))
    with readonly_session() as session:
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        session.execute(text(f"SET LOCAL statement_timeout='{SPEC.query_seconds}s'"))
        session.execute(text("SET LOCAL lock_timeout='1s'"))
        if session.execute(text('SHOW transaction_read_only')).scalar_one() != 'on':
            raise ValueError('Database session is not read only')
        check_time(deadline)
        calendar = read_unit(out, 'calendar')
        if calendar is None:
            raw = session.execute(select(C.trade_date, C.is_open).where(
                C.exchange == SPEC.calendar_exchange,
                C.trade_date >= date.fromisoformat(SPEC.start),
                C.trade_date <= date.fromisoformat(SPEC.end))
                .order_by(C.trade_date).limit(SPEC.max_calendar + 1)).all()
            calendar = [dict(trade_date=d.isoformat(), is_open=o) for d, o in raw]
            validate_calendar(calendar)
            check_time(deadline)
            seal(out, 'calendar', calendar)
        for code in SPEC.codes:
            check_time(deadline)
            existing = read_unit(out, 'source_' + code)
            if existing is not None:
                validate_rows(code, existing, calendar)
                continue
            rows, after = [], None
            while True:
                check_time(deadline)
                filters = [I.ts_code == code, I.trade_date >= date.fromisoformat(SPEC.start),
                           I.trade_date <= date.fromisoformat(SPEC.end)]
                if after is not None:
                    filters.append(I.trade_date > after)
                raw = session.execute(select(I.ts_code, I.trade_date, I.close,
                    I.macd_dif_bfq, I.macd_dea_bfq, I.macd_bfq).where(*filters)
                    .order_by(I.trade_date).limit(SPEC.batch)).all()
                if not raw:
                    break
                rows.extend(dict(zip(('ts_code', 'trade_date', 'close', 'macd_dif_bfq',
                    'macd_dea_bfq', 'macd_bfq'), (r[0], r[1].isoformat(), *r[2:]))) for r in raw)
                if len(rows) > SPEC.max_rows:
                    raise ValueError('Source exceeds row budget')
                after = raw[-1][1]
            validate_rows(code, rows, calendar)
            check_time(deadline)
            seal(out, 'source_' + code, rows)
            print(json.dumps(dict(stage='source', ts_code=code, rows=len(rows))), flush=True)
    manifest = dict(calendarExchange=SPEC.calendar_exchange,
                    files={p.name: sha(p) for p in out.glob('source_*.json')
                           if not p.name.endswith('.complete.json')},
                    calendarSha256=sha(out / 'calendar.json'), readonly=True)
    previous = read_unit(out, 'source_manifest')
    if previous is None:
        seal(out, 'source_manifest', manifest)
    elif previous != manifest:
        raise ValueError('Source manifest changed')


def event_view(event):
    return {k: event[k] for k in ('time', 'direction', 'type', 'route', 'fromState', 'eventReference')}


def point_view(step):
    return {k: step.point[k] for k in ('ordinaryState', 'ordinaryDirection', 'activeReference')}


def ordinary_events(step):
    return [event_view(e) for e in step.events if e['type'] != 'RESEARCH_HISTORICAL_WITHDRAWAL']


def calculate(bars, source, deadline, *, checks):
    calculators = {v: ReferenceGateCalculator(period='day', source_identity=source, variant=v)
                   for v in SPEC.variants}
    direct = XxmCalculator(period='day', source_identity=source) if checks else None
    cuts = {next(i for i, b in enumerate(bars, 1) if b.time >= SPEC.candidate_start), len(bars) - 3}
    results, snapshots = [], {}
    for index, bar in enumerate(bars, 1):
        check_time(deadline)
        steps = {v: c.step(bar) for v, c in calculators.items()}
        if direct is not None and steps['BASE'] != direct.step(bar):
            raise AssertionError('Research BASE differs from product numerical calculation')
        if not all(c.wave == calculators['BASE'].wave and c.history == calculators['BASE'].history
                   for c in calculators.values()):
            raise AssertionError('Selector experiment changed segmentation/history pool')
        if checks and index in cuts:
            snapshots[index] = {v: c.snapshot() for v, c in calculators.items()}
        if bar.time >= SPEC.candidate_start:
            results.append(dict(bar=asdict(bar), wave=asdict(calculators['BASE'].wave),
                history=[asdict(w) for w in calculators['BASE'].history[1]],
                variants={v: dict(point=point_view(step), events=[event_view(e) for e in step.events])
                          for v, step in steps.items()}))
    if checks:
        for cut, saved in snapshots.items():
            for variant, snapshot in saved.items():
                prefix = ReferenceGateCalculator(period='day', source_identity=source, variant=variant)
                for bar in bars[:cut]:
                    check_time(deadline)
                    prefix.step(bar)
                if prefix.snapshot() != snapshot:
                    raise AssertionError('Complete prefix differs')
                restored = ReferenceGateCalculator(period='day', source_identity=source, variant=variant)
                restored.restore(snapshot)
                for bar in bars[cut:cut + 3]:
                    check_time(deadline)
                    if prefix.step(bar) != restored.step(bar):
                        raise AssertionError('Restored suffix differs')
                wrong = ReferenceGateCalculator(period='day', source_identity=source + ':OTHER', variant=variant)
                try:
                    wrong.restore(snapshot)
                except ValueError:
                    pass
                else:
                    raise AssertionError('Cross-source restore was accepted')
    return results


def classify(row):
    """Literal event predicates, not software accuracy labels."""
    states = row['variants']
    activations = {v: [e for e in s['events'] if e['type'] == 'DULL'
        and e['direction'] == 'TOP' and e['route'] == 'activation'] for v, s in states.items()}
    if (activations['ZR'] and not activations['ZC']
            and states['ZC']['point']['ordinaryState'] == 'NONE'
            and row['bar']['dif'] <= 0 and activations['ZR'][0]['eventReference']['dif'] > 0):
        return 'CURRENT_VS_REFERENCE'
    if (activations['BASE'] and not activations['ZC'] and not activations['ZR']
            and all(states[v]['point']['ordinaryState'] == 'NONE' for v in ('ZC', 'ZR'))):
        return 'BASE_VS_BOTH'
    return None


def scan(code, rows, calendar, source_hash, deadline):
    bars = validate_rows(code, rows, calendar)
    source = 'cross-index-numeric-only:' + code + ':' + source_hash
    result = calculate(bars, source, deadline, checks=True)
    alternate = calculate(tuple(b for b in bars if b.time >= SPEC.alternate_start),
                          source, deadline, checks=False)
    stability = []
    for full, short in zip(result, alternate, strict=True):
        def semantic(row):
            return {v: dict(point=s['point'], events=[e for e in s['events']
                if e['type'] != 'RESEARCH_HISTORICAL_WITHDRAWAL']) for v, s in row['variants'].items()}
        if semantic(full) != semantic(short):
            stability.append(full['bar']['time'])
    candidates = []
    for index, row in enumerate(result):
        kind = classify(row)
        if kind:
            candidates.append(dict(ts_code=code, date=row['bar']['time'], kind=kind,
                stableFrom2020And2021=not stability, softwareVerified=False,
                detail=row, following=result[index + 1:index + 11]))
    return dict(ts_code=code, sourceSha256=source_hash, rows=len(bars),
                productIdentityUsedAsSecurityIdentity=False,
                baseMatchesProduct=True, segmentationAndHistoryUnchanged=True,
                prefixAndRestoreChecks=6, crossSourceRestoreRejected=True,
                alternateStartDifferences=stability, candidates=candidates,
                dailyResults=result)


def run(out, *, resume=False):
    start = time.perf_counter()
    if resume:
        if read_unit(out, 'identity') != identity():
            raise ValueError('Research settings/code identity changed')
        # No prior result means capture was interrupted before calculation;
        # both indices can be calculated once within the normal phase budget.
        # After one result completed, only the other index is calculated.
        for code in SPEC.codes:
            read_unit(out, 'source_' + code)
            read_unit(out, 'result_' + code)
    else:
        out.mkdir(parents=True, exist_ok=False)
        seal(out, 'identity', identity())
    status = dict(status='RUNNING', readonly=True, productCodeChanged=False, formalWrites=False)
    try:
        capture_start = time.perf_counter()
        if read_unit(out, 'source_manifest') is None:
            capture_source(out, min(start + SPEC.total_seconds, capture_start + SPEC.phase_seconds))
        calendar = read_unit(out, 'calendar')
        validate_calendar(calendar)
        calculate_start = time.perf_counter()
        completed = []
        for code in SPEC.codes:
            check_time(min(start + SPEC.total_seconds, calculate_start + SPEC.phase_seconds))
            rows = read_unit(out, 'source_' + code)
            validate_rows(code, rows, calendar)
            result = read_unit(out, 'result_' + code)
            if result is None:
                result = scan(code, rows, calendar, sha(out / ('source_' + code + '.json')),
                              min(start + SPEC.total_seconds, calculate_start + SPEC.phase_seconds))
                seal(out, 'result_' + code, result)
            if result['ts_code'] != code or result['sourceSha256'] != sha(out / ('source_' + code + '.json')):
                raise ValueError('Result belongs to different source')
            completed.append(result)
            print(json.dumps(dict(stage='comparison', ts_code=code,
                                  candidates=len(result['candidates']))), flush=True)
        candidates = [c for r in completed for c in r['candidates'] if c['stableFrom2020And2021']]
        candidates.sort(key=lambda c: (c['kind'] == 'CURRENT_VS_REFERENCE',
            abs(c['detail']['bar']['dif']) / c['detail']['bar']['close'], c['date']), reverse=True)
        summary = dict(candidates=candidates, recommended=candidates[:3],
                       rows={r['ts_code']:r['rows'] for r in completed},
                       calendarNaturalDays=len(calendar), openDays=len(validate_calendar(calendar)))
        previous = read_unit(out, 'summary')
        if previous is None:
            seal(out, 'summary', summary)
        elif previous != summary:
            raise ValueError('Prior summary differs')
        status.update(status='COMPLETE', candidates=len(candidates),
            sourceSeconds=calculate_start - capture_start,
            comparisonSeconds=time.perf_counter() - calculate_start)
    except Exception as exc:
        status.update(status='FAILED', failure=dict(type=type(exc).__name__, message=str(exc)))
        raise
    finally:
        status['seconds'] = time.perf_counter() - start
        status['codeUnchanged'] = read_unit(out, 'identity') == identity()
        save(out / 'run.json', status)
        if not status['codeUnchanged']:
            raise AssertionError('Research code changed while running')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    run(args.output, resume=args.resume)


if __name__ == '__main__':
    main()
