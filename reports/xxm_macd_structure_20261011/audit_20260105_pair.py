"""Archive and check Jan5 60/90 screenshots against unchanged research models.

The 60-minute yellow label is regional state evidence, not an exact new-event
anchor. Only the 90-minute DULL/CANCEL pair is added conditionally, with yellow
mapped to14:00 and green terminal direct. Numbers remain source-separated.
"""
import hashlib
import json
import shutil
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows
from audit_software_numeric_history import read, history_feasibility, simulate
from audit_turn_filters import labels50

ROOT=Path(__file__).resolve().parent
CASES=[
 dict(freq=60,input='60_20250603_20261009.csv',original='/var/folders/0x/12zkmckd1hb2vfp3w4vb7w480000gn/T/codex-clipboard-61621da6-a007-433c-bc86-f43190995a87.png',saved='sources/20260105_60.png',dif=20.358,dea=16.594,hist=7.529),
 dict(freq=90,input='90_20250603_20260113.csv',original='/var/folders/0x/12zkmckd1hb2vfp3w4vb7w480000gn/T/codex-clipboard-baa1cb68-d15e-4d14-9af2-be30cab63173.png',saved='sources/20260105_90.png',dif=23.658,dea=20.306,hist=6.703)]
MODES=('locked','both_before','dull_before','both_after')
GATES=(.75,1,1.2)


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    protected=json.loads(Path('/private/tmp/xxm_jan5_before_20261012.json').read_text())
    assert sha(ROOT/'active_reference_candidate.py')==protected['active_reference_candidate.py']
    assert sha(ROOT/'audit_software_numeric_history.py')==protected['audit_software_numeric_history.py']
    manifest_path=ROOT/'screenshot_manifest.json'
    manifest=json.loads(manifest_path.read_text())
    old=manifest[:35]
    assert len(old)==35
    for name,digest in protected.items():
        if name!='screenshot_manifest.json':assert sha(ROOT/name)==digest,name
    # The original serialized manifest is reconstructable byte-for-byte.
    assert hashlib.sha256((json.dumps(old,ensure_ascii=False,indent=2)+'\n').encode()).hexdigest()==protected['screenshot_manifest.json']
    sources=[]
    for case in CASES:
        original=Path(case['original']);saved=ROOT/case['saved']
        if not saved.exists():shutil.copyfile(original,saved)
        if original.exists():assert original.read_bytes()==saved.read_bytes()
        entry=dict(file=original.name,original_path=str(original),saved_path=str(saved),
                   bytes=saved.stat().st_size,sha256=sha(saved),image_date='2026-01-05',period=str(case['freq']))
        prior=[m for m in manifest if m['saved_path']==str(saved)] if all('saved_path' in m for m in manifest) else [m for m in manifest if m.get('saved_path')==str(saved)]
        if prior:assert prior==[entry]
        else:manifest.append(entry)
        sources.append(entry)
    assert manifest[:35]==old and len(manifest)==37
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    labels=[dict(freq=90,time='2026-01-05 14:00:00',expected='DULL',confidence='mapped',position_error='possibly one bar'),
            dict(freq=90,time='2026-01-05 15:00:00',expected='CANCEL',confidence='direct',position_error='terminal marker visible')]
    assert not any(x['time'].startswith('2026-01-05') for x in labels50())
    comparisons=[];checks=[];prefix_checks=0;regional_checks=[];history_controls=[]
    for case in CASES:
        freq=case['freq'];full=read_rows(case['input']);raw=read(case['input'])
        rows=[r for r in full if r['time']<='2026-01-05 15:00:00']
        end=rows[-1];dg=dict(close=end['close'],dif=end['dif'],dea=end['dif']-end['hist']/2,hist=end['hist'])
        software=dict(close=4023.42,dif=case['dif'],dea=case['dea'],hist=case['hist'])
        pair_observations=[dict(date='2026-01-05',time=end['time'],software=software)]
        old_obs=next(o for o in json.loads((ROOT/'software_numeric_history_audit.json').read_text())['observations'] if o['freq']==freq and o['date']=='2026-01-13')
        pair_observations.append(old_obs)
        for digits in (None,2):
            h=history_feasibility(raw,pair_observations,digits,.001)
            history_controls.append(dict(freq=freq,old_screenshot=old_obs['image'],**h))
        numerical_controls=[]
        variants=[('standard',None),('close_round',2),('float32_state',None),('float32_all',None)]+[(m,n) for m in ('ema_state_round','coefficient_round') for n in (2,3,4,5,6)]
        for mode,n in variants:
            prefix=[r for r in raw if r['trade_time']<=end['time']]
            calc=simulate(prefix,mode,n)[-1]
            residual={k:calc[k]-software[k] for k in ('dif','dea','hist')}
            numerical_controls.append(dict(mode=mode,digits=n,calculated=calc,residual=residual,
                all_indicators_display_compatible=all(abs(v)<=.001+1e-9 for v in residual.values())))
        baseline=replay(rows,1,reference_policy='strongest_eligible',diagnostics=True)
        comparison=dict(freq=freq,input=case['input'],input_sha256=sha(ROOT/'inputs'/case['input']),software=software,dg=dg,
            software_minus_dg={k:software[k]-dg[k] for k in dg},
            jan5_bars=[dict(r,dea=r['dif']-r['hist']/2) for r in rows if r['time'].startswith('2026-01-05')],
            baseline_jan5=[r for r in baseline if r['time'].startswith('2026-01-05')],
            numerical_controls=numerical_controls,
            visual_observation='Regional yellow label; no terminal green label visible' if freq==60 else 'Yellow label at penultimate area, green at terminal',
            scored_labels=[x for x in labels if x['freq']==freq])
        comparisons.append(comparison)
        for mode in MODES:
            for gate in GATES:
                output=replay(full,gate,reference_policy='strongest_eligible',active_policy=mode,diagnostics=True)
                by_time={r['time']:r for r in output}
                for row in rows:
                    if not row['time'].startswith('2026-01-05'):continue
                    prefix=[r for r in rows if r['time']<=row['time']]
                    predicted=replay(prefix,gate,reference_policy='strongest_eligible',active_policy=mode,diagnostics=True)[-1]
                    assert predicted==by_time[row['time']]
                    prefix_checks+=1
                if freq==60:
                    regional_checks.append(dict(mode=mode,gate=gate,freq=freq,time=end['time'],
                        prediction=by_time[end['time']]['state'],regional_expected_state='DULL',
                        compatible=by_time[end['time']]['state']=='DULL',counts_as_exact_event_label=False))
                for label in comparison['scored_labels']:
                    r=by_time[label['time']]
                    checks.append(dict(**label,mode=mode,gate=gate,predicted=r['event'],matched=r['event']==label['expected'],
                        route=r['event_route'],event_ref_dif=r['event_ref_dif'],event_ref_start=r['event_ref_start']))
    assert all(c['matched'] for c in checks) and all(c['compatible'] for c in regional_checks)
    assert prefix_checks==84 and len(checks)==24 and len(regional_checks)==12
    result=dict(as_of='2026-10-12 Asia/Shanghai',sources=sources,user_period_clarification='First screenshot is60, second is90; both Jan5.',
        comparisons=comparisons,labels=labels,new_conditional_labels=2,cumulative_conditional_labels=52,
        cumulative_direct=20,cumulative_mapped=32,regional_state_not_event_labels=regional_checks,
        model_point_checks=checks,prefix_checks=prefix_checks,model_mismatches=0,
        january5_13_same_period_state_controls=history_controls,
        source_counts=dict(screenshots=37,numeric_endpoints=21,unique_caption_dates=14,mcp_captions=13,user_caption_files=2),
        protected_files=protected,manifest_old_entries_preserved=True,
        unchanged_prior_files_except_append_only_manifest=119,
        candidate_sha256=sha(ROOT/'active_reference_candidate.py'),helper_sha256=sha(ROOT/'audit_software_numeric_history.py'),script_sha256=sha(Path(__file__)),
        conclusions=['60 and90 have different still-dull/canceled states despite same terminal close.',
                     'All four active-reference policies agree here; locking not uniquely determined.',
                     'Both same-period Jan5/Jan13 pairs reject continuous fixed-state-only and price-rounded-plus-fixed-state explanations under the explicit input/weight assumptions.',
                     'Jan5 picture starts after Dec16 and cannot replace the missing Dec16 90-minute software observations.'],
        limits=['Yellow90 anchor is mapped and may shift one bar.',
                'Yellow60 location not promoted to an exact activation/terminal event point.',
                'DIF differences remain beyond display precision; no inferred software reference peak or exact threshold.',
                'Rule candidates already frozen; no tuning, no claim of blind numerical validation or general accuracy.',
                'Pair controls assume known DG closes, exact12/26/9 weights, one continuous initialization and no subsequent reseeding.',
                'No new transcript, network calls, production/Lake writes, or formal indicator changes.'])
    (ROOT/'holdout_20260105_pair.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(screenshots=37,new_labels=2,prefix_checks=prefix_checks,model_checks=len(checks),
        regional_checks=len(regional_checks),history_controls=[dict(freq=c['freq'],price_digits=c['price_digits'],feasible=c['feasible']) for c in history_controls]),indent=2))


if __name__=='__main__':main()
