"""Verify new forecasts against sealed, independently derived inequalities."""
from fractions import Fraction as F
import math

from .frozen_inputs import expected_unit

MATH_KEYS=('status','reasonCode','targetEndpoint','barsAhead','activation','assumption','targetEntryRanges',
           'targetEntryExclusions','relations','commonConditions','examples','nextBarOutcomes')


def fraction(value):
    return F(*value) if isinstance(value,list) else F(value)


def contains(region, value):
    lo,hi=region['lower'],region['upper']
    return ((lo is None or value>lo or value==lo and region['lowerInclusive']) and
            (hi is None or value<hi or value==hi and region['upperInclusive']))


def regions(proof):
    return [dict(reference=r['reference'],priceRange=dict(lower=float(fraction(r['entryDomain']['lower'])),
        upper=float(fraction(r['entryDomain']['upper'])),lowerInclusive=r['entryDomain']['lowerInclusive'],
        upperInclusive=r['entryDomain']['upperInclusive'])) for r in proof['ranges']]


def assert_partition(activation):
    values=sorted([v['priceRange'] for v in activation['ranges']+activation['exclusions']],
        key=lambda r:(r['lower'] or 0,not r['lowerInclusive']))
    assert values and values[0]['lower']==0 and not values[0]['lowerInclusive'] and values[-1]['upper'] is None
    for a,b in zip(values,values[1:]):
        assert a['upper']==b['lower'] and a['upperInclusive']!=b['lowerInclusive']


def coefficients(expr, first):
    """Interpret the public expression contract independently of solver helpers."""
    op=expr['op']
    if op=='affine':return tuple(F(expr[k]) for k in ('pCoefficient','cCoefficient','constant'))
    if op=='scale':return tuple(v*F(expr['factor']) for v in coefficients(expr['arg'],first))
    if op=='sub':return tuple(a-b for a,b in zip(*(coefficients(v,first) for v in expr['args'])))
    if op=='abs':
        result=coefficients(expr['arg'],first)
        assert all(math.isclose(float(a),float(b),abs_tol=1e-10,rel_tol=1e-12) for a,b in zip(result,first))
        # All sealed nonempty TOP entry domains independently prove D1>0.
        return result
    raise AssertionError('Unexpected expression in the sealed minute case: '+op)


def verify_changed_forecast(value, proof, context):
    assert value['status']==proof['status'] and value['reasonCode']==proof['reasonCode']
    assert value['targetEndpoint']==proof['targetEndpoint']
    assert value['activation'] is not None
    assert_partition(value['activation'])
    if proof['classification']=='NO_ENTRY':
        assert not value['activation']['ranges'] and not value['relations'] and not value['examples']
        return
    assert value['barsAhead']==2 and value['activation']['endpoint']==proof['activationEndpoint']
    assert not value['targetEntryExclusions'] and value['assumption']['intermediateEndpoints']==[proof['activationEndpoint']]
    wanted=regions(proof);actual=value['activation']['ranges']
    e12,e26,a0=(proof['projection'][k] for k in ('e12','e26','dea'))
    k=F(28,351);b=fraction(proof['firstDif']['b']);d1=(k,F(0),b)
    ap=fraction(proof['secondDif']['p']);b2=fraction(proof['secondDif']['b']);d2=(ap,k,b2)
    h2=tuple(F(8,5)*(x-y) for x,y in zip(d2,(k/5,F(0),F(4,5)*F(a0)+b/5)))
    # The old numerical enclosure is an input roundoff bound, not a changed
    # detector epsilon. No unmatched interval away from these cuts is allowed.
    w=context['wave'];refs=context['history']['1']
    float_b=e12*11/13-e26*25/27
    float_k=2/13-2/27
    levels=[F(w['dif']),F(a0),F(0),*[F(ref['dif']) for ref in refs]]
    cuts=[(float((level-b)/k),(float(level)-float_b)/float_k) for level in levels]
    cuts.extend((v,v) for v in [0.,w['price'],*[ref['price'] for ref in refs]])
    def near_cut(p):
        for exact,center in cuts:
            if center<0:continue
            enclosure=8*math.ulp(max(abs(e12),abs(e26),abs(center),1.))/float_k
            # Keep the original product enclosure. Separately bind its IEEE
            # center to the independent rational root; do not enlarge a range.
            assert abs(exact-center)<=enclosure
            if center-enclosure<=p<=center+enclosure:return True
        return False
    endpoints={0.}
    for item in actual+value['activation']['exclusions']+wanted:
        endpoints.update(v for v in item['priceRange'].values() if isinstance(v,(int,float)) and not isinstance(v,bool) and v is not None)
    ordered=sorted(endpoints)
    probes=[*ordered,*[(a+b)/2 for a,b in zip(ordered,ordered[1:])],ordered[-1]+max(1.,ordered[-1]/10)]
    for p in probes:
        if p<=0:continue
        hits=[r for r in actual if contains(r['priceRange'],p)]
        expected=[r for r in wanted if contains(r['priceRange'],p)]
        if near_cut(p):continue
        assert [r['reference'] for r in hits]==[r['reference'] for r in expected],('entry domain',p)
    for exclusion in value['activation']['exclusions']:
        if exclusion['reason']=='PRECISION_UNRESOLVED':
            lo,hi=exclusion['priceRange']['lower'],exclusion['priceRange']['upper']
            assert hi is not None and near_cut(lo) and near_cut(hi)
    # Prove that the public target conditions are the complete independent
    # affine inequalities, not merely passing example points.
    tolerance=8*math.ulp(max(abs(e12),abs(e26),1.))
    def same(actual,expected):
        assert all(abs(float(a-b))<=tolerance for a,b in zip(actual,expected)),(actual,expected)
    ratio=F(str(proof['gate']))/100
    for relation in value['relations']:
        assert relation['initialReference']==relation['reference'] and not relation['referenceTransitions'] and not relation['prefixConditions']
        assert any(relation['reference']==r['reference'] for r in wanted)
        target=relation['targetConditions']
        expected=[(tuple(x-y for x,y in zip(d2,(F(0),F(0),F(relation['reference']['dif'])))),'le'),
                  (h2,'gt' if relation['route']=='dif_turn' else 'lt')]
        if relation['route']=='dif_turn':expected.extend([(d1,'gt'),(tuple((1-ratio)*a-b for a,b in zip(d1,d2)),'ge')])
        assert len(target)==len(expected)
        for condition,(coeff,op) in zip(target,expected):
            assert condition['op']==op
            actual_coeff=tuple(a-b for a,b in zip(coefficients(condition['left'],d1),coefficients(condition['right'],d1)))
            same(actual_coeff,coeff)
    # Complete target P coverage: the independent proof establishes positive C
    # for every allowed P at endpoint two; the solver cannot drop a subdomain.
    for p in probes:
        if p<=0 or near_cut(p):continue
        wanted_hit=any(contains(r['priceRange'],p) for r in wanted)
        assert any(contains(r['priceRange'],p) for r in value['targetEntryRanges'])==wanted_hit
    # Displayed common ranges must satisfy the independent affine conditions
    # across their entire P interval. Affine extrema occur at rectangle corners.
    def verify_close(p,c,route):
        d=float(ap)*p+float(k)*c+float(b2);prev=float(k)*p+float(b);hist=float(F(8,5))*(d-(.8*a0+.2*prev))
        assert hist<=tolerance if route=='color_flip' else hist>=-tolerance
        if route=='dif_turn':assert prev-d>=float(ratio)*prev-tolerance
    for common in value['commonConditions']:
        domain=common['entryDomain']
        for close in common['closeRanges']:
            for p in (domain['lower'],domain['upper']):
                for c in (close['displayLower'],close['displayUpper']):
                    assert c is not None and c>0
                    verify_close(p,c,common['route'])
    for example in value['examples']:
        p=example['preClose'];assert any(contains(r['priceRange'],p) for r in wanted)
        for close in example['closeRanges']:
            for c in (close['displayLower'],close['displayUpper']):
                assert c is not None and c>0
                verify_close(p,c,close['route'])
