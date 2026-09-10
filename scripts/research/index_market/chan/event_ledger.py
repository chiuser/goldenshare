"""Append-only first-observable signals; no forward labels or prices accepted."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from scripts.research.index_market.chan.m0_data import SPEC


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def groups(types, buy):
    prefix = 'B' if buy else 'S'
    result = [prefix+t for t in ('1', '2') if t in types]
    if set(types) & {'3a', '3b'}:
        result.append(prefix+'3')
    return result


def candidate_id(code, point):
    return f"{code}|K_DAY|{'buy' if point['buy'] else 'sell'}|{point['start_date']}"


class EventLedger:
    def __init__(self, code, spec=SPEC):
        if code not in spec.codes:
            raise ValueError('unapproved code')
        self.code, self.spec = code, spec
        self.active = {}
        self.ever_seen = set()
        self.triggered = set()
        self.previous_identity = {}
        self.last_date = None
        self.event_count = self.change_count = 0

    def step(self, day, index, points):
        if self.last_date is not None and day <= self.last_date:
            raise ValueError('days must be strictly increasing')
        if len(points) > self.spec.max_points:
            raise ValueError('point budget')
        current = {}
        for p in points:
            if (not p['types'] or set(p['types']) - {'1', '1p', '2', '2s', '3a', '3b'}
                    or type(p['sure']) is not bool or type(p['buy']) is not bool):
                raise ValueError('invalid point labels or flags')
            if not p['start_date'] <= p['anchor_date'] <= day or p['end_date'] > day:
                raise ValueError('point uses future or invalid dates')
            key = candidate_id(self.code, p)
            if key in current:
                raise ValueError('ambiguous candidate identity')
            current[key] = deepcopy(p)
        changes, events = [], []
        for key in sorted(set(self.active) | set(current)):
            before, after = self.active.get(key), current.get(key)
            if before != after:
                kind = ('disappeared' if after is None else
                        'updated' if before is not None else
                        'reappeared' if key in self.ever_seen else 'appeared')
                related = None
                if after is not None:
                    identity = (after['buy'], after['bi_index'])
                    previous = self.previous_identity.get(identity)
                    if previous is not None and previous != key:
                        related = previous
                    self.previous_identity[identity] = key
                changes.append(dict(date=day, index=index, candidate_id=key, change=kind,
                                    before=before, after=after, same_index_previous_candidate=related))
            if after is None:
                continue
            self.ever_seen.add(key)
            if not after['sure']:
                continue
            for group in groups(after['types'], after['buy']):
                event_key = f'{key}|{group}'
                if event_key in self.triggered:
                    continue
                self.triggered.add(event_key)
                events.append(dict(event_id=event_key, candidate_id=key, code=self.code,
                                   frequency=self.spec.frequency, group=group,
                                   signal_date=day, signal_index=index,
                                   evaluation=day >= self.spec.evaluation_start,
                                   lag_bars=index-after['anchor_index'], **deepcopy(after)))
        self.active = current
        self.last_date = day
        self.change_count += len(changes)
        self.event_count += len(events)
        if self.event_count > self.spec.max_events or self.change_count > self.spec.max_changes:
            raise ValueError('ledger budget')
        daily = dict(date=day, index=index, points=len(current),
                     eligible_group_occurrences=sum(len(groups(p['types'], p['buy'])) for p in points if p['sure']),
                     new_events=len(events), changes=len(changes),
                     state_sha256=hashlib.sha256(canonical(current).encode()).hexdigest())
        return changes, events, daily
