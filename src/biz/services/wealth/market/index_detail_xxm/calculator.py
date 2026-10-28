from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import math
from typing import Any

from .snapshot_validation import ParsedXxmSnapshot, parse_xxm_snapshot
from .spec import MAIN_SPEC, XxmSpec
from .types import Wave, XxmBar, XxmBottomHistory, XxmPeriod, XxmRearmRecord, XxmStep


class XxmCalculator:
    """Causal bounded state. Callers keep the immutable event/point ledger."""

    def __init__(self, *, period: XxmPeriod, source_identity: str, ts_code: str = "000001.SH",
                 spec: XxmSpec = MAIN_SPEC, record_decisions: bool = False) -> None:
        if type(record_decisions) is not bool:
            raise ValueError("record_decisions must be a boolean")
        if ts_code != "000001.SH" or period not in ("day", "m60", "m90", "m120") or not source_identity:
            raise ValueError("Unsupported XXM identity")
        self.period, self.source_identity, self.ts_code, self.spec = period, source_identity, ts_code, spec
        self.wave: Wave | None = None
        self.history: dict[int, list[Wave]] = {1: [], -1: []}
        self.state = "NONE"
        self.reference: Wave | None = None
        self.previous: XxmBar | None = None
        self.pending: dict[str, Any] | None = None
        self.pending_bottom_history: XxmBottomHistory | None = None
        self.pending_rearm: XxmRearmRecord | None = None
        self.processed = 0
        self.record_decisions = record_decisions
        self._decision_context: dict[str, Any] | None = None

    def _id(self, *parts: Any) -> str:
        identity = [self.spec.algorithm_version, self.spec.spec_hash, self.ts_code, self.period, *parts]
        return hashlib.sha256("|".join(map(str, identity)).encode()).hexdigest()[:24]

    def _point(self, bar: XxmBar) -> dict[str, Any]:
        sign = self.wave.sign if self.wave is not None else 0
        return {"time": bar.time, "close": bar.close, "dif": bar.dif, "dea": bar.dea, "hist": bar.hist,
                "ordinaryState": self.state,
                "ordinaryDirection": ("TOP" if sign == 1 else "BOTTOM") if self.state != "NONE" else None,
                "activeReference": self.reference.reference() if self.reference else None,
                "pendingTopHistoryId": self.pending["id"] if self.pending else None,
                "pendingBottomHistoryId": self.pending_bottom_history["id"] if self.pending_bottom_history else None,
                "pendingRearmId": self.pending_rearm["id"] if self.pending_rearm else None}

    def _begin_decision(self, bar: XxmBar) -> None:
        previous = self.previous.dif if self.previous else None
        self._decision_context = {
            "time": bar.time, "rawSign": (bar.hist > 0) - (bar.hist < 0),
            "before": {"state": self.state, "reference": self.reference.reference() if self.reference else None,
                       "wave": asdict(self.wave) if self.wave else None, "previousDif": previous},
            "referenceChecks": [], "selectionCalls": [], "selectionStage": "activation",
            "turn": {"previousDif": previous, "currentDif": bar.dif, "threshold": None,
                     "referenceBroken": None, "checked": False, "reason": "未进入相邻DIF转折分支"},
            "rearm": {"blocked": False, "status": None, "referenceBroken": None}, "switched": False,
        }

    def _record_reference_check(self, stage: str, name: str, candidate: Wave, *, checked: bool = False,
                                price: bool | None = None, dif: bool | None = None, reason: str) -> None:
        if self._decision_context is not None:
            self._decision_context["referenceChecks"].append({
                "stage": stage, "candidate": name, "wave": asdict(candidate), "checked": checked,
                "pricePassed": price, "difPassed": dif, "reason": reason,
            })

    def _selection_result(self, selected: Wave | None) -> Wave | None:
        context = self._decision_context
        if context is not None:
            context["selectionCalls"].append({"stage": context["selectionStage"],
                                               "selected": selected.reference() if selected else None})
        return selected

    def _finish_step(self, result: XxmStep) -> XxmStep:
        context = self._decision_context
        if context is None:
            return result
        ordinary = next((event for event in result.events if event["type"] != "RESEARCH_HISTORICAL_WITHDRAWAL"), None)
        if ordinary is not None:
            branch, reason = ordinary["route"], "实际普通事件：" + ordinary["type"] + "/" + ordinary["route"]
        elif context["rearm"]["blocked"]:
            branch, reason = "waiting", "等待处理阻断本根首次或相邻转折判断"
        elif context["switched"]:
            branch, reason = "reference_switch", "B已突破且A合格，当根切换并保持钝化"
        elif self.wave is None:
            branch, reason = "leading_zero", "开头零柱尚无逻辑色段"
        elif context["before"]["wave"] is not None and context["before"]["wave"]["sign"] != self.wave.sign:
            branch, reason = "segment_changed", "真实柱色改变，本根无普通事件"
        elif self.reference is not None:
            branch, reason = "retained", "沿用已有参照，本根无普通事件"
        else:
            branch, reason = "no_activation", "未达到首次钝化条件"
        if context["switched"] and ordinary is not None:
            reason = "当根已从B切换到A；" + reason
        if not context["selectionCalls"] and self.wave is not None:
            for i, candidate in enumerate(reversed(self.history[self.wave.sign])):
                self._record_reference_check("not_entered", "B" if i == 0 else "A", candidate,
                                             reason="未调用参照选择：" + reason)
        decision = {key: context[key] for key in (
            "time", "rawSign", "before", "referenceChecks", "selectionCalls", "turn", "rearm", "switched")}
        decision.update(wave=asdict(self.wave) if self.wave else None,
                        referenceAfter=self.reference.reference() if self.reference else None,
                        branch=branch, reason=reason)
        return replace(result, decision=deepcopy(decision))

    def step(self, bar: XxmBar) -> XxmStep:
        bar.validate(self.period)
        if self.previous is not None and bar.time <= self.previous.time:
            raise ValueError("Duplicate or unordered XXM input")
        if self.record_decisions:
            self._begin_decision(bar)
        try:
            raw_sign = (bar.hist > 0) - (bar.hist < 0)
            old_wave, old_state = self.wave, self.state
            if old_wave is None and raw_sign == 0:
                self.previous = bar
                self.processed += 1
                return self._finish_step(XxmStep(self._point(bar), (), (), (), ()))
            true_flip = old_wave is not None and raw_sign == -old_wave.sign
            event_type, route, direction, event_ref = "", "", 0, None
            if old_wave is None or true_flip:
                if old_wave is not None:
                    old_sign = old_wave.sign
                    if self.reference is not None:
                        broken_on_flip = old_sign * (bar.dif - self.reference.dif) > 0
                        if self._decision_context is not None:
                            self._decision_context["turn"].update(referenceBroken=broken_on_flip, reason="真实翻色，未检查相邻转折")
                        if broken_on_flip:
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
            if self._decision_context is not None:
                record = rearm_records[-1] if rearm_records else None
                self._decision_context["rearm"].update(
                    blocked=blocked, status=record["status"] if record else None)
                if blocked:
                    self._decision_context["turn"]["reason"] = "等待处理阻断相邻转折分支"
            if reactivated is not None:
                event_type, route, direction, event_ref = "DULL", "reactivation", -1, reactivated
            if not event_type and not blocked:
                if reactivated is None:
                    self._rescue_dull_reference(bar, old_wave, old_state)
                ref = self.reference
                reference_broken = sign * (wave.dif - ref.dif) > 0 if ref is not None else None
                if self._decision_context is not None:
                    self._decision_context["turn"]["referenceBroken"] = reference_broken
                    if reference_broken:
                        self._decision_context["turn"]["reason"] = "原参照DIF已突破，优先取消"
                if ref is not None and reference_broken:
                    event_type, route, direction, event_ref = "CANCEL", "dif_break", sign, ref
                    self.state, self.reference = "NONE", None
                elif ref is not None and self.previous is not None:
                    basis = self.previous.dif
                    delta = sign * (bar.dif - basis)
                    gate = abs(basis) * self.spec.dif_turn_pct / 100
                    if self._decision_context is not None:
                        self._decision_context["turn"].update(threshold=gate, checked=True,
                            reason="相邻实际DIF按1%检查" if basis != 0 else "前值DIF为0，不触发转折")
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
            return self._finish_step(XxmStep(point, tuple(events), tuple(histories), tuple(bottom_histories), rearm_records))
        finally:
            self._decision_context = None

    def _select_eligible_reference(self, wave: Wave, history: list[Wave]) -> Wave | None:
        if not history or wave.count < self.spec.min_bars:
            return self._selection_result(None)
        pool = list(reversed(history))[:self.spec.max_refs]
        stage = self._decision_context["selectionStage"] if self._decision_context is not None else "activation"
        nearest_price = wave.sign * (wave.price - pool[0].price) > 0
        self._record_reference_check("nearest_price_gate", "B", pool[0], checked=True, price=nearest_price,
                                     reason="最近B收盘门槛通过" if nearest_price else "未严格突破最近B收盘门槛")
        if not nearest_price:
            if len(pool) == 2:
                self._record_reference_check(stage, "A", pool[1], reason="B价格门槛未过，未检查A")
            return self._selection_result(None)
        for index, candidate in enumerate(pool):
            price = nearest_price if index == 0 else wave.sign * (wave.price - candidate.price) > 0
            dif = wave.sign * (wave.dif - candidate.dif) < 0 if price else None
            self._record_reference_check(stage, "B" if index == 0 else "A", candidate,
                                         checked=True, price=price, dif=dif,
                                         reason="参照合格" if price and dif else "DIF未严格背离" if price else "未突破该参照收盘")
            if price and dif:
                if index == 0 and len(pool) == 2:
                    self._record_reference_check(stage, "A", pool[1], reason="B已合格，未检查A")
                return self._selection_result(candidate)
        return self._selection_result(None)

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
        context = self._decision_context
        if context is not None:
            context["selectionStage"] = "same_bar_rescue"
        try:
            candidate = self._select_eligible_reference(wave, self.history[sign])
        finally:
            if context is not None:
                context["selectionStage"] = "activation"
        if candidate is not None and candidate.reference() == pool[1].reference():
            self.reference = deepcopy(candidate)
            if context is not None:
                context["switched"] = True

    def snapshot(self) -> dict[str, Any]:
        return {"specHash": self.spec.spec_hash, "tsCode": self.ts_code, "period": self.period, "sourceIdentity": self.source_identity,
                "processed": self.processed, "wave": asdict(self.wave) if self.wave else None,
                "history": {str(k): [asdict(w) for w in waves] for k, waves in self.history.items()},
                "state": self.state, "reference": asdict(self.reference) if self.reference else None,
                "previous": asdict(self.previous) if self.previous else None, "pending": deepcopy(self.pending),
                "pendingBottomHistory": deepcopy(self.pending_bottom_history), "pendingRearm": deepcopy(self.pending_rearm)}

    def _qualifies_bottom_close(self, bar: XxmBar, reference: Wave, nearest_price: float) -> bool:
        return (bar.hist <= 0 and self.wave is not None and self.wave.sign == -1
                and self.wave.count >= self.spec.min_bars and bar.close < min(reference.price, nearest_price)
                and self.wave.dif > reference.dif)

    def _start_rearm(self, bar: XxmBar, reference: Wave, original: XxmBottomHistory) -> XxmRearmRecord:
        if (self.pending_rearm is not None or original["leftOriginAt"] is not None or self.wave is None
                or original["confirmationRoute"] != "dif_turn" or original["originSegmentStart"] != self.wave.start
                or original["originalReference"] != reference.reference()):
            raise ValueError("Invalid original structure for rearm")
        record: XxmRearmRecord = dict(
            id=self._id("rearm", original["structureEventId"], bar.time), direction="BOTTOM",
            bottomHistoryId=original["id"], structureEventId=original["structureEventId"],
            structureConfirmedAt=original["confirmedAt"], structureRoute=original["confirmationRoute"],
            segmentStart=self.wave.start, nearestPriceGate=self.history[-1][-1].price,
            referenceWave=asdict(reference), disappearedAt=bar.time, observedThrough=bar.time,
            status="WAITING", endedAt=None, endReason=None)
        self.pending_rearm = record
        return deepcopy(record)

    def _end_rearm(self, bar: XxmBar, status: str, reason: str) -> XxmRearmRecord:
        assert self.pending_rearm is not None
        self.pending_rearm.update(status=status, endedAt=bar.time, endReason=reason, observedThrough=bar.time)
        record = deepcopy(self.pending_rearm)
        self.pending_rearm = None
        return record

    def _advance_rearm(self, bar: XxmBar) -> tuple[bool, Wave | None, tuple[XxmRearmRecord, ...]]:
        record = self.pending_rearm
        if record is None:
            return False, None, ()
        assert self.wave is not None
        if bar.hist > 0 or self.wave.start != record["segmentStart"]:
            return False, None, (self._end_rearm(bar, "SEGMENT_ENDED", "color_flip"),)
        reference = Wave(**record["referenceWave"])
        reference_broken = bar.dif < reference.dif
        if self._decision_context is not None:
            self._decision_context["rearm"]["referenceBroken"] = reference_broken
        if reference_broken:
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

    def _validate_bottom_history_snapshot(self, raw: Any, *, previous: XxmBar | None,
                                         wave: Wave | None, processed: int) -> XxmBottomHistory | None:
        if raw is None:
            return None
        if not isinstance(raw, dict) or set(raw) != set(XxmBottomHistory.__annotations__):
            raise ValueError("Invalid BOTTOM snapshot fields")
        try:
            if (not isinstance(raw["structureEventId"], str) or not raw["structureEventId"]
                    or raw["id"] != self._id("bottom-history", raw["structureEventId"])
                    or raw["status"] != "PENDING" or raw["endedAt"] is not None or raw["endReason"] is not None
                    or raw["confirmationRoute"] not in ("dif_turn", "color_flip")
                    or type(raw["ageBars"]) is not int or not 0 <= raw["ageBars"] <= processed
                    or not math.isfinite(raw["priceLow"]) or raw["priceLow"] <= 0 or previous is None
                    or raw["observedThrough"] != previous.time):
                raise ValueError("Invalid pending BOTTOM snapshot")
            ref = raw["originalReference"]
            if (not isinstance(ref, dict) or set(ref) != {"startTime", "endTime", "price", "dif"}
                    or not math.isfinite(ref["dif"]) or not math.isfinite(ref["price"]) or ref["price"] <= 0):
                raise ValueError("Invalid BOTTOM original reference")
            stamps = [raw[k] for k in ("originSegmentStart", "priceLowAt", "confirmedAt", "observedThrough")]
            stamps += [ref["startTime"], ref["endTime"]]
            if raw["leftOriginAt"] is not None:
                stamps.append(raw["leftOriginAt"])
            for stamp in stamps:
                XxmBar(stamp, 1., 0., 0., 0.).validate(self.period)
            if not (raw["originSegmentStart"] <= raw["priceLowAt"] <= raw["confirmedAt"] <= raw["observedThrough"]
                    and ref["startTime"] <= ref["endTime"] < raw["originSegmentStart"]):
                raise ValueError("Invalid BOTTOM snapshot chronology")
            expected_structure_id = self._id(raw["confirmedAt"], "STRUCTURE", -1, ref["startTime"])
            if raw["structureEventId"] != expected_structure_id:
                raise ValueError("Invalid BOTTOM structure event identity")
            left = raw["leftOriginAt"]
            if left is not None:
                if not raw["confirmedAt"] <= left <= raw["observedThrough"]:
                    raise ValueError("Invalid BOTTOM origin exit")
            elif wave is None or wave.sign != -1 or wave.start != raw["originSegmentStart"]:
                raise ValueError("BOTTOM snapshot lost its original segment")
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("Malformed BOTTOM snapshot") from exc
        return deepcopy(raw)

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
        if parsed.state != "NONE" and parsed.wave.count < self.spec.min_bars:
            raise ValueError("An active r4 state requires two colored bars")

    def restore(self, snapshot: dict[str, Any]) -> None:
        # Build independent progress before publishing, including legal rewinds.
        try:
            expected = (self.spec.spec_hash, self.ts_code, self.period, self.source_identity)
            parsed = parse_xxm_snapshot(snapshot, expected_identity=expected, period=self.period,
                                        max_refs=self.spec.max_refs)
            parsed.pending_bottom_history = self._validate_bottom_history_snapshot(
                parsed.pending_bottom_history, previous=parsed.previous, wave=parsed.wave, processed=parsed.processed)
            parsed.pending_rearm = self._validate_rearm_snapshot(
                parsed.pending_rearm, previous=parsed.previous, wave=parsed.wave, state=parsed.state,
                reference=parsed.reference, bottom_history=parsed.pending_bottom_history,
                processed=parsed.processed, history=parsed.history)
            if parsed.pending is not None:
                pending = parsed.pending
                expected_top_id = self._id("history", pending["confirmedAt"], pending["confirmationRoute"],
                                           pending["originalReference"]["startTime"])
                if pending["id"] != expected_top_id:
                    raise ValueError("Invalid TOP snapshot identity")
            self._validate_restored_state(parsed)
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("Malformed XXM snapshot") from exc
        self.wave, self.history, self.state, self.reference = parsed.wave, parsed.history, parsed.state, parsed.reference
        self.previous, self.pending, self.processed = parsed.previous, parsed.pending, parsed.processed
        self.pending_bottom_history, self.pending_rearm = parsed.pending_bottom_history, parsed.pending_rearm
        self._decision_context = None
