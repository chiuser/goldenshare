import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from reports.xxm_forecast_range_precheck_20261014 import range_model as m
from src.biz.services.wealth.market.index_detail_xxm.types import Wave,XxmBar
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.projection import ProjectionState
T0='2020-01-02T15:00:00+08:00';T1='2020-01-03T10:30:00+08:00';T2='2020-01-03T11:30:00+08:00'

def wave(s,price,dif,date='2019-01-02T10:30:00+08:00',count=4):return Wave(s,date,date,count,price,dif,date,date)

def c(sign,price,dif,dea):
    value=XxmCalculator(period='m60',source_identity='synthetic-boundary')
    value.wave=wave(sign,price,dif,T0,1);value.previous=XxmBar(T0,price,dif,dea,2*(dif-dea));return value

v=c(-1,85,-1,2);v.history[-1]=[wave(-1,90,-20),wave(-1,100,-10,'2019-02-01T10:30:00+08:00')]
p=ProjectionState(99,100,2)
a=m.solve_entry_ranges(v,p,T1)
assert any(m.as_interval(r['priceRange']).contains(105) for r in a['ranges'])
assert m.activation_signature(v,p,105,T1)['price']==90
before=v.snapshot();result=m.make_result(v,p,[T1,T2]);assert result['targetEndpoint']==T2 and v.snapshot()==before
v.wave.count=0;assert not m.solve_entry_ranges(v,p,T1)['ranges']

v=c(1,105,8,4);v.history[1]=[wave(1,110,20),wave(1,100,10,'2019-02-01T10:30:00+08:00')]
p=ProjectionState(108,100,4)
a=m.solve_entry_ranges(v,p,T1)
assert m.activation_signature(v,p,107,T1)['price']==100
assert m.activation_signature(v,p,111,T1)['price']==110
assert len(a['ranges'])>=2

v=c(-1,100,-1,0);v.wave.count=4;v.reference=wave(-1,110,-2);v.state='DULL';p=ProjectionState(100,100,0)
assert not m.event_options(v,p,100,T1,'STRUCTURE')[0][2] # exact zero H
v.reference=wave(-1,110,-10);p=ProjectionState(80,100,-50)
# Positive H with DIF below the old reference cancels before a bottom flip.
bar,vals=p.project(100,T1,'m60');step=m.clone(v).step(bar)
assert any(e['type']=='CANCEL' for e in step.events)
assert not any(e['type']=='STRUCTURE' for e in step.events)

# A mature top DULL with very negative DIF can have no positive-close solution
# on the next bar; this verifies the whole 20-bar horizon is not assumed j=1.
v=c(1,1,-600,-1000);v.wave=wave(1,1,-500,T0,4);v.reference=wave(1,.5,-100);v.state='DULL';p=ProjectionState(400,1000,-1000)
slots=[f'2020-01-{day:02d}T15:00:00+08:00' for day in range(3,23)]
result=m.make_result(v,p,slots)
assert result['status']=='NO_CANDIDATE' and result['reasonCode']=='NO_CONFIRMATION_IN_HORIZON'
print(json.dumps(dict(status='PASS',cases=['already_price_extreme_above_old_low','min_bars','strongest_ref_switch','zero_hist','cancellation_before_flip','full_20_bar_no_solution'],noSolution=result['status'])))
