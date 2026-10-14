"""Screen original November participants and later bases without trading logic.

Old rounded daily input stays unchanged. Its tail is explicitly a derivation.
All predicates below are diagnostic hypotheses, not author-software truth.
"""
import csv
import hashlib
import json
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
DEFS = ROOT/'november_followup_definitions_20261012.json'
KEYS = ('event', 'state', 'event_direction', 'event_route', 'event_ref_start')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(row):
    return row['time'] if len(row['time']) > 10 else row['time']+' 15:00:00'


def extend_daily(seed, fixture, end, mode):
    af, ass = 2/13, 2/27
    reconstruction = []
    if mode == 'recovered_rounded_seed':
        a,b = seed[:2]
        slow = (b['dif']-(1-af)*a['dif']-(af-ass)*b['close'])/(ass-af)
        fast, dea = slow+a['dif'], a['dif']-a['hist']/2
        reconstruction = [dict(a)]
        for r in seed[1:]:
            fast = af*r['close']+(1-af)*fast
            slow = ass*r['close']+(1-ass)*slow
            dif = fast-slow
            dea = .2*dif+.8*dea
            reconstruction.append(dict(time=r['time'], close=r['close'], dif=dif, hist=2*(dif-dea)))
    else:
        assert mode == 'fixture_first_close'
        fast = slow = float(fixture[0]['close'])
        dea = 0.
        seed_dates = {r['time'] for r in seed}
        for r in fixture:
            if r['trade_date'] > seed[-1]['time']: break
            close = float(r['close'])
            fast = af*close+(1-af)*fast
            slow = ass*close+(1-ass)*slow
            dif = fast-slow
            dea = .2*dif+.8*dea
            if r['trade_date'] in seed_dates:
                reconstruction.append(dict(time=r['trade_date'], close=close, dif=dif, hist=2*(dif-dea)))
    assert [r['time'] for r in reconstruction] == [r['time'] for r in seed]
    residuals = {k:max(abs(a[k]-b[k]) for a,b in zip(seed,reconstruction)) for k in ('close','dif','hist')}
    assert residuals['close'] == 0.
    # No tolerance is used to certify software equivalence; report every residual.
    out = [dict(r) for r in seed]
    for r in fixture:
        if not seed[-1]['time'] < r['trade_date'] <= end: continue
        close = float(r['close'])
        fast = af*close+(1-af)*fast
        slow = ass*close+(1-ass)*slow
        dif = fast-slow
        dea = .2*dif+.8*dea
        out.append(dict(time=r['trade_date'], close=close, dif=dif, hist=2*(dif-dea)))
    assert out[:len(seed)] == seed
    assert [r['time'] for r in out] == sorted({r['time'] for r in out})
    return out, dict(mode=mode, seed_rows_kept_verbatim=len(seed),
                     added_rows=len(out)-len(seed), seed_reconstruction_max_abs_errors=residuals,
                     seed_last_errors={k:reconstruction[-1][k]-seed[-1][k] for k in ('dif','hist')},
                     status='DERIVED_NOT_SOFTWARE_NUMERIC_HISTORY')


def timeline(outputs, defs, trend):
    anchors = defs['anchor']['structure_times']
    originals = {p:next(r for r in outputs[p] if r['time']==t) for p,t in anchors.items()}
    assert all(r['event']=='STRUCTURE' and r['event_direction']==1 for r in originals.values())
    start, end = defs['window']['start'], defs['window']['end']
    merged = {}
    for p, rows in outputs.items():
        for r in rows:
            if r['time'][:10] <= end:
                merged.setdefault(stamp(r), []).append((p,r))
    latest, crossed, canceled = {}, set(), set()
    bottom_seen, down_seen = False, False
    firsts = {d['key']:None for d in defs['diagnostics']}
    rows_out = []
    anchor_current_states = None
    for time, updates in sorted(merged.items()):
        for p,r in updates:
            latest[p]=r
            if time[:10] <= defs['anchor']['date']: continue
            if p in originals:
                if r['dif'] > originals[p]['event_ref_dif']: crossed.add(p)
                if r['event']=='CANCEL' and r['event_direction']==1: canceled.add(p)
            if p in ('60','90','120') and r['event']=='STRUCTURE' and r['event_direction']==-1:
                bottom_seen=True
        if time==defs['anchor']['date']+' 15:00:00':
            anchor_current_states={p:latest[p]['state'] for p in originals}
        if not start <= time[:10] <= end: continue
        statuses = [latest[p]['state']=='NONE' for p in originals]
        criteria = dict(current_none_any=any(statuses), current_none_all=all(statuses),
            strict_original_reference_break_any=bool(crossed),
            strict_original_reference_break_all=set(originals)<=crossed,
            post_anchor_cancel_any=bool(canceled), post_anchor_cancel_all=set(originals)<=canceled,
            bottom_structure_any=bottom_seen)
        if time.endswith('15:00:00'):
            tr=trend[time[:10]]
            short_down = tr['short_channel']['state']=='DOWN'
            down_seen |= short_down
            criteria.update(short_direction_down=short_down,
                short_direction_restore_up=down_seen and tr['short_channel']['state']=='UP',
                long_direction_down=tr['long_channel']['state']=='DOWN')
        for key, value in criteria.items():
            if value and firsts[key] is None: firsts[key]=time
        if time.endswith('15:00:00'):
            rows_out.append(dict(time=time, criteria=criteria,
                original_participant_current_states={p:latest[p]['state'] for p in originals},
                current_state_direction={p:latest[p]['wave_sign'] for p in originals},
                top_cancel_seen=sorted(canceled), original_reference_break_seen=sorted(crossed),
                trend={k:dict(position=trend[time[:10]][k]['position'],state=trend[time[:10]][k]['state'])
                       for k in ('short_channel','long_channel')}))
    assert anchor_current_states is not None
    return firsts, rows_out, originals, anchor_current_states


def main():
    defs=json.loads(DEFS.read_text())
    end=defs['window']['end']
    fixture_path=REPO/defs['inputs']['daily_close_fixture']
    expected_path=REPO/defs['inputs']['trend_expected']
    fixture=json.loads(fixture_path.read_text())
    expected=json.loads(expected_path.read_text())
    assert sha(fixture_path)==expected['input_file_sha256']
    trend={r['trade_date']:r for r in expected['rows']}
    seed=read_rows('daily_2025.csv')
    minute={}
    for p in ('60','90','120'):
        path=ROOT/defs['inputs'][p]
        if p=='120':
            with path.open(newline='') as h:
                data=[dict(time=r['time'],**{k:float(r[k]) for k in ('close','dif','hist')}) for r in csv.DictReader(h)]
        else: data=read_rows(path.name)
        minute[p]=[r for r in data if r['time'][:10] <= end]
    close_alignment={}
    for p, data in minute.items():
        closes={r['time'][:10]:r['close'] for r in data if r['time'].endswith('15:00:00')}
        differences=[dict(date=r['trade_date'],minute_close=closes[r['trade_date']],
                          fixture_close=float(r['close']),difference=closes[r['trade_date']]-float(r['close']))
                     for r in fixture['rows'] if defs['window']['start']<=r['trade_date']<=end]
        close_alignment[p]=dict(compared_days=len(differences),
            max_abs_difference=max(abs(r['difference']) for r in differences),
            nonzero_rows=[r for r in differences if r['difference']!=0])
    minute_closes={r['time'][:10]:r['close'] for r in minute['60'] if r['time'].endswith('15:00:00')}
    dailies={};derivations=[]
    for close_origin in ('daily_fixture','minute60_daily_endpoint'):
        close_rows=[dict(r) for r in fixture['rows']]
        if close_origin=='minute60_daily_endpoint':
            for r in close_rows:
                if seed[-1]['time']<r['trade_date']<=end:r['close']=str(minute_closes[r['trade_date']])
        for mode in ('recovered_rounded_seed','fixture_first_close'):
            rows, info=extend_daily(seed,close_rows,end,mode)
            name=close_origin+':'+mode
            dailies[name]=rows;derivations.append(dict(**info,close_origin=close_origin))
    baseline_daily=next(iter(dailies.values()))
    tail_errors={name:{k:max(abs(a[k]-b[k]) for a,b in zip(baseline_daily,rows))
                      for k in ('close','dif','hist')} for name,rows in dailies.items()}
    variants=[]; checks=0; baseline=None
    for mode, daily in dailies.items():
        series={**minute,'daily':daily}
        for gate in defs['variants']['gate_pct']:
            for policy in defs['variants']['reference_policy']:
                outputs={p:replay(data,gate,reference_policy=policy) for p,data in series.items()}
                firsts, daily_conditions, originals, anchor_states=timeline(outputs,defs,trend)
                events={p:[r for r in outs if defs['window']['start']<=r['time'][:10]<=end and r['event']!='NONE']
                        for p,outs in outputs.items()}
                for p,data in series.items():
                    # Probe all later events and each daily-close checkpoint.
                    for i,r in enumerate(data):
                        if not defs['window']['start']<=r['time'][:10]<=end: continue
                        if outputs[p][i]['event']=='NONE' and not stamp(r).endswith('15:00:00'):continue
                        partial=replay(data[:i+1],gate,reference_policy=policy)[-1]
                        assert all(partial[k]==outputs[p][i][k] for k in KEYS)
                        checks+=1
                record=dict(daily_initialization=mode,gate_pct=gate,reference_policy=policy,
                    first_satisfaction=firsts, events=events,anchor_current_states=anchor_states,
                    original_confirmed_references={p:{k:r[k] for k in ('time','event_ref_start','event_ref_dif')}
                                                  for p,r in originals.items()},
                    original_reference_monitor={p:dict(
                        max_dif_after_anchor=max(r['dif'] for r in outputs[p] if stamp(r)>defs['anchor']['date']+' 15:00:00'),
                        max_dif_minus_reference=max(r['dif'] for r in outputs[p] if stamp(r)>defs['anchor']['date']+' 15:00:00')-ref['event_ref_dif'])
                        for p,ref in originals.items()})
                variants.append(record)
                if baseline is None:baseline=dict(**record,daily_conditions=daily_conditions)
    first_summary={key:sorted({v['first_satisfaction'][key] or 'NOT_REACHED' for v in variants})
                   for key in baseline['first_satisfaction']}
    # Inspect source locators; raw spelling and predictions remain unchanged.
    sources={}
    for date, markers in {'20251111':['再减两成','钝化消失我们就买回来'],
                         '20251216':['价格创新低它就具备了','如果近期跌穿长期趋势就不再','做好买回来的准备']}.items():
        p=ROOT/'sources'/('20251111_user_transcript.txt' if date=='20251111' else '20251216_vidiq_transcript.json')
        text=p.read_text() if p.suffix=='.txt' else json.loads(p.read_text())['response']['transcription']
        evidence=[]
        for marker in markers:
            i=text.find(marker);assert i>=0,marker
            evidence.append(dict(marker=marker,char_offset=i,zero_based=True,not_video_timestamp=True,
                                 excerpt=text[max(0,i-100):i+250]))
        sources[date]=dict(path=str(p),sha256=sha(p),evidence=evidence)
    no_post_anchor_cancel=all(not any(r['event']=='CANCEL' and r['event_direction']==1
        for p in ('90','daily') for r in v['events'][p]) for v in variants)
    selected_dates=['2025-11-14','2025-11-20','2025-12-12']
    def at_date(v,date):
        return {p:[{k:r[k] for k in ('time','event','event_direction','event_ref_dif')} for r in events
                   if r['time'][:10]==date] for p,events in v['events'].items()}
    selected_signature_counts={date:len({json.dumps({p:[{k:r[k] for k in ('time','event','event_direction')}
             for r in events if r['time'][:10]==date] for p,events in v['events'].items()},sort_keys=True)
             for v in variants}) for date in selected_dates}
    output=dict(research_date=defs['research_date'],status=defs['status'],
        definitions_sha256=sha(DEFS),candidate_sha256=sha(ROOT/'active_reference_candidate.py'),
        input_sha256={p:sha(ROOT/defs['inputs'][p]) for p in ('60','90','120','daily_seed')},
        fixture_sha256=sha(fixture_path),trend_expected_sha256=sha(expected_path),
        daily_derivations=derivations,daily_initialization_and_close_source_max_abs_difference=tail_errors,
        minute_daily_close_alignment=close_alignment,
        sources=sources,variants=variants,baseline=baseline,
        first_satisfaction_across_variants=first_summary,
        first_satisfaction_means='First true checkpoint inside Nov12-Dec16 only, not the first time in history; current_none_any was already true at Nov11 close',
        current_none_limitation='Naive diagnostic of the current active state irrespective of direction/reference; a later bottom active state is not a revival of the old top structure',
        selected_date_event_signature_counts=selected_signature_counts,
        selected_date_events={date:[dict(daily_initialization=v['daily_initialization'],gate_pct=v['gate_pct'],
                                    reference_policy=v['reference_policy'],events=at_date(v,date)) for v in variants]
                              for date in selected_dates},
        original_participants_have_no_later_top_cancel=no_post_anchor_cancel,
        recommended_material=dict(primary_date='2025-11-14',secondary_date='2025-11-20',
            primary_question='Did a second minute top structure add two-tenths defense or retain prior amount? Which periods now govern correction?',
            secondary_question='Did short trend breach add defense, replace an existing basis or cause no additional quantity?',
            not_requested='No new minute pictures yet; subtitles prioritized; Dec12 bottom candidate has source-standard caveats.'),
        prefix_checks=checks,software_labels_added=0,
        limitations=['Only Dec16 stored lecture within screened window; no actual Nov14/20 recommendation/fills inferred',
            'Rounded old daily values cannot yield exact EMA reconstruction; initialization comparisons are sensitivity evidence only',
            '90-minute software data differences unresolved; extended120 and daily are derived',
            'None, reference crossing, local cancellation, bottom entry and trend restoration are different objects',
            'No original-participant cancel in this window means AND versus OR of cancellation is unidentifiable here',
            'Dec16 lack of prior price new low limits interpretation of earlier bottom candidate',
            'No fixed expiry, final holdings, action accumulation or universal priority identified'])
    (ROOT/'november_followup_20261012.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(firsts=first_summary,derivations=derivations,
        initialization_errors=tail_errors,prefix_checks=checks,
        no_original_top_cancel=no_post_anchor_cancel,
        baseline_selected_events={d:at_date(baseline,d) for d in selected_dates}),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
