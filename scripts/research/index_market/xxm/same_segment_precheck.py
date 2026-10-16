"""Frozen-only A-group research. No HTTP, DB, Lake or product-module writes."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from .acceptance import load_source, sha
from .bottom_history_acceptance import calendar_rows, future_slots, B1
from .same_segment_candidate import SameSegmentCandidate, clone, candidate_forecast, RESEARCH_ID, GATES
from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec
from src.biz.services.wealth.market.index_detail_xxm.forecast import inactive_result
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection, ProjectionPrecisionError

ROOT = Path(__file__).resolve().parents[4]
PERIODS = ('day', 'm60', 'm90', 'm120')
MATH_KEYS = ('status', 'reasonCode', 'targetEndpoint', 'barsAhead', 'activation', 'assumption',
             'targetEntryRanges', 'targetEntryExclusions', 'relations', 'commonConditions', 'examples')
CASES = {
    'day': {
        '2024-08-13': ('STRUCTURE', 'STRUCTURE', 'dif_turn'),
        '2024-08-14': ('DULL', 'DULL', 'dif_return'),
        '2024-08-15': ('NONE', 'STRUCTURE', 'color_flip'),
    },
    'm120': {
        '2026-07-10T15:00:00+08:00': ('NONE', 'STRUCTURE_DISAPPEARED', 'dif_return'),
        '2026-07-13T11:30:00+08:00': ('DULL', 'DULL', 'reactivation'),
    },
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def protected(source):
    paths = set(source.rglob('*'))
    for name in ('src/biz/services/wealth/market/index_detail_xxm', 'src/biz/queries/wealth/market/index_detail_xxm',
                 'wealth/src/features/index-detail/xxm', 'wealth/src/features/index-detail/xxm-forecast',
                 'reports/xxm_software_indicator_crosscheck_20261015', 'reports/xxm_bottom_history_precheck_20261016',
                 'reports/xxm_bottom_history_h1_frozen_20261016_02',
                 'reports/xxm_same_segment_precheck_20261016_01', 'reports/xxm_same_segment_precheck_20261016_02',
                 'reports/xxm_same_segment_precheck_20261016_03'):
        paths.update((ROOT / name).rglob('*'))
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths) if p.is_file() and '__pycache__' not in p.parts}


def event_key(event):
    return json.dumps({k: event[k] for k in ('time', 'direction', 'type', 'route', 'eventReference')}, sort_keys=True)


def step_key(step, calculator):
    return digest(dict(point=step.point, events=step.events, top=step.histories, bottom=step.bottom_histories,
                       rearm=calculator.last_rearm_changes))


def _new(period, gate=1.):
    return SameSegmentCandidate(period=period, source_identity=f'a-research:{period}', spec=XxmSpec(dif_turn_pct=gate))


def audit_differences(removed, added, waits, baseline_bottom, old_events):
    """Every difference must trace to an A wait or its missing successor history."""
    old_by_id = {e['id']: e for e in old_events}
    removed_ids = {e['id'] for e in removed}
    result = []
    for operation, events in (('removed', removed), ('added', added)):
        for event in events:
            anchor = event
            if event['type'] == 'RESEARCH_HISTORICAL_WITHDRAWAL':
                record = baseline_bottom[event['relatedBottomHistoryId']]
                assert record['structureEventId'] in removed_ids
                anchor = old_by_id[record['structureEventId']]
            causes = [record for record in waits.values()
                if record['disappearedAt'] <= anchor['time']
                and (record['endedAt'] is None or anchor['time'] <= record['endedAt'])]
            assert len(causes) == 1, ('unexplained lifecycle difference', operation, event)
            cause = causes[0]
            result.append(dict(operation=operation, event=event, anchorTime=anchor['time'],
                waitId=cause['id'], disappearedAt=cause['disappearedAt'], endReason=cause['endReason'],
                explanation='successor_structure_absent' if anchor is not event else 'same_segment_wait'))
    return result


def replay_period(period, bars, out):
    wanted = {v['rows'] for v in json.loads((B1 / f'forecast_{period}.json').read_text())}
    fixed = {1, 25, 1000, len(bars)//2, len(bars)-1, len(bars)}
    snapshots, confirmations, hashes, transitions, candidate_events, records = {}, {}, [], [], [], {}
    current_confirmation = None
    summaries = {}
    for gate in GATES:
        base = XxmCalculator(period=period, source_identity=f'a-research:{period}', spec=XxmSpec(dif_turn_pct=gate))
        candidate = _new(period, gate)
        old_events, new_events, histories, bottom, waits, state_changes, timeline = [], [], {}, {}, {}, [], []
        baseline_bottom = {}
        case_checks = []
        began = time.perf_counter()
        for n, bar in enumerate(bars, 1):
            old, new = base.step(bar), candidate.step(bar)
            assert base.wave == candidate.wave and base.history == candidate.history
            assert old.histories == new.histories
            for h in old.bottom_histories: baseline_bottom[h['id']] = h
            old_events.extend(old.events); new_events.extend(new.events)
            for h in new.histories: histories[h['id']] = h
            for h in new.bottom_histories: bottom[h['id']] = h
            for h in candidate.last_rearm_changes: waits[h['id']] = h
            if bar.time in CASES.get(period, {}):
                state, kind, route = CASES[period][bar.time]
                case_checks.append(dict(time=bar.time, state=candidate.state, waiting=candidate.rearm is not None,
                    events=list(new.events), passed=candidate.state == state and len(new.events) == 1
                    and new.events[0]['type'] == kind and new.events[0]['route'] == route))
            if gate == 1.:
                hashes.append(step_key(new, candidate))
                current_confirmation = next((e for e in reversed(new.events) if e['type'] == 'STRUCTURE'), current_confirmation)
                transition = any(h['disappearedAt'] == bar.time or h['endedAt'] == bar.time for h in candidate.last_rearm_changes)
                if n in wanted | fixed or transition:
                    snapshots[n] = candidate.snapshot(); confirmations[n] = deepcopy(current_confirmation)
                if transition: transitions.append(n)
                fields = ('ordinaryState', 'ordinaryDirection', 'activeReference')
                if any(old.point[k] != new.point[k] for k in fields):
                    state_changes.append(dict(time=bar.time, before={k: old.point[k] for k in fields},
                        after={k: new.point[k] for k in fields}, waiting=candidate.rearm is not None))
                if '2026-07-09' <= bar.time[:10] <= '2026-07-13':
                    timeline.append(dict(bar=asdict(bar), before=old.point, after=new.point,
                        oldEvents=list(old.events), newEvents=list(new.events), waiting=deepcopy(candidate.rearm)))
        old_by_key, new_by_key = {event_key(e): e for e in old_events}, {event_key(e): e for e in new_events}
        removed = [e for key, e in old_by_key.items() if key not in new_by_key]
        added = [e for key, e in new_by_key.items() if key not in old_by_key]
        assert all(e['direction'] == 'BOTTOM' for e in removed + added)
        difference_audit = audit_differences(removed, added, waits, baseline_bottom, old_events)
        assert [event_key(e) for e in old_events if e['direction'] == 'TOP'] == [event_key(e) for e in new_events if e['direction'] == 'TOP']
        # Match h1 and A disappearances through the original structure identity.
        gone = Counter(h['structureEventId'] for h in waits.values())
        for e in new_events:
            if e['direction'] == 'BOTTOM' and e['type'] == 'RESEARCH_HISTORICAL_WITHDRAWAL':
                gone[bottom[e['relatedBottomHistoryId']]['structureEventId']] += 1
        assert not any(count > 1 for count in gone.values()), (period, gate, 'duplicate disappearance')
        summary = dict(rows=len(bars), baselineEvents=len(old_events), candidateEvents=len(new_events),
            removed=len(removed), added=len(added), topSignalsUnchanged=True,
            waveAndReferencePoolUnchanged=True, topHistoryUnchanged=True, explainedDifferences=len(difference_audit),
            disappeared=sum(e['type'] == 'STRUCTURE_DISAPPEARED' for e in new_events),
            reactivated=sum(e['route'] == 'reactivation' for e in new_events),
            qualifiedDirectReturns=sum(e['direction'] == 'BOTTOM' and e['type'] == 'DULL' and e['route'] == 'dif_return' for e in new_events),
            historicalBottom=sum(e['direction'] == 'BOTTOM' and e['type'] == 'RESEARCH_HISTORICAL_WITHDRAWAL' for e in new_events),
            waitEndReasons=dict(Counter(h['endReason'] or 'still_waiting' for h in waits.values())),
            duplicateDisappearances=0, knownSequences=case_checks, seconds=time.perf_counter()-began)
        summaries[str(gate)] = summary
        dump(out / f'diff_{period}_{gate}.json', dict(summary=summary, removed=removed, added=added,
            waits=list(waits.values()), differenceAudit=difference_audit))
        if gate == 1.:
            candidate_events = new_events; records = bottom
            dump(out / f'timeline_{period}.json', timeline)
            dump(out / f'state_changes_{period}.json', state_changes)
            dump(out / f'events_{period}.json', dict(events=new_events, bottomHistories=list(bottom.values()), topHistories=list(histories.values())))
        print('replay', period, gate, json.dumps(summary), flush=True)
    # Replay selected causal prefixes and resume from actual candidate snapshots.
    sampled = sorted(set(transitions[:3] + transitions[len(transitions)//2:len(transitions)//2+2] + transitions[-3:]))
    cuts = sorted(n for n in fixed | set(sampled) if n in snapshots)
    for n in cuts:
        child = _new(period)
        for i, bar in enumerate(bars[:n]):
            step = child.step(bar); assert step_key(step, child) == hashes[i]
        assert child.snapshot() == snapshots[n]
        resumed = _new(period); resumed.restore(snapshots[n])
        for i, bar in enumerate(bars[n:n+250], n):
            step = resumed.step(bar); assert step_key(step, resumed) == hashes[i]
    return dict(sensitivity=summaries, prefixRestoreCuts=len(cuts)), snapshots, confirmations, candidate_events, records


def model(c, bars, calendar, check):
    before = c.snapshot()
    if c.state == 'STRUCTURE':
        result = inactive_result('CONFIRMED')
    else:
        try:
            projection = recover_projection(tuple(bars), c.period, check)
            forecast, _, _ = candidate_forecast()
            result = forecast(c, projection, future_slots(calendar, c.period, c.previous.time), check)
        except ProjectionPrecisionError as exc:
            result = inactive_result('PRECISION_PENDING', exc.reason)
    assert c.snapshot() == before
    if c.rearm is not None:
        assert result['status'] not in ('READY', 'CONFIRMED')
    return result


def forecasts(period, bars, snapshots, confirmations, calendar, out):
    old = {item['rows']: item['result'] for item in json.loads((B1 / f'forecast_{period}.json').read_text())}
    # Every newly observed disappearance is checked in addition to the old grid.
    wanted = sorted(set(old) | {n for n, s in snapshots.items() if s['research']['rearm'] and s['research']['rearm']['disappearedAt'] == bars[n-1].time})
    results, differences, failures, durations = [], [], [], []
    for n in wanted:
        started = time.perf_counter()
        def check():
            if time.perf_counter()-started > .2: raise TimeoutError('200ms offline candidate model')
        c = _new(period); c.restore(snapshots[n])
        try:
            if confirmations[n] and confirmations[n]['time'] == bars[n-1].time:
                result = inactive_result('CONFIRMED')
            else:
                result = model(c, bars[:n], calendar, check)
            check()
            ms = (time.perf_counter()-started)*1000
            durations.append(ms)
            row = dict(rows=n, through=bars[n-1].time, waiting=c.rearm is not None, milliseconds=ms, result=result)
            results.append(row)
            if n in old:
                before = {key: old[n][key] for key in MATH_KEYS}
                if before != result:
                    differences.append(dict(rows=n, through=bars[n-1].time, before=before, after=result,
                        beforeState='old_frozen', afterState=c.state, waiting=deepcopy(c.rearm)))
        except (AssertionError, TimeoutError, ValueError) as exc:
            failures.append(dict(rows=n, through=bars[n-1].time, type=type(exc).__name__, message=str(exc)))
    dump(out / f'forecasts_{period}.json', dict(results=results, differences=differences, failures=failures))
    return dict(oldGrid=len(old), addedWaitEndpoints=len(wanted)-len(old), passed=len(results), failures=failures,
        changedOldGrid=len(differences), maxModelMs=max(durations, default=0.),
        calibrationProtected=sum(v['result']['reasonCode'] == 'CALIBRATION_FAILED' for v in results))


def simulations(sources, out):
    scenarios = [('m120','2026-07-10T15:00:00+08:00','2026-07-13T11:30:00+08:00',3959.16,'DULL','reactivation',True),
        ('m120','2026-07-10T15:00:00+08:00','2026-07-13T11:30:00+08:00',3960.,'NONE',None,False),
        ('m120','2026-07-13T15:00:00+08:00','2026-07-14T11:30:00+08:00',3892.79,'NONE','dif_break',True),
        ('m90','2026-07-13T15:00:00+08:00','2026-07-14T11:00:00+08:00',3944.79,'DULL',None,True)]
    result = []
    for period, through, stamp, close, state, route, software in scenarios:
        bars = [b for b in sources[period] if b.time <= through]
        c = _new(period)
        for bar in bars: c.step(bar)
        before = c.snapshot(); projection = recover_projection(tuple(bars), period, lambda:None)
        bar, _ = projection.project(close, stamp, period)
        child = clone(c); step = child.step(bar)
        assert child.state == state and (any(e['route'] == route for e in step.events) if route else not step.events)
        assert c.snapshot() == before
        result.append(dict(period=period, through=through, hypothetical=asdict(bar), softwareObservation=software,
            state=child.state, events=list(step.events), sourceSnapshotUnchanged=True))
    dump(out / 'simulations.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(); out = args.output
    sources = {period: load_source(source, period) for period in PERIODS}
    before = protected(source)
    out.mkdir(parents=True, exist_ok=False)
    dump(out / 'protection_before.json', before)
    metadata = dict(candidate=RESEARCH_ID, gates=GATES, source=str(source.relative_to(ROOT)),
        productVersion=XxmSpec().algorithm_version, formalWrites=False, productCodeModified=False,
        researchCode={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__).resolve(), Path(__file__).with_name('same_segment_candidate.py').resolve()]},
        startedAt=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
    dump(out / 'run.json', metadata)
    dump(out / 'software_observations.json', dict(
        source='user confirmation of existing 2024-08-22 daily screenshot',
        observation='两次紫色之间有黄色“钝化”，没有绿色“消失”',
        screenshot='reports/xxm_software_indicator_crosscheck_20261015/sources/20240822_day.png',
        exactYellowTimestampConfirmed=False, internalSameBarOrderProven=False,
        interpretation='A qualifying return may remain DULL without a green event; tested as a hypothesis'))
    summary = dict(periods={}, softwareFormulaProven=False, formalFourSecondBudgetTested=False)
    calendar = calendar_rows(source)
    positives = []
    try:
        for period, bars in sources.items():
            recognition, snapshots, confirmations, events, _ = replay_period(period, bars, out)
            stamps = ['2024-07-23','2024-08-05','2024-08-22'] if period == 'day' else ['2024-08-05T15:00:00+08:00','2024-08-14T15:00:00+08:00'] if period == 'm120' else []
            for stamp in stamps:
                hits = [e for e in events if e['time'] == stamp and e['direction']=='BOTTOM' and e['type']=='RESEARCH_HISTORICAL_WITHDRAWAL']
                positives.append(dict(period=period,time=stamp,preserved=len(hits)==1))
            recognition['forecast'] = forecasts(period, bars, snapshots, confirmations, calendar, out)
            summary['periods'][period] = recognition
            dump(out / 'summary.json', summary)
            print('forecast', period, json.dumps(recognition['forecast']), flush=True)
        summary['softwarePositiveObservations'] = positives
        simulations(sources, out)
        summary['conflicts'] = [p for p in positives if not p['preserved']]
        summary['sequenceConflicts'] = [dict(period=period, gate=gate, **case)
            for period, data in summary['periods'].items() for gate, replay in data['sensitivity'].items()
            for case in replay['knownSequences'] if not case['passed']]
        summary['passed'] = (not summary['conflicts'] and not summary['sequenceConflicts']
            and all(not p['forecast']['failures'] for p in summary['periods'].values()))
    finally:
        after = protected(source)
        summary['protectedFiles'] = len(before)
        summary['protectedUnchanged'] = before == after
        dump(out / 'summary.json', summary)
        metadata.update(finishedAt=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), passed=summary.get('passed',False))
        dump(out / 'run.json', metadata)
        assert before == after, 'Protected product/evidence files changed'
    if not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
