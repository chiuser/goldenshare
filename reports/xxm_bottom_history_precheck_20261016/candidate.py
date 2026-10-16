"""Approved B-only precheck; original product calculator is never edited."""
from copy import deepcopy
from dataclasses import dataclass

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator as OriginalCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import XxmSpec


@dataclass(frozen=True, slots=True)
class CandidateSpec(XxmSpec):
    algorithm_version: str = 'xxm-direction-v0.1-h1'
    bottom_history_policy: str = 'closed_origin_close_break_v1'


SPEC = CandidateSpec()


@dataclass(frozen=True, slots=True)
class CandidateStep:
    point: dict
    events: tuple
    histories: tuple
    bottomHistories: tuple


class CandidateCalculator(OriginalCalculator):
    def __init__(self, *, period, source_identity, ts_code='000001.SH', spec=SPEC):
        super().__init__(period=period, source_identity=source_identity, ts_code=ts_code, spec=spec)
        self.pendingBottomHistory = None

    def advance_bottom(self, bar, ordinary, original_wave, events):
        changes = []
        record = self.pendingBottomHistory
        if record is not None:
            record['observedThrough'] = bar.time
            record['ageBars'] += 1
            if record['leftOriginAt'] is None and bar.hist >= 0:
                record['leftOriginAt'] = bar.time
            reason = None
            if bar.dif < record['originalReference']['dif']:
                reason = 'original_reference_break'
            elif ordinary and ordinary['direction'] == 'BOTTOM' and ordinary['type'] in ('DULL', 'STRUCTURE'):
                reason = 'new_bottom_' + ordinary['type']
            elif record['leftOriginAt'] is not None and bar.time > record['confirmedAt'] and bar.close < record['priceLow']:
                reason = 'historical_price_break'
                events.append(dict(id=self._id(bar.time, 'RESEARCH_HISTORICAL_WITHDRAWAL', record['id']),
                                   time=bar.time, direction='BOTTOM', type='RESEARCH_HISTORICAL_WITHDRAWAL',
                                   route='historical_price_break', fromState=self.state,
                                   eventReference=deepcopy(record['originalReference']),
                                   relatedTopHistoryId=None, relatedBottomHistoryId=record['id']))
            if reason:
                record.update(status='ENDED', endedAt=bar.time, endReason=reason)
                self.pendingBottomHistory = None
            changes.append(deepcopy(record))
        if ordinary and ordinary['direction'] == 'BOTTOM' and ordinary['type'] == 'STRUCTURE':
            wave = self.wave if bar.hist < 0 else original_wave
            assert wave is not None and wave.sign == -1
            key = self._id('bottom-history', ordinary['id'])
            self.pendingBottomHistory = dict(id=key, structureEventId=ordinary['id'], confirmedAt=bar.time,
                confirmationRoute=ordinary['route'], originSegmentStart=wave.start,
                leftOriginAt=bar.time if bar.hist >= 0 else None,
                priceLow=wave.price, priceLowAt=wave.price_at,
                originalReference=deepcopy(ordinary['eventReference']), status='PENDING', endedAt=None,
                endReason=None, observedThrough=bar.time, ageBars=0)
            ordinary['relatedBottomHistoryId'] = key
            changes.append(deepcopy(self.pendingBottomHistory))
        return changes

    def step(self, bar):
        previous_wave = deepcopy(self.wave)
        original = super().step(bar)
        point = dict(original.point)
        events = [dict(e, relatedBottomHistoryId=None) for e in original.events]
        ordinary = next((e for e in events if e['type'] != 'RESEARCH_HISTORICAL_WITHDRAWAL'), None)
        changes = self.advance_bottom(bar, ordinary, previous_wave, events)
        point['pendingBottomHistoryId'] = self.pendingBottomHistory['id'] if self.pendingBottomHistory else None
        return CandidateStep(point, tuple(events), original.histories, tuple(changes))

    def snapshot(self):
        return dict(super().snapshot(), pendingBottomHistory=deepcopy(self.pendingBottomHistory))

    def restore(self, snapshot):
        super().restore(snapshot)
        record = deepcopy(snapshot['pendingBottomHistory'])
        if record is not None:
            assert record['status'] == 'PENDING' and record['endedAt'] is None and record['endReason'] is None
            assert record['priceLowAt'] <= record['confirmedAt'] <= record['observedThrough'] <= self.previous.time
            assert record['leftOriginAt'] is None or record['confirmedAt'] <= record['leftOriginAt'] <= self.previous.time
        self.pendingBottomHistory = record
