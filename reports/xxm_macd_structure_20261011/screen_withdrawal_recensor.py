"""Offline top-structure withdrawal discrimination with explicit censoring.

This changes diagnostic selection, not the immutable original candidate or
software lifecycle. Missing predictions remain censored observations.
"""
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from active_reference_candidate import replay
from replay import read_rows

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rule(row, previous, peak, gate):
    price = row['close'] > peak
    rise = row['dif'] - previous['dif']
    margin = rise - abs(previous['dif']) * gate / 100
    dif = previous['dif'] != 0 and rise > 0 and margin >= 0
    return dict(price_only=price, price_and_dif=price and dif), dict(
        time=row['time'], close=row['close'], dif=row['dif'], hist=row['hist'],
        price_margin=row['close']-peak, dif_rise=rise,
        dif_gate_margin=margin, previous_dif=previous['dif'])


def analyze(rows, gate, policy):
    out = replay(rows, gate, reference_policy=policy)
    records = []
    checks = 0
    for i, a in enumerate(out):
        if a['event'] != 'STRUCTURE' or a['event_direction'] != 1:
            continue
        end = i if a['hist'] > 0 else i-1
        assert end >= 0 and out[end]['hist'] > 0
        start = end
        while start > 0 and out[start-1]['hist'] > 0:
            start -= 1
        peak = max(out[start:end+1], key=lambda r:r['close'])
        hits = dict(price_only=None, price_and_dif=None)
        evidence = {}
        first_negative = a['time'] if a['hist'] < 0 else None
        censor = dict(kind='input_end', time=None, index=len(out))
        for j in range(i+1, len(out)):
            r = out[j]
            competitors = []
            if r['dif'] > a['event_ref_dif']:
                competitors.append('original_dif_reference_break')
            if r['event_direction'] == 1 and r['event'] in ('DULL', 'STRUCTURE'):
                competitors.append('new_top_'+r['event'].lower())
            if competitors:
                censor = dict(kind='+'.join(competitors), time=r['time'], index=j)
                break
            if first_negative is None and r['hist'] < 0:
                first_negative = r['time']
            flags, nums = rule(r, out[j-1], peak['close'], gate)
            for key, ok in flags.items():
                if ok and hits[key] is None:
                    hits[key] = r['time']
                    evidence[key] = nums
        last = censor['index']-1
        targets = {last} | {j for j in range(i+1, last+1) if out[j]['time'] in hits.values()}
        for target in targets:
            partial = replay(rows[:target+1], gate, reference_policy=policy)
            assert partial[target] == out[target]
            prefix = dict(price_only=None, price_and_dif=None)
            for j in range(i+1, target+1):
                flags, _ = rule(partial[j], partial[j-1], peak['close'], gate)
                for key, ok in flags.items():
                    if ok and prefix[key] is None:
                        prefix[key] = partial[j]['time']
            assert prefix == {k:t if t is not None and t<=out[target]['time'] else None for k,t in hits.items()}
            checks += 1
        p, d = hits.values()
        informative = p is not None and (d is None or p<d)
        phase = p is not None and first_negative is not None and first_negative<=p
        records.append(dict(anchor_time=a['time'], gate_pct=gate, policy=policy,
            anchor=dict(time=a['time'], dif=a['dif'], hist=a['hist'], old_dif_reference=a['event_ref_dif']),
            local_peak=dict(time=peak['time'],close=peak['close']), firsts=hits,
            endpoint_evidence=evidence, first_negative=first_negative,
            informative=informative, clean_negative_phase=phase,
            censor={k:v for k,v in censor.items() if k!='index'}, last_observed=out[last]['time'],
            price_and_dif_censored=d is None))
    return records, checks


def main():
    before=json.loads(Path('/private/tmp/xxm_withdrawal_recensor_before_20261012.json').read_text())
    for path,digest in before.items():
        assert sha(REPO/path)==digest,path
    defs_path=ROOT/'withdrawal_recensor_definitions_20261012.json'
    defs=json.loads(defs_path.read_text())
    source_defs=json.loads((ROOT/'structure_withdrawal_definitions_20261012.json').read_text())
    for spec in source_defs['inputs'].values():
        assert sha(REPO/spec['path'])==spec['sha256']
    series={'90':read_rows('90_20250603_20260113.csv')}
    with (ROOT/'discrimination_screen_20261012/derived_120.csv').open() as f:
        series['120']=[dict(time=r['time'], **{k:float(r[k]) for k in ('close','dif','hist')}) for r in csv.DictReader(f)]
    groups=defaultdict(list); checks=0
    for period,rows in series.items():
        for gate in defs['gate_pct']:
            for policy in defs['reference_policy']:
                records,n=analyze(rows,gate,policy); checks+=n
                for r in records:
                    groups[(period,r['anchor_time'])].append(r)
    summaries=[]
    for (period,time),records in groups.items():
        signatures={tuple(r['firsts'].items()) for r in records}
        stable=len(records)==6 and len(signatures)==1
        summaries.append(dict(period=period,anchor_time=time,variants=len(records), stable_predictions=stable,
            informative_variants=sum(r['informative'] for r in records),
            clean_informative_variants=sum(r['informative'] and r['clean_negative_phase'] for r in records),
            all_six_clean_informative=len(records)==6 and all(r['informative'] and r['clean_negative_phase'] for r in records),
            records=records))
    candidates=[r for r in summaries if r['clean_informative_variants']]
    candidates.sort(key=lambda r:(r['period']!='120',not r['all_six_clean_informative'],not r['stable_predictions'],r['anchor_time']))
    counts={period:dict(input_bars=len(series[period]),anchor_groups=sum(r['period']==period for r in summaries),
        any_clean_disagreement=sum(r['period']==period for r in candidates),
        all_six_clean_disagreement=sum(r['period']==period and r['all_six_clean_informative'] for r in candidates),
        stable_all_six=sum(r['period']==period and r['all_six_clean_informative'] and r['stable_predictions'] for r in candidates))
        for period in series}
    coincident=[]
    for g in summaries:
        recs=g['records']
        if len(recs)==6 and all(r['firsts']['price_only'] is not None and r['clean_negative_phase']
                               and r['firsts']['price_only']==r['firsts']['price_and_dif'] for r in recs):
            b=recs[0];e=b['endpoint_evidence']['price_only']
            ratios=[100*r['endpoint_evidence']['price_only']['dif_rise']/abs(r['endpoint_evidence']['price_only']['previous_dif']) for r in recs]
            coincident.append(dict(period=g['period'],anchor_time=g['anchor_time'],first_price=b['firsts']['price_only'],
                dif_rise_pct_min=min(ratios),minimum_gate_margin=min(r['endpoint_evidence']['price_only']['dif_gate_margin'] for r in recs),
                previous_dif=e['previous_dif'],hist=e['hist']))
    result=dict(research_date='2026-10-12',definitions_sha256=sha(defs_path),
        original_candidate_sha256=sha(ROOT/'active_reference_candidate.py'),
        inputs={k:source_defs['inputs'][k] for k in series},
        old_price_screen_sha256=sha(ROOT/'structure_withdrawal_price_context_20261012.json'),
        preserved_prior_files=len(before),counts=counts,prefix_checks=checks,
        all_groups=summaries,clean_candidates=candidates,coincident_clean_groups=coincident,
        diagnostic_only=True,new_software_labels=0,
        limitations=['Changed diagnostic censoring is not original software expiry',
            'No finite later DIF hit before censoring is not permanent rule failure',
            'Stable predictions are not software validation','90 software historical numeric differences unresolved',
            'No new source, bottom symmetry, gate change or correction join conclusion'])
    (ROOT/'withdrawal_recensor_screen_20261012.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(counts=counts,prefix_checks=checks,coincident_clean_groups=coincident,candidates=[dict(period=r['period'],anchor=r['anchor_time'],stable=r['stable_predictions'],
        all_six=r['all_six_clean_informative'],predictions=[dict(gate=x['gate_pct'],policy=x['policy'],firsts=x['firsts'],censor=x['censor']) for x in r['records']]) for r in candidates]),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
