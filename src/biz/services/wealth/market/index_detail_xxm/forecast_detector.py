"""All hypothetical events are decided by independent original-kernel copies."""
import json
from itertools import product
from .calculator import XxmCalculator
from .types import XxmBar
from .forecast_math import source_options


def clone(c):
    child = XxmCalculator(period=c.period, source_identity=c.source_identity, ts_code=c.ts_code, spec=c.spec)
    child.restore(c.snapshot())
    return child


def possible_bars(projection, close, stamp, day):
    projected, (d, a, h) = projection.advance(close)
    return projected, tuple(XxmBar(stamp, close, dd, round(a, 3) if day else a, hh)
                            for dd, hh in product(source_options(d, day), source_options(h, day)))


def event_options(c, projection, close, stamp, kind, check=lambda: None):
    state, bars = possible_bars(projection, close, stamp, c.period == 'day')
    results = []
    for bar in bars:
        check()
        child = clone(c)
        step = child.step(bar)
        event = next((e for e in step.events if e['type'] == kind and e['direction'] == ('TOP' if c.wave.sign > 0 else 'BOTTOM')), None)
        results.append((child, state, event))
    return results


def activation_signature(c, projection, p, stamp):
    options = event_options(c, projection, p, stamp, 'DULL')
    events = [o[2] for o in options]
    route = 'reactivation' if c.pending_rearm is not None else 'activation'
    if events and all(e is not None and e['route'] == route for e in events):
        refs = {e['eventReference']['startTime'] for e in events}
        if len(refs) == 1:
            return events[0]['eventReference']
    if any(events):
        return 'PRECISION_UNRESOLVED'
    return None


def confirmed_options(c,projection,stamps,p,target,route,reference,check=lambda: None,*,reference_transitions=()):
    states=[(clone(c),projection)]
    for stamp in stamps[:-1]:
        expected=reference
        for transition in reference_transitions:
            if transition['endpoint']<=stamp:expected=transition['toReference']
        newer=[]
        for state,proj in states:
            check()
            next_proj,bars=possible_bars(proj,p,stamp,c.period=='day')
            for bar in bars:
                check()
                child=clone(state);step=child.step(bar)
                if child.state!='DULL' or child.reference.reference()!=expected:return False
                if any(e['type'] in ('CANCEL','STRUCTURE') for e in step.events):return False
                newer.append((child,next_proj))
        # Source-rounding variants can converge to identical original state.
        # Keep every distinct state; avoid exponential copies of the same one.
        if len(newer)>1:
            unique={}
            for state,proj in newer:
                check()
                key=json.dumps(state.snapshot(),sort_keys=True,separators=(',',':'))
                unique.setdefault(key,(state,proj))
            states=list(unique.values())
        else:states=newer
    final_reference=reference_transitions[-1]['toReference'] if reference_transitions else reference
    for state,proj in states:
        check()
        options=event_options(state,proj,target,stamps[-1],'STRUCTURE',check)
        if not all(o[2] and o[2]['route']==route and o[2]['eventReference']==final_reference for o in options):return False
    return True
