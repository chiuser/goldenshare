"""Read a new lecture against the frozen November screen, without fitting.

Structure disappearance is recorded as a distinct author assertion. The old
CANCEL means strict DIF reference break and cannot exhaust software semantics.
"""
import hashlib
import json
from pathlib import Path

from active_reference_candidate import replay
from audit_november_followup import extend_daily
from replay import read_rows

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
SOURCE=ROOT/'sources/20251114_user_transcript.txt'
SCREEN=ROOT/'november_followup_20261012.json'
KEYS=('event','state','event_direction','event_route','event_ref_start')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    text=SOURCE.read_text();lines=text.splitlines()
    screen=json.loads(SCREEN.read_text())
    assert screen['candidate_sha256']==sha(ROOT/'active_reference_candidate.py')
    claims=[]
    specs=[
      ('trend_not_breached',13,14,'也没有跌穿趋势','Actual author trend-position assertion; no exact author band values'),
      ('daily_structure_disappearance',32,37,'这个消失是结构消失 不是钝化消失','Daily displayed structure disappearance reported by Nov14; exact marker bar/date and raw formula unobserved'),
      ('period_context_changed',35,47,'现在呢是60分钟90分钟120分钟','Current visible minute structures differ from previous90/daily; coordination only slightly better. Correction membership is not specified.'),
      ('index_coordination',38,45,'所以指数之间的协调性就不会好','Target index makes new high but others do not; morphology matters beyond shared labels. No cross-index numeric labels.'),
      ('amount_conditional',48,49,'不排除会再次减','Further reduction conditional on index coordination; four-tenths-position and reduce-four-tenths wording both retained; no inferred final holdings'),
      ('large_down_day',50,51,'大阴线的判断是2%以上','Author defines a large down day here at2% or above; not an automatic structure/trade gate'),
      ('minute_structure_ordinals',51,59,'90分钟是第二次形成','Author confirms120/60 first structure in this recent context and90 second; not lifetime counts or exact timestamps'),
      ('act_without_second_foreknowledge',53,56,'第一次顶部结构形成 它就符合交易的标准','Future second structure was unknown at first action; does not justify delaying all first structures'),
      ('duration_heuristic',60,63,'没有办法得出来精确的数字','About two weeks is a contextual adjustment expectation; no exact duration, fixed expiry or tested guarantee'),
      ('future_long_trend_action',64,65,'到时候再说','Further long-trend reduction left unresolved; not an automatic two-tenths instruction now'),
      ('disappearance_wording_scope',66,71,'这个动画消失是不是要买回来','Generic question is discussed with risk of misunderstanding; nearby SSE disappearance phrasing does not identify minute cancellation or exact join'),
      ('correction_not_close',118,119,'离纠错很远了','Author explicitly says correction far away; daily structure disappearance alone did not establish present episode correction. Not account fills.'),
      ('next_week_plan',125,129,'下周一预计还没有操作','Future Monday expected observation and next-week trend focus; not actual Monday no-action evidence'),
    ]
    for key,start,end,marker,meaning in specs:
        excerpt='\n'.join(lines[start-1:end]);assert marker in excerpt,(key,start,end)
        claims.append(dict(key=key,line_start=start,line_end_inclusive=end,marker=marker,
            literal_start_line=lines[start-1],interpretation=meaning,
            literal_prefix_not_verified_video_time=True))
    # The screen predated this source; do not rewrite its software predictions.
    checks=[]
    for v in screen['variants']:
        rows={p:[r for r in v['events'][p] if r['time'][:10]=='2025-11-14'] for p in ('60','90','120','daily')}
        assert all(any(r['event']=='STRUCTURE' and r['event_direction']==1 for r in rows[p])
                   for p in ('60','90','120'))
        assert not rows['daily']
        count90=1+sum(r['event']=='STRUCTURE' and r['event_direction']==1
                     for r in v['events']['90'] if r['time'][:10]<='2025-11-14')
        assert count90==2
        assert all(sum(r['event']=='STRUCTURE' and r['event_direction']==1
                       for r in v['events'][p] if r['time'][:10]<='2025-11-14')==1 for p in ('60','120'))
        checks.append(dict(daily_initialization=v['daily_initialization'],gate_pct=v['gate_pct'],
                           reference_policy=v['reference_policy'],date_level_minute_events_agree=True,
                           author_exact_times_observed=False, ordinals_agree_in_recent_screen=True))
    fixture_path=REPO/'tests/fixtures/quote_trend_channel/000001_sh_daily_input.json'
    expected_path=REPO/'tests/fixtures/quote_trend_channel/000001_sh_daily_expected_v1.json'
    fixture=json.loads(fixture_path.read_text());expected=json.loads(expected_path.read_text())
    assert sha(fixture_path)==expected['input_file_sha256']==screen['fixture_sha256']
    assert sha(expected_path)==screen['trend_expected_sha256']
    trend=next(r for r in expected['rows'] if r['trade_date']=='2025-11-14')
    assert all(trend[k]['state']=='UP' and trend[k]['position']=='ABOVE' for k in ('short_channel','long_channel'))
    price=next(r for r in fixture['rows'] if r['trade_date']=='2025-11-14')
    prev=next(r for r in fixture['rows'] if r['trade_date']=='2025-11-13')
    change_pct=100*(float(price['close'])/float(prev['close'])-1)
    seed=read_rows('daily_2025.csv')
    candidate_daily,derivation=extend_daily(seed,fixture['rows'],'2025-11-14','recovered_rounded_seed')
    actual=replay(candidate_daily,1.)
    window=[r for r in actual if '2025-11-11'<=r['time']<='2025-11-14']
    assert all(r['event']=='NONE' for r in window if r['time']>'2025-11-11')
    # These are intentionally competing mechanisms, not patched candidate events.
    anchor=next(r for r in actual if r['time']=='2025-11-11')
    anchor_i=actual.index(anchor)
    tail=actual[anchor_i+1:]
    previous_map={actual[i]['time']:actual[i-1] for i in range(1,len(actual))}
    provisional={
        'current_state_clear':next((r['time'] for r in tail if r['state']=='NONE'),None),
        'histogram_back_positive_after_negative':next((r['time'] for r in tail if r['hist']>0 and previous_map[r['time']]['hist']<0),None),
        'upward_dif_turn_after_structure':{str(g):next((r['time'] for r in tail if
            r['dif']-previous_map[r['time']]['dif']>=abs(previous_map[r['time']]['dif'])*g/100
            and r['dif']>previous_map[r['time']]['dif']),None) for g in (.75,1.,1.2)},
        'dif_above_confirmed_bar':next((r['time'] for r in tail if r['dif']>anchor['dif']),None),
        'dif_above_original_reference':next((r['time'] for r in tail if r['dif']>anchor['event_ref_dif']),None),
    }
    # Prefix comparisons evaluate exactly the unchanged baseline's daily events.
    prefix_checks=0
    for r in window:
        prefix=[x for x in candidate_daily if x['time']<=r['time']]
        last=replay(prefix,1.)[-1]
        assert all(last[k]==r[k] for k in KEYS)
        prefix_checks+=1
    manifest=dict(received_on='2026-10-12',date='2025-11-14',provider='user async-question reply',
        original_path=None,saved_path=str(SOURCE),sha256=sha(SOURCE),characters=len(text),lines=len(lines),
        capture_method='Manually save supplied full text, literal malformed prefixes and transcription retained; no original-file byte comparator',
        limitations=['No audio/video verification','Exact screenshot marker and date of daily structure disappearance missing',
            'Four-tenths-position versus reduce-four-tenths wording ambiguous; no inferred final holdings',
            'Author speech and forecasts are evidence, not trade instructions or fills'])
    save(ROOT/'sources/20251114_user_transcript_manifest.json',manifest)
    output=dict(research_date='2026-10-12',status='NEW_LECTURE_VS_PREEXISTING_SCREEN_NOT_PARAMETER_FITTING',
        source_sha256=sha(SOURCE),prior_screen_sha256=sha(SCREEN),
        candidate_sha256=sha(ROOT/'active_reference_candidate.py'),claims=claims,
        frozen_screen_checks=checks,prefix_checks=prefix_checks,software_labels_added=0,
        source_assertions=[dict(period=p,kind='top_structure',recent_ordinal=n,
                               asserted_by_date='2025-11-14',exact_event_time=None)
                           for p,n in [('60',1),('90',2),('120',1)]]+
                          [dict(period='daily',kind='structure_disappearance_distinct_from_dulling_disappearance',
                                asserted_by_date='2025-11-14',exact_event_date=None,
                                not_mapped_to_candidate_CANCEL=True)],
        trend_fixture=dict(row=trend,price=price,close_to_close_change_pct=change_pct,
                           author_exact_bands_unknown=True),
        daily_candidate=dict(window=window,derivation=derivation,
            provisional_disappearance_mechanisms=provisional,
            limitation='Source does not specify marker date; NONE on12 and competing transitions on13 are unverified explanations, not new software labels'),
        decision_inferences={
            'daily_disappearance_sufficient_for_episode_correction':'INCOMPATIBLE_WITH_AUTHOR_THIS_CASE_DAILY_DISAPPEARS_YET_CORRECTION_FAR',
            'old_candidate_CANCEL_exhausts_software_disappearance':'UNSUPPORTED_SEMANTIC_GAP_EXPOSED',
            'every_second_structure_adds_two_tenths':'NOT_SUPPORTED_ADDITIONAL_REDUCTION_CONDITIONAL_NO_EXPLICIT_ADDITION_THIS_DAY',
            'final_holdings':'UNRESOLVED_FOUR_TENTHS_POSITION_VS_REDUCTION',
            'updated_minute_structures_automatically_change_correction_join':'NOT_IDENTIFIED',
            'raw_reference_break_is_required_for_structure_disappearance':'NOT_ESTABLISHED_SOURCE_DISTINGUISHES_TERMS_EXACT_DATE_FORMULA_UNVERIFIED'},
        material_request=dict(primary='2025-11-14 video daily indicator screenshot with the structure-disappearance label and nearby dates',
            reason='New text exposes missing event category and date; resolve before treating old CANCEL as all disappearance',
            paused='Nov20 transcript remains useful backup but no simultaneous request'),
        limitations=['Date/ordinal agreement does not prove software input or precise structure times',
            'Original screen no CANCEL remains true only for narrow candidate semantics, not absence of all software disappearance',
            'No blanket AND/OR, additive amount, fixed duration or trade performance identified',
            'Nearby later SSE-disappearance phrase lacks explicit period; do not label minute CANCEL',
            'Direction reset, historical structure withdrawal, dulling disappearance and decision closure need separate identities'])
    save(ROOT/'nov14_lecture_comparison_20261012.json',output)
    print(json.dumps(dict(source_lines=len(lines),source_characters=len(text),source_claims=len(claims),
        frozen_variant_checks=len(checks),daily_prefix_checks=prefix_checks,
        provisional_mechanisms=provisional,close_change_pct=change_pct,software_labels_added=0),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
