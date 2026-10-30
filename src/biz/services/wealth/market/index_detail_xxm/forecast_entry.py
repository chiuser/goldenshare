"""First dull conditions for one explicitly selected historical reference."""
from .forecast_next import (_compare, _empty_reference, _against, _nodes,
                            _solve_conditions, _validate_reference)
from .forecast_math import scaled


def solve_first_dull(c, projection, endpoint, reference, role, check):
    pool = _validate_reference(c, reference, role, check)
    if c.state != 'NONE':
        raise ValueError('First-dull solver requires an inactive ordinary state')
    if (c.wave.count + 1 < c.spec.min_bars
            or c._reference_was_broken(c.wave, reference)):
        return _empty_reference()
    s = c.wave.sign
    d, h, price = _nodes(c, projection)
    # With only one existing colored bar, zero cannot supply the second.
    color_op = 'ge' if c.wave.count >= c.spec.min_bars else 'gt'
    predicates = [_compare(scaled(h, s), color_op),
                  _compare(_against(price, pool[0].price, s), 'gt'),
                  _compare(_against(price, reference.price, s), 'gt'),
                  _compare(_against(d, reference.dif, s), 'lt')]
    if s == 1 and c.spec.top_activation_requires_positive_dif:
        predicates.append(_compare(d, 'gt'))
    return _solve_conditions(c, projection, endpoint, reference, role,
                             [('DULL_FORMED', tuple(predicates))], check)
