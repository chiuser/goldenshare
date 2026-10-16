"""Offline A-group hypothesis on the current h1 kernel; never imported by products.

The two explicit step edits are compiled in an isolated namespace. Everything
else, including source validation and TOP rules, remains current product code.
This is a research hypothesis, not a second online engine or software formula.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import inspect
import textwrap
from types import FunctionType

from src.biz.services.wealth.market.index_detail_xxm import calculator as product
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec
from src.biz.services.wealth.market.index_detail_xxm.types import Wave

RESEARCH_ID = 'a-same-segment-h1-research-2'
GATES = (.75, 1., 1.2)


def _isolated_step():
    source = textwrap.dedent(inspect.getsource(XxmCalculator.step))
    edits = {
        '    if not event_type:\n':
        '    waiting_event = self._advance_rearm(bar)\n'
        '    if waiting_event is not None:\n'
        '        event_type, route, direction, event_ref = waiting_event\n'
        '    if not event_type and not self._block_ordinary:\n',
        '                event_type, route, self.state = "DULL", "dif_return", "DULL"\n':
        '                if sign == -1 and not self._qualifies_current_bar(bar, ref, self.history[-1][-1].price):\n'
        '                    self._start_rearm(bar, ref)\n'
        '                    event_type, route, self.state = "STRUCTURE_DISAPPEARED", "dif_return", "NONE"\n'
        '                    self.reference = None\n'
        '                else:\n'
        '                    event_type, route, self.state = "DULL", "dif_return", "DULL"\n',
    }
    for old, new in edits.items():
        if source.count(old) != 1:
            raise ValueError('Current h1 step no longer matches the audited research edit')
        source = source.replace(old, new)
    scope = dict(vars(product))
    exec(compile(source, '<offline-A-h1-step>', 'exec'), scope)
    return scope['step']


_STEP = _isolated_step()


class SameSegmentCandidate(XxmCalculator):
    def __init__(self, *, period, source_identity, ts_code='000001.SH', spec=None):
        super().__init__(period=period, source_identity=source_identity, ts_code=ts_code, spec=spec or XxmSpec())
        self.rearm = None
        self.last_rearm_changes = []
        self._current_structure_id = None
        self._block_ordinary = False

    def _end_rearm(self, bar, status, reason):
        self.rearm.update(status=status, endedAt=bar.time, endReason=reason, observedThrough=bar.time)
        self.last_rearm_changes.append(deepcopy(self.rearm))
        self.rearm = None

    def _start_rearm(self, bar, reference):
        if self.rearm is not None or self._current_structure_id is None:
            raise AssertionError('A disappearance must have one active BOTTOM structure')
        identity = f'{RESEARCH_ID}|{self.spec.dif_turn_pct}|{self.period}|{self._current_structure_id}|{bar.time}'
        self.rearm = dict(id=hashlib.sha256(identity.encode()).hexdigest()[:24],
            structureEventId=self._current_structure_id, reference=asdict(reference),
            nearestPriceGate=self.history[-1][-1].price, segmentStart=self.wave.start,
            disappearedAt=bar.time, observedThrough=bar.time, status='WAITING', endedAt=None, endReason=None)
        self.last_rearm_changes.append(deepcopy(self.rearm))

    def _qualifies_current_bar(self, bar, reference, nearest_price):
        return (bar.hist < 0 and self.wave.sign == -1 and self.wave.count >= self.spec.min_bars
                and bar.close < min(reference.price, nearest_price) and self.wave.dif > reference.dif)

    def _advance_rearm(self, bar):
        if self.rearm is None:
            return None
        record = self.rearm
        record['observedThrough'] = bar.time
        if bar.hist >= 0 or self.wave.start != record['segmentStart']:
            self._end_rearm(bar, 'SEGMENT_ENDED', 'zero' if bar.hist == 0 else 'color_flip')
            return None
        self._block_ordinary = True
        ref = Wave(**record['reference'])
        if bar.dif < ref.dif:
            self._end_rearm(bar, 'INVALIDATED', 'reference_dif_break')
        elif (bar.time > record['disappearedAt']
              and self._qualifies_current_bar(bar, ref, record['nearestPriceGate'])):
            self.reference, self.state = ref, 'DULL'
            self._end_rearm(bar, 'REACTIVATED', 'price_requalified')
            return 'DULL', 'reactivation', -1, ref
        else:
            self.last_rearm_changes.append(deepcopy(record))
        return None

    def _advance_bottom_history(self, bar, ordinary_event):
        events, histories = super()._advance_bottom_history(bar, ordinary_event)
        if ordinary_event and ordinary_event['type'] == 'STRUCTURE_DISAPPEARED':
            record = self.pending_bottom_history
            if record is not None:
                if record['structureEventId'] != self._current_structure_id or record['leftOriginAt'] is not None:
                    raise AssertionError('Same-segment disappearance cannot close unrelated history')
                record.update(status='ENDED', endedAt=bar.time, endReason='structure_disappeared')
                histories = [deepcopy(record)]
                self.pending_bottom_history = None
        return events, histories

    def _start_bottom_history(self, bar, structure_event, negative_wave):
        self._current_structure_id = structure_event['id']
        return super()._start_bottom_history(bar, structure_event, negative_wave)

    def step(self, bar):
        self.last_rearm_changes = []
        self._block_ordinary = False
        result = _STEP(self, bar)
        result.point['pendingRearmId'] = self.rearm['id'] if self.rearm else None
        for event in result.events:
            change = self.last_rearm_changes[-1] if self.last_rearm_changes else None
            event['relatedRearmId'] = (change['id'] if change and event['direction'] == 'BOTTOM'
                and (event['type'] == 'STRUCTURE_DISAPPEARED' or event['route'] == 'reactivation') else None)
        if self.rearm is not None:
            assert self.state == 'NONE' and self.reference is None and self.pending_bottom_history is None
        return result

    def snapshot(self):
        return dict(super().snapshot(), research=dict(id=RESEARCH_ID,
            rearm=deepcopy(self.rearm), structureId=self._current_structure_id))

    def restore(self, snapshot):
        extra = deepcopy(snapshot['research'])
        if extra['id'] != RESEARCH_ID:
            raise ValueError('Research snapshot identity mismatch')
        record = extra['rearm']
        if record is not None:
            if (record['status'] != 'WAITING' or snapshot['state'] != 'NONE' or snapshot['reference'] is not None
                or snapshot['pendingBottomHistory'] is not None or record['endedAt'] is not None
                or record['endReason'] is not None or record['observedThrough'] != snapshot['previous']['time']
                or record['segmentStart'] != snapshot['wave']['start'] or snapshot['wave']['sign'] != -1
                or record['structureEventId'] != extra['structureId']):
                raise ValueError('Invalid research wait snapshot')
            Wave(**record['reference'])
        super().restore(snapshot)
        self.rearm, self._current_structure_id = record, extra['structureId']
        self.last_rearm_changes = []
        self._block_ordinary = False


def clone(c):
    child = type(c)(period=c.period, source_identity=c.source_identity, ts_code=c.ts_code, spec=c.spec)
    child.restore(c.snapshot())
    return child


def _namespace(module):
    scope = dict(vars(module))
    for key, value in vars(module).items():
        if isinstance(value, FunctionType) and value.__module__ == module.__name__:
            fn = FunctionType(value.__code__, scope, value.__name__, value.__defaults__, value.__closure__)
            fn.__kwdefaults__ = value.__kwdefaults__
            scope[key] = fn
    return scope


def candidate_forecast():
    """Bind existing range math to candidate clones without monkeypatching modules."""
    import math
    from src.biz.services.wealth.market.index_detail_xxm import forecast as orchestration
    from src.biz.services.wealth.market.index_detail_xxm import forecast_detector, forecast_entry, forecast_joint
    from src.biz.services.wealth.market.index_detail_xxm.forecast_math import Interval, K, GUARD, merge
    detector, entry, joint, main = map(_namespace, (forecast_detector, forecast_entry, forecast_joint, orchestration))
    detector['clone'] = clone

    def activation(c, projection, p, stamp):
        options = detector['event_options'](c, projection, p, stamp, 'DULL')
        events = [item[2] for item in options]
        route = 'reactivation' if getattr(c, 'rearm', None) else 'activation'
        if events and all(event and event['route'] == route for event in events):
            if len({event['eventReference']['startTime'] for event in events}) == 1:
                return events[0]['eventReference']
        return 'PRECISION_UNRESOLVED' if any(events) else None

    def partition(c, projection):
        cuts, bands = forecast_entry.entry_partition(c, projection)
        if not getattr(c, 'rearm', None):
            return cuts, bands
        ref = c.rearm['reference']
        cuts = set(cuts) | {ref['price'], c.rearm['nearestPriceGate']}
        b = projection.e12 * 11 / 13 - projection.e26 * 25 / 27
        for d in ((ref['dif'] - .0005, ref['dif'] + .0005) if c.period == 'day' else (ref['dif'],)):
            for g in ((-GUARD, 0., GUARD) if c.period == 'day' else (0.,)):
                root = (d + g - b) / K
                if root < 0 or not math.isfinite(root):
                    continue
                error = 8 * math.ulp(max(abs(projection.e12), abs(projection.e26), abs(root), 1.)) / K
                band = Interval(max(0., root - error), root + error, True, True)
                cuts.update((root, band.lo, band.hi)); bands.append(band)
        return sorted(cuts), merge(bands)

    def stable(c, projection, region, reference):
        if not getattr(c, 'rearm', None):
            return forecast_entry.stable_reference_on_band(c, projection, region, reference)
        if region.hi is None:
            return False
        ref = c.rearm['reference']
        values = [projection.advance(p)[1] for p in (region.lo, region.hi)]
        error = 8 * math.ulp(max(abs(projection.e12), abs(projection.e26), abs(region.hi), 1.))
        low = min(v[0] for v in values) - error
        high_hist = max(v[2] for v in values) + 2 * error
        if c.period == 'day':
            low = math.floor(low * 1000) / 1000
            high_hist = math.ceil(high_hist * 1000) / 1000
        return (reference == Wave(**ref).reference() and c.wave.count + 1 >= c.spec.min_bars and high_hist < 0
                and min(c.wave.dif, low) > ref['dif']
                and region.hi < min(ref['price'], c.rearm['nearestPriceGate']))

    def reason(c, projection, p):
        if not getattr(c, 'rearm', None):
            return forecast_entry.reason_for(c, projection, p)
        _, bars = detector['possible_bars'](projection, p, '2099-01-01' if c.period == 'day' else '2099-01-01T11:30:00+08:00', c.period == 'day')
        if any(bar.hist >= 0 for bar in bars):
            return 'WRONG_COLOR_OR_ZERO'
        if c.wave.count + 1 < c.spec.min_bars:
            return 'INSUFFICIENT_BARS'
        ref = c.rearm['reference']
        if any(min(c.wave.dif, bar.dif) <= ref['dif'] for bar in bars):
            return 'DIF_NOT_DIVERGENT'
        return 'PRICE_NOT_EXTREME'

    detector['activation_signature'] = activation
    entry.update(activation_signature=activation, entry_partition=partition,
        stable_reference_on_band=stable, reason_for=reason)
    joint['confirmed_options'] = detector['confirmed_options']
    main.update(clone=clone, possible_bars=detector['possible_bars'], confirmed_options=detector['confirmed_options'],
        solve_entry_ranges=entry['solve_entry_ranges'])
    for name, value in joint.items():
        if isinstance(value, FunctionType) and name in main:
            main[name] = value
    return main['forecast'], entry['solve_entry_ranges'], detector
