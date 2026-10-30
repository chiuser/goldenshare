"""One-reference conditions for an existing r4 relationship."""
from copy import deepcopy
import math

from .forecast_detector import clone, evaluate_next_at_price, evaluation_scope, _validate_endpoint, _finite
from .forecast_expression import macd_expression, sourced
from .forecast_math import (Interval, candidate_prices, condition, const, difference,
                            display_range, merge, scaled, solve_predicates, subtract)
from .types import ForecastConditionDraft, ReferenceForecast


_RELATIONSHIPS = frozenset(('DULL_FORMED', 'DULL_HELD', 'STRUCTURE_FORMED',
                            'STRUCTURE_FORMED_AND_LOCKED'))
OUTCOME_ORDER = ('DULL_FORMED', 'DULL_HELD', 'STRUCTURE_FORMED', 'STRUCTURE_HELD',
                 'RETURNED_TO_DULL', 'STRUCTURE_FORMED_AND_LOCKED', 'STRUCTURE_LOCKED',
                 'SIGNAL_DISAPPEARED', 'REFERENCE_INVALIDATED')


def _empty_reference():
    return ReferenceForecast(conditions=(), relationship_ranges=(),
                             relationship_precision_ranges=(), precision_ranges=())


def _validate_reference(c, reference, role, check):
    check()
    # The formal restore validator checks the full bounded input without ever
    # changing c. No forecast-specific alternate state validator is introduced.
    clone(c)
    if c.wave is None or c.previous is None or role not in ('NEAR', 'FAR'):
        raise ValueError('Missing one-bar relationship context')
    pool = list(reversed(c.history[c.wave.sign]))[:c.spec.max_refs]
    index = 0 if role == 'NEAR' else 1
    if len(pool) <= index or reference != pool[index]:
        raise ValueError('One-bar reference differs from its complete history identity')
    _finite(c.wave.dif - reference.dif)
    check()
    return pool


def _nodes(c, projection):
    day = c.period == 'day'
    d = sourced(macd_expression(projection, field='dif'), day)
    h = sourced(macd_expression(projection, field='hist'), day)
    price = {'op': 'affine', 'pCoefficient': 0., 'cCoefficient': 1., 'constant': 0.}
    return d, h, price


def _against(expr, value, sign):
    return scaled(difference(expr, const(value)), sign)


def _compare(expr, op, value=0.):
    return condition(expr, op, const(value))


def _remove(ranges, cuts):
    return tuple(merge([part for region in ranges for part in subtract(region, cuts)]))


def _matches(value, outcome, reference):
    return (value is not None and value['outcome'] == outcome
            and value['reference'] == reference.reference())


def _solve_conditions(c, projection, endpoint, reference, role, definitions, check):
    """Prove ranges, then certify only the finite necessary points and integers."""
    check()
    _validate_endpoint(c, endpoint)
    if not definitions:
        return _empty_reference()
    before = c.snapshot()
    with evaluation_scope():
        proved = []
        candidates = set()
        for outcome, predicates in definitions:
            check()
            certificate = solve_predicates(predicates, projection=projection, period=c.period, check=check)
            candidates.update(candidate_prices(predicates, projection=projection, period=c.period, check=check))
            for region in (*certificate.certain_true, *certificate.undecided):
                for value in (region.lo, region.hi):
                    if value is not None and value > 0 and math.isfinite(value):
                        candidates.add(value)
            proved.append((outcome, predicates, certificate))
        evaluated = {}
        for C in sorted(candidates):
            check()
            evaluated[C] = evaluate_next_at_price(c, projection, C, endpoint, role, check)
        conditions = []
        all_true, all_pending, relation_true, relation_pending = [], [], [], []
        for outcome, predicates, certificate in proved:
            confirmed = list(certificate.certain_true)
            pending = list(certificate.undecided)
            for C, value in evaluated.items():
                check()
                matches = _matches(value, outcome, reference)
                if any(region.contains(C) for region in certificate.certain_true):
                    if not matches:
                        raise ValueError('Certified one-bar point differs from the formal calculator')
                elif matches and any(region.contains(C) for region in certificate.certain_false):
                    raise ValueError('Certified false point differs from the formal calculator')
                elif matches and any(region.contains(C) for region in pending):
                    point = Interval(C, C, True, True)
                    confirmed.append(point)
                    pending = list(_remove(pending, (point,)))
            confirmed, pending = tuple(merge(confirmed)), tuple(merge(pending))
            ranges = []
            for region in confirmed:
                check()
                shown = display_range(region)
                for n in (shown['displayLower'], shown['displayUpper']):
                    if n is None:
                        continue
                    # display_range already rejects a changed/non-finite float;
                    # use that same actual C for both contains and original step.
                    C = float(n)
                    if not region.contains(C):
                        raise ValueError('Display integer is outside its original interval')
                    value = evaluated.get(C)
                    if C not in evaluated:
                        value = evaluate_next_at_price(c, projection, C, endpoint, role, check)
                        evaluated[C] = value
                    if not _matches(value, outcome, reference):
                        raise ValueError('Display integer differs from the formal calculator')
                check()
                ranges.append(shown)
            if ranges:
                conditions.append(ForecastConditionDraft(
                    outcome=outcome, reference_role=role, price_ranges=tuple(deepcopy(ranges)),
                    predicates=tuple(deepcopy(predicates))))
            all_true.extend(confirmed)
            all_pending.extend(pending)
            if outcome in _RELATIONSHIPS:
                relation_true.extend(confirmed)
                relation_pending.extend(pending)
        true_ranges = tuple(merge(all_true))
        precision = _remove(all_pending, true_ranges)
        relationship_precision = _remove(relation_pending, true_ranges)
        check()
        if c.snapshot() != before:
            raise ValueError('Forecast changed its real source progress')
        return ReferenceForecast(
            conditions=tuple(sorted(conditions, key=lambda value: OUTCOME_ORDER.index(value.outcome))),
            relationship_ranges=tuple(merge(relation_true)),
            relationship_precision_ranges=relationship_precision, precision_ranges=precision)


def solve_active_reference(c, projection, endpoint, reference, role, check):
    pool = _validate_reference(c, reference, role, check)
    if c.state not in ('DULL', 'STRUCTURE') or c.reference is None:
        raise ValueError('Active-reference solver requires an existing relationship')
    s = c.wave.sign
    d, h, price = _nodes(c, projection)
    signed_h = scaled(h, s)
    ref_delta = _against(d, reference.dif, s)
    same = _compare(signed_h, 'ge')
    opposite = _compare(signed_h, 'lt')
    valid = _compare(ref_delta, 'le')
    broken = _compare(ref_delta, 'gt')
    rescue = reference != c.reference
    if rescue:
        if (c.state != 'DULL' or role != 'FAR' or len(pool) != 2 or c.reference != pool[0]):
            raise ValueError('Only a dull nearest reference can request far rescue')
        if c._reference_was_broken(c.wave, reference):
            return _empty_reference()
        predicates = [same, _compare(_against(d, pool[0].dif, s), 'gt'),
                      _compare(_against(price, pool[0].price, s), 'gt'),
                      _compare(_against(price, reference.price, s), 'gt'),
                      _compare(ref_delta, 'lt')]
        if c.wave.count < c.spec.min_bars:
            # Valid DULL snapshots already have enough colored bars.
            raise ValueError('An active dull relationship has too few colored bars')
        if s == 1 and c.spec.top_activation_requires_positive_dif:
            predicates.append(_compare(d, 'gt'))
        definitions = [('DULL_HELD', tuple(predicates))]
    else:
        if c._reference_was_broken(c.wave, reference):
            raise ValueError('The active reference was already broken in this segment')
        P = c.previous.dif
        gate = abs(P) * c.spec.dif_turn_pct / 100
        if not math.isfinite(gate):
            raise ValueError('Non-finite original one-percent gate')
        delta = _against(d, P, s)
        if c.state == 'DULL':
            definitions = [('STRUCTURE_FORMED_AND_LOCKED', (opposite, valid))]
            if P != 0:
                definitions.append(('STRUCTURE_FORMED',
                                    (same, valid, _compare(delta, 'lt'),
                                     _compare(scaled(delta, -1), 'ge', gate))))
            hold = () if P == 0 else ((_compare(scaled(delta, -1), 'lt', gate),)
                                      if gate > 0 else (_compare(delta, 'ge'),))
            definitions.append(('DULL_HELD', (same, valid, *hold)))
            if role == 'NEAR':
                definitions.extend((('REFERENCE_INVALIDATED', (same, broken)),
                                    ('SIGNAL_DISAPPEARED', (opposite, broken))))
            else:
                definitions.append(('SIGNAL_DISAPPEARED', (broken,)))
        else:
            definitions = [('SIGNAL_DISAPPEARED', (broken,)),
                           ('STRUCTURE_LOCKED', (opposite, valid))]
            if P != 0:
                definitions.append(('RETURNED_TO_DULL',
                                    (same, valid, _compare(delta, 'gt'), _compare(delta, 'ge', gate))))
            hold = () if P == 0 else ((_compare(delta, 'lt', gate),)
                                      if gate > 0 else (_compare(delta, 'le'),))
            definitions.append(('STRUCTURE_HELD', (same, valid, *hold)))
    return _solve_conditions(c, projection, endpoint, reference, role, definitions, check)
