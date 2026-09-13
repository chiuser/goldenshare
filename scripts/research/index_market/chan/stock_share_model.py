"""Explicit inputs for the synthetic-first share account; no Lake/source adapter."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP


D = Decimal
ZERO = D('0')
BUY = {'B1': D('.2'), 'B2': D('.3'), 'B3': D('.5')}
SELL = {'S1': D('.5'), 'S2': D('.3'), 'S3': D('.2')}


class DataBlocked(ValueError):
    """An input cannot support the claimed account simulation."""


def decimal_value(value, minimum=ZERO):
    if not isinstance(value, D) or not value.is_finite() or value < minimum:
        raise DataBlocked('finite Decimal with valid range required')


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise DataBlocked('integer quantity required')


def local_time(value):
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise DataBlocked('naive Asia/Shanghai datetime required')


def money(value):
    return value.quantize(D('.01'), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class StockShareBacktestSpec:
    initial_cash: D = D('1000000')
    warmup_days: int = 250
    slippage: D = D('.0005')
    participation: D = D('.01')
    commission_rate: D = D('.0003')
    minimum_commission: D = D('5')
    q_step: int = 1000
    max_bars: int = 10000

    def __post_init__(self):
        for value in (self.initial_cash, self.minimum_commission):
            decimal_value(value)
        for value in (self.slippage, self.participation, self.commission_rate):
            decimal_value(value)
            if value >= 1:
                raise DataBlocked('fraction must be below one')
        integer(self.warmup_days)
        integer(self.max_bars, 1)
        if self.initial_cash <= 0 or money(self.initial_cash) != self.initial_cash or self.q_step != 1000:
            raise DataBlocked('positive cash and fixed 1000-share Q grid required')
        if self.max_bars > 10000:
            raise DataBlocked('10000-bar account budget')


@dataclass(frozen=True)
class TradingRule:
    """Rates and lot rules are supplied dated facts, not inferred market defaults."""
    start: date
    end: date
    buy_min: int
    buy_step: int
    sell_min: int
    sell_step: int
    odd_final_sell: bool
    tick: D
    transfer_rate: D
    stamp_sell_rate: D
    source: str

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise DataBlocked('rule date range')
        for value in (self.buy_min, self.buy_step, self.sell_min, self.sell_step):
            integer(value, 1)
        for value in (self.tick, self.transfer_rate, self.stamp_sell_rate):
            decimal_value(value)
        if (self.tick <= 0 or self.transfer_rate >= 1 or self.stamp_sell_rate >= 1
                or type(self.odd_final_sell) is not bool or not self.source):
            raise DataBlocked('rule facts/source required')

    def quantity(self, maximum, buy, holdings):
        """Floor without inventing a universal 100-share lot rule."""
        integer(maximum)
        if not buy and self.odd_final_sell and maximum == holdings:
            return maximum
        minimum, step = (self.buy_min, self.buy_step) if buy else (self.sell_min, self.sell_step)
        return 0 if maximum < minimum else minimum + (maximum-minimum)//step*step


@dataclass(frozen=True)
class RawBar:
    code: str
    frequency: int
    start: datetime
    end: datetime
    open: D
    close: D
    volume_shares: int
    lower: D | None
    upper: D | None
    limits_known: bool
    rule: TradingRule
    source: str
    price_basis: str = 'raw'

    def __post_init__(self):
        local_time(self.start)
        local_time(self.end)
        for value in (self.open, self.close):
            decimal_value(value)
        integer(self.volume_shares)
        if (self.frequency not in (30, 60) or self.start.date() != self.end.date()
                or (self.end-self.start).total_seconds() != self.frequency*60
                or min(self.open, self.close) <= 0 or not self.source or self.price_basis != 'raw'):
            raise DataBlocked('raw bar grid/price/source')
        if type(self.limits_known) is not bool or not self.limits_known:
            raise DataBlocked('unknown price limits')
        if (self.lower is None) != (self.upper is None):
            raise DataBlocked('both limits or explicit unlimited session required')
        if self.lower is not None:
            decimal_value(self.lower)
            decimal_value(self.upper)
            if not 0 < self.lower <= min(self.open, self.close) <= max(self.open, self.close) <= self.upper:
                raise DataBlocked('prices outside legal range')
        if not self.rule.start <= self.start.date() <= self.rule.end:
            raise DataBlocked('historical rule not effective')
        if any(p % self.rule.tick for p in (self.open, self.close)):
            raise DataBlocked('price off tick grid')


@dataclass(frozen=True)
class Signal:
    event_id: str
    code: str
    frequency: int
    time: datetime
    group: str

    def __post_init__(self):
        local_time(self.time)
        if not self.event_id or self.group not in BUY.keys() | SELL.keys():
            raise DataBlocked('unsupported signal identity/group')

    @classmethod
    def from_chan_event(cls, event):
        """Consume first-known sure events, NEVER the legacy evaluation/anchor flag."""
        group = event['group']
        allowed = {'1'} if group[-1:] == '1' else {'2'} if group[-1:] == '2' else {'3a', '3b'}
        if (event.get('sure') is not True or type(event.get('buy')) is not bool
                or event['buy'] != group.startswith('B') or not allowed.intersection(event['types'])):
            raise DataBlocked('not a confirmed mapped Chan event')
        known = datetime.fromisoformat(event['signal_time'])
        anchor = datetime.fromisoformat(event['anchor_time'])
        local_time(known)
        local_time(anchor)
        if anchor > known:
            raise DataBlocked('future structural anchor')
        return cls(event['event_id'], event['code'], event['frequency'], known, group)


@dataclass(frozen=True)
class CorporateEffect:
    """Already-normalized facts; not a source entitlement or tax calculation.

    cash_right records a net receivable at ex-time; cash_pay settles that exact
    right. unit_split is an immediate, pure unit conversion, NOT a stock bonus.
    Unimplemented effects such as delayed bonus listing fail closed.
    """
    event_id: str
    time: datetime
    kind: str
    value: D
    reference: str
    source: str

    def __post_init__(self):
        local_time(self.time)
        decimal_value(self.value)
        if (self.kind not in {'cash_right', 'cash_pay', 'unit_split'} or self.value <= 0
                or not self.event_id or not self.reference or not self.source):
            raise DataBlocked('unsupported/missing corporate effect')
        if self.kind != 'unit_split' and money(self.value) != self.value:
            raise DataBlocked('cash effect must be in cents')


def model_price(price, buy, rule, spec):
    adjusted = price*(1+spec.slippage if buy else 1-spec.slippage)
    rounding = ROUND_CEILING if buy else ROUND_FLOOR
    return (adjusted/rule.tick).to_integral_value(rounding=rounding)*rule.tick


def fees(quantity, price, buy, rule, spec):
    if quantity == 0:
        return dict(commission=ZERO, transfer=ZERO, stamp=ZERO)
    amount = price*quantity
    return dict(commission=money(max(spec.minimum_commission, amount*spec.commission_rate)),
                transfer=money(amount*rule.transfer_rate),
                stamp=money(ZERO if buy else amount*rule.stamp_sell_rate))


def affordable(cash, price, maximum, minimum, step, rule, spec):
    """Monotone bounded binary search over legal quantities, including minimum fees."""
    if maximum < minimum:
        return 0
    low, high, best = 0, (maximum-minimum)//step, 0
    while low <= high:
        middle = (low+high)//2
        qty = minimum+middle*step
        cost = price*qty + sum(fees(qty, price, True, rule, spec).values())
        if cost <= cash:
            best, low = qty, middle+1
        else:
            high = middle-1
    return best
