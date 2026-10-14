"""Post-review context contrast, not a validated disappearance formula."""
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from active_reference_candidate import replay
from audit_november_followup import extend_daily
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    defs_path = ROOT/'structure_withdrawal_price_definitions_20261012.json'
    defs = json.loads(defs_path.read_text())
    screen_path = ROOT/'structure_withdrawal_screen_20261012.json'
    assert sha(screen_path) == defs['prior_screen_sha256']
    screen = json.loads(screen_path.read_text())
    source_defs = json.loads((ROOT/'structure_withdrawal_definitions_20261012.json').read_text())
    for spec in source_defs['inputs'].values():
        assert sha(REPO/spec['path']) == spec['sha256']
    # Reuse the exact numeric windows selected by the already-frozen screen.
    known = {(records[0]['period'], records[0]['anchor_time'])
             for records in screen['all_episodes'].values()
             if records[0]['existing_observed_anchor']}
    series = {'60': read_rows('60_20250603_20261009.csv'), '90': read_rows('90_20250603_20260113.csv')}
    import csv
    with (ROOT/'discrimination_screen_20261012/derived_120.csv').open() as f:
        series['120'] = [dict(time=r['time'], **{k:float(r[k]) for k in ('close','dif','hist')}) for r in csv.DictReader(f)]
    seed = read_rows('daily_2025.csv')
    fixture = json.loads((REPO/source_defs['inputs']['daily_fixture']['path']).read_text())['rows']
    end = min(fixture[-1]['trade_date'], series['60'][-1]['time'][:10])
    closes60 = {r['time'][:10]:r['close'] for r in series['60'] if r['time'].endswith('15:00:00')}
    for origin in source_defs['daily_close_origins']:
        prices = [dict(r) for r in fixture]
        if origin == 'minute60_daily_endpoint':
            for r in prices:
                if seed[-1]['time'] < r['trade_date'] <= end:
                    r['close'] = str(closes60[r['trade_date']])
        for mode in source_defs['daily_initializations']:
            series['daily:'+origin+':'+mode] = extend_daily(seed, prices, end, mode)[0]
    groups = defaultdict(list)
    prefix_checks = 0
    for name, rows in series.items():
        period = 'daily' if name.startswith('daily:') else name
        for gate in source_defs['gate_pct']:
            for policy in source_defs['reference_policy']:
                out = replay(rows, gate, reference_policy=policy)
                anchors = [i for i,r in enumerate(out) if r['event']=='STRUCTURE' and r['event_direction']==1]
                for n, i in enumerate(anchors):
                    a = out[i]
                    peak_end = i if a['hist'] > 0 else i-1
                    assert peak_end >= 0 and out[peak_end]['hist'] > 0
                    peak_start = peak_end
                    while peak_start > 0 and out[peak_start-1]['hist'] > 0:
                        peak_start -= 1
                    local = max(out[peak_start:peak_end+1], key=lambda r:r['close'])
                    stop = anchors[n+1] if n+1 < len(anchors) else len(out)
                    hits = {k:None for k in defs['mechanisms']}
                    evidence = {}
                    raw_break = None
                    first_negative = a['time'] if a['hist'] < 0 else None
                    new_dull = None
                    for j in range(i+1, stop):
                        r,p = out[j],out[j-1]
                        if first_negative is None and r['hist'] < 0:
                            first_negative = r['time']
                        if new_dull is None and r['event']=='DULL' and r['event_direction']==1:
                            new_dull = r['time']
                        price = r['close'] > local['close']
                        dif = p['dif'] != 0 and r['dif'] > p['dif'] and r['dif']-p['dif'] >= abs(p['dif'])*gate/100
                        hist = r['hist'] > 0
                        rules = dict(price_only=price, price_and_dif=price and dif,
                                     price_and_positive_hist=price and hist,
                                     price_dif_and_positive_hist=price and dif and hist)
                        if raw_break is None and r['dif'] > a['event_ref_dif']:
                            raw_break = r['time']
                        for key, ok in rules.items():
                            if ok and hits[key] is None:
                                hits[key] = r['time']
                                evidence[key] = dict(time=r['time'], close=r['close'], dif=r['dif'], hist=r['hist'],
                                                     previous_dif=p['dif'], dif_rise_pct=100*(r['dif']-p['dif'])/abs(p['dif']) if p['dif'] else None)
                    for target in sorted({t for t in hits.values() if t is not None}):
                        target_i = next(j for j in range(i+1,stop) if out[j]['time']==target)
                        partial = replay(rows[:target_i+1],gate,reference_policy=policy)
                        assert partial[-1]==out[target_i]
                        prefix_hits = {k:None for k in hits}
                        for j in range(i+1,len(partial)):
                            r,p = partial[j],partial[j-1]
                            price = r['close'] > local['close']
                            dif = p['dif'] != 0 and r['dif'] > p['dif'] and r['dif']-p['dif'] >= abs(p['dif'])*gate/100
                            hist = r['hist'] > 0
                            rules = dict(price_only=price,price_and_dif=price and dif,
                                         price_and_positive_hist=price and hist,
                                         price_dif_and_positive_hist=price and dif and hist)
                            for key,ok in rules.items():
                                if ok and prefix_hits[key] is None:
                                    prefix_hits[key]=r['time']
                        assert prefix_hits=={k:t if t is not None and t<=target else None for k,t in hits.items()}
                        prefix_checks += 1
                    groups[(period,a['time'])].append(dict(series=name, gate_pct=gate, policy=policy,
                        local_price_peak=dict(time=local['time'],close=local['close']),
                        anchor=dict(time=a['time'], close=a['close'], dif=a['dif'],hist=a['hist'],old_dif_reference=a['event_ref_dif']),
                        firsts=hits, endpoint_evidence=evidence, raw_reference_break=raw_break,
                        first_negative=first_negative, new_top_dull=new_dull,
                        censored_at=out[stop-1]['time']))
    candidates = []
    expected = {'daily':24, '60':6, '90':6, '120':6}
    for (period,time), records in groups.items():
        signatures = {tuple(r['firsts'].items()) for r in records}
        stable = len(records)==expected[period] and len(signatures)==1
        base = records[0]
        times = list(base['firsts'].values())
        distinct = stable and all(t is not None for t in times) and len(set(times)) > 1
        if not distinct:
            continue
        raw = base['raw_reference_break']
        clean = all(r['raw_reference_break'] is None or r['raw_reference_break'] > max(times) for r in records)
        phase_clear = all(r['first_negative'] is not None and r['first_negative'] <= min(r['firsts'].values())
                          and (r['new_top_dull'] is None or r['new_top_dull'] > max(r['firsts'].values()))
                          for r in records)
        candidates.append(dict(period=period, anchor_time=time, variants=len(records),
                               existing_observed_anchor=(period,time) in known, no_raw_break_competition=clean,
                               negative_phase_without_new_dull_before_predictions=phase_clear,
                               firsts=base['firsts'], baseline=base))
    candidates.sort(key=lambda r:(not r['negative_phase_without_new_dull_before_predictions'],
                                 not r['no_raw_break_competition'],not r['existing_observed_anchor'],
                                 r['period'] not in ('daily','120'),r['period']!='daily',r['anchor_time']))
    # These two previously-seen cases calibrate the context hypothesis only.
    contrast = {}
    for time in ('2025-10-13','2025-11-11'):
        records = groups[('daily',time)]
        assert len(records)==24
        contrast[time] = records
    assert all(r['local_price_peak']['close']==3933.9724 for r in contrast['2025-10-13'])
    assert all(all(t is None or t>'2025-10-16' for t in r['firsts'].values()) for r in contrast['2025-10-13'])
    assert all(r['local_price_peak']['close']==4018.5972 for r in contrast['2025-11-11'])
    assert all(all(t=='2025-11-13' for t in r['firsts'].values()) for r in contrast['2025-11-11'])
    result = dict(research_date='2026-10-12', status=defs['status'],definitions_sha256=sha(defs_path),
        frozen_screen_sha256=sha(screen_path), candidate_sha256=screen['candidate_sha256'],
        prior_evidence={name:sha(ROOT/'sources'/name) for name in ['20251016_daily.png','20251016_120.png','20251016_transcript.txt','20251114_daily.png','20251114_user_transcript.txt','20250711_120.png']},
        existing_chart_review=[dict(image='20251016_daily.png',window=['2025-10-15','2025-10-16'],visible='No visible green disappearance text at15/16; mapped conditional absence, no new software truth label',scope='Does not prove global marker absence, original formula or decision correction'),
                              dict(image='20251016_120.png',window=['2025-10-15 15:00:00','2025-10-16 11:30:00'],visible='No visible green disappearance text at those anchors; source/page annotations may affect visibility'),
                              dict(image='20250711_120.png',window=['2025-07-03 15:00:00','2025-07-04 11:30:00'],visible='No new visible green disappearance at price-rule predictions; this interval already returned to DULL without a negative phase. Not the Nov13 cross-phase context.')],
        source_locators=[dict(file='20251016_transcript.txt',lines=[7,10],claim='daily again dulls only if price above roughly3934'),dict(file='20251016_transcript.txt',lines=[31,34],claim='close above3934; speaker corrects second structure to second dulling')],
        known_case_contrast=contrast, groups=len(groups), differing_candidates=candidates,
        endpoint_prefix_checks=prefix_checks,
        new_software_labels=0, limitations=defs['limitations'],
        conclusion='Simple DIF/color sufficient rules fail existing conditional visibility contrast. Added price qualification can accommodate both but is post-review calibration, not original software identification.')
    (ROOT/'structure_withdrawal_price_context_20261012.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(contrast={t:dict(peak=r[0]['local_price_peak'],firsts=r[0]['firsts']) for t,r in contrast.items()},
                         candidates=len(candidates), first_candidates=candidates[:7]),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
