"""Independent r4 reference/zero trial; no input loading or product integration."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
from typing import Any

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.snapshot_validation import ParsedXxmSnapshot
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import (
    Wave, XxmBar, XxmBottomHistory, XxmPeriod, XxmRearmRecord, XxmStep,
)


@dataclass(frozen=True, slots=True)
class R4TrialSpec:
    research_version: str = "xxm-research-r4-v2"
    reference_policy: str = "nearest_then_farther_two"
    active_reference_policy: str = "same_bar_near_to_far_on_dull_break"
    zero_policy: str = "neutral_real_opposite"
    allow_zero_activation: bool = True
    allow_zero_reactivation: bool = True
    dif_turn_pct: float = 1.0
    max_refs: int = 2
    min_colored_bars: int = 2
    max_input_bars: int = 1000
    deadline_seconds: float = 20.0
    max_memory_bytes: int = 256 * 1024 * 1024
    max_result_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        if any(type(getattr(self, field.name)) is not type(field.default)
               or getattr(self, field.name) != field.default for field in fields(self)):
            raise ValueError("R4 research rules and limits are immutable")

    @property
    def research_hash(self) -> str:
        identity = {**asdict(self), "parentSpecHash": MAIN_SPEC.spec_hash}
        return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


R4_TRIAL_SPEC = R4TrialSpec()
_WRAPPER_FIELDS = frozenset(("researchVersion", "researchHash", "tsCode", "period", "inputIdentity", "parentState"))


class R4Calculator(XxmCalculator):
    """Near-first references, same-bar DULL switching and neutral zero columns."""

    def __init__(self, *, period: XxmPeriod, source_identity: str, ts_code: str = "000001.SH",
                 trial_spec: R4TrialSpec = R4_TRIAL_SPEC) -> None:
        if type(trial_spec) is not R4TrialSpec or not isinstance(source_identity, str) or not source_identity:
            raise ValueError("Invalid r4 research identity")
        self.trial_spec = trial_spec
        self.input_identity = source_identity
        parent_source = f"r4|{trial_spec.research_hash}|{period}|{source_identity}"
        super().__init__(period=period, source_identity=parent_source, ts_code=ts_code, spec=MAIN_SPEC)

    def _id(self, *parts: Any) -> str:
        parent_id = super()._id(*parts)
        return hashlib.sha256(f"{self.trial_spec.research_hash}|{parent_id}".encode()).hexdigest()[:24]

    def snapshot(self) -> dict[str, Any]:
        return {"researchVersion": self.trial_spec.research_version, "researchHash": self.trial_spec.research_hash,
                "tsCode": self.ts_code, "period": self.period, "inputIdentity": self.input_identity,
                "parentState": super().snapshot()}

    def restore(self, snapshot: dict[str, Any]) -> None:
        if not isinstance(snapshot, dict) or set(snapshot) != _WRAPPER_FIELDS:
            raise ValueError("Invalid r4 snapshot wrapper")
        expected = (self.trial_spec.research_version, self.trial_spec.research_hash,
                    self.ts_code, self.period, self.input_identity)
        keys = ("researchVersion", "researchHash", "tsCode", "period", "inputIdentity")
        if tuple(snapshot[key] for key in keys) != expected:
            raise ValueError("R4 snapshot research/source identity mismatch")
        parent_state = snapshot["parentState"]
        if (not isinstance(parent_state, dict)
                or set(parent_state) != set(XxmCalculator.snapshot(self))):
            raise ValueError("Invalid r4 parent snapshot fields")
        candidate = R4Calculator(period=self.period, source_identity=self.input_identity,
                                 ts_code=self.ts_code, trial_spec=self.trial_spec)
        XxmCalculator.restore(candidate, parent_state)
        self.wave, self.history, self.state, self.reference = (
            candidate.wave, candidate.history, candidate.state, candidate.reference)
        self.previous, self.pending, self.processed = candidate.previous, candidate.pending, candidate.processed
        self.pending_bottom_history, self.pending_rearm = candidate.pending_bottom_history, candidate.pending_rearm

    def _validate_restored_state(self, parsed: ParsedXxmSnapshot) -> None:
        if parsed.wave is None:
            if (parsed.state != "NONE" or parsed.reference is not None or any(parsed.history.values())
                    or parsed.pending is not None or parsed.pending_bottom_history is not None
                    or parsed.pending_rearm is not None
                    or (parsed.previous is not None and parsed.previous.hist != 0)):
                raise ValueError("R4 leading-zero snapshot carries an active segment")
            return
        if (parsed.wave.sign not in (-1, 1) or parsed.previous is None
                or (parsed.previous.hist > 0) - (parsed.previous.hist < 0) not in (0, parsed.wave.sign)):
            raise ValueError("R4 snapshot lost its logical color segment")

    def _point(self, bar: XxmBar) -> dict[str, Any]:
        sign = self.wave.sign if self.wave is not None else 0
        return {"time": bar.time, "close": bar.close, "dif": bar.dif, "dea": bar.dea, "hist": bar.hist,
                "ordinaryState": self.state,
                "ordinaryDirection": ("TOP" if sign == 1 else "BOTTOM") if self.state != "NONE" else None,
                "activeReference": self.reference.reference() if self.reference else None,
                "pendingTopHistoryId": self.pending["id"] if self.pending else None,
                "pendingBottomHistoryId": self.pending_bottom_history["id"] if self.pending_bottom_history else None,
                "pendingRearmId": self.pending_rearm["id"] if self.pending_rearm else None}

    def step(self, bar: XxmBar) -> XxmStep:
        bar.validate(self.period)
        if self.previous is not None and bar.time <= self.previous.time:
            raise ValueError("Duplicate or unordered XXM input")
        raw_sign = (bar.hist > 0) - (bar.hist < 0)
        old_wave, old_state = self.wave, self.state
        if old_wave is None and raw_sign == 0:
            self.previous = bar
            self.processed += 1
            return XxmStep(self._point(bar), (), (), (), ())
        true_flip = old_wave is not None and raw_sign == -old_wave.sign
        event_type, route, direction, event_ref = "", "", 0, None
        if old_wave is None or true_flip:
            if old_wave is not None:
                old_sign = old_wave.sign
                if self.reference is not None:
                    if old_sign * (bar.dif - self.reference.dif) > 0:
                        event_type, route = "CANCEL", "dif_break_on_flip"
                    elif self.state == "DULL":
                        event_type, route = "STRUCTURE", "color_flip"
                    if event_type:
                        direction, event_ref = old_sign, self.reference
                pool = self.history[old_sign]
                pool.append(deepcopy(old_wave))
                del pool[:-self.spec.max_refs]
            self.wave = Wave(raw_sign, bar.time, bar.time, 0, bar.close, bar.dif, bar.time, bar.time)
            self.state, self.reference = "NONE", None
        wave = self.wave
        assert wave is not None
        sign = wave.sign
        wave.count += int(raw_sign != 0)
        wave.end = bar.time
        if sign * (bar.close - wave.price) > 0:
            wave.price, wave.price_at = bar.close, bar.time
        if sign * (bar.dif - wave.dif) > 0:
            wave.dif, wave.dif_at = bar.dif, bar.time
        blocked, reactivated, rearm_records = self._advance_rearm(bar)
        if reactivated is not None:
            event_type, route, direction, event_ref = "DULL", "reactivation", -1, reactivated
        if not event_type and not blocked:
            if reactivated is None:
                self._rescue_dull_reference(bar, old_wave, old_state)
            ref = self.reference
            if ref is not None and sign * (wave.dif - ref.dif) > 0:
                event_type, route, direction, event_ref = "CANCEL", "dif_break", sign, ref
                self.state, self.reference = "NONE", None
            elif ref is not None and self.previous is not None:
                basis = self.previous.dif
                delta = sign * (bar.dif - basis)
                gate = abs(basis) * self.spec.dif_turn_pct / 100
                if basis != 0 and self.state == "DULL" and delta < 0 and -delta >= gate:
                    event_type, route, self.state = "STRUCTURE", "dif_turn", "STRUCTURE"
                elif basis != 0 and self.state == "STRUCTURE" and delta > 0 and delta >= gate:
                    if sign == -1 and not self._qualifies_bottom_close(bar, ref, self.history[-1][-1].price):
                        original = self.pending_bottom_history
                        if original is None:
                            raise ValueError("Same-segment structure has no BOTTOM history")
                        rearm_records = (self._start_rearm(bar, ref, original),)
                        event_type, route, self.state = "STRUCTURE_DISAPPEARED", "dif_return", "NONE"
                        self.reference = None
                    else:
                        event_type, route, self.state = "DULL", "dif_return", "DULL"
                if event_type:
                    direction, event_ref = sign, ref
            elif (wave.count >= self.spec.min_bars and self.history[sign]
                  and (sign != 1 or bar.dif > 0)):
                candidate = self._select_eligible_reference(wave, self.history[sign])
                if candidate is not None:
                    self.reference = deepcopy(candidate)
                    event_type, route, direction, event_ref = "DULL", "activation", sign, self.reference
                    self.state = "DULL"
        events: list[dict[str, Any]] = []
        if event_type:
            events.append({"id": self._id(bar.time, event_type, direction, event_ref.start if event_ref else ""),
                           "time": bar.time, "direction": "TOP" if direction == 1 else "BOTTOM",
                           "type": event_type, "route": route, "fromState": old_state,
                           "eventReference": event_ref.reference() if event_ref else None,
                           "relatedTopHistoryId": None, "relatedBottomHistoryId": None,
                           "relatedRearmId": rearm_records[-1]["id"]
                           if event_type == "STRUCTURE_DISAPPEARED" or route == "reactivation" else None})
            if event_type == "STRUCTURE_DISAPPEARED":
                events[0]["relatedBottomHistoryId"] = rearm_records[-1]["bottomHistoryId"]
        ordinary_event = events[0] if event_type else None
        histories: list[dict[str, Any]] = []
        pending = self.pending
        top_new = direction == 1 and event_type in ("DULL", "STRUCTURE")
        if pending is not None:
            pending["observedThrough"] = bar.time
            pending["ageBars"] += 1
            pending["negativeBars"] += int(raw_sign < 0)
            pending["zeroBars"] += int(raw_sign == 0)
            pending["colorChanges"] += int(true_flip)
            reason = None
            if bar.dif > pending["originalReference"]["dif"]:
                reason = "original_reference_break"
            elif top_new:
                reason = f"new_top_{event_type}"
            elif bar.time > pending["confirmedAt"] and bar.close > pending["pricePeak"]:
                reason = "historical_price_break"
                events.append({"id": self._id(bar.time, "RESEARCH_HISTORICAL_WITHDRAWAL", pending["id"]),
                               "time": bar.time, "direction": "TOP", "type": "RESEARCH_HISTORICAL_WITHDRAWAL",
                               "route": "historical_price_break", "fromState": self.state,
                               "eventReference": deepcopy(pending["originalReference"]),
                               "relatedTopHistoryId": pending["id"], "relatedBottomHistoryId": None,
                               "relatedRearmId": None})
            if reason is not None:
                pending.update(status="ENDED", endedAt=bar.time, endReason=reason)
                self.pending = None
            histories.append(deepcopy(pending))
        if direction == 1 and event_type == "STRUCTURE":
            assert event_ref is not None
            peak_wave = wave if sign == 1 else old_wave
            assert peak_wave is not None and peak_wave.sign == 1
            history_id = self._id("history", bar.time, route, event_ref.start)
            self.pending = {"id": history_id, "confirmedAt": bar.time, "confirmationRoute": route,
                            "pricePeak": peak_wave.price, "pricePeakAt": peak_wave.price_at,
                            "originalReference": event_ref.reference(), "status": "PENDING", "endedAt": None,
                            "endReason": None, "observedThrough": bar.time, "ageBars": 0,
                            "negativeBars": 0, "zeroBars": 0, "colorChanges": 0}
            histories.append(deepcopy(self.pending))
            events[0]["relatedTopHistoryId"] = history_id
        bottom_events, bottom_histories = self._advance_bottom_history(bar, ordinary_event)
        events.extend(bottom_events)
        if ordinary_event is not None and direction == -1 and event_type == "STRUCTURE":
            negative_wave = wave if sign == -1 else old_wave
            if negative_wave is None or negative_wave.sign != -1:
                raise ValueError("BOTTOM structure requires its original negative segment")
            bottom_histories.append(self._start_bottom_history(bar, ordinary_event, negative_wave))
        point = self._point(bar)
        self.previous = bar
        self.processed += 1
        return XxmStep(point, tuple(events), tuple(histories), tuple(bottom_histories), rearm_records)

    def _select_eligible_reference(self, wave: Wave, history: list[Wave]) -> Wave | None:
        if not history or wave.count < self.spec.min_bars:
            return None
        pool = list(reversed(history))[:self.spec.max_refs]
        if wave.sign * (wave.price - pool[0].price) <= 0:
            return None
        return next((candidate for candidate in pool
                     if wave.sign * (wave.price - candidate.price) > 0
                     and wave.sign * (wave.dif - candidate.dif) < 0), None)

    def _rescue_dull_reference(self, bar: XxmBar, old_wave: Wave | None, old_state: str) -> None:
        wave, ref = self.wave, self.reference
        if (old_state != "DULL" or self.state != "DULL" or wave is None or wave is not old_wave
                or wave.sign not in (-1, 1) or ref is None or self.pending_rearm is not None):
            return
        sign = wave.sign
        raw_sign = (bar.hist > 0) - (bar.hist < 0)
        if raw_sign not in (0, sign) or sign * (wave.dif - ref.dif) <= 0:
            return
        pool = list(reversed(self.history[sign]))[:self.spec.max_refs]
        if len(pool) != 2 or ref.reference() != pool[0].reference():
            return
        candidate = self._select_eligible_reference(wave, self.history[sign])
        if candidate is not None and candidate.reference() == pool[1].reference():
            self.reference = deepcopy(candidate)

    def _qualifies_bottom_close(self, bar: XxmBar, reference: Wave, nearest_price: float) -> bool:
        return (bar.hist <= 0 and self.wave is not None and self.wave.sign == -1
                and self.wave.count >= self.spec.min_bars and bar.close < min(reference.price, nearest_price)
                and self.wave.dif > reference.dif)

    def _advance_rearm(self, bar: XxmBar) -> tuple[bool, Wave | None, tuple[XxmRearmRecord, ...]]:
        record = self.pending_rearm
        if record is None:
            return False, None, ()
        assert self.wave is not None
        if bar.hist > 0 or self.wave.start != record["segmentStart"]:
            return False, None, (self._end_rearm(bar, "SEGMENT_ENDED", "color_flip"),)
        reference = Wave(**record["referenceWave"])
        if bar.dif < reference.dif:
            return True, None, (self._end_rearm(bar, "INVALIDATED", "reference_dif_break"),)
        if bar.time > record["disappearedAt"] and self._qualifies_bottom_close(bar, reference, record["nearestPriceGate"]):
            self.reference, self.state = reference, "DULL"
            return True, reference, (self._end_rearm(bar, "REACTIVATED", "price_requalified"),)
        record["observedThrough"] = bar.time
        return True, None, (deepcopy(record),)

    def _advance_bottom_history(self, bar: XxmBar, ordinary_event: dict[str, Any] | None
                                ) -> tuple[list[dict[str, Any]], list[XxmBottomHistory]]:
        record = self.pending_bottom_history
        if record is None:
            return [], []
        record["observedThrough"] = bar.time
        record["ageBars"] += 1
        if record["leftOriginAt"] is None and bar.hist > 0:
            record["leftOriginAt"] = bar.time
        reason = None
        events = []
        if bar.dif < record["originalReference"]["dif"]:
            reason = "original_reference_break"
        elif ordinary_event is not None and ordinary_event["type"] == "STRUCTURE_DISAPPEARED":
            if record["leftOriginAt"] is not None or ordinary_event["relatedBottomHistoryId"] != record["id"]:
                raise ValueError("Same-segment disappearance targets unrelated BOTTOM history")
            reason = "structure_disappeared"
        elif ordinary_event is not None and ordinary_event["direction"] == "BOTTOM" and ordinary_event["type"] in ("DULL", "STRUCTURE"):
            reason = "new_bottom_" + ordinary_event["type"]
        elif record["leftOriginAt"] is not None and bar.time > record["confirmedAt"] and bar.close < record["priceLow"]:
            reason = "historical_price_break"
            events.append({"id": self._id(bar.time, "RESEARCH_HISTORICAL_WITHDRAWAL", record["id"]),
                           "time": bar.time, "direction": "BOTTOM", "type": "RESEARCH_HISTORICAL_WITHDRAWAL",
                           "route": "historical_price_break", "fromState": self.state,
                           "eventReference": deepcopy(record["originalReference"]),
                           "relatedTopHistoryId": None, "relatedBottomHistoryId": record["id"], "relatedRearmId": None})
        if reason is not None:
            record.update(status="ENDED", endedAt=bar.time, endReason=reason)
            self.pending_bottom_history = None
        return events, [deepcopy(record)]

    def _start_bottom_history(self, bar: XxmBar, structure_event: dict[str, Any], negative_wave: Wave) -> XxmBottomHistory:
        if negative_wave.sign != -1 or structure_event["eventReference"] is None:
            raise ValueError("BOTTOM history requires a negative segment and a reference")
        history_id = self._id("bottom-history", structure_event["id"])
        record: XxmBottomHistory = {
            "id": history_id, "structureEventId": structure_event["id"], "confirmedAt": bar.time,
            "confirmationRoute": structure_event["route"], "originSegmentStart": negative_wave.start,
            "leftOriginAt": bar.time if bar.hist > 0 else None,
            "priceLow": negative_wave.price, "priceLowAt": negative_wave.price_at,
            "originalReference": deepcopy(structure_event["eventReference"]), "status": "PENDING",
            "endedAt": None, "endReason": None, "observedThrough": bar.time, "ageBars": 0,
        }
        self.pending_bottom_history = record
        structure_event["relatedBottomHistoryId"] = history_id
        return deepcopy(record)

    def _validate_rearm_snapshot(self, raw: Any, *, previous: XxmBar | None, wave: Wave | None,
                                 state: str, reference: Wave | None, bottom_history: XxmBottomHistory | None,
                                 processed: int, history: dict[int, list[Wave]]) -> XxmRearmRecord | None:
        if raw is None:
            return None
        if not isinstance(raw, dict) or set(raw) != set(XxmRearmRecord.__annotations__):
            raise ValueError("Invalid rearm snapshot fields")
        try:
            if (raw["status"] != "WAITING" or raw["endedAt"] is not None or raw["endReason"] is not None
                    or raw["direction"] != "BOTTOM" or raw["structureRoute"] != "dif_turn"
                    or state != "NONE" or reference is not None or bottom_history is not None
                    or previous is None or processed < 1 or wave is None or wave.sign != -1
                    or previous.hist > 0 or wave.end != previous.time or type(wave.count) is not int
                    or not 1 <= wave.count <= processed
                    or raw["segmentStart"] != wave.start or raw["observedThrough"] != previous.time
                    or not math.isfinite(raw["nearestPriceGate"]) or raw["nearestPriceGate"] <= 0):
                raise ValueError("Invalid active rearm snapshot")
            values = raw["referenceWave"]
            if not isinstance(values, dict) or set(values) != set(Wave.__dataclass_fields__):
                raise ValueError("Incomplete original rearm Wave")
            saved = Wave(**values)
            if (type(saved.sign) is not int or saved.sign != -1 or type(saved.count) is not int or saved.count < 1
                    or not math.isfinite(saved.price) or saved.price <= 0 or not math.isfinite(saved.dif)
                    or saved not in history[-1] or not history[-1]
                    or raw["nearestPriceGate"] != history[-1][-1].price or wave.dif < saved.dif):
                raise ValueError("Invalid saved rearm reference")
            stamps = [raw[key] for key in ("segmentStart", "structureConfirmedAt", "disappearedAt", "observedThrough")]
            stamps += [saved.start, saved.end, saved.price_at, saved.dif_at]
            for stamp in stamps:
                XxmBar(stamp, 1., 0., 0., 0.).validate(self.period)
            if not (saved.start <= saved.price_at <= saved.end < raw["segmentStart"]
                    and saved.start <= saved.dif_at <= saved.end
                    and raw["segmentStart"] <= raw["structureConfirmedAt"] < raw["disappearedAt"] <= raw["observedThrough"]):
                raise ValueError("Invalid rearm chronology")
            structure = self._id(raw["structureConfirmedAt"], "STRUCTURE", -1, saved.start)
            if (raw["structureEventId"] != structure or raw["bottomHistoryId"] != self._id("bottom-history", structure)
                    or raw["id"] != self._id("rearm", structure, raw["disappearedAt"])):
                raise ValueError("Invalid rearm identities")
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("Malformed rearm snapshot") from exc
        return deepcopy(raw)
