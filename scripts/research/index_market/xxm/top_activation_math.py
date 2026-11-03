"""Independent rational arithmetic for the saved three-decimal source contract."""
from fractions import Fraction as F

def pair(value):
    return [value.numerator, value.denominator]


def daily_options(value):
    # Source contract: nearest .001, with both values within 1e-10 of a tie.
    scaled = value * 1000
    lower = scaled.numerator // scaled.denominator
    midpoint = F(2 * lower + 1, 2000)
    if abs(value - midpoint) <= F(1, 10**10):
        return [F(lower, 1000), F(lower + 1, 1000)]
    return [F(lower + int(value > midpoint), 1000)]
