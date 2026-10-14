"""Audit user-supplied Oct 16 screenshots/transcript against unchanged models.

Preserves clipboard images in the evidence directory. Historical labels are
mapped, not independent intraday captures. A missing histogram-color path is
reported explicitly; matching the terminal price test is not full replication.
"""
import hashlib
import json
import shutil
from pathlib import Path

from replay import read_rows, replay

ROOT=Path(__file__).resolve().parent
FILES=dict(daily='daily_2025.csv',mins120='120_20250401_20251111.csv')
OPTIONS=[('frozen_reference',{}),
         ('require_nearest_price_break',dict(require_nearest_price_break=True)),
         ('reject_dominated_reference',dict(reject_dominated_reference=True))]


def main():
    source_dir=ROOT/'sources'
    source_dir.mkdir(exist_ok=True)
    sources=[('20251016_daily.png',Path('/var/folders/0x/12zkmckd1hb2vfp3w4vb7w480000gn/T/codex-clipboard-57a8e280-a070-42e4-bbd6-2c7d490ef5f1.png')),
             ('20251016_120.png',Path('/var/folders/0x/12zkmckd1hb2vfp3w4vb7w480000gn/T/codex-clipboard-601c67b9-51cf-4b37-9225-e7396146ecb6.png')),
             ('20251016_transcript.txt',Path('/Users/congming/.codex/attachments/719254be-adc9-4934-9b4c-d23d516d5003/Pasted text.txt'))]
    source_meta=[]
    for name,original in sources:
        target=source_dir/name
        if not target.exists():shutil.copyfile(original,target)
        # Reuse the preserved copy when temporary clipboard paths have expired.
        if original.exists():assert target.read_bytes()==original.read_bytes()
        source_meta.append(dict(file=original.name,original_path=str(original),saved_path=str(target),
                                bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    # Label terminal observations separately from mapped historical markers.
    labels=[('daily','2025-10-16','NONE','direct'),
            ('mins120','2025-10-16 15:00:00','NONE','direct'),
            ('daily','2025-10-10','DULL','mapped'),
            ('daily','2025-10-13','STRUCTURE','mapped'),
            ('mins120','2025-10-09 11:30:00','DULL','mapped'),
            ('mins120','2025-10-10 15:00:00','STRUCTURE','mapped'),
            ('mins120','2025-10-14 11:30:00','DULL','mapped'),
            ('mins120','2025-10-14 15:00:00','STRUCTURE','mapped')]
    datasets={k:read_rows(f) for k,f in FILES.items()}
    checks=[]
    for mode,kwargs in OPTIONS:
        for pct in [.75,1,1.2]:
            for case,time,expected,confidence in labels:
                full={r['time']:r for r in replay(datasets[case],pct,**kwargs)}
                prefix=[r for r in datasets[case] if r['time']<=time]
                predicted=replay(prefix,pct,**kwargs)[-1]
                assert predicted==full[time]
                checks.append(dict(reference_mode=mode,threshold_pct=pct,case=case,time=time,
                                   expected=expected,label_confidence=confidence,
                                   predicted=predicted['event'],state=predicted['state'],
                                   matched=expected==predicted['event'],causal_prefix_matched=True))
    diagnostics=[]
    for case,time in [('daily','2025-10-13'),('mins120','2025-10-14 15:00:00')]:
        rows=datasets[case]
        i=next(i for i,r in enumerate(rows) if r['time']==time)
        previous=replay(rows[:i],1,require_nearest_price_break=True)[-1]
        diagnostics.append(dict(case=case,time=time,previous=rows[i-1],current=rows[i],
                                previous_candidate_state=previous['state'],
                                positive_to_negative=rows[i-1]['hist']>0 and rows[i]['hist']<0,
                                observed='STRUCTURE',confidence='mapped',
                                explanation='Existing replay resets state at sign change before confirmation; color-flip path not implemented.'))
    terminals=[]
    for case,time,dif,dea,hist in [('daily','2025-10-16',31.246,31.153,.185),
                                  ('mins120','2025-10-16 15:00:00',15.519,13.741,3.557)]:
        row=next(r for r in datasets[case] if r['time']==time)
        terminals.append(dict(case=case,software_dif=dif,software_dea=dea,software_hist=hist,
                              dg=row,dg_dea=row['dif']-row['hist']/2,
                              dif_software_minus_dg=dif-row['dif']))
    original_queue=json.loads((ROOT/'available_period_candidate_search.json').read_text())
    target=original_queue['next_screenshot']
    assert target['date']=='2025-10-16' and target['freq']==120
    output=dict(video_date='2025-10-16',sources=source_meta,terminal_observations=terminals,
                direct_points=2,mapped_points=6,model_point_checks=len(checks),checks=checks,
                original_selection_snapshot='available_period_candidate_search.json',
                frozen_selection_target=target,
                terminal_120_result='nearest-price prerequisite matches; frozen and dominated-only variants falsely emit DULL',
                color_flip_diagnostics=diagnostics,
                transcript_claims=[
                    dict(time='04:10-04:26',claim='Daily new top dullness requires a subsequent closing price above about 3934, not an already confirmed structure.'),
                    dict(time='04:44-05:31',claim='120-minute price trigger is closing price above 3933.97; repeated red/green changes have moved the old highest reference out of scope; the new dullness level is smaller.'),
                    dict(time='05:58-06:23',claim='90-minute new dullness also uses about 3934 as the price trigger; periods can reach it at different times.'),
                    dict(time='11:17-11:41',claim='Signals use the close of their own bars; 90- and 120-minute cancellations both must hold, but need not occur simultaneously.'),
                    dict(time='01:22-02:20;14:28-15:24',claim='This correction episode monitors the periods used for the preceding structure, 90 and 120; a later daily signal is a separate episode. Dullness disappearance prices differ by period.')],
                availability_correction='The Aug 6 small-period comment was scenario-specific; do not globally exclude 60-minute or lower evidence.',
                candidate_script_sha256=hashlib.sha256((ROOT/'replay.py').read_bytes()).hexdigest(),
                limits=['Transcript is user-provided ASR, with ambiguous words and numeric transcription errors.',
                        'Historical marker times may be displaced by one bar.',
                        'This confirms a price prerequisite, not the full DIF-reference retention/expiry algorithm.',
                        'Daily and 120-minute color-flip structure examples expose an existing missing confirmation path.',
                        'NONE, no pending DULL, historical STRUCTURE validity, and CANCEL must not be conflated.'])
    (ROOT/'holdout_20251016.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'source_manifest_20251016.json').write_text(json.dumps(source_meta,ensure_ascii=False,indent=2)+'\n')
    manifest_path=ROOT/'screenshot_manifest.json'
    manifest=json.loads(manifest_path.read_text())
    for entry in source_meta[:2]:
        existing=[r for r in manifest if r['file']==entry['file']]
        if existing:assert existing==[entry]
        else:manifest.append(entry)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(direct_points=2,mapped_points=6,model_point_checks=len(checks),
        r1_results=[dict(mode=mode,terminal_mismatches=sum(not r['matched'] for r in checks if r['reference_mode']==mode and r['threshold_pct']==1 and r['label_confidence']=='direct'),
                        mapped_mismatches=sum(not r['matched'] for r in checks if r['reference_mode']==mode and r['threshold_pct']==1 and r['label_confidence']=='mapped')) for mode,_ in OPTIONS],
        color_flip_diagnostics=diagnostics),ensure_ascii=False))


if __name__=='__main__':
    main()
