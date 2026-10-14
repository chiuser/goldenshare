import csv
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import random

import pytest
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone, activation_signature, confirmed_options, event_options
from src.biz.services.wealth.market.index_detail_xxm.forecast_entry import solve_entry_ranges, entry_cuts
from src.biz.services.wealth.market.index_detail_xxm.forecast_math import Interval, as_interval, display_range, project_affine_prefix, K
from src.biz.services.wealth.market.index_detail_xxm.forecast_joint import close_bounds, survival_reason, domains_for_target
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState, ProjectionPrecisionError, recover_projection
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar, Wave
from src.biz.queries.wealth.market.index_detail_xxm.source import ENDPOINTS, CN_ZONE

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "reports/xxm_source_audit_20261013_213852"


def frozen(period):
    path = SOURCE / ("daily_source.csv" if period == "day" else f"minute_{period[1:]}_source.csv")
    with path.open() as f:
        rows = list(csv.DictReader(f))
    if period == "day":
        return tuple(XxmBar(r["trade_date"], float(r["close"]), float(r["macd_dif_bfq"]), float(r["macd_dea_bfq"]), float(r["macd_bfq"])) for r in rows)
    return tuple(XxmBar(r["trade_time"].replace(" ", "T") + "+08:00", float(r["close"]), float(r["macd_dif"]), float(r["macd_dea"]), float(r["macd"])) for r in rows)


def endpoints(period, through):
    rows = sorted({r["trade_date"]:r for r in json.loads((SOURCE / "sse_minute_calendar.json").read_text()) + json.loads((ROOT / "reports/xxm_forecast_precheck_20261014/future_sse_calendar.json").read_text())["rows"]}.values(),key=lambda r:r["trade_date"])
    slots = []
    for r in rows:
        if not r["is_open"]:
            continue
        for t in ([None] if period == "day" else ENDPOINTS[int(period[1:])]):
            stamp = r["trade_date"] if t is None else datetime.combine(date.fromisoformat(r["trade_date"]), t, CN_ZONE).isoformat()
            if stamp > through:
                slots.append(stamp)
    return slots[:20]


def replay(bars, period):
    c = XxmCalculator(period=period, source_identity="frozen-test")
    for b in bars:
        c.step(b)
    return c


@pytest.mark.parametrize("period,target", [("day", "2026-10-15"), ("m60", None), ("m90", "2026-10-14T14:00:00+08:00"), ("m120", None)])
def test_frozen_nearest_endpoint_full_ranges_and_no_real_mutation(period, target):
    bars = frozen(period);c = replay(bars, period);projection = recover_projection(bars, period, lambda: None)
    before=c.snapshot();slots=endpoints(period,bars[-1].time)
    result=forecast(c,projection,slots)
    assert result["targetEndpoint"] == target and c.snapshot()==before
    assert forecast(c,projection,slots)==result
    assert "scenarios" not in result
    validate_replay(c,projection,slots,result)
    if period=="day":
        act=result["activation"]["ranges"][0]["priceRange"]
        assert act["lower"] < 3500 < act["upper"] < 3764.16
        assert any(3500 < e["preClose"] < 3764 for e in result["examples"])
        assert len(result["commonConditions"])==2


def validate_replay(c,projection,slots,result):
    rng=random.Random(1209);activation=result['activation']
    if activation:
        # Complete activation partition, including exact/one-ULP cuts.
        for cut in entry_cuts(c,projection):
            for p in (cut,math.nextafter(cut,0),math.nextafter(cut,math.inf),cut-.0001,cut+.0001):
                if p<=0:continue
                owners=[r for r in activation['ranges']+activation['exclusions'] if as_interval(r['priceRange']).contains(p)]
                assert len(owners)==1
                hit=activation_signature(c,projection,p,slots[0]);owner=owners[0]
                if 'reference' in owner:assert hit==owner['reference']
                elif owner['reason']!='PRECISION_UNRESOLVED':assert hit is None
    if not result['relations']:return
    j=result['barsAhead'];ds,hs,d,h=project_affine_prefix(projection,j-1)
    domains=result['targetEntryRanges'] if activation else [dict(priceRange=Interval(c.previous.close,c.previous.close,True,True).json(),entryRangeIds=[])]
    for domain in domains:
        iv=as_interval(domain['priceRange'])
        prices=[iv.lo] if iv.lo==iv.hi else [rng.uniform(iv.lo+1e-6,iv.hi-1e-6) for _ in range(20)]
        ref=next(r['reference'] for r in activation['ranges'] if r['entryRangeId'] in domain['entryRangeIds']) if activation else c.reference.reference()
        for p in prices:
            for route in ('dif_turn','color_flip'):
                raw=close_bounds(c,ref,ds,d,h,p,route);shown=display_range(raw) if raw else None
                if shown:
                    for close in [shown['displayLower'],shown['displayUpper'] or shown['displayLower']+10000]:
                        assert confirmed_options(c,projection,slots[:j],p,close,route,ref)
    for common in result['commonConditions']:
        iv=as_interval(common['entryDomain']) if common['entryDomain'] else Interval(c.previous.close,c.previous.close,True,True)
        for p in ([iv.lo] if iv.lo==iv.hi else [rng.uniform(iv.lo+1e-6,iv.hi-1e-6) for _ in range(20)]):
            for shown in common['closeRanges']:
                for close in [shown['displayLower'],shown['displayUpper'] or shown['displayLower']+10000]:
                    assert confirmed_options(c,projection,slots[:j],p,close,common['route'],common['reference'])
    if activation:
        for entry in activation['ranges']:
            iv=as_interval(entry['priceRange'])
            relevant=[r for r in result['targetEntryRanges']+result['targetEntryExclusions'] if entry['entryRangeId'] in r['entryRangeIds']]
            for p in [iv.lo+(iv.hi-iv.lo)*t for t in (.001,.25,.5,.75,.999)]:
                assert sum(as_interval(r['priceRange']).contains(p) for r in relevant)==1


T0='2020-01-02T15:00:00+08:00';T1='2020-01-03T10:30:00+08:00';T2='2020-01-03T11:30:00+08:00'
def wave(sign,price,dif,stamp='2019-01-02T10:30:00+08:00',count=4):
    return Wave(sign,stamp,stamp,count,price,dif,stamp,stamp)
def synthetic(sign,price,dif,dea):
    c=XxmCalculator(period='m60',source_identity='synthetic')
    c.wave=wave(sign,price,dif,T0,1);c.previous=XxmBar(T0,price,dif,dea,2*(dif-dea));return c


def test_price_above_old_low_can_activate_when_wave_already_made_new_low():
    c=synthetic(-1,85,-1,2);c.history[-1]=[wave(-1,90,-20),wave(-1,100,-10,'2019-02-01T10:30:00+08:00')]
    p=ProjectionState(99,100,2);a=solve_entry_ranges(c,p,T1)
    assert any(as_interval(r['priceRange']).contains(105) for r in a['ranges'])
    assert activation_signature(c,p,105,T1)['price']==90
    result=forecast(c,p,[T1,T2]);assert result['targetEndpoint']==T2
    c.wave.count=0;assert not solve_entry_ranges(c,p,T1)['ranges']


def test_strongest_qualified_reference_changes_with_price_not_tied_to_example():
    c=synthetic(1,105,8,4);c.history[1]=[wave(1,110,20),wave(1,100,10,'2019-02-01T10:30:00+08:00')]
    p=ProjectionState(108,100,4)
    assert activation_signature(c,p,107,T1)['price']==100
    assert activation_signature(c,p,111,T1)['price']==110
    assert len(solve_entry_ranges(c,p,T1)['ranges'])>=2


def test_zero_and_reference_break_and_intermediate_flip_order():
    c=synthetic(-1,100,-1,0);c.wave.count=4;c.reference=wave(-1,110,-2);c.state='DULL'
    assert not event_options(c,ProjectionState(100,100,0),100,T1,'STRUCTURE')[0][2]
    c.reference=wave(-1,110,-10);p=ProjectionState(80,100,-50)
    child=clone(c);bar,_=p.project(100,T1,'m60');events=child.step(bar).events
    assert events[0]['type']=='CANCEL'
    from src.biz.services.wealth.market.index_detail_xxm.forecast_math import Affine
    ds=[Affine(b=-1),Affine(b=-11)];hs=[Affine(b=-1),Affine(b=1)]
    assert survival_reason(c,c.reference.reference(),ds,hs,100)=='CANCEL_BEFORE_TARGET'
    ds[1]=Affine(b=-9)
    assert survival_reason(c,c.reference.reference(),ds,hs,100)=='EARLY_STRUCTURE'
    hs[1]=Affine(b=0)
    assert survival_reason(c,c.reference.reference(),ds,hs,100)=='COLOR_OR_ZERO'


def test_earlier_narrow_interval_is_not_skipped():
    c=synthetic(1,100,0,-1);c.reference=wave(1,90,10);c.state='DULL'
    # With zero previous DIF the 1% turn is disabled. The flip interval is
    # positive but narrower than the four-decimal display lattice.
    base=100*11/13-100*25/27
    result=forecast(c,ProjectionState(100,100,base+K*.00001),[T1,T2])
    assert result['status']=='PRECISION_PENDING' and result['reasonCode']=='NARROW_INTERVAL'
    assert result['targetEndpoint']==T1 and result['barsAhead']==1


def test_whole_twenty_bar_horizon_has_no_positive_close_solution():
    c=synthetic(1,1,-600,-1000);c.wave=wave(1,1,-500,T0,4);c.reference=wave(1,.5,-100);c.state='DULL'
    slots=[f'2020-01-{day:02d}T15:00:00+08:00' for day in range(3,23)]
    result=forecast(c,ProjectionState(400,1000,-1000),slots)
    assert result['status']=='NO_CANDIDATE' and result['reasonCode']=='NO_CONFIRMATION_IN_HORIZON'


def test_daily_half_tick_not_guessed():
    from src.biz.services.wealth.market.index_detail_xxm.projection import near_rounding_tie
    assert near_rounding_tie(.0005) and near_rounding_tie(-.0005)
    assert not near_rounding_tie(.00050001)
    p=ProjectionState(100,100,0);b=100*11/13-100*25/27
    with pytest.raises(ProjectionPrecisionError,match='ROUNDING_BOUNDARY'):p.project((.0005-b)/K,'2020-01-03','day')


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
def test_calibration_requires_full_tail_and_rejects_changed_source(period):
    from dataclasses import replace
    bars=frozen(period)
    with pytest.raises(ProjectionPrecisionError,match='CALIBRATION_FAILED'):recover_projection(bars[:249],period,lambda:None)
    with pytest.raises(ProjectionPrecisionError):recover_projection((*bars[:-1],replace(bars[-1],dif=bars[-1].dif+1)),period,lambda:None)


@pytest.mark.parametrize('period',['day','m60','m90','m120'])
def test_history_states_signs_replay_rebuild_and_no_future_leak(period):
    bars=frozen(period);c=XxmCalculator(period=period,source_identity='frozen-test');selected={}
    for i,b in enumerate(bars):
        c.step(b)
        if i>=250:selected[(c.state,c.wave.sign)]=(i,c.snapshot())
    assert {'NONE','DULL','STRUCTURE'} <= {key[0] for key in selected}
    for (state,sign),(idx,snapshot) in selected.items():
        prefix=bars[:idx+1];child=replay(prefix,period);assert child.snapshot()==snapshot
        before=child.snapshot();proj=None if state=='STRUCTURE' else recover_projection(prefix,period,lambda:None);slots=endpoints(period,prefix[-1].time)
        result=forecast(child,proj,slots);assert child.snapshot()==before
        validate_replay(child,proj,slots,result)
        if state=='STRUCTURE':assert result['status']=='CONFIRMED' and result['targetEndpoint'] is None
        if idx+1<len(bars):
            child.step(bars[idx+1]);assert child.snapshot()==replay(bars[:idx+2],period).snapshot()


def test_original_replay_variants_obey_budget_check_without_mutating_real_state():
    c=synthetic(-1,100,-1,0);c.wave.count=4;c.reference=wave(-1,110,-2);c.state='DULL';before=c.snapshot()
    def reject():raise TimeoutError('budget checkpoint')
    with pytest.raises(TimeoutError,match='budget checkpoint'):
        confirmed_options(c,ProjectionState(100,100,0),[T1,T2],100,110,'color_flip',c.reference.reference(),reject)
    assert c.snapshot()==before
