"""Independent rational expectations for LLD 27/29; no product imports."""
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


def expectations():
    k, guard = F(28, 351), F(1, 10**10)
    b = F(102 * 11, 13) - F(100 * 25, 27)
    assert b == F(-2206, 351)
    lower, upper = -b / k, (10 - b) / k
    assert (lower, upper) == (F(1103, 14), F(1429, 7))
    day_lower, day_upper = (F(1, 2000) - b) / k, (F(19999, 2000) - b) / k
    assert day_lower == F(4412351, 56000)
    assert day_upper == upper - F(351, 56000)
    prices = []
    for p, expected_dif, active in [(60, F(-526, 351), False), (100, F(22, 13), True), (210, F(3674, 351), False)]:
        d = b + k * p
        assert d == expected_dif and (lower < p < upper) == active
        prices.append(dict(price=p, dif=pair(d), hist=pair(F(8, 5)*(d+2)), activation=active))
    precision = []
    cases = [(-F(1, 2000)-2*guard, 'NONPOSITIVE'), (-F(1, 2000), 'NONPOSITIVE'),
             (-F(1, 2000)+2*guard, 'NONPOSITIVE'), (F(0), 'NONPOSITIVE'),
             (F(4, 10000), 'NONPOSITIVE'), (F(1, 2000)-2*guard, 'NONPOSITIVE'),
             (F(1, 2000)-guard/2, 'MIXED'), (F(1, 2000), 'MIXED'),
             (F(1, 2000)+guard/2, 'MIXED'), (F(1, 2000)+2*guard, 'POSITIVE'),
             (F(6, 10000), 'POSITIVE')]
    for raw, expected in cases:
        choices = daily_options(raw)
        actual = 'POSITIVE' if min(choices) > 0 else 'NONPOSITIVE' if max(choices) <= 0 else 'MIXED'
        assert actual == expected
        precision.append(dict(raw=pair(raw), sourceDif=[pair(v) for v in choices], expected=expected))
    # Second completed bar: first P, then C; the coefficients follow the EMA
    # recurrence on paper and are independent of product Affine/interval code.
    ap = F(2*11, 13*13) - F(2*25, 27*27)
    b2 = F(102*121, 169) - F(100*625, 729)
    d1p, d1b = k, b
    a1p, a1b = d1p/5, -F(8, 5)+d1b/5
    flip_p, flip_b = (a1p-ap)/k, (a1b-b2)/k
    relations = []
    for gate in (F(3, 4), F(1), F(6, 5)):
        turn_p = ((1-gate/100)*d1p-ap)/k
        turn_b = ((1-gate/100)*d1b-b2)/k
        # C=40 after P=100 is a literal successful color flip for all gates;
        # C=100 is a dif_turn structure; C=110 is above both bounds, no DIF break.
        assert 40 < flip_p*100+flip_b < 100 < turn_p*100+turn_b < 110
        relations.append(dict(gate=pair(gate), activationP=dict(lower=pair(lower), upper=pair(upper), strict=True),
            targetBarsAhead=2, earlierEndpoint='ACTIVATION_ONLY',
            colorFlip=dict(lowerC=[0, 1], lowerStrict=True, upperC=dict(p=pair(flip_p), b=pair(flip_b)), upperStrict=True),
            difTurn=dict(lowerC=dict(p=pair(flip_p), b=pair(flip_b)), lowerStrict=True,
                         upperC=dict(p=pair(turn_p), b=pair(turn_b)), upperStrict=False),
            examples=[dict(P=100, C=40, result='STRUCTURE', route='color_flip'), dict(P=100, C=100, result='STRUCTURE', route='dif_turn'), dict(P=100, C=110, result='DULL')]))
    # A legal already-active TOP does not acquire the new first-entry gate.
    existing_d = F(98*11, 13) - F(100*25, 27) + k*40
    assert existing_d == F(-758, 117) and F(8, 5)*(existing_d+4) < 0
    return dict(status='FROZEN_INDEPENDENT_MATH', softwareFormulaProven=False,
        source='LLD 26.5 and 27.8 literal prefix; EMA(12,26,9), source .001 and guard 1e-10',
        prefix=[[100,10,2],[99,0,-2],[105,2,8]], projection=dict(e12=102,e26=100,dea=-2),
        firstDif=dict(p=pair(k),b=pair(b)), firstHist='8/5*(D+2)',
        minuteEntry=dict(lower=pair(lower),upper=pair(upper),lowerStrict=True,upperStrict=True),
        dailyEntry=dict(idealLower=pair(day_lower),idealUpper=pair(day_upper),guardInPrice=pair(guard/k),
            tie='mixed 0/.001 at lower; 9.999/10 at upper; float-root enclosure is separate'),
        literalPrices=prices, dailyPrecision=precision, secondDif=dict(p=pair(ap),c=pair(k),b=pair(b2)),
        minuteRelations=relations,
        noEntry=dict(prefix=[[100,-1,2],[99,-5,-2],[105,-2,8]],projection=dict(e12=98,e26=100,dea=-6),
            reason='CURRENT_DIF_NOT_POSITIVE or no divergence: D>0 and max(-2,D)<-1 have empty intersection',
            activationRanges=[],targetEndpoint=None,status='NO_CANDIDATE',reasonCode='NO_ENTRY_RANGE', horizon=20),
        existingDull=dict(prefix=[[100,10,2],[99,0,-2],[105,2,8],[106,1,6],[106.5,-2.1,3.8],[106.5,-2,4]],
            projection=dict(e12=98,e26=100,dea=-4),close=40,dif=pair(existing_d),expected='TOP STRUCTURE color_flip'),
        limits=['Exact rational minute domains, not product float-root attribution',
                'Daily entry and rounding only; daily complete P-C nearest results still require independent preparation',
                'No forecast solver or detector used to generate these expectations'])
