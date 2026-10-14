"""Audit suppliedJuly3 text and explicit120 price scenarios, no rule edits.

Derive the next-bar DIF line from the last two saved observations under the
unchanged standard EMA12/26 assumption. This is not recovered software state.
"""
import csv
import hashlib
import json
from pathlib import Path

from active_reference_candidate import replay

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    before=json.loads(Path('/private/tmp/xxm_july3_lecture_before_20261012.json').read_text())
    for path,digest in before.items():
        assert sha(REPO/path)==digest,path
    frozen_path=ROOT/'withdrawal_next_source_july3_20261012.json'
    frozen=json.loads(frozen_path.read_text())
    assert sha(ROOT/'active_reference_candidate.py')==frozen['candidate_sha256']
    assert sha(ROOT/'structure_withdrawal_price_context_20261012.json')==frozen['old_screen_sha256']
    assert sha(ROOT/'withdrawal_recensor_screen_20261012.json')==frozen['recensor_screen_sha256']
    source=ROOT/'sources/20250703_user_transcript.txt'
    txt=source.read_text();lines=txt.splitlines()
    specs=[
        ('date','今天是2025年的7月3号','Source date explicitly spoken; malformed prefixes not verified audio times'),
        ('dull_still_generic','动画也没有消失','Generic current dulling not disappeared; chart/period not specified here'),
        ('structure_not_guaranteed_decline','也不是说所有的结构都是一定会下跌','Separates standard-following from guaranteed future decline'),
        ('correction_standard','就是纠错一定要有标准啊','Correction uses standards; a modest rise alone does not imply buyback'),
        ('120_next3460','今天收盘3461 明天跌到3460','Explicit120 approximate future-price structure condition, not exact software boundary'),
        ('120_flat','今天和昨天的DF值数值是一样的','Oral flat/equal description; no software historical numbers or rounding rule recovered'),
        ('120_flat_level_ambiguous','动画的级别无法测算','Flat path makes extrapolative dulling-level calculation unreliable; no universal rule never to cancel'),
        ('90_structure_shown','90分钟啊 结构形成在这是吧','Author explicitly shows90 historical structure, but no formation/disappearance bar date'),
        ('no_whole_correction','还没有进行纠错','Whole defense not corrected by current close; not proof that every individual structure remains'),
        ('120_repeat_forecast','今天是3,461 明天到3,460','Repeats120 conditional scenario, not another independent forecast sample'),
        ('dull_correction','这是减仓所应对的纠错的标准','Dulling disappearance is named as a correction standard; correction-period AND/OR not given'),
        ('low_not_immediate','低点它需要一段时间','Immediate large negative candle alone does not identify a bottom; no fixed waiting duration'),
    ]
    claims=[]
    for key,marker,interpretation in specs:
        hits=[i+1 for i,line in enumerate(lines) if marker in line]
        assert len(hits)==1,(key,hits)
        claims.append(dict(key=key,line=hits[0],marker=marker,interpretation=interpretation))
    dump(ROOT/'sources/20250703_user_transcript_manifest.json',dict(date='2025-07-03',received_on='2026-10-12',
        provider='user async-question reply',saved_path=str(source),original_path=None,sha256=sha(source),
        lines=len(lines),characters=len(txt),capture_method='Full supplied text manually preserved; original malformed prefixes, typos and unrelated discussion retained',
        limitations=['No audio verification','No source-file byte comparator','No explicit90 withdrawal event time']))
    spec=json.loads((ROOT/'structure_withdrawal_definitions_20261012.json').read_text())['inputs']['120']
    input_path=REPO/spec['path'];assert sha(input_path)==spec['sha256']
    with input_path.open() as f:
        rows=[dict(time=r['time'],**{k:float(r[k]) for k in ('close','dif','hist')}) for r in csv.DictReader(f)]
    i=next(i for i,r in enumerate(rows) if r['time']=='2025-07-03 15:00:00')
    prefix=rows[:i+1];r,p=prefix[-1],prefix[-2]
    a,b=2/13,2/27
    # d_t=(a-b)*C_t+(1-a)*d_(t-1)+(b-a)*EMA26_(t-1)
    old26=(r['dif']-(a-b)*r['close']-(1-a)*p['dif'])/(b-a)
    ema26=b*r['close']+(1-b)*old26
    intercept=(1-a)*r['dif']+(b-a)*ema26
    slope=a-b
    dea=r['dif']-r['hist']/2
    # Independently validate this local reconstruction against stored later DIF.
    # This is hindsight consistency only, not an input to the forecast scenarios.
    next_real=rows[i+1]
    reconstruction_residual=slope*next_real['close']+intercept-next_real['dif']
    assert abs(reconstruction_residual)<1e-8
    variants=[];checks=0
    for policy in ('nearest_qualifying','strongest_eligible'):
        for gate in (.75,1.,1.2):
            out=replay(prefix,gate,reference_policy=policy)
            assert out[-1]['state']=='DULL' and out[-1]['event']=='NONE'
            scenarios=[]
            boundary=(r['dif']-abs(r['dif'])*gate/100-intercept)/slope
            for price in (3460.,r['close'],boundary-.01,boundary+.01):
                dif=slope*price+intercept
                next_dea=.2*dif+.8*dea
                hist=2*(dif-next_dea)
                row=dict(time='2025-07-04 11:30:00',close=price,dif=dif,hist=hist)
                predicted=replay(prefix+[row],gate,reference_policy=policy)[-1]
                assert hist>0
                if price==3460. or price<boundary:
                    assert predicted['event']=='STRUCTURE'
                elif price>boundary:
                    assert predicted['event']=='NONE'
                # Reconstruct directly from EMA12 and EMA26, independent algebra.
                direct_dif=(a*price+(1-a)*(ema26+r['dif']))-(b*price+(1-b)*ema26)
                assert abs(direct_dif-dif)<1e-9
                scenarios.append(dict(close=price,dif=dif,hist=hist,event=predicted['event'],
                    dif_decline_pct=100*(r['dif']-dif)/abs(r['dif'])))
                checks+=1
            variants.append(dict(policy=policy,gate_pct=gate,latest=out[-1],boundary=boundary,
                next_scenarios=scenarios))
    equal_prices=[next(v for v in variants if v['policy']=='nearest_qualifying' and v['gate_pct']==g)['next_scenarios'][1] for g in (.75,1.,1.2)]
    assert [r['event'] for r in equal_prices]==['STRUCTURE','NONE','NONE']
    result=dict(research_date='2026-10-12',source_sha256=sha(source),frozen_request_sha256=sha(frozen_path),
        candidate_sha256=frozen['candidate_sha256'],input120=spec,source_claims=claims,
        frozen90_predictions=frozen['predictions'],
        observation90=dict(author_shows_historical_structure=True,formation_time_confirmed=False,
            structure_disappearance_confirmed=False,positive_hist_requirement_identified=False,
            classification='UNSCORED_NO_PERIOD_SPECIFIC_DISAPPEARANCE_CLAIM',
            whole_correction=False,whole_correction_does_not_label_individual_structure=True),
        next120_dif_line=dict(slope=slope,intercept=intercept,ema26_from_saved_prefix=ema26,
            assumption='One standard EMA12/26 next-bar update; DEA EMA9; not original software state',
            latest=r,previous=p,next_real_consistency_residual=reconstruction_residual,
            next_real_used_only_for_independent_hindsight_check=True),
        variants120=variants,scenario_checks=checks,
        forecast_assessment='3460 gives STRUCTURE in all six unchanged variants; sufficient scenario fits, not unique gate or exact minimum sell threshold',
        flat_price_counterfactual=dict(price=r['close'],results=equal_prices,
            limitation='Never observed as software event; distinguishes diagnostic gates only. No claim author said flat price cannot form a structure.'),
        old_files_preserved=len(before),new_software_labels=0,
        next_step='July3 transcript request satisfied; if obtaining one image, target its90 chart shown around literal9:51 to identify historical labels, without assuming those malformed prefixes are verified timestamps. No new date or threshold fitting.',
        limitations=['Generic dulling not disappeared cannot label90 structure withdrawal',
            'Mentioning90 structure on chart does not establishJuly2 14:00 anchor',
            'Rounded3461/3460 speech gives no claimed necessary-and-sufficient price cutoff',
            'DF flat/equal speech has no precise historical software readout',
            'No original cancellation formula, correction AND/OR, reference expiry or automatic trading identified'])
    dump(ROOT/'july3_lecture_comparison_20261012.json',result)
    print(json.dumps(dict(source_lines=len(lines),source_characters=len(txt),claims=len(claims),scenario_checks=checks,
        observed90=result['observation90'],boundaries={g:next(v['boundary'] for v in variants if v['gate_pct']==g) for g in (.75,1.,1.2)},
        at3460=variants[0]['next_scenarios'][0],at_flat=equal_prices,next_real_consistency_residual=reconstruction_residual),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
