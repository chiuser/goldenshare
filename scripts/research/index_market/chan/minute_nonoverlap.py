"""C2 changes only C1 sampling: next-trading-day observation windows cannot overlap."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

import duckdb
import pandas as pd

from scripts.research.index_market.chan.m0_data import REPO, digest, safe_output
from scripts.research.index_market.chan.minute_comparison import (
    SPEC as C1, ComparisonSpec, evaluate, intervals, matched_labels, sensitivity,
    simple_signals,
)
from scripts.research.index_market.chan.minute_diagnostics import PLAN, authenticated_input
from scripts.research.index_market.chan.minute_score import label_rows, select_events
from scripts.research.index_market.chan.run_m0 import save
from scripts.research.index_market.chan.verify_comparison import verify_cell


@dataclass(frozen=True)
class NonOverlapSpec(ComparisonSpec):
    variant: str = 'C2-next-day-nonoverlap'
    selection_policy: str = 'signal_time_ge_previous_target_close'
    reference_report: str = 'reports/chan_minute_comparison_c1_20260909'
    reference_manifest: str = '9703ca2c0f93f9bfd4e533acf1e30aeec4c9ef72c709dc5f064cc3035c83d66c'
    source_max_files: int = 100
    source_max_bytes: int = 128*1024**2


SPEC = NonOverlapSpec()


def select_nonoverlap(events, days):
    """No price, outcome, background or scorer dependency: use only scheduled time."""
    if days!=sorted(set(days)):
        raise ValueError('calendar order/duplicate')
    day_index = {d:i for i,d in enumerate(days)}
    selected, ledger, seen = [], [], set()
    previous_time, blocked_until, tail = '', '', False
    for event in events:
        ts, identity = event['signal_time'], event['event_id']
        if ts<previous_time or identity in seen:
            raise ValueError('event order/duplicate')
        previous_time = ts
        seen.add(identity)
        if not event['evaluation'] or event['group']!='B3':
            continue
        if ts[:10] not in day_index:
            raise ValueError('event outside calendar')
        day = day_index[ts[:10]]
        end = days[day+1]+' 15:00:00' if day+1<len(days) else None
        keep = not tail and ts>=blocked_until
        ledger.append(dict(event_id=identity,signal_time=ts,observation_end=end,selected=keep,
                           reason=('selected_tail' if end is None else 'selected') if keep else 'overlap',
                           previous_selected_end=blocked_until or None))
        if keep:
            selected.append(event)
            tail = end is None
            if end is not None:
                blocked_until = end
    return selected,ledger


def selection_diff(old, new):
    a, b = {e['event_id'] for e in old}, {e['event_id'] for e in new}
    return dict(retained=sorted(a&b),added=sorted(b-a),removed=sorted(a-b))


def verify_selection(events, days, actual, ledger):
    """Independent greedy recursion in SQL, not a second call to the selector."""
    frame = pd.DataFrame([dict(ordinal=i,event_id=e['event_id'],signal_time=e['signal_time'])
        for i,e in enumerate(events) if e['evaluation'] and e['group']=='B3'],
        columns=['ordinal','event_id','signal_time'])
    with duckdb.connect(':memory:',config={'threads':4,'memory_limit':'1GiB',
            'max_temp_directory_size':'0B','enable_external_access':False,
            'allow_persistent_secrets':False,'autoinstall_known_extensions':False,
            'autoload_known_extensions':False}) as con:
        con.register('event_frame',frame)
        con.register('calendar_frame',pd.DataFrame({'date':days}))
        found = con.execute('''WITH RECURSIVE cal AS (
            SELECT date,lead(date) OVER(ORDER BY date)||' 15:00:00' AS finish FROM calendar_frame),
            candidates AS (SELECT row_number() OVER(ORDER BY e.ordinal) AS rn,
                e.event_id,e.signal_time,cal.finish FROM event_frame e JOIN cal
                ON substr(e.signal_time,1,10)=cal.date),
            chosen AS (SELECT * FROM candidates WHERE rn=1 UNION ALL
                SELECT nxt.* FROM chosen prior CROSS JOIN LATERAL (
                    SELECT * FROM candidates c WHERE c.rn>prior.rn
                    AND c.signal_time>=prior.finish ORDER BY c.rn LIMIT 1) nxt)
            SELECT event_id,signal_time,finish FROM chosen ORDER BY rn''').fetchall()
    assert [r[0] for r in found]==[e['event_id'] for e in actual]
    assert found==[(r['event_id'],r['signal_time'],r['observation_end']) for r in ledger if r['selected']]
    assert len(ledger)==len(frame) and sum(r['selected'] for r in ledger)==len(actual)
    return dict(sql_selected=len(found),ledger_rows=len(ledger),recursive_selection_equal=True)


def authenticate_reference(spec=SPEC):
    folder = REPO/spec.reference_report
    raw = (folder/'manifest.json').read_bytes()
    if digest(raw)!=spec.reference_manifest:
        raise ValueError('C1 manifest changed')
    manifest = json.loads(raw)
    if manifest['spec']!=json.loads(json.dumps(asdict(C1))) or manifest['status']!='complete':
        raise ValueError('C1 configuration/status changed')
    paths = [(folder/name).resolve(strict=True) for name in manifest['artifacts_sha256']]
    if len(paths)>spec.source_max_files or any(not p.is_relative_to(folder.resolve()) for p in paths):
        raise ValueError('C1 path/file budget')
    if sum(p.stat().st_size for p in paths)>spec.source_max_bytes:
        raise ValueError('C1 byte budget')
    for name,sha in manifest['artifacts_sha256'].items():
        if digest((folder/name).read_bytes())!=sha:
            raise ValueError(f'C1 artifact changed: {name}')
    for name,sha in manifest['code_sha256'].items():
        if digest((Path(__file__).parent/name).read_bytes())!=sha:
            raise ValueError(f'C1 dependency changed: {name}')
    return folder,manifest,paths


def execute(output, spec=SPEC):
    if asdict(spec)!=asdict(SPEC):
        raise ValueError('unapproved nonoverlap specification')
    started = time.monotonic()
    output = safe_output(output)
    c1_folder,c1_manifest,c1_paths = authenticate_reference(spec)
    a_folder,a_manifest,source_audit,source = authenticated_input()
    a_paths = [a_folder/name for name in a_manifest['artifacts_sha256']]
    if len(a_paths+c1_paths)>spec.source_max_files or sum(p.stat().st_size for p in a_paths+c1_paths)>spec.source_max_bytes:
        raise ValueError('combined input budget')
    if a_manifest['artifacts_sha256']['source.json']!=c1_manifest['source_sha256']:
        raise ValueError('C1/A input identity mismatch')
    days = json.loads((a_folder/'calendar.json').read_bytes())
    if shutil.disk_usage(REPO/'reports').free<spec.reserve_bytes+spec.max_output_bytes:
        raise ValueError('insufficient report disk budget')
    output.mkdir(parents=True,exist_ok=False)
    metadata = dict(spec=asdict(spec),created_at_utc=datetime.now(timezone.utc).isoformat(),
        source_audit=source_audit,reference_report=str(c1_folder),reference_artifacts=len(c1_paths),
        combined_input_files=len(a_paths+c1_paths),source_sha256=c1_manifest['source_sha256'],
        plan_sha256_before_run=digest(PLAN.read_bytes()),
        code_sha256={p.name:digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')})
    save(output/'started.json',metadata)
    results = []
    for code in spec.codes:
        for frequency in spec.frequencies:
            cell = f'{code}_{frequency}'
            print(f'{cell}: authenticating original labels and selecting by calendar',flush=True)
            folder = c1_folder/cell
            rows = [r for r in source if r['code']==code and r['frequency']==frequency]
            ctx = json.loads((folder/'contexts.json').read_bytes())
            labels = matched_labels(label_rows(rows,days,1,spec),ctx)
            assert list(labels.values())==json.loads((folder/'labels.json').read_bytes())
            old_events = json.loads((folder/'events.json').read_bytes())
            original = json.loads((folder/'metrics.json').read_bytes())
            raw = {m:[r['event'] for r in old_events if r['mode']=='raw' and r['method']==m] for m in ('simple','chan')}
            legacy = {m:select_events(ee,days,'B3',True,spec) for m,ee in raw.items()}
            for mode,methods in (('raw',raw),('cooldown',legacy)):
                assert evaluate(methods,labels,spec)[0]==original['modes'][mode]
            selected,ledgers,changes = {},{},{}
            for method,events in raw.items():
                selected[method],ledgers[method] = select_nonoverlap(events,days)
                changes[method] = selection_diff(legacy[method],selected[method])
            stats,scored,eligible = evaluate(selected,labels,spec)
            print(f'{cell}: simple {len(legacy["simple"])}->{len(selected["simple"])}, A {len(legacy["chan"])}->{len(selected["chan"])}; intervals',flush=True)
            result = dict(code=code,frequency=frequency,modes=dict(raw=original['modes']['raw'],
                c1_cooldown=original['modes']['cooldown'],nonoverlap=stats),selection_diff=changes,
                intervals=intervals(scored,eligible,labels,days,spec),sensitivity=sensitivity(selected,labels,spec),yearly={})
            for year in sorted({r['date'][:4] for r in labels.values()}):
                ll = {i:r for i,r in labels.items() if r['date'][:4]==year}
                ee = {m:[e for e in ev if e['signal_index'] in ll] for m,ev in selected.items()}
                result['yearly'][year] = evaluate(ee,ll,spec)[0]
            simple,candidates = simple_signals(rows,ctx,frequency,spec)
            assert select_events(simple,days,'B3',False,spec)==raw['simple']
            assert candidates==json.loads((folder/'candidates.json').read_bytes())
            # The frozen SQL verifier names its supplied score slot 'cooldown';
            # it does not select events. Supply the new explicit set, do not relabel output.
            verification = verify_cell(rows,days,ctx,simple,candidates,labels,selected,
                                       {'modes':{'cooldown':stats}},frequency,spec)
            verification['selection'] = {}
            for method,events in raw.items():
                check = verify_selection(events,days,selected[method],ledgers[method])
                check['prefixes'] = []
                for cutoff in spec.prefix_dates:
                    before = [e for e in events if e['signal_time'][:10]<=cutoff]
                    actual = select_nonoverlap(before,days)[0]
                    assert actual==[e for e in selected[method] if e['signal_time'][:10]<=cutoff]
                    check['prefixes'].append(dict(cutoff=cutoff,unchanged=True))
                verification['selection'][method] = check
            new_events = []
            for method,events in raw.items():
                old_ids = {e['event_id'] for e in legacy[method]}
                chosen_ids = {e['event_id'] for e in selected[method]}
                for e in events:
                    new_events.append(dict(method=method,event=e,label=labels.get(e['signal_index']),
                        c1_selected=e['event_id'] in old_ids,c2_selected=e['event_id'] in chosen_ids,
                        supported=e['signal_index'] in eligible))
            cell_dir = output/cell
            cell_dir.mkdir()
            for name,data in (('metrics',result),('events',new_events),('selection',ledgers),('verification',verification)):
                save(cell_dir/f'{name}.json',data)
            results.append(result)
            if time.monotonic()-started>spec.total_seconds or sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>spec.max_output_bytes:
                raise ValueError('execution/output budget exceeded')
            print(f'{cell}: SQL and prefix checks passed, saved',flush=True)
    authenticate_reference(spec)
    assert authenticated_input()[2]==source_audit
    assert all(digest((Path(__file__).parent/name).read_bytes())==sha for name,sha in metadata['code_sha256'].items())
    save(output/'metrics.json',results)
    save(output/'manifest.json',dict(metadata,status='complete',seconds=time.monotonic()-started,source_unchanged=True,
        artifacts_sha256={str(p.relative_to(output)):digest(p.read_bytes()) for p in output.rglob('*') if p.is_file()}))
    return dict(output=str(output),cells=len(results),seconds=time.monotonic()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.output),ensure_ascii=False))


if __name__=='__main__':
    main()
