"""Single-stock share quotas and a causal cash account; never places real orders."""
from copy import deepcopy
from dataclasses import asdict
from decimal import ROUND_FLOOR
import re

from scripts.research.index_market.chan.stock_share_model import (
    BUY, SELL, D, ZERO, DataBlocked, StockShareBacktestSpec, affordable, fees, model_price,
)


class Account:
    def __init__(self, code, frequency=30, spec=StockShareBacktestSpec()):
        # Identity is necessary, not a substitute for P0 lifecycle/board verification.
        if (not isinstance(code, str) or not re.fullmatch(r'(?:60\d{4}|688\d{3})\.SH|(?:00\d{4}|30\d{4})\.SZ', code)
                or frequency not in (30, 60)):
            raise DataBlocked('single SH/SZ stock identity required')
        self.code, self.frequency, self.spec = code, frequency, spec
        self.cash, self.shares, self.cost_basis = spec.initial_cash, 0, ZERO
        self.realized = ZERO
        self.phase = 'flat'
        self.q = self.v = self.bought = self.sold = 0
        self.buy_groups, self.sell_groups = set(), set()
        self.seen, self.effect_ids, self.right_ids, self.rights = {}, set(), set(), {}
        self.lots = []
        self.days = set()
        self.previous_volume = 0
        self.last_end = self.closed_bar = None
        self.cycle_number, self.cycle_start_cash, self.cycle_first_fill = 0, None, None
        self.fills, self.journal, self.decisions, self.equity, self.cycles = [], [], [], [], []
        self.failed = False

    def _journal(self, kind, time, cash_delta=ZERO, share_delta=0, right_delta=ZERO, **detail):
        self.journal.append(dict(kind=kind, time=time.isoformat(), cycle=self.cycle_number, cash_delta=cash_delta,
            share_delta=share_delta, right_delta=right_delta, cash=self.cash,
            shares=self.shares, rights=sum(self.rights.values(), ZERO), **detail))

    def _decision(self, bar, reason, **details):
        self.decisions.append(dict(time=bar.end.isoformat(), reason=reason,
                                   cycle=self.cycle_number, **details))

    def _reset(self):
        self.phase = 'flat'
        self.q = self.v = self.bought = self.sold = 0
        self.buy_groups, self.sell_groups = set(), set()
        self.cycle_start_cash = self.cycle_first_fill = None

    def _close_cycle(self, bar):
        if self.phase == 'reducing' and self.shares == 0 and not self.rights:
            self.cycles.append(dict(cycle=self.cycle_number, start=self.cycle_first_fill,
                end=bar.start.isoformat(), profit=self.cash-self.cycle_start_cash,
                start_cash=self.cycle_start_cash, end_cash=self.cash))
            self.closed_bar = bar.end
            self._reset()

    def _effect(self, effect, bar):
        if effect.time != bar.start or effect.event_id in self.effect_ids:
            raise DataBlocked('corporate effect time/duplicate')
        if self.phase == 'flat':
            raise DataBlocked('corporate entitlement without an active cycle')
        value = effect.value
        if effect.kind == 'cash_right':
            if self.bought == 0 or effect.reference in self.right_ids:
                raise DataBlocked('duplicate entitlement reference')
            self.right_ids.add(effect.reference)
            self.rights[effect.reference] = value
            self.realized += value
            self._journal(effect.kind, effect.time, right_delta=value, effect=asdict(effect))
        elif effect.kind == 'cash_pay':
            if self.rights.get(effect.reference) != value:
                raise DataBlocked('cash payment differs from recorded entitlement')
            del self.rights[effect.reference]
            self.cash += value
            self._journal(effect.kind, effect.time, cash_delta=value, right_delta=-value,
                          effect=asdict(effect))
        elif effect.kind == 'unit_split':
            names = ('shares', 'q', 'v', 'bought', 'sold')
            converted = [D(getattr(self, name))*value for name in names]
            lot_quantities = [D(lot['quantity'])*value for lot in self.lots]
            if any(q != q.to_integral_value() for q in converted+lot_quantities):
                raise DataBlocked('fractional split needs an explicit rights contract')
            old_shares = self.shares
            for name, quantity in zip(names, converted, strict=True):
                setattr(self, name, int(quantity))
            for lot, quantity in zip(self.lots, lot_quantities, strict=True):
                lot['quantity'] = int(quantity)
            # Previous volume must use today's share units for the participation cap.
            self.previous_volume = int((D(self.previous_volume)*value).to_integral_value(rounding=ROUND_FLOOR))
            self._journal(effect.kind, effect.time, share_delta=self.shares-old_shares,
                          effect=asdict(effect))
        else:
            raise DataBlocked('unsupported corporate effect')
        self.effect_ids.add(effect.event_id)

    def _quota(self, buy):
        weights, active, base, filled = ((BUY, self.buy_groups, self.q, self.bought) if buy else
                                         (SELL, self.sell_groups, self.v, self.sold))
        target = int(D(base)*sum((weights[g] for g in active), ZERO))
        return max(0, target-filled)

    def _execute(self, bar):
        if self.phase == 'flat':
            return
        buy = self.phase == 'building'
        pending = self._quota(buy)
        if pending <= 0:
            return
        cap = int(D(self.previous_volume)*self.spec.participation)
        sellable = sum(lot['quantity'] for lot in self.lots if lot['date'] < bar.start.date())
        maximum = min(pending, cap, pending if buy else sellable)
        rule = bar.rule
        if ((buy and bar.upper is not None and bar.open >= bar.upper)
                or (not buy and bar.lower is not None and bar.open <= bar.lower)):
            self._decision(bar, 'open_at_limit', pending=pending)
            return
        price = model_price(bar.open, buy, rule, self.spec)
        if price <= 0 or (bar.lower is not None and not bar.lower <= price <= bar.upper):
            self._decision(bar, 'slippage_price_outside_limits', pending=pending)
            return
        quantity = rule.quantity(maximum, buy, self.shares)
        if buy:
            quantity = affordable(self.cash, price, quantity, rule.buy_min, rule.buy_step, rule, self.spec)
        if quantity == 0:
            reason = ('t_plus_one' if not buy and sellable == 0 else 'previous_volume_cap' if cap == 0
                      else 'cash_or_lot_limit')
            self._decision(bar, reason, pending=pending, cap=cap, sellable=sellable)
            return
        costs = fees(quantity, price, buy, rule, self.spec)
        total_fee = sum(costs.values(), ZERO)
        cash_delta = -price*quantity-total_fee if buy else price*quantity-total_fee
        if self.cash+cash_delta < 0:
            self._decision(bar, 'cash_for_sell_fees', pending=pending)
            return
        if buy:
            profit = ZERO
            self.cash += cash_delta
            self.cost_basis -= cash_delta
            self.shares += quantity
            self.bought += quantity
            self.lots.append(dict(date=bar.start.date(), quantity=quantity))
            if self.cycle_first_fill is None:
                self.cycle_first_fill = bar.start.isoformat()
        else:
            removed_cost = self.cost_basis if quantity == self.shares else self.cost_basis*D(quantity)/self.shares
            profit = cash_delta-removed_cost
            self.realized += profit
            self.cost_basis -= removed_cost
            self.cash += cash_delta
            self.shares -= quantity
            self.sold += quantity
            remaining = quantity
            for lot in self.lots:
                if lot['date'] < bar.start.date():
                    taken = min(remaining, lot['quantity'])
                    lot['quantity'] -= taken
                    remaining -= taken
            if remaining:
                raise AssertionError('sellability calculation mismatch')
            self.lots = [lot for lot in self.lots if lot['quantity']]
        fill = dict(cycle=self.cycle_number, time=bar.start.isoformat(), bar_end=bar.end.isoformat(),
            side='buy' if buy else 'sell', quantity=quantity, price=price, fees=costs,
            cash_delta=cash_delta, cash=self.cash, shares=self.shares, q=self.q, v=self.v,
            bought=self.bought, sold=self.sold, active=sorted(self.buy_groups if buy else self.sell_groups),
            previous_volume=self.previous_volume, cost_basis=self.cost_basis, realized_profit=profit,
            rule=asdict(rule))
        self.fills.append(fill)
        self._journal('fill', bar.start, cash_delta=cash_delta, share_delta=quantity if buy else -quantity,
                      fill_index=len(self.fills)-1)

    def _signals(self, signals, bar):
        fresh = []
        for signal in sorted(signals, key=lambda s: s.event_id):
            if signal.code != self.code or signal.frequency != self.frequency:
                raise DataBlocked('mixed signal identity')
            if signal.event_id in self.seen:
                if signal != self.seen[signal.event_id]:
                    raise DataBlocked('changed first-known event')
                self._decision(bar, 'duplicate_event', event_id=signal.event_id)
                continue
            if signal.time != bar.end:
                raise DataBlocked('signal must be first known at this completed bar')
            self.seen[signal.event_id] = signal
            fresh.append(signal)
        if not fresh:
            return
        if len(self.days) <= self.spec.warmup_days:
            for s in fresh:
                self._decision(bar, 'warmup', event_id=s.event_id)
            return
        sells = {s.group for s in fresh if s.group in SELL}
        buys = {s.group for s in fresh if s.group in BUY}
        if self.closed_bar == bar.end:
            reason = 'cycle_closed_this_bar'
        elif sells:
            if self.phase == 'flat':
                reason = 'flat_sell_priority'
            elif self.phase == 'building' and self.shares == 0:
                self._reset()
                reason = 'cancel_unfilled_cycle'
            else:
                if self.phase == 'building':
                    self.v = self.shares
                    self.phase = 'reducing'
                new = sells-self.sell_groups
                self.sell_groups |= sells
                reason = 'sell_quota_activated' if new else 'sell_class_already_used'
        elif self.phase == 'reducing':
            reason = 'buy_ignored_while_reducing'
        else:
            if self.phase == 'flat':
                price = model_price(bar.close, True, bar.rule, self.spec)
                maximum = int(self.cash/price) if price > 0 else 0
                q = affordable(self.cash, price, maximum, self.spec.q_step, self.spec.q_step,
                               bar.rule, self.spec) if price > 0 else 0
                if q == 0:
                    for s in fresh:
                        self._decision(bar, 'insufficient_cash_for_Q', event_id=s.event_id)
                    return
                self.q, self.phase = q, 'building'
                self.cycle_number += 1
                self.cycle_start_cash = self.cash
            new = buys-self.buy_groups
            self.buy_groups |= buys
            reason = 'buy_quota_activated' if new else 'buy_class_already_used'
        for s in fresh:
            individual = 'buy_ignored_sell_priority' if sells and s.group in BUY else reason
            self._decision(bar, individual, event_id=s.event_id, group=s.group,
                           q=self.q, v=self.v, buy_quota=self._quota(True), sell_quota=self._quota(False))

    def step(self, bar, signals=(), effects=()):
        """Open executes old intent; close values; only then observe new signals.

        Failure poisons this instance: partial units must be recomputed, never
        treated as successful checkpoints or resumed past a rejected input.
        """
        if self.failed:
            raise DataBlocked('failed account must be recomputed')
        try:
            if (bar.code != self.code or bar.frequency != self.frequency
                    or (self.last_end is not None and bar.start < self.last_end)
                    or len(self.equity) >= self.spec.max_bars):
                raise DataBlocked('bar identity/order/budget')
            self.days.add(bar.start.date())
            for effect in effects:
                self._effect(effect, bar)
            self._execute(bar)
            self._close_cycle(bar)
            right_value = sum(self.rights.values(), ZERO)
            equity = self.cash+self.shares*bar.close+right_value
            self._journal('mark', bar.end, price=bar.close, equity=equity)
            self.equity.append(dict(time=bar.end.isoformat(), cash=self.cash, shares=self.shares,
                rights=right_value, price=bar.close, equity=equity, cost_basis=self.cost_basis,
                realized=self.realized, phase=self.phase, q=self.q, v=self.v,
                bought=self.bought, sold=self.sold))
            self._signals(signals, bar)
            if (self.cash < 0 or self.shares < 0 or self.shares != sum(lot['quantity'] for lot in self.lots)
                    or self.bought > self.q or self.sold > self.v
                    or (self.shares == 0 and self.cost_basis != 0)):
                raise AssertionError('account conservation invariant')
            self.previous_volume, self.last_end = bar.volume_shares, bar.end
        except Exception:
            self.failed = True
            raise

    def result(self):
        if self.failed:
            raise DataBlocked('failed account cannot publish results')
        return deepcopy(dict(scope='synthetic_account_core_not_real_backtest', code=self.code,
            frequency=self.frequency, spec=asdict(self.spec), fills=self.fills,
            journal=self.journal, decisions=self.decisions, equity=self.equity, cycles=self.cycles,
            end_state=dict(phase=self.phase, cash=self.cash, shares=self.shares,
                rights=sum(self.rights.values(), ZERO), q=self.q, v=self.v,
                bought=self.bought, sold=self.sold, pending_buy=self._quota(True) if self.phase == 'building' else 0,
                pending_sell=self._quota(False) if self.phase == 'reducing' else 0)))
