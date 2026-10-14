"""Record IMG_0374 and select only attainable screenshot frequencies.

Reads archived CSVs only; does not change replay rules or earlier evidence.
The two historical labels are mapped with possible one-bar positioning error.
The terminal NONE label does not mean that the ongoing DULL state is absent.
"""
import hashlib
import json
from pathlib import Path

from replay import read_rows, replay

ROOT=Path(__file__).resolve().parent
OPTIONS=[('frozen_reference',{}),
         ('require_nearest_price_break',dict(require_nearest_price_break=True)),
         ('reject_dominated_reference',dict(reject_dominated_reference=True))]


def positive_wave_stats(rows):
    waves=[]
    for r in rows:
        sign=1 if r['hist']>0 else -1 if r['hist']<0 else 0
        if not waves or waves[-1]['sign']!=sign:
            waves.append(dict(sign=sign,rows=[]))
        waves[-1]['rows'].append(r)
    result=[]
    for wave in [w for w in waves if w['sign']==1][-3:]:
        rs=wave['rows']
        c,d=max(rs,key=lambda r:r['close']),max(rs,key=lambda r:r['dif'])
        result.append(dict(start=rs[0]['time'],end=rs[-1]['time'],bars=len(rs),
                           max_close=c['close'],max_close_time=c['time'],
                           max_dif=d['dif'],max_dif_time=d['time']))
    return result


def main():
    source='90_20250603_20260113.csv'
    full=read_rows(source)
    rows=[r for r in full if r['time']<='2025-08-06 15:00:00']
    labels=[dict(time='2025-08-05 15:00:00',event='NONE',confidence='mapped'),
            dict(time='2025-08-06 11:00:00',event='DULL',confidence='mapped'),
            dict(time='2025-08-06 15:00:00',event='NONE',confidence='direct')]
    checks=[]
    for mode,kwargs in OPTIONS:
        for pct in [.75,1,1.2]:
            predictions={r['time']:r for r in replay(full,pct,**kwargs)}
            for label in labels:
                predicted=predictions[label['time']]
                prefix=[r for r in rows if r['time']<=label['time']]
                assert replay(prefix,pct,**kwargs)[-1]==predicted
                checks.append(dict(reference_mode=mode,threshold_pct=pct,**label,
                                   predicted_event=predicted['event'],state=predicted['state'],
                                   matched=predicted['event']==label['event'],causal_prefix_matched=True))
    output=dict(screenshot='IMG_0374.PNG',date='2025-08-06',freq=90,
                observed=dict(software_close=3633.99,software_dif=12.244,software_dea=7.817,
                              software_hist=8.855,visible_yellow_dull=True,
                              terminal_new_event='NONE',labels=labels),
                dg_terminal=rows[-1],dg_terminal_dea=rows[-1]['dif']-rows[-1]['hist']/2,
                dif_software_minus_dg=12.244-rows[-1]['dif'],
                dg_aug5_aug6=[r for r in rows if r['time']>='2025-08-05'],
                reference_wave_stats=positive_wave_stats(rows),checks=checks,
                model_point_mismatches=sum(not r['matched'] for r in checks),
                candidate_script_sha256=hashlib.sha256((ROOT/'replay.py').read_bytes()).hexdigest(),
                input_sha256=hashlib.sha256((ROOT/'inputs'/source).read_bytes()).hexdigest(),
                screenshot_availability=dict(source='user reported video explanation',
                                             requested_frequencies=[90,120,'daily'],
                                             exclude_new_requests_at_or_below_60=True,
                                             interpretation='Screenshot availability constraint; not proof of an algorithmic minimum frequency.'),
                limits=['Two mapped labels can be displaced by one bar.',
                        'This image does not distinguish the two reference refinements or tested turn thresholds.',
                        'Software/DG numbers differ beyond display rounding.',
                        '27 model-point comparisons are not 27 independent samples.'])
    (ROOT/'holdout_0374.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    files=[(90,source),(120,'120_20250401_20251111.csv'),
           (120,'120_20260101_20260507.csv'),(120,'120_20260701_20260901.csv'),
           ('daily','daily_2025.csv'),('daily','daily_20260801_20261009.csv')]
    searches=[]
    for freq,name in files:
        rs=read_rows(name)
        a=replay(rs,1,require_nearest_price_break=True)
        b=replay(rs,1,reject_dominated_reference=True)
        lo,hi=[replay(rs,pct) for pct in [.75,1.2]]
        disagreements=[dict(time=x['time'],event_nearest_price=x['event'],event_dominated_ref=y['event'],
                            ref_nearest_price=x['ref_start'],ref_dominated_ref=y['ref_start'],software_label='NOT_CONFIRMED')
                       for x,y in zip(a,b) if x['event']!=y['event']]
        searches.append(dict(freq=freq,input=name,bars=len(rs),
                             threshold_event_differences=sum(x['event']!=y['event'] for x,y in zip(lo,hi)),
                             reference_event_disagreements=disagreements,
                             input_sha256=hashlib.sha256((ROOT/'inputs'/name).read_bytes()).hexdigest()))
    target_rows=read_rows('120_20250401_20251111.csv')
    prefix=[r for r in target_rows if r['time']<='2025-10-16 15:00:00']
    target_checks=[]
    for mode,kwargs in OPTIONS:
        for pct in [.75,1,1.2]:
            target=replay(prefix,pct,**kwargs)[-1]
            full_target=next(r for r in replay(target_rows,pct,**kwargs) if r['time']==target['time'])
            assert full_target==target
            target_checks.append(dict(reference_mode=mode,threshold_pct=pct,**target,
                                      software_label='NOT_CONFIRMED'))
    search=dict(scope='Existing archived 90/120-minute and daily extracts only, not all possible dates.',
                searches=searches,next_screenshot=dict(date='2025-10-16',freq=120,
                time='15:00:00',fallback='2025-10-17 120-minute image retaining Oct 16 historical text',
                checks=target_checks,positive_wave_stats=positive_wave_stats(prefix)),
                caveat='Selecting candidate disagreements is not software validation.')
    (ROOT/'available_period_candidate_search.json').write_text(json.dumps(search,ensure_ascii=False,indent=2)+'\n')
    path=Path('/Users/congming/Downloads/IMG_0374.PNG')
    entry=dict(file=path.name,original_path=str(path),bytes=path.stat().st_size,
               sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    manifest_path=ROOT/'screenshot_manifest.json'
    manifest=json.loads(manifest_path.read_text())
    old=[r for r in manifest if r['file']==path.name]
    if old:assert old==[entry]
    else:manifest.append(entry)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(model_point_mismatches=output['model_point_mismatches'],
                          comparisons=len(checks),searches=searches),ensure_ascii=False))


if __name__=='__main__':
    main()
