"""Retrospective, bounded numeric audit of existing minute-chart screenshots.

No marker fitting, formal indicator changes, network, Lake/DB access, or imports
of Dagster resources. Software numbers are terminal readouts, not a recovered
per-bar history. Controls below are explicit finite implementations, not a claim
about the original software. Initial states are recovered from DG only.
"""
import csv
import hashlib
import json
import itertools
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = {60:'60_20250603_20261009.csv',90:'90_20250603_20260113.csv',
         120:'120_20250401_20251111.csv'}
# (period, date, image, close, DIF, DEA, histogram); unreadable values stay None.
OBS = [
 (120,'2025-06-25','sources/20250625_120.png',3455.97,12.048,4.513,15.069),
 (120,'2025-06-26','sources/20250626_120.png',3448.45,17.443,8.885,17.116),
 (120,'2025-07-11','sources/20250711_120.png',3510.18,26.367,23.778,5.178),
 (120,'2025-07-23','sources/20250723_120.png',3582.30,29.954,24.672,10.563),
 (120,'2025-08-08','IMG_0318.PNG',3635.13,21.612,19.670,3.884),
 (120,'2025-08-12','IMG_0358.PNG',3665.92,24.917,22.157,5.519),
 (120,'2025-08-18','sources/20250818_120.png',3728.03,33.190,28.511,9.358),
 (120,'2025-10-16','sources/20251016_120.png',3916.23,15.519,13.741,3.557),
 (120,'2025-10-27','sources/20251027_120.png',3996.94,25.717,15.981,19.472),
 (120,'2026-05-07','IMG_0310.PNG',4180.09,35.653,29.911,11.483),
 (120,'2026-09-01','IMG_0360.PNG',3979.89,17.049,9.777,14.544),
 (90,'2025-08-06','IMG_0374.PNG',3633.99,12.244,7.817,8.855),
 (90,'2025-08-12','IMG_0359.PNG',3665.92,18.704,16.557,4.293),
 (90,'2025-08-14','IMG_0315.PNG',3666.44,20.435,20.109,.652),
 (90,'2026-01-13','IMG_0369.PNG',4138.76,45.344,44.449,1.790),
 (60,'2025-12-16','sources/20251216_60.png',3824.81,-16.223,-9.596,-13.253),
 (60,'2026-01-13','IMG_0370.PNG',4138.76,36.343,37.311,-1.936),
 (60,'2026-04-07','IMG_0366.PNG',3890.16,-10.804,-8.638,-4.331),
 (60,'2026-04-20','IMG_0361.PNG',4082.13,25.084,24.306,None),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    with (ROOT/'inputs'/name).open() as f:
        rows=[{k:(v if k=='trade_time' else float(v)) for k,v in r.items()}
              for r in csv.DictReader(f)]
    assert len(rows)<3000
    for r in rows:
        r.setdefault('dea',r['dif']-r['hist']/2)
    return rows


def f32(x):
    return struct.unpack('f',struct.pack('f',x))[0]


def simulate(rows, mode, digits=None):
    af,asl,ad=2/13,2/27,2/10
    if mode=='coefficient_round': af,asl,ad=[round(x,digits) for x in (af,asl,ad)]
    if mode=='float32_all': af,asl,ad=[f32(x) for x in (af,asl,ad)]
    bf,bs=1-af,1-asl
    # Match the first two DG DIF rows under these coefficients, not software.
    slow=rows[1]['close']+(bf*rows[0]['dif']-rows[1]['dif'])/(af-asl)
    fast=slow+rows[0]['dif'];dea=rows[0]['dea']
    if mode.startswith('float32'):fast,slow,dea=[f32(x) for x in (fast,slow,dea)]
    result=[dict(trade_time=rows[0]['trade_time'],dif=fast-slow,dea=dea,hist=2*(fast-slow-dea))]
    for row in rows[1:]:
        c=row['close']
        if mode=='close_round':c=round(c,digits)
        if mode=='float32_all':
            c=f32(c)
            fast=f32(f32(f32(1-af)*fast)+f32(af*c))
            slow=f32(f32(f32(1-asl)*slow)+f32(asl*c))
            d=f32(fast-slow)
            dea=f32(f32(f32(1-ad)*dea)+f32(ad*d))
            h=f32(2*f32(d-dea))
        else:
            fast=bf*fast+af*c;slow=bs*slow+asl*c
            if mode=='ema_state_round':fast,slow=round(fast,digits),round(slow,digits)
            if mode=='float32_state':fast,slow=f32(fast),f32(slow)
            d=fast-slow;dea=(1-ad)*dea+ad*d
            if mode=='ema_state_round':dea=round(dea,digits)
            if mode=='float32_state':dea=f32(dea)
            h=2*(d-dea)
        result.append(dict(trade_time=row['trade_time'],dif=d,dea=dea,hist=h))
    return result


def solve_three(a,b):
    """Three-plane intersection via Cramer; no external solver dependency."""
    def det(m):
        return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
                -m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
                +m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))
    d=det(a)
    if abs(d)<1e-16:return None
    return tuple(det([[b[i] if j==k else a[i][j] for j in range(3)] for i in range(3)])/d for k in range(3))


def history_feasibility(rows,observations,price_digits,tolerance):
    """Does one continuous known close series permit all display intervals?

    Three free state offsets at the first screenshot (fast EMA, slow EMA, DEA).
    Later offsets follow the exact linear recurrence. The first two dates' DIF
    and first DEA bound all three dimensions. Checking vertices is therefore
    sufficient for this bounded, full-rank three-dimensional interval problem.
    Software display intervals are symmetric conservative hypotheses, not
    certified display behavior. A witness is explanatory fitting, not a rule.
    """
    obs=sorted(observations,key=lambda r:r['time'])
    start=next(i for i,r in enumerate(rows) if r['trade_time']==obs[0]['time'])
    af,asl,ad=2/13,2/27,2/10;bf,bs,bd=1-af,1-asl,1-ad
    r0,r1=rows[start],rows[start+1]
    slow=r1['close']+(bf*r0['dif']-r1['dif'])/(af-asl)
    fast=slow+r0['dif'];dea=r0['dea']
    fv,sv,av=(1.,0.,0.),(0.,1.,0.),(0.,0.,1.)
    by_time={o['time']:o for o in obs};constraints=[];predictions=[]
    for i,row in enumerate(rows[start:]):
        if row['trade_time']>obs[-1]['time']:break
        if i:
            close=row['close'] if price_digits is None else round(row['close'],price_digits)
            fast=bf*fast+af*close;slow=bs*slow+asl*close
            fv=tuple(bf*x for x in fv);sv=tuple(bs*x for x in sv)
            dv=tuple(x-y for x,y in zip(fv,sv))
            dea=bd*dea+ad*(fast-slow)
            av=tuple(bd*x+ad*y for x,y in zip(av,dv))
        dv=tuple(x-y for x,y in zip(fv,sv))
        hv=tuple(2*(x-y) for x,y in zip(dv,av))
        base=dict(dif=fast-slow,dea=dea,hist=2*(fast-slow-dea))
        if row['trade_time'] in by_time:
            o=by_time[row['trade_time']]
            for k,v in [('dif',dv),('dea',av),('hist',hv)]:
                target=o['software'][k]-base[k]
                constraints.extend([(v,target+tolerance),(tuple(-x for x in v),-target+tolerance)])
                predictions.append(dict(date=o['date'],field=k,base=base[k],vector=v,software=o['software'][k]))
    # First date DIF and DEA plus second date DIF form an invertible basis.
    normals=[constraints[i][0] for i in (0,2,6)]
    assert solve_three(normals,[0,0,0]) is not None
    # Independent contradiction check: outer parallelepiped defined by first
    # DIF/DEA and second DIF. Every feasible state must lie in this envelope.
    cube_vertices=[]
    for bits in itertools.product((0,1),repeat=3):
        b=[constraints[k if bit==0 else k+1][1]*(1 if bit==0 else -1)
           for k,bit in zip((0,2,6),bits)]
        cube_vertices.append(solve_three(normals,b))
    certificates=[]
    for p in predictions:
        values=[p['base']+sum(a*b for a,b in zip(p['vector'],x)) for x in cube_vertices]
        lo,hi=min(values),max(values)
        wanted_lo,wanted_hi=p['software']-tolerance,p['software']+tolerance
        if hi<wanted_lo-1e-9 or lo>wanted_hi+1e-9:
            certificates.append(dict(date=p['date'],field=p['field'],
                possible_from_first_two_dates=[lo,hi],required_display_interval=[wanted_lo,wanted_hi]))
    witness=None;vertices=0
    for triple in itertools.combinations(constraints,3):
        x=solve_three([v for v,b in triple],[b for v,b in triple])
        if x is None:continue
        vertices+=1
        if all(sum(a*b for a,b in zip(v,x))<=bound+1e-9 for v,bound in constraints):
            witness=x;break
    if witness is None:assert certificates, 'Numerical vertex absence alone is not a rejection certificate'
    residuals=[]
    direct_verification_max=None
    if witness:
        # Recompute directly from perturbed EMA states, independently of the
        # sensitivity vectors used by the feasibility search.
        r0,r1=rows[start],rows[start+1]
        slow=r1['close']+(bf*r0['dif']-r1['dif'])/(af-asl)+witness[1]
        fast=(slow-witness[1])+r0['dif']+witness[0];dea=r0['dea']+witness[2]
        direct={}
        for i,r in enumerate(rows[start:]):
            if r['trade_time']>obs[-1]['time']:break
            if i:
                close=r['close'] if price_digits is None else round(r['close'],price_digits)
                fast=bf*fast+af*close;slow=bs*slow+asl*close
                dea=bd*dea+ad*(fast-slow)
            direct[r['trade_time']]=dict(dif=fast-slow,dea=dea,hist=2*(fast-slow-dea))
        direct_verification_max=max(abs(direct[o['time']][k]-o['software'][k]) for o in obs for k in ('dif','dea','hist'))
        assert direct_verification_max<=tolerance+1e-8
        for p in predictions:
            actual=p['base']+sum(a*b for a,b in zip(p['vector'],witness))
            residuals.append(dict(date=p['date'],field=p['field'],calculated=actual,residual=actual-p['software']))
    return dict(price_digits=price_digits,display_tolerance=tolerance,anchor=obs[0]['time'],
        observations=len(obs),constraints=len(constraints),nondegenerate_vertices_checked=vertices,
        incompatible_interval_certificates=certificates,
        feasible=witness is not None,state_offsets=witness,residuals=residuals,
        direct_recurrence_verification_max_residual=direct_verification_max,
        interpretation='Existence within explicit intervals, not recovered software history or a held-out validation.')


def main():
    protected_path=Path('/private/tmp/xxm_numeric_crossperiod_before_20261012.json')
    protected=json.loads(protected_path.read_text())
    assert all(sha(ROOT/name)==digest for name,digest in protected.items())
    manifest=json.loads((ROOT/'screenshot_manifest.json').read_text())
    input_names=set(FILES.values())|{'120_20260101_20260507.csv','120_20260701_20260901.csv'}
    inputs={name:read(name) for name in sorted(input_names)}
    observations=[]
    for freq,date,img,c,d,a,h in OBS:
        name=FILES[freq]
        if freq==120 and date>'2025-11-11':
            name=('120_20260101_20260507.csv' if date<'2026-07-01' else '120_20260701_20260901.csv')
        rows=inputs[name];time=date+' 15:00:00'
        r=next(x for x in rows if x['trade_time']==time)
        path=ROOT/img if img.startswith('sources/') else Path('/Users/congming/Downloads')/img
        digest=sha(path)
        assert any(m['sha256']==digest for m in manifest)
        sw=dict(close=c,dif=d,dea=a,hist=h)
        delta={k:(None if sw[k] is None else sw[k]-r[k]) for k in sw}
        observations.append(dict(freq=freq,date=date,time=time,image=str(path),image_sha256=digest,
            input=name,software=sw,dg={k:r[k] for k in sw},software_minus_dg=delta,
            dif_within_conservative_display_unit=abs(delta['dif'])<=.001+1e-9,
            all_readable_indicators_within_display_unit=all(v is None or abs(v)<=.001+1e-9 for k,v in delta.items() if k!='close'),
            close_matches_two_decimals=abs(delta['close'])<=.0051,
            hist_identity_display_residual=None if h is None else h-2*(d-a),
            observation_type='terminal_readout_not_continuous_software_series'))
    grouped=[]
    for freq in (60,90,120):
        rs=[r for r in observations if r['freq']==freq]
        ds=[r['software_minus_dg']['dif'] for r in rs]
        grouped.append(dict(freq=freq,count=len(rs),dif_abs_min=min(map(abs,ds)),dif_abs_max=max(map(abs,ds)),
            min_delta=min(ds),max_delta=max(ds),dif_display_compatible=sum(r['dif_within_conservative_display_unit'] for r in rs),
            all_indicator_display_compatible=sum(r['all_readable_indicators_within_display_unit'] for r in rs),
            fixed_dif_shift_feasible=max(x-.001 for x in ds)<=min(x+.001 for x in ds),
            fixed_shift_interval_lower=max(x-.001 for x in ds),fixed_shift_interval_upper=min(x+.001 for x in ds)))
    modes=[('standard',None),('close_round',2),('float32_state',None),('float32_all',None)]
    modes += [(m,n) for m in ('ema_state_round','coefficient_round') for n in (2,3,4,5,6)]
    controls=[];prefix_count=0
    for mode,n in modes:
        simulations={name:simulate(rows,mode,n) for name,rows in inputs.items()}
        comparisons=[]
        for obs in observations:
            rows=inputs[obs['input']];i=next(i for i,r in enumerate(rows) if r['trade_time']==obs['time'])
            predicted=simulations[obs['input']][i]
            # Key controls have exact prefix invariance, avoiding future input.
            if mode in ('standard','float32_all','ema_state_round'):
                assert simulate(rows[:i+1],mode,n)[-1]==predicted
                prefix_count+=1
            differences={k:predicted[k]-obs['software'][k] for k in ('dif','dea','hist') if obs['software'][k] is not None}
            comparisons.append(dict(nearest_three_decimal_all_match=all(round(predicted[k],3)==obs['software'][k] for k in differences),freq=obs['freq'],date=obs['date'],predicted=predicted,
                residual=differences,all_indicators_within_display_unit=all(abs(v)<=.001+1e-9 for v in differences.values()),
                dif_within_display_unit=abs(differences['dif'])<=.001+1e-9))
        controls.append(dict(mode=mode,digits=n,by_period=[dict(freq=f,count=sum(c['freq']==f for c in comparisons),
            dif_matches=sum(c['freq']==f and c['dif_within_display_unit'] for c in comparisons),
            all_indicator_matches=sum(c['freq']==f and c['all_indicators_within_display_unit'] for c in comparisons),
            exact_nearest_display_matches=sum(c['freq']==f and c['nearest_three_decimal_all_match'] for c in comparisons)) for f in (60,90,120)],comparisons=comparisons))
    # Independent standard recurrence parity with the saved series (first two identify state).
    parity=[]
    for name,rs in inputs.items():
        calculated=simulate(rs,'standard')
        residual=max(abs(x[k]-y[k]) for x,y in zip(calculated[2:],rs[2:]) for k in ('dif','dea','hist'))
        assert residual<1e-8
        parity.append(dict(input=name,rows=len(rs),max_residual=residual))
    assert all(r['close_matches_two_decimals'] for r in observations)
    assert all(r['hist_identity_display_residual'] is None or abs(r['hist_identity_display_residual'])<=.0031 for r in observations)
    history_cases=[]
    o120=[o for o in observations if o['freq']==120 and o['date']<'2026']
    for price_digits in (None,2):
        for tolerance in (.0005,.001):
            history_cases.append(history_feasibility(inputs[FILES[120]],o120,price_digits,tolerance))
    # Interior witness avoids treating a display-rounding tie as evidence.
    history_cases.append(history_feasibility(inputs[FILES[120]],o120,2,.00049))
    assert history_cases[-1]['feasible']
    report=dict(history_interval_cases=history_cases,as_of='2026-10-12 Asia/Shanghai',scope='Existing terminal screenshots only; retrospective controls, no new software labels.',
        observations=observations,period_summaries=grouped,controls=controls,standard_recurrence_parity=parity,
        prefix_checks=prefix_count,inputs={n:sha(ROOT/'inputs'/n) for n in inputs},
        protected_files=protected,protected_files_unchanged=True,script_sha256=sha(Path(__file__)),
        unavailable=[dict(freq=120,date='2025-12-16',reason='Software screenshot available, saved 120 CSV ends 2025-11-11.'),
                     dict(freq=90,date='2025-12-16',reason='DG available, no same-period software screenshot.'),
                     dict(freq=90,start='2025-12-05',end='2025-12-16',reason='No numeric software per-bar history; drawn curves cannot yield three-decimal DIF.')],
        conclusions=['Small 120-minute differences are not ordinary nearest-rounding proof.',
                     'No fixed DIF correction works across these four 90-minute observations, or across the four 60-minute observations.',
                     'Specified precision controls cannot be promoted to a software implementation merely by partial fit.',
                     '19 terminal numbers do not supply software values for prior peaks or December16 intraday bars.'],
        limits=['Two-decimal controls use Python round; vendor tie-breaking is not known.',
                'Tolerance .001 is a conservative display-unit compatibility screen, not a bound on unknown software internal errors.',
                'Rounded state/coefficient controls start from DG-derived states, not the software loaded history.',
                'Float32_all is one explicitly parenthesized implementation, not every possible floating-point evaluation order.',
                'No precision-mode tuning or software marker fitting; no blind/out-of-sample claim.',
                'April20 histogram partly obscured: excluded rather than inferred from displayed DIF and DEA.'])
    (ROOT/'software_numeric_history_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (ROOT/'software_numeric_history.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['freq','date','software_close','dg_close','software_dif','dg_dif','delta_dif','software_dea','dg_dea','delta_dea','software_hist','dg_hist','delta_hist','image_sha256'])
        w.writeheader()
        for r in observations:
            w.writerow(dict(freq=r['freq'],date=r['date'],image_sha256=r['image_sha256'],
                **{f'{s}_{k}':r[s][k] for s in ('software','dg') for k in ('close','dif','dea','hist')},
                **{f'delta_{k}':r['software_minus_dg'][k] for k in ('dif','dea','hist')}))
    print(json.dumps(dict(observations=len(observations),periods=grouped,prefix_checks=prefix_count,
        history_cases=[{k:v for k,v in x.items() if k not in ('residuals','interpretation')} for x in history_cases],
        controls=[dict(mode=c['mode'],digits=c['digits'],counts=c['by_period']) for c in controls],
        protected_files=len(protected)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
