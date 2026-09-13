"""QFQ strategy model: explicit adjusted prices, no corporate-action accounting."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal as D
import math

from scripts.research.index_market.chan.stock_share_account import Account
from scripts.research.index_market.chan.stock_share_audit import audit, metrics
from scripts.research.index_market.chan.stock_share_model import Signal, StockShareBacktestSpec, TradingRule


@dataclass(frozen=True)
class QfqRunSpec:
    code: str = '002245.SZ'
    name: str = '蔚蓝锂芯'
    start: str = '2021-09-09'
    end: str = '2026-09-08'
    asof: str = '2026-09-12'
    frequency: int = 30
    account: StockShareBacktestSpec = field(default_factory=StockShareBacktestSpec)
    precision: D = D('.00000001')
    stress_slippage: D = D('.001')
    max_files: int = 8
    max_bytes: int = 2*1024**2
    max_output_bytes: int = 128*1024**2
    reserve_bytes: int = 256*1024**2
    total_seconds: int = 1800
    query_seconds: int = 60
    replay_seconds: int = 180
    memory: str = '1GiB'
    threads: int = 4
    limit_queue_model: str = 'not_simulated_next_open_assumption'
    corporate_actions: str = 'none_qfq_only'


SPEC = QfqRunSpec()


@dataclass(frozen=True)
class QfqBar:
    """Account-compatible model bar; deliberately NOT a RawBar."""
    code: str
    frequency: int
    start: datetime
    end: datetime
    open: D
    close: D
    volume_shares: int
    rule: TradingRule
    lower: None = None
    upper: None = None
    price_basis: str = 'qfq_model'


def to_bar(row, spec=SPEC):
    if row['code'] != spec.code or row['frequency'] != spec.frequency:
        raise ValueError('QFQ stock/frequency mismatch')
    if row.get('price_basis') != 'qfq':
        raise ValueError('explicit QFQ source required')
    if any(not math.isfinite(row[k]) or row[k] <= 0 for k in ('open', 'close', 'vol')):
        raise ValueError('invalid QFQ price/volume')
    if row['vol'] != int(row['vol']):
        raise ValueError('minute volume must be integral shares, not lots')
    end = datetime.fromisoformat(row['time'])
    rule = TradingRule(date.fromisoformat(spec.start), date.fromisoformat(spec.end),
        100, 100, 100, 100, True, spec.precision, D(0), D(0),
        'QFQ model: numeric precision; zero transfer/stamp assumption, not historical rule')
    return QfqBar(spec.code, spec.frequency, end-timedelta(minutes=spec.frequency), end,
                  D(str(row['open'])).quantize(spec.precision), D(str(row['close'])).quantize(spec.precision),
                  int(row['vol']), rule)


def simulate(rows, events, spec=SPEC, mode='model_cost', hold=False):
    if mode not in ('gross', 'model_cost', 'stress'):
        raise ValueError('unknown cost mode')
    account_spec = spec.account
    if mode == 'gross':
        account_spec = replace(account_spec, commission_rate=D(0), minimum_commission=D(0), slippage=D(0))
    elif mode == 'stress':
        account_spec = replace(account_spec, slippage=spec.stress_slippage)
    ledger = Account(spec.code, spec.frequency, account_spec)
    indexed = defaultdict(list)
    times = {r['time'] for r in rows}
    if len(times) != len(rows):
        raise ValueError('duplicate QFQ time')
    for event in events:
        if event['signal_time'] not in times:
            raise ValueError('event outside input prefix')
        signal = Signal.from_chan_event(event)
        indexed[signal.time].append(signal)
    days, activated = set(), False
    for row in rows:
        bar = to_bar(row, spec)
        days.add(bar.start.date())
        signals = indexed[bar.end]
        if hold:
            signals = []
            if not activated and len(days) > spec.account.warmup_days:
                signals = [Signal(f'buy-hold:{g}', spec.code, spec.frequency, bar.end, g)
                           for g in ('B1', 'B2', 'B3')]
                activated = True
        ledger.step(bar, signals)  # No effects are supplied, even at ex-dividend dates.
    result = ledger.result()
    result['scope'] = 'qfq_strategy_model_not_broker_account'
    result['cost_mode'], result['buy_hold'] = mode, hold
    audit(result)
    return result


def summarize(result, rows, events, spec=SPEC):
    summary = metrics(result)
    days = sorted({r['date'] for r in rows})
    eligible = days[spec.account.warmup_days] if len(days) > spec.account.warmup_days else None
    initial, ending = float(spec.account.initial_cash), float(summary['ending_equity'])
    def annualized(start):
        n = (date.fromisoformat(days[-1])-date.fromisoformat(start)).days
        return (ending/initial)**(365.25/n)-1 if n > 0 else None
    year_ends = {}
    for row in result['equity']:
        year_ends[row['time'][:4]] = row
    previous = spec.account.initial_cash
    annual = []
    for year, row in sorted(year_ends.items()):
        annual.append(dict(year=int(year), ending_equity=row['equity'], return_value=row['equity']/previous-1,
                           partial_calendar_year=year in (spec.start[:4], spec.end[:4])))
        previous = row['equity']
    cycle_days = [(datetime.fromisoformat(c['end'])-datetime.fromisoformat(c['start'])).total_seconds()/86400
                  for c in result['cycles']]
    entry = result['fills'][0]['time'] if result['fills'] else None
    active = [e for e in events if eligible and e['signal_time'][:10] >= eligible]
    summary.update(data_start=days[0], data_end=days[-1], eligible_signal_start=eligible,
        full_range_annualized=annualized(days[0]), eligible_range_annualized=annualized(eligible) if eligible else None,
        first_fill=entry, fill_count=len(result['fills']), annual=annual,
        confirmed_signals=dict(sorted(Counter(e['group'] for e in events).items())),
        eligible_signals=dict(sorted(Counter(e['group'] for e in active).items())),
        mean_completed_holding_days=sum(cycle_days)/len(cycle_days) if cycle_days else None,
        max_completed_holding_days=max(cycle_days) if cycle_days else None,
        average_invested_fraction=sum(float(r['shares']*r['price']/r['equity']) for r in result['equity'])/len(rows))
    return summary


def account_prefix_equal(full, prefix, cutoff):
    # A next-bar open can equal the preceding bar's end. Compare bar inclusion,
    # not fill time <= cutoff, which would incorrectly include the next fill.
    for key in ('fills', 'equity', 'decisions'):
        field = 'bar_end' if key == 'fills' else 'time'
        expected = [r for r in full[key] if r[field] <= cutoff.replace(' ', 'T')]
        if expected != prefix[key]:
            return False
    stop = next(i+1 for i, r in enumerate(full['journal'])
                if r['kind'] == 'mark' and r['time'] == cutoff.replace(' ', 'T'))
    return full['journal'][:stop] == prefix['journal']
