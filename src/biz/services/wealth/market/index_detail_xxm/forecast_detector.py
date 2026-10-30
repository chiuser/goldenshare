"""Finite one-bar checks against the single formal r4 calculator."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace
from itertools import product
import json
import math

from .calculator import XxmCalculator
from .forecast_math import source_options
from .types import XxmBar


# The dictionary exists only inside one synchronous forecast/solver invocation.
# ContextVar isolates concurrent callers; the finally reset releases every price.
_EVALUATIONS = ContextVar('xxm_next_bar_evaluations', default=None)


@contextmanager
def next_bar_evaluations():
    token = _EVALUATIONS.set({})
    try:
        yield
    finally:
        _EVALUATIONS.reset(token)


@contextmanager
def evaluation_scope():
    if _EVALUATIONS.get() is not None:
        yield
    else:
        with next_bar_evaluations():
            yield


def clone(c):
    child = XxmCalculator(period=c.period, source_identity=c.source_identity,
                          ts_code=c.ts_code, spec=c.spec)
    child.restore(c.snapshot())
    return child


def _finite(value):
    if type(value) not in (int, float):
        raise ValueError('One-bar projection requires original numeric values')
    try:
        if not math.isfinite(value):
            raise ValueError('Non-finite one-bar projection')
    except OverflowError as exc:
        raise ValueError('Non-finite one-bar projection') from exc
    return value


def possible_bars(projection, close, stamp, day, check=lambda: None):
    check()
    _finite(close)
    if close <= 0 or type(day) is not bool:
        raise ValueError('One-bar projection requires a positive close and a source period')
    try:
        price = float(close)
    except OverflowError as exc:
        raise ValueError('Non-finite forecast close') from exc
    if price != close:
        raise ValueError('Forecast close changes when converted to float')
    key = ('projection', id(projection), price, stamp, day)
    cache = _EVALUATIONS.get()
    if cache is not None and key in cache:
        check()
        return cache[key]
    for value in (projection.e12, projection.e26, projection.dea):
        _finite(value)
    projected, (d, a, h) = projection.advance(price)
    for value in (projected.e12, projected.e26, projected.dea, d, a, h):
        _finite(value)
    if day:
        _finite(d * 1000)
        _finite(h * 1000)
    ds, hs = source_options(d, day), source_options(h, day)
    bars = tuple(XxmBar(stamp, price, dd, round(a, 3) if day else a, hh)
                 for dd, hh in product(ds, hs))
    for bar in bars:
        for value in (bar.dif, bar.dea, bar.hist):
            _finite(value)
    result = projected, bars
    check()
    if cache is not None:
        cache[key] = result
    return result


def verify_reference_invalidation(c, bar, reference):
    """Only the near reference fact; never run the far selector or full step."""
    if c.state != 'DULL' or c.wave is None:
        raise ValueError('Near invalidation requires an existing dull state')
    pool = list(reversed(c.history[c.wave.sign]))[:c.spec.max_refs]
    if not pool or reference != pool[0] or c.reference != reference:
        raise ValueError('Near invalidation must use the actual nearest reference')
    bar.validate(c.period)
    if c.wave.sign * bar.hist < 0:
        return False
    extreme = max(c.wave.dif, bar.dif) if c.wave.sign > 0 else min(c.wave.dif, bar.dif)
    _finite(extreme - reference.dif)
    wave = replace(c.wave, dif=extreme)
    return c._reference_was_broken(wave, reference)


def _validate_endpoint(c, endpoint):
    XxmBar(endpoint, 1., 0., 0., 0.).validate(c.period)
    if c.previous is None or endpoint <= c.previous.time:
        raise ValueError('Forecast endpoint must follow the completed source prefix')


def _qualification_wave(c, bar, reference, nearest):
    """Build only this input's original extrema and check needed finite differences."""
    s = c.wave.sign
    raw_sign = (bar.hist > 0) - (bar.hist < 0)
    if raw_sign == -s:
        return None
    wave = replace(c.wave, count=c.wave.count + int(raw_sign != 0), end=bar.time)
    if s * (bar.close - wave.price) > 0:
        wave.price, wave.price_at = bar.close, bar.time
    if s * (bar.dif - wave.dif) > 0:
        wave.dif, wave.dif_at = bar.dif, bar.time
    if (wave.count >= c.spec.min_bars
            and not (s == 1 and c.spec.top_activation_requires_positive_dif and bar.dif <= 0)
            and s * (bar.close - nearest.price) > 0
            and s * (bar.close - reference.price) > 0):
        _finite(wave.dif - reference.dif)
        _finite(bar.dif - reference.dif)
    return wave


def _first_near_qualifies(c, bar, reference):
    """Check only B with the original qualification helper, never the A loop."""
    if c.state != 'NONE' or c.wave is None:
        raise ValueError('First-near check requires an inactive ordinary state')
    wave = _qualification_wave(c, bar, reference, reference)
    return wave is not None and c._current_reference_qualifies(bar, wave, reference, reference)


def _check_original_arithmetic(c, bar):
    """Reject non-finite arithmetic actually needed by the original branch."""
    s = c.wave.sign
    if s * bar.hist < 0:
        if c.reference is not None:
            _finite(bar.dif - c.reference.dif)
        return
    _finite(bar.close - c.wave.price)
    _finite(bar.dif - c.wave.dif)
    if c.reference is not None:
        _finite(bar.dif - c.reference.dif)
        extreme = max(c.wave.dif, bar.dif) if s > 0 else min(c.wave.dif, bar.dif)
        distance = _finite(extreme - c.reference.dif)
        if s * distance <= 0 and c.previous.dif != 0:
            delta = _finite(bar.dif - c.previous.dif)
            _finite(s * delta)
            _finite(abs(c.previous.dif) * c.spec.dif_turn_pct / 100)


def _actual_outcome(c, child, step):
    """Read actual events and structure updates, including a flip's old state."""
    events, records = step.events, step.structures
    old_id = c.active_structure['id'] if c.active_structure is not None else None
    if events:
        if len(events) != 1:
            raise ValueError('One bar invented multiple ordinary events')
        event = events[0]
        reference = event['eventReference']
        direction = 'TOP' if c.wave.sign > 0 else 'BOTTOM'
        if (event['fromState'] != c.state or event['direction'] != direction
                or event['time'] != step.point['time']):
            raise ValueError('Forecast event differs from its original state/time/direction')
        if event['type'] == 'DULL' and event['route'] == 'activation':
            if (c.state != 'NONE' or child.state != 'DULL' or records
                    or child.reference.reference() != reference or event['relatedStructureId'] is not None):
                raise ValueError('Invalid first-dull forecast semantics')
            return {'outcome': 'DULL_FORMED', 'reference': reference}
        if event['type'] == 'DULL' and event['route'] == 'dif_return':
            if (c.state != 'STRUCTURE' or child.state != 'DULL' or len(records) != 1
                    or records[0]['id'] != old_id or records[0]['status'] != 'DISAPPEARED'
                    or records[0]['disappearanceReason'] != 'dif_return'
                    or records[0]['disappearedAt'] != event['time']
                    or event['relatedStructureId'] != old_id or child.reference != c.reference):
                raise ValueError('Invalid return-to-dull forecast semantics')
            return {'outcome': 'RETURNED_TO_DULL', 'reference': reference}
        if event['type'] == 'STRUCTURE':
            if c.state != 'DULL' or len(records) != 1:
                raise ValueError('Invalid structure-formation forecast semantics')
            record = records[0]
            if (record['id'] != event['relatedStructureId']
                    or record['structureEventId'] != event['id']
                    or record['formedAt'] != event['time']
                    or record['originalReference'] != reference):
                raise ValueError('Forecast formation association differs')
            if event['route'] == 'color_flip':
                if (record['status'] != 'LOCKED' or record['formedAt'] != record['lockedAt']
                        or child.state != 'NONE'):
                    raise ValueError('Invalid same-bar lock forecast semantics')
                outcome = 'STRUCTURE_FORMED_AND_LOCKED'
            elif event['route'] == 'dif_turn':
                if (record['status'] != 'ASSESSING' or child.state != 'STRUCTURE'
                        or child.active_structure['id'] != record['id']):
                    raise ValueError('Invalid assessing-structure forecast semantics')
                outcome = 'STRUCTURE_FORMED'
            else:
                raise ValueError('Unknown structure formation route')
            return {'outcome': outcome, 'reference': reference}
        if event['type'] == 'CANCEL' and event['route'] in ('dif_break', 'dif_break_on_flip'):
            if child.state != 'NONE':
                raise ValueError('Cancellation did not finish the relationship')
            if c.state == 'STRUCTURE':
                if (len(records) != 1 or records[0]['id'] != old_id
                        or records[0]['status'] != 'DISAPPEARED'
                        or records[0]['disappearanceReason'] != 'reference_dif_break'
                        or records[0]['disappearedAt'] != event['time']
                        or event['relatedStructureId'] != old_id):
                    raise ValueError('Forecast disappearance association differs')
            elif records or event['relatedStructureId'] is not None:
                raise ValueError('Dull cancellation invented a structure')
            return {'outcome': 'SIGNAL_DISAPPEARED', 'reference': reference}
        raise ValueError('Unexpected one-bar event')
    if records:
        record = records[0]
        if (c.state != 'STRUCTURE' or len(records) != 1 or record['id'] != old_id
                or record['status'] != 'LOCKED' or child.state != 'NONE'
                or record['lockedAt'] != step.point['time']
                or record['originalReference'] != c.reference.reference()):
            raise ValueError('Invalid existing-structure lock forecast semantics')
        return {'outcome': 'STRUCTURE_LOCKED', 'reference': c.reference.reference()}
    if c.state == 'STRUCTURE' and child.state == 'STRUCTURE':
        if (child.active_structure['id'] != old_id or child.active_structure['status'] != 'ASSESSING'
                or child.reference != c.reference):
            raise ValueError('Forecast changed the assessing structure')
        return {'outcome': 'STRUCTURE_HELD', 'reference': c.reference.reference()}
    if c.state == 'DULL' and child.state == 'DULL':
        return {'outcome': 'DULL_HELD', 'reference': child.reference.reference()}
    return {'outcome': None, 'reference': None}


def evaluate_next_at_price(c, projection, C, endpoint, role, check):
    if role not in ('NEAR', 'FAR') or c.wave is None or c.previous is None:
        raise ValueError('Invalid one-bar evaluation context')
    check()
    _validate_endpoint(c, endpoint)
    _finite(C)
    try:
        actual_close = float(C)
    except OverflowError as exc:
        raise ValueError('Non-finite forecast close') from exc
    if actual_close != C or actual_close <= 0:
        raise ValueError('Invalid forecast close')
    snapshot = c.snapshot()
    pool = list(reversed(c.history[c.wave.sign]))[:c.spec.max_refs]
    index = 0 if role == 'NEAR' else 1
    if len(pool) <= index:
        raise ValueError('Forecast reference is absent')
    requested = pool[index]
    key = ('outcome', id(projection), actual_close, endpoint, role,
           json.dumps(snapshot, sort_keys=True, separators=(',', ':')))
    with evaluation_scope():
        cache = _EVALUATIONS.get()
        if key in cache:
            check()
            return deepcopy(cache[key])
        _, bars = possible_bars(projection, C, endpoint, c.period == 'day', check)
        values = []
        for bar in bars:
            check()
            _check_original_arithmetic(c, bar)
            if role == 'FAR' and c.state == 'NONE':
                # The original selector inspects B before the selected A. This
                # checks only finite arithmetic, without making a selection.
                _qualification_wave(c, bar, pool[0], pool[0])
            if role == 'FAR' and (c.state == 'NONE' or
                    c.state == 'DULL' and c.reference != requested
                    and c.wave.sign * (bar.hist) >= 0
                    and c.wave.sign * ((max(c.wave.dif, bar.dif) if c.wave.sign > 0
                                       else min(c.wave.dif, bar.dif)) - c.reference.dif) > 0):
                _qualification_wave(c, bar, requested, pool[0])
            if role == 'NEAR' and c.state == 'NONE' and not _first_near_qualifies(c, bar, requested):
                value = {'outcome': None, 'reference': None}
            elif (role == 'NEAR' and c.state == 'DULL' and c.reference == requested
                    and verify_reference_invalidation(c, bar, requested)):
                value = {'outcome': 'REFERENCE_INVALIDATED', 'reference': requested.reference()}
            else:
                child = clone(c)
                check()
                step = child.step(bar)
                check()
                value = _actual_outcome(c, child, step)
            values.append(value)
        result = values[0] if all(value == values[0] for value in values) else None
        check()
        cache[key] = deepcopy(result)
        return deepcopy(result)
