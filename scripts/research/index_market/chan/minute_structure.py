"""S1: capture same-timeframe upper structures at original A B3 trigger time."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from statistics import mean, median
import time

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_diagnostics import authenticated_input, PLAN
from scripts.research.index_market.chan.minute_replay import MinuteLedger
from scripts.research.index_market.chan.minute_score import select_events
from scripts.research.index_market.chan.minute_variant_a import VARIANT_A, verify_variant_source
from scripts.research.index_market.chan.run_m0 import save


@dataclass(frozen=True)
class StructureSpec:
    version: str = 'S1-asof-upper-structure'
    cutoffs: tuple[str, ...] = ('2022-12-31','2024-12-31')
    tail_count: int = 3
    omit_year: str = '2024'


SPEC = StructureSpec()
CLASS_FIELDS = ('owner_state','latest_segment_state','last_confirmed_direction',
                'higher_segment_state','higher_center_position','higher_centers_relation')


def endpoint(unit, rows, now):
    index = unit.idx
    if not 0 <= index <= now < len(rows):
        raise ValueError('structure endpoint outside current prefix')
    return dict(index=index, time=rows[index]['time'])


def line_snapshot(line, rows, now):
    if line is None:
        return None
    members = list(line.bi_list)
    for member in members:
        endpoint(member.get_begin_klu(), rows, now)
        endpoint(member.get_end_klu(), rows, now)
    return dict(index=line.idx, direction='UP' if line.is_up() else 'DOWN', sure=bool(line.is_sure),
                start_element=line.start_bi.idx, end_element=line.end_bi.idx,
                begin=endpoint(line.get_begin_klu(),rows,now), end=endpoint(line.get_end_klu(),rows,now),
                begin_value=line.get_begin_val(), end_value=line.get_end_val(),
                member_count=len(members), sure_members=sum(bool(x.is_sure) for x in members))


def center_snapshot(center, rows, now):
    members = list(center.bi_lst)
    for member in members:
        endpoint(member.get_begin_klu(), rows, now)
        endpoint(member.get_end_klu(), rows, now)
    return dict(begin=endpoint(center.begin,rows,now), end=endpoint(center.end,rows,now),
                begin_element=center.begin_bi.idx, end_element=center.end_bi.idx,
                low=center.low, high=center.high, peak_low=center.peak_low, peak_high=center.peak_high,
                sure=bool(center.is_sure), member_count=len(members), sure_members=sum(bool(x.is_sure) for x in members),
                incoming_end=endpoint(center.bi_in.get_end_klu(),rows,now) if center.bi_in else None,
                outgoing_end=endpoint(center.bi_out.get_end_klu(),rows,now) if center.bi_out else None)


def owner_of(lines, index):
    matches = [line for line in lines if line.start_bi.idx <= index <= line.end_bi.idx]
    if len(matches)>1:
        raise ValueError('multiple current structure owners')
    return matches[0] if matches else None


def state(line):
    if line is None:
        return 'MISSING'
    return line['direction']+('_SURE' if line['sure'] else '_PROVISIONAL')


def classify(snapshot, close):
    centers = snapshot['higher_centers']
    position, relation = 'MISSING', 'INSUFFICIENT'
    if centers:
        last = centers[-1]
        position = 'ABOVE' if close>last['high'] else 'BELOW' if close<last['low'] else 'INSIDE'
    if len(centers)>=2:
        old, new = centers[-2:]
        relation = 'UP_DISJOINT' if new['low']>old['high'] else 'DOWN_DISJOINT' if new['high']<old['low'] else 'OVERLAP'
    return dict(owner_state=state(snapshot['owner']), latest_segment_state=state(snapshot['latest_segment']),
                last_confirmed_direction=snapshot['last_confirmed_segment']['direction'] if snapshot['last_confirmed_segment'] else 'MISSING',
                higher_segment_state=state(snapshot['latest_higher_segment']),
                higher_center_position=position, higher_centers_relation=relation)


def take_snapshot(kl, bsp, rows, now, spec=SPEC):
    segments, higher = list(kl.seg_list), list(kl.segseg_list)
    owner = owner_of(segments, bsp.bi.idx)
    pointer = bsp.bi.parent_seg
    centers = [z for z in kl.segzs_list.zs_lst if not z.is_one_bi_zs()][-2:]
    result = dict(as_of=rows[now]['time'], signal_index=now, bi_index=bsp.bi.idx, declared_seg_index=bsp.bi.seg_idx,
                  owner=line_snapshot(owner,rows,now), parent_pointer=line_snapshot(pointer,rows,now),
                  pointer_live=pointer is not None and any(pointer is s for s in segments),
                  pointer_matches_owner=pointer is owner,
                  latest_segment=line_snapshot(segments[-1] if segments else None,rows,now),
                  last_confirmed_segment=line_snapshot(next((s for s in reversed(segments) if s.is_sure),None),rows,now),
                  latest_higher_segment=line_snapshot(higher[-1] if higher else None,rows,now),
                  owner_higher_segment=line_snapshot(owner_of(higher,owner.idx) if owner else None,rows,now),
                  segment_tail=[line_snapshot(s,rows,now) for s in segments[-spec.tail_count:]],
                  higher_centers=[center_snapshot(z,rows,now) for z in centers])
    result['classes'] = classify(result,rows[now]['close'])
    return result


def replay_structure(rows, code, frequency, spec=SPEC):
    from ChanConfig import CChanConfig
    from Common.CEnum import KL_TYPE
    from Common.CTime import CTime
    from KLine.KLine_List import CKLine_List
    from KLine.KLine_Unit import CKLine_Unit

    if not 0<len(rows)<=VARIANT_A.max_bars:
        raise ValueError('bar budget')
    kind = {30:KL_TYPE.K_30M,60:KL_TYPE.K_60M}[frequency]
    kl = CKLine_List(kind,CChanConfig(VARIANT_A.chan_config()))
    ledger = MinuteLedger(code,frequency,VARIANT_A)
    previous, events, snapshots = None, [], {}
    started = time.monotonic()
    for i,row in enumerate(rows):
        if time.monotonic()-started>VARIANT_A.replay_seconds:
            raise TimeoutError('structure replay budget')
        if row['code']!=code or row['frequency']!=frequency:
            raise ValueError('mixed input series')
        dt = datetime.fromisoformat(row['time'])
        unit = CKLine_Unit(dict(time_key=CTime(dt.year,dt.month,dt.day,dt.hour,dt.minute,auto=False),
                               **{k:row[k] for k in ('open','high','low','close')}))
        unit.set_idx(i)
        unit.kl_type = kind
        if previous is not None:
            unit.set_pre_klu(previous)
        kl.add_single_klu(unit)
        previous = unit
        points = []
        for bsp in kl.bs_point_lst.bsp_store_flat_dict.values():
            begin,end,anchor = bsp.bi.get_begin_klu().idx,bsp.bi.get_end_klu().idx,bsp.klu.idx
            if not 0<=begin<=anchor<=end<=i:
                raise ValueError('invalid or future event endpoints')
            points.append(dict(buy=bool(bsp.is_buy),sure=bool(bsp.bi.is_sure),types=sorted({t.value for t in bsp.type}),
                               bi_index=bsp.bi.idx,start_index=begin,end_index=end,anchor_index=anchor,
                               start_time=rows[begin]['time'],end_time=rows[end]['time'],anchor_time=rows[anchor]['time']))
        new,_ = ledger.step(row['time'],i,points)
        events.extend(new)
        for e in new:
            if e['evaluation'] and e['group']=='B3':
                bsp = kl.bs_point_lst.bsp_store_flat_dict[e['bi_index']]
                snapshots[e['event_id']] = take_snapshot(kl,bsp,rows,i,spec)
    return events,snapshots


def describe(records):
    return dict(n=len(records), positives=sum(r['q']>0 for r in records),
                q_up=mean(r['q']>0 for r in records) if records else None,
                q=mean(r['q'] for r in records) if records else None,
                median_q=median(r['q'] for r in records) if records else None,
                mae=mean(r['mae'] for r in records) if records else None)


def grouped(records, spec=SPEC):
    result = {}
    for field in CLASS_FIELDS:
        panels = {}
        for category in sorted({r['structure']['classes'][field] for r in records}):
            part = [r for r in records if r['structure']['classes'][field]==category]
            panels[category] = dict(all=describe(part),without_2024=describe([r for r in part if r['date'][:4]!=spec.omit_year]),
                                   yearly={year:describe([r for r in part if r['date'][:4]==year]) for year in sorted({r['date'][:4] for r in part})})
        assert sum(p['all']['n'] for p in panels.values())==len(records)
        result[field] = panels
    return result


def execute(source_path, output, spec=SPEC):
    if asdict(spec)!=asdict(SPEC):
        raise ValueError('unapproved structure specification')
    started = time.monotonic()
    output = safe_output(output)
    folder,manifest,source_audit,prices = authenticated_input()
    for name in ('minute_replay.py','minute_score.py','minute_variant_a.py','minute_data.py','event_ledger.py','run_m0.py','m0_data.py'):
        if digest((Path(__file__).parent/name).read_bytes())!=manifest['code_sha256'][name]:
            raise ValueError(f'frozen source changed: {name}')
    source = verify_variant_source(source_path)
    for key in ('commit','tracked_python_sha256','expanded_config'):
        if source[key]!=manifest['source'][key]:
            raise ValueError(f'A source differs: {key}')
    if shutil.disk_usage(REPO/'reports').free<VARIANT_A.reserve_bytes+VARIANT_A.max_output_bytes:
        raise ValueError('report disk budget')
    days = json.loads((folder/'calendar.json').read_bytes())
    metadata = dict(spec=asdict(spec), signal_spec=asdict(VARIANT_A), source=source, source_audit=source_audit,
                    source_manifest_sha256=digest((folder/'manifest.json').read_bytes()),
                    source_sha256=manifest['artifacts_sha256']['source.json'],plan_sha256_before_run=digest(PLAN.read_bytes()),
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    code_sha256={p.name:digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')})
    output.mkdir(parents=True,exist_ok=False)
    save(output/'started.json',metadata)
    results, all_records = [], []
    for code in VARIANT_A.codes:
        for frequency in VARIANT_A.frequencies:
            cell = f'{code}_{frequency}'
            rows = [r for r in prices if r['code']==code and r['frequency']==frequency]
            print(f'{cell}: replaying trigger-time structures',flush=True)
            events,snapshots = replay_structure(rows,code,frequency,spec)
            assert events==json.loads((folder/cell/'events.json').read_bytes()), 'replay differs from A'
            checks = []
            for cutoff in spec.cutoffs:
                count = sum(r['date']<=cutoff for r in rows)
                prefix_events,prefix_snapshots = replay_structure(rows[:count],code,frequency,spec)
                assert prefix_events==[e for e in events if e['signal_index']<count]
                assert prefix_snapshots=={k:v for k,v in snapshots.items() if v['signal_index']<count}
                checks.append(dict(cutoff=cutoff,bars=count,events_and_snapshots_equal=True))
            count = sum(r['date']<=spec.cutoffs[-1] for r in rows)
            changed = rows[:count]+[{**r,**{k:r[k]*1.1 for k in ('open','high','low','close')}} for r in rows[count:]]
            altered_events,altered_snapshots = replay_structure(changed,code,frequency,spec)
            assert [e for e in altered_events if e['signal_index']<count]==[e for e in events if e['signal_index']<count]
            assert {k:v for k,v in altered_snapshots.items() if v['signal_index']<count}=={k:v for k,v in snapshots.items() if v['signal_index']<count}
            saved = [r for r in json.loads((folder/cell/'next_day_scored.json').read_bytes()) if r['group']=='B3']
            scores = {r['event_id']:r for r in saved if r['mode']=='raw'}
            cool = {e['event_id'] for e in select_events(events,days,'B3',True,VARIANT_A)}
            assert set(scores)==set(snapshots)
            assert cool=={r['event_id'] for r in saved if r['mode']=='cooldown'}
            records = [dict(scores[eid],structure=s,cooled=eid in cool,code=code,frequency=frequency) for eid,s in snapshots.items()]
            all_records.extend(records)
            result = dict(code=code,frequency=frequency,raw=grouped(records,spec),cooldown=grouped([r for r in records if r['cooled']],spec),
                          raw_n=len(records),cooldown_n=len(cool),
                          pointer_mismatches=sum(not r['structure']['pointer_matches_owner'] for r in records))
            cell_dir = output/cell
            cell_dir.mkdir()
            save(cell_dir/'events.json',records)
            save(cell_dir/'metrics.json',result)
            save(cell_dir/'verification.json',dict(all_A_events_equal=len(events),prefixes=checks,future_perturbation_equal=True))
            results.append(result)
            if time.monotonic()-started>VARIANT_A.total_seconds or sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>VARIANT_A.max_output_bytes:
                raise ValueError('execution/output budget exceeded')
            print(f'{cell}: {len(records)} raw B3 snapshots saved and verified',flush=True)
    # Ensure read-only engine inspection did not modify the isolated third-party files.
    after = verify_variant_source(source_path)
    assert after['tracked_python_sha256']==source['tracked_python_sha256']
    save(output/'events.json',all_records)
    save(output/'metrics.json',results)
    save(output/'manifest.json',dict(metadata,status='complete',seconds=time.monotonic()-started,
                                    artifacts_sha256={str(p.relative_to(output)):digest(p.read_bytes()) for p in output.rglob('*') if p.is_file()}))
    return dict(output=str(output),raw_B3=len(all_records),cooled_B3=sum(r['cooled'] for r in all_records),seconds=time.monotonic()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chan-source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.chan_source,args.output),ensure_ascii=False))


if __name__=='__main__':
    main()
