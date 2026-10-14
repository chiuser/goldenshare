"""Archive-backed chart comparison; no candidate or old prediction is rewritten.

Pixel anchors/readouts are manual observations. Historical disappearance is
mapped with an explicit semantic condition, not a software-export timestamp.
"""
import csv
import hashlib
import json
import struct
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    before = json.loads(Path('/private/tmp/xxm_nov13_charts_before_20261012.json').read_text())
    for name, digest in before.items():
        if name != str(ROOT.relative_to(REPO) / 'screenshot_manifest.json'):
            assert sha(REPO / name) == digest, name
    manifest_path = ROOT / 'screenshot_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert len(manifest) == 41
    assert hashlib.sha256((json.dumps(manifest[:38], ensure_ascii=False, indent=2)+'\n').encode()).hexdigest() == before[str(ROOT.relative_to(REPO) / 'screenshot_manifest.json')]
    prior_path = ROOT / 'nov13_lecture_comparison_20261012.json'
    prior = json.loads(prior_path.read_text())
    assert sha(ROOT / 'active_reference_candidate.py') == prior['candidate_sha256']
    request_path = ROOT / 'structure_withdrawal_next_source_20261012.json'
    assert sha(request_path) == prior['frozen_request_sha256']
    request = json.loads(request_path.read_text())
    price_path = ROOT / 'structure_withdrawal_price_context_20261012.json'
    assert sha(price_path) == request['screen_sha256']
    price = json.loads(price_path.read_text())
    chosen = next(r for r in price['differing_candidates']
                  if r['period'] == '90' and r['anchor_time'] == '2025-11-11 11:00:00')
    series = {'60': read_rows('60_20250603_20261009.csv'),
              '90': read_rows('90_20250603_20260113.csv')}
    with (ROOT / 'discrimination_screen_20261012/derived_120.csv').open() as handle:
        series['120'] = [dict(time=r['time'], **{k:float(r[k]) for k in ('close','dif','hist')})
                         for r in csv.DictReader(handle)]
    specs = [
        ('60', '2025-11-13 15:00:00', '20251113_60.png', (2822,1088),
         dict(close=4029.50,dif=9.045,dea=7.750,hist=2.591)),
        ('120', '2025-11-13 15:00:00', '20251113_120.png', (2822,1092),
         dict(close=4029.50,dif=17.772,dea=17.678,hist=.187)),
        ('90', '2025-11-17 15:00:00', '20251117_90.png', (2824,1084),
         dict(close=3972.03,dif=.365,dea=6.738,hist=-12.746)),
    ]
    numeric = []
    sources = []
    for period, endpoint, name, dims, software in specs:
        image = ROOT / 'sources' / name
        data = image.read_bytes()
        assert tuple(struct.unpack('>II',data[16:24])) == dims
        entry = next(m for m in manifest if m.get('saved_path') == str(image))
        assert sha(image) == entry['sha256']
        assert Path(entry['original_path']).read_bytes() == data
        row = next(r for r in series[period] if r['time'] == endpoint)
        dg = dict(close=row['close'],dif=row['dif'],hist=row['hist'],dea=row['dif']-row['hist']/2)
        delta = {k:software[k]-dg[k] for k in software}
        assert abs(delta['close']) <= .00500001
        if period == '120':
            assert all(abs(delta[k]) <= .001 for k in ('dif','dea','hist'))
        else:
            assert any(abs(delta[k]) > .001 for k in ('dif','dea','hist'))
        numeric.append(dict(period=period,time=endpoint,software=software,dg=dg,
            software_minus_dg=delta,three_decimal_matches={k:round(dg[k],3)==software[k] for k in ('dif','dea','hist')},
            software_hist_identity_residual=software['hist']-2*(software['dif']-software['dea'])))
        sources.append(entry)
    # Original PNG coordinates are approximate manual readouts. Anchor is the
    # left edge of the software text, not its centre or the author's red pen.
    observations = [
        dict(text='钝化',color='yellow',left_x=974,time='2025-11-10 15:00:00',kind='DULL'),
        dict(text='结构形成',color='magenta',left_x=1037,time='2025-11-11 11:00:00',kind='STRUCTURE'),
        dict(text='消失',color='green',left_x=1493,time='2025-11-13 14:00:00',kind='historical_disappearance'),
        dict(text='钝化',color='yellow',left_x=1624,time='2025-11-14 11:00:00',kind='DULL'),
        dict(text='结构形成',color='magenta',left_x=1688,time='2025-11-14 14:00:00',kind='STRUCTURE'),
    ]
    recent90 = [r for r in series['90'] if '2025-11-10' <= r['time'][:10] <= '2025-11-17']
    centers = [(r['time'],1948-(len(recent90)-1-i)*65.3) for i,r in enumerate(recent90)]
    for obs in observations:
        time,x = min(centers,key=lambda r:abs(r[1]-obs['left_x']))
        assert time == obs['time']
        obs.update(confidence='mapped_not_cursor',anchor_distance_px=abs(x-obs['left_x']))
        # ±6px for endpoint and label, ±0.5px for spacing. This checks
        # robustness of the declared geometry, not correctness of the anchor convention.
        for last in (1942,1954):
            for step in (64.8,65.8):
                for left in (obs['left_x']-6,obs['left_x']+6):
                    options=[(r['time'],last-(len(recent90)-1-i)*step) for i,r in enumerate(recent90)]
                    assert min(options,key=lambda r:abs(r[1]-left))[0] == obs['time']
    variants=[]
    prefix_checks=0
    for policy in ('nearest_qualifying','strongest_eligible'):
        for gate in (.75,1.,1.2):
            windows={}
            for period, rows in series.items():
                end='2025-11-13' if period=='60' else '2025-11-17'
                rows=[r for r in rows if r['time'][:10]<=end]
                output=replay(rows,gate,reference_policy=policy)
                start='2025-11-10' if period=='90' else '2025-11-13'
                window=[r for r in output if start<=r['time'][:10]<=end]
                windows[period]=window
                for row in window:
                    assert replay([r for r in rows if r['time']<=row['time']],gate,reference_policy=policy)[-1] == row
                    prefix_checks+=1
            assert windows['60'][-1]['event']=='DULL'
            assert windows['120'][1]['time']=='2025-11-13 15:00:00'
            assert windows['120'][1]['wave_count']==1 and windows['120'][1]['event']=='NONE'
            by90={r['time']:r for r in windows['90']}
            for o in observations:
                if o['kind']!='historical_disappearance':
                    assert by90[o['time']]['event']==o['kind']
            assert by90['2025-11-13 14:00:00']['event']=='NONE'
            last90=windows['90'][-1]
            struct90=next(r for r in windows['90'] if r['time']=='2025-11-14 14:00:00')
            struct120=next(r for r in windows['120'] if r['time']=='2025-11-14 15:00:00')
            counts={p:sum(r['time']>s['time'] for r in windows[p]) for p,s in [('90',struct90),('120',struct120)]}
            assert counts=={'90':4,'120':2}
            variants.append(dict(policy=policy,gate_pct=gate,windows=windows,
                subsequent_bars_excluding_formation=counts,terminal90_state=last90['state'],
                historical_structure_marker_not_equated_with_current_state=True))
    source=ROOT/'sources/20251117_user_transcript.txt'
    txt=source.read_text();lines=txt.splitlines()
    claim_specs=[
        ('trend_service','如果结构不能够导致趋势破位','Effectiveness for trend and prior defensive action are distinct; no waiting-for-break requirement invented'),
        ('minute_structures','60分钟 90分钟 120分钟都有顶部结构','Current recent minute confirmations remain discussed'),
        ('daily_disappeared','所以暂时不用看日线','Daily structure observation focus removed; correction AND/OR membership still not specified'),
        ('short_upper_crossed','今天已经跌穿了短期趋势的上轨','Upper crossing is channel entry, not yet lower-bound full breach'),
        ('lower_breach_standard','如果跌穿下轨 就代表跌穿了趋势','Full breach uses lower channel boundary in this downward case'),
        ('next_day_threshold','明天收盘是3937点','Forecast forNov18, not a fixed multi-day threshold or verified execution'),
        ('large_down_location','这单日大阴线得在顶部出现','Location of a confirming down day matters, not just its magnitude'),
        ('120_elapsed','目前是两个周期','Two subsequent120 bars compared with24-bar expectation'),
        ('90_elapsed','90分钟四个周期了啊','Four subsequent90 bars; assumes counting after formation for comparison'),
        ('early_low_uncertain','近期我没有办法判断低点','24 bars are contextual expectations, not fixed expiry or a guaranteed bottom'),
        ('reduction_summary','所以我们只是减了4成仓啊','Author states a four-tenths reduction; not a four-tenths remaining position or verified account fills'),
        ('buyback_shorthand','如果后面创新高 我们再加回来','Generic price-high shorthand not a replacement of detailed minute dulling-cancellation standard'),
    ]
    claims=[]
    for key,marker,interpretation in claim_specs:
        hits=[i+1 for i,line in enumerate(lines) if marker in line]
        assert len(hits)==1,(key,hits)
        claims.append(dict(key=key,line=hits[0],marker=marker,interpretation=interpretation,
                           literal_prefix_not_verified_video_time=True))
    save(ROOT/'sources/20251117_user_transcript_manifest.json',dict(date='2025-11-17',received_on='2026-10-12',
        provider='user async-question reply',original_path=None,saved_path=str(source),sha256=sha(source),
        lines=len(lines),characters=len(txt),capture_method='Full supplied text manually preserved, including literal malformed prefixes and unrelated discussion; no original-file byte comparator',
        limitations=['No audio verification','90 historical green-marker identity not explicitly explained in supplied text']))
    fixture_path=REPO/'tests/fixtures/quote_trend_channel/000001_sh_daily_input.json'
    expected_path=REPO/'tests/fixtures/quote_trend_channel/000001_sh_daily_expected_v1.json'
    fixture=json.loads(fixture_path.read_text());expected=json.loads(expected_path.read_text())
    assert sha(fixture_path)==expected['input_file_sha256']
    assert sha(fixture_path)==json.loads((ROOT/'november_followup_20261012.json').read_text())['fixture_sha256']
    trend={r['trade_date']:r for r in expected['rows'] if r['trade_date'] in ('2025-11-17','2025-11-18')}
    prices={r['trade_date']:r for r in fixture['rows'] if r['trade_date'] in trend}
    target=trend['2025-11-17'];c=float(prices['2025-11-17']['close'])
    assert float(target['short_channel']['lower'])<c<float(target['short_channel']['upper'])
    assert target['short_channel']['position']=='INSIDE' and target['short_channel']['state']=='UP'
    assert target['long_channel']['position']=='ABOVE'
    lower18=float(trend['2025-11-18']['short_channel']['lower'])
    assert round(lower18)==3937
    queue120=[r for r in price['differing_candidates'] if r['period']=='120'
              and r['firsts']['price_only']!=r['firsts']['price_and_dif']]
    clean120=[r for r in queue120 if r['negative_phase_without_new_dull_before_predictions']
              and r['no_raw_break_competition']]
    assert len(queue120)==1 and not clean120
    result=dict(research_date='2026-10-12',candidate_sha256=prior['candidate_sha256'],prior_audit_sha256=sha(prior_path),
        frozen_request_sha256=sha(request_path),frozen_price_screen_sha256=sha(price_path),sources=sources,
        numerical_endpoint_comparisons=numeric,observations90=observations,approximate90_centers=centers,
        mapping_conditions=['Three successive90 endpoint bars per trading day','Last bar isNov17 closing bar',
            'Software text left edge anchors at event bar','Labels remain displayed without unverified retrospective relocation'],
        green_marker_identity=dict(raw_text='消失',interpretation='conditional_structure_withdrawal',
            reason='Previous magenta structure, subsequent yellow dulling; Nov13 generic text-prefix reading instruction',
            author_explicit90_marker_identity=False,not_intrabar_first_display_observation=True),
        frozen_prediction_comparison=dict(mapped_time='2025-11-13 14:00:00',
            simple_dif=request['primary']['simple_dif_prediction'],price_predictions=chosen['firsts'],
            price_only_and_price_dif_agree=True,only_dif_is_earlier_under_mapping=True,
            histogram_models_later_on_saved_DG_input=True,
            histogram_necessity_in_software='UNRESOLVED_HIST_NEAR_ZERO_AND_SOFTWARE_NUMBERS_DIFFER'),
        software14_hist_observed=False,variants=variants,prefix_checks=prefix_checks,
        nov17_source_sha256=sha(source),nov17_claims=claims,
        trend_comparison=dict(prices=prices,saved_fixture=trend,input_sha256=sha(fixture_path),
            expected_sha256=sha(expected_path),author_nov18_lower_forecast=3937,
            fixture_actual_nov18_lower=lower18,actual_minus_rounded_author=lower18-3937,
            limitation='Nov18 fixture is a hindsight actual value, not aNov17-as-of reconstruction of the author forecast'),
        tally=dict(screenshots=41,legacy_labels_unchanged=52,new_observations_kept_separate=True,
            cumulative_mapped_structure_disappearance_observations=2,
            new_minute_numeric_endpoints=3,cumulative_minute_numeric_endpoints=24,daily_numeric_endpoints=1,
            subtitle_files=24,distinct_subtitle_dates=23),
        frozen_queue_review=dict(stable_candidates=len(price['differing_candidates']),
            price_vs_price_dif_120_candidates=len(queue120),clean_negative_phase120_candidates=len(clean120),
            excluded120_anchor=queue120[0]['anchor_time'],
            reason='Already-observed same-colour state return, with new dulling before predictions; not a clean cross-negative structure withdrawal',
            scope='Only the five stable candidates in the frozen price screen, not every possible120 case'),
        next_step='Current image andNov17 transcript requests are fulfilled. KeepNov13 14:00 mapping conditional; inspect software historical numeric evidence or find a genuinely different120 case before requesting more materials. Do not reuse excludedJune27 anchor or request unavailableNov13-only90 image.',
        limitations=['Historical marker mapping is conditional, not an exported software event time',
            'All current numeric variants share these timings; no unique reference or DIF threshold identified',
            'Green disappearance formula and whole-defense correction join remain unresolved',
            'Do not add two-tenths automatically, force a24-bar expiry or infer account positions',
            'No formal algorithm, parameter, API, DB, Lake, network or trade changes'])
    save(ROOT/'nov13_17_charts_comparison_20261012.json',result)
    print(json.dumps(dict(screenshots=41,variants=len(variants),prefix_checks=prefix_checks,
        mapped_green='2025-11-13 14:00:00',numeric=[dict(period=r['period'],delta=r['software_minus_dg']) for r in numeric],
        claims=len(claims),source_lines=len(lines),source_characters=len(txt),nov18_fixture_lower=lower18),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
