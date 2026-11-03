"""Independent open/closed interval arithmetic; no strategy or replay."""
from .top_activation_math import pair

def meet(a,b):
    lo=max(a[0],b[0]);hi=min(a[1],b[1])
    lc=(a[2] if lo==a[0] else True) and (b[2] if lo==b[0] else True)
    hc=(a[3] if hi==a[1] else True) and (b[3] if hi==b[1] else True)
    return (lo,hi,lc,hc) if lo<hi or lo==hi and lc and hc else None


def minus(a,b):
    overlap=meet(a,b)
    if overlap is None:return [a]
    lo,hi,lc,hc=overlap
    result=[]
    for part in ((a[0],lo,a[2],not lc),(hi,a[1],not hc,a[3])):
        if part[0]<part[1] or part[0]==part[1] and part[2] and part[3]:result.append(part)
    return result


def interval(a):
    return dict(lower=pair(a[0]),upper=pair(a[1]),lowerInclusive=a[2],upperInclusive=a[3])
