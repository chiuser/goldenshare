"""Minute-only, first-observable ledger; daily M0 remains frozen."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import time

from scripts.research.index_market.chan.event_ledger import groups
from scripts.research.index_market.chan.minute_data import MINUTE


class MinuteLedger:
    def __init__(self, code, frequency, spec=MINUTE):
        if code not in spec.codes or frequency not in spec.frequencies:
            raise ValueError('unapproved identity')
        self.code, self.frequency, self.spec = code, frequency, spec
        self.active, self.triggered = {}, set()
        self.last_time = ''
        self.changes = 0

    def step(self, timestamp, index, points):
        if timestamp <= self.last_time or len(points) > self.spec.max_points:
            raise ValueError('time order or point budget')
        current, events, changes = {}, [], []
        for point in points:
            if (type(point['sure']) is not bool or type(point['buy']) is not bool
                    or not point['types'] or set(point['types'])-{'1','1p','2','2s','3a','3b'}
                    or not 0 <= point['start_index'] <= point['anchor_index'] <= point['end_index'] <= index):
                raise ValueError('invalid point')
            if not point['start_time'] <= point['anchor_time'] <= point['end_time'] <= timestamp:
                raise ValueError('future point time')
            key = f"{self.code}|K_{self.frequency}M|{'buy' if point['buy'] else 'sell'}|{point['start_time']}"
            if key in current:
                raise ValueError('duplicate candidate identity')
            current[key] = deepcopy(point)
        for key in sorted(self.active.keys() | current.keys()):
            before, after = self.active.get(key), current.get(key)
            if before != after:
                changes.append(dict(time=timestamp,index=index,candidate_id=key,before=before,after=after))
            if after is None or not after['sure']:
                continue
            for group in groups(after['types'], after['buy']):
                event_id = key+'|'+group
                if event_id in self.triggered:
                    continue
                self.triggered.add(event_id)
                events.append(dict(event_id=event_id,code=self.code,frequency=self.frequency,
                    group=group,signal_time=timestamp,signal_index=index,
                    evaluation=timestamp[:10]>=self.spec.evaluation_start,
                    lag_bars=index-after['anchor_index'],**deepcopy(after)))
        self.active, self.last_time = current, timestamp
        self.changes += len(changes)
        if len(self.triggered)>self.spec.max_events or self.changes>self.spec.max_changes:
            raise ValueError('ledger budget')
        return events, changes


def replay(rows, code, frequency, spec=MINUTE, sink=None):
    from ChanConfig import CChanConfig
    from Common.CEnum import KL_TYPE
    from Common.CTime import CTime
    from KLine.KLine_List import CKLine_List
    from KLine.KLine_Unit import CKLine_Unit

    if not 0<len(rows)<=spec.max_bars:
        raise ValueError('bar budget')
    kind = {30:KL_TYPE.K_30M,60:KL_TYPE.K_60M}[frequency]
    kl = CKLine_List(kind,CChanConfig(spec.chan_config()))
    ledger = MinuteLedger(code,frequency,spec)
    previous, events, started = None, [], time.monotonic()
    for i, row in enumerate(rows):
        if time.monotonic()-started>spec.replay_seconds:
            raise TimeoutError('replay time budget')
        if row['code']!=code or row['frequency']!=frequency:
            raise ValueError('mixed replay identity')
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
            begin, end, anchor = bsp.bi.get_begin_klu().idx,bsp.bi.get_end_klu().idx,bsp.klu.idx
            points.append(dict(buy=bool(bsp.is_buy),sure=bool(bsp.bi.is_sure),
                types=sorted({t.value for t in bsp.type}),bi_index=bsp.bi.idx,
                start_index=begin,end_index=end,anchor_index=anchor,
                start_time=rows[begin]['time'],end_time=rows[end]['time'],anchor_time=rows[anchor]['time']))
        new, changes = ledger.step(row['time'],i,points)
        events.extend(new)
        if sink is not None:
            sink(changes)
        if (i+1)%2000==0:
            print(f'{code}/{frequency} {i+1}/{len(rows)} bars, {len(events)} events',flush=True)
    return events
