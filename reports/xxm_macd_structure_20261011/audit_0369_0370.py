"""Check two new terminal observations without changing candidate rules.

Historical text positions are regional observations, not exact-time labels.
The existing 25-point calibration and IMG_0366 files remain unchanged.
"""
import csv
import hashlib
import json
from pathlib import Path

from replay import read_rows, replay

ROOT = Path(__file__).resolve().parent


def main():
    cases = [dict(screenshot='IMG_0370.PNG',freq=60,input='60_20250603_20261009.csv',
                  software_dif=36.343,software_dea=37.311,software_hist=-1.936,
                  regional_observation='Two historical DULL/CANCEL pairs; no purple structure text near the terminal reversal.'),
             dict(screenshot='IMG_0369.PNG',freq=90,input='90_20250603_20260113.csv',
                  software_dif=45.344,software_dea=44.449,software_hist=1.790,
                  regional_observation='A historical DULL/CANCEL pair near Jan 5; no subsequent visible DULL or purple structure text.')]
    audits=[]
    for case in cases:
        full_rows=read_rows(case['input'])
        rows=[r for r in full_rows if r['time']<='2026-01-13 15:00:00']
        assert rows[-1]['time']=='2026-01-13 15:00:00'
        checks=[]
        for mode,kwargs in [('frozen_reference',{}),
                            ('require_nearest_price_break',dict(require_nearest_price_break=True)),
                            ('reject_dominated_reference',dict(reject_dominated_reference=True))]:
            for pct in [.75,1,1.2]:
                result=replay(rows,pct,**kwargs)
                complete={r['time']:r for r in replay(full_rows,pct,**kwargs)}
                assert result[-1]==complete[rows[-1]['time']]
                checks.append(dict(reference_mode=mode,threshold_pct=pct,
                                   terminal_expected='NONE',label_confidence='direct',
                                   terminal_predicted=result[-1]['event'],terminal_state=result[-1]['state'],
                                   matched=result[-1]['event']=='NONE',causal_prefix_matched=True,
                                   january_events=[r for r in result if r['time']>='2026-01-05' and r['event']!='NONE']))
        tail=[]
        for i,r in enumerate(rows):
            if r['time'].startswith('2026-01-13'):
                tail.append(dict(**r,dea=r['dif']-r['hist']/2,
                                 dif_change_pct=100*(r['dif']-rows[i-1]['dif'])/abs(rows[i-1]['dif'])))
        end=tail[-1]
        audits.append(dict(**case,terminal_time=end['time'],terminal_expected='NONE',
                           dg_jan13_bars=tail,dif_software_minus_dg=case['software_dif']-end['dif'],
                           input_sha256=hashlib.sha256((ROOT/'inputs'/case['input']).read_bytes()).hexdigest(),
                           checks=checks))
    # Find reference-rule disagreements using the existing 60-minute extract.
    rows=read_rows('60_20250603_20261009.csv')
    a=replay(rows,1,require_nearest_price_break=True)
    b=replay(rows,1,reject_dominated_reference=True)
    queue=[dict(freq=60,time=x['time'],event_nearest_price=x['event'],event_dominated_ref=y['event'],
                ref_nearest_price=x['ref_start'],ref_dominated_ref=y['ref_start'],software_label='NOT_CONFIRMED')
           for x,y in zip(a,b) if x['event']!=y['event']]
    with (ROOT/'reference_disagreement_60.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(queue[0]))
        writer.writeheader()
        writer.writerows(queue)
    nine=read_rows('90_20250603_20260113.csv')
    lo,hi=[replay(nine,pct) for pct in [.75,1.2]]
    ra=replay(nine,1,require_nearest_price_break=True)
    rb=replay(nine,1,reject_dominated_reference=True)
    output=dict(candidate_script_sha256=hashlib.sha256((ROOT/'replay.py').read_bytes()).hexdigest(),
                original_frozen_script_sha256=hashlib.sha256((ROOT/'replay_frozen_25_points.py').read_bytes()).hexdigest(),
                new_terminal_points=2,model_point_checks=18,
                model_point_mismatches=sum(not c['matched'] for a in audits for c in a['checks']),
                causal_prefix_checks=18,audits=audits,
                reference_disagreement_60_count=len(queue),
                bounded_90_search=dict(bars=len(nine),threshold_event_differences=sum(x['event']!=y['event'] for x,y in zip(lo,hi)),
                                       reference_event_differences=sum(x['event']!=y['event'] for x,y in zip(ra,rb))),
                limits=['Two terminal NONE labels are correlated by market date, not a general accuracy estimate.',
                        'Historical marker times are not promoted to exact labels.',
                        'Neither terminal point differentiates the tested turn thresholds.',
                        'Software/DG DIF differs more than display rounding; percentages describe DG only.'])
    (ROOT/'holdout_0369_0370.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    manifest_path=ROOT/'screenshot_manifest.json'
    manifest=json.loads(manifest_path.read_text())
    for case in cases:
        path=Path('/Users/congming/Downloads')/case['screenshot']
        entry=dict(file=path.name,original_path=str(path),bytes=path.stat().st_size,
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        prior=[r for r in manifest if r['file']==path.name]
        if prior:
            assert prior==[entry]
        else:
            manifest.append(entry)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(new_terminal_points=2,model_point_checks=18,
                          mismatches=output['model_point_mismatches'],reference_disagreements=len(queue),
                          bounded_90_search=output['bounded_90_search']),ensure_ascii=False))


if __name__=='__main__':
    main()
