from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
from typing import Any

from .snapshot_validation import (
    ParsedXxmSnapshot, parse_xxm_snapshot, validate_structure_record, validate_xxm_progress,
)
from .spec import MAIN_SPEC, XxmSpec
from .types import Wave, XxmBar, XxmPeriod, XxmStep, XxmStructureRecord


def _same_facts(left: Any, right: Any) -> bool:
    """Copies must preserve types too: True is not the recorded integer 1."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_facts(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(_same_facts(a, b) for a, b in zip(left, right))
    return left == right


class XxmCalculator:
    """Causal, bounded progress; callers retain the immutable result ledger."""

    def __init__(self, *, period: XxmPeriod, source_identity: str, ts_code: str = "000001.SH",
                 spec: XxmSpec = MAIN_SPEC, record_decisions: bool = False) -> None:
        if type(record_decisions) is not bool:
            raise ValueError("record_decisions must be a boolean")
        if (ts_code != "000001.SH" or period not in ("day", "m60", "m90", "m120")
                or not isinstance(source_identity, str) or not source_identity
                or type(spec) is not XxmSpec):
            raise ValueError("Unsupported XXM identity")
        self.period, self.source_identity, self.ts_code, self.spec = period, source_identity, ts_code, spec
        self.wave: Wave | None = None
        self.history: dict[int, list[Wave]] = {1: [], -1: []}
        self.state = "NONE"
        self.reference: Wave | None = None
        self.previous: XxmBar | None = None
        self.active_structure: XxmStructureRecord | None = None
        self.processed = 0
        self.record_decisions = record_decisions
        self._decision_context: dict[str, Any] | None = None

    def _id(self, *parts: Any) -> str:
        identity = [self.spec.algorithm_version, self.spec.spec_hash, self.ts_code, self.period, *parts]
        return hashlib.sha256("|".join(map(str, identity)).encode()).hexdigest()[:24]

    def _progress(self) -> ParsedXxmSnapshot:
        return ParsedXxmSnapshot(wave=self.wave, history=self.history, state=self.state,
                                 reference=self.reference, previous=self.previous,
                                 active_structure=self.active_structure, processed=self.processed)

    def _publish(self, work: ParsedXxmSnapshot) -> None:
        (self.wave, self.history, self.state, self.reference, self.previous,
         self.active_structure, self.processed) = (
            work.wave, work.history, work.state, work.reference, work.previous,
            work.active_structure, work.processed)

    def _point(self, bar: XxmBar, work: ParsedXxmSnapshot) -> dict[str, Any]:
        return {"time": bar.time, "close": bar.close, "dif": bar.dif, "dea": bar.dea, "hist": bar.hist,
                "ordinaryState": work.state,
                "ordinaryDirection": ("TOP" if work.wave.sign == 1 else "BOTTOM")
                if work.state != "NONE" and work.wave is not None else None,
                "activeReference": work.reference.reference() if work.reference else None,
                "activeStructureId": work.active_structure["id"] if work.active_structure else None}

    def _event(self, bar: XxmBar, event_type: str, route: str, sign: int, event_ref: Wave,
               from_state: str, related_structure_id: str | None) -> dict[str, Any]:
        return {"id": self._id(bar.time, event_type, sign, event_ref.start), "time": bar.time,
                "direction": "TOP" if sign == 1 else "BOTTOM", "type": event_type,
                "route": route, "fromState": from_state, "eventReference": deepcopy(event_ref.reference()),
                "relatedStructureId": related_structure_id}

    def _start_structure(self, bar: XxmBar, origin_wave: Wave, ref: Wave,
                         route: str) -> tuple[dict[str, Any], XxmStructureRecord]:
        event_id = self._id(bar.time, "STRUCTURE", origin_wave.sign, ref.start)
        structure_id = self._id("structure", event_id)
        record: XxmStructureRecord = {
            "id": structure_id, "direction": "TOP" if origin_wave.sign == 1 else "BOTTOM",
            "structureEventId": event_id, "formedAt": bar.time, "formationRoute": route,
            "originSegmentStart": origin_wave.start, "originalReference": deepcopy(ref.reference()),
            "priceExtreme": origin_wave.price, "priceExtremeAt": origin_wave.price_at,
            "status": "LOCKED" if route == "color_flip" else "ASSESSING",
            "lockedAt": bar.time if route == "color_flip" else None,
            "disappearedAt": None, "disappearanceReason": None,
        }
        return self._event(bar, "STRUCTURE", route, origin_wave.sign, ref, "DULL", structure_id), record

    def _finish_structure(self, record: XxmStructureRecord, bar: XxmBar,
                          status: str, reason: str | None) -> XxmStructureRecord:
        if record["status"] != "ASSESSING" or status not in ("LOCKED", "DISAPPEARED"):
            raise ValueError("Only an assessing structure can reach its final status")
        result = deepcopy(record)
        result.update(status=status, lockedAt=bar.time if status == "LOCKED" else None,
                      disappearedAt=bar.time if status == "DISAPPEARED" else None,
                      disappearanceReason=reason)
        return result

    @staticmethod
    def _reference_was_broken(wave: Wave, ref: Wave) -> bool:
        # Equal is not a strict break. Each reference has its own comparison.
        return wave.sign * (wave.dif - ref.dif) > 0

    def _record_reference_check(self, stage: str, name: str, candidate: Wave, *, checked: bool = False,
                                price: bool | None = None, dif: bool | None = None,
                                broken: bool | None = None, reason: str) -> None:
        if self._decision_context is not None:
            self._decision_context["referenceChecks"].append({
                "stage": stage, "candidate": name, "wave": asdict(candidate), "checked": checked,
                "pricePassed": price, "difPassed": dif, "referenceBroken": broken, "reason": reason,
            })

    def _current_reference_qualifies(self, bar: XxmBar, wave: Wave, ref: Wave, nearest: Wave) -> bool:
        if (wave.count < self.spec.min_bars or (bar.hist > 0) - (bar.hist < 0) not in (0, wave.sign)
                or (wave.sign == 1 and self.spec.top_activation_requires_positive_dif and bar.dif <= 0)):
            return False
        price = wave.sign * (bar.close - nearest.price) > 0 and wave.sign * (bar.close - ref.price) > 0
        broken = self._reference_was_broken(wave, ref) if price else None
        dif = wave.sign * (bar.dif - ref.dif) < 0 if price else None
        if self._decision_context is not None:
            stage = self._decision_context["selectionStage"]
            self._record_reference_check(stage, "B" if ref == nearest else "A", ref, checked=True,
                                         price=price, dif=dif, broken=broken,
                                         reason="未突破该参照收盘" if not price else
                                         "本轮曾突破参照DIF" if broken else
                                         "本根DIF未严格背离" if not dif else "参照合格")
        return price and dif is True and broken is False

    def _selection_result(self, selected: Wave | None) -> Wave | None:
        if self._decision_context is not None:
            self._decision_context["selectionCalls"].append({
                "stage": self._decision_context["selectionStage"],
                "selected": selected.reference() if selected else None})
        return selected

    def _select_eligible_reference(self, bar: XxmBar, wave: Wave, history: list[Wave]) -> Wave | None:
        if (not history or wave.count < self.spec.min_bars
                or (wave.sign == 1 and self.spec.top_activation_requires_positive_dif and bar.dif <= 0)):
            return self._selection_result(None)
        pool = list(reversed(history))[:self.spec.max_refs]
        nearest = pool[0]
        price_gate = wave.sign * (bar.close - nearest.price) > 0
        self._record_reference_check("nearest_price_gate", "B", nearest, checked=True, price=price_gate,
                                     reason="最近B收盘门槛通过" if price_gate else "未严格突破最近B收盘门槛")
        if not price_gate:
            if len(pool) == 2:
                stage = self._decision_context["selectionStage"] if self._decision_context else "activation"
                self._record_reference_check(stage, "A", pool[1], reason="B价格门槛未过，未检查A")
            return self._selection_result(None)
        for index, candidate in enumerate(pool):
            if self._current_reference_qualifies(bar, wave, candidate, nearest):
                if index == 0 and len(pool) == 2:
                    self._record_reference_check("activation", "A", pool[1], reason="B已合格，未检查A")
                return self._selection_result(candidate)
        return self._selection_result(None)

    def _rescue_dull_reference(self, bar: XxmBar, wave: Wave, reference: Wave,
                              history: list[Wave]) -> Wave | None:
        # The caller permits this only in DULL, on the same logical segment.
        pool = list(reversed(history))[:self.spec.max_refs]
        if (len(pool) != 2 or reference != pool[0]
                or (bar.hist > 0) - (bar.hist < 0) not in (0, wave.sign)
                or not self._reference_was_broken(wave, reference)):
            return None
        context = self._decision_context
        if context is not None:
            context["selectionStage"] = "same_bar_rescue"
        try:
            candidate = pool[1] if self._current_reference_qualifies(bar, wave, pool[1], pool[0]) else None
            self._selection_result(candidate)
            if candidate is not None:
                if context is not None:
                    context["switched"] = True
                return deepcopy(candidate)
            return None
        finally:
            if context is not None:
                context["selectionStage"] = "activation"

    def _begin_decision(self, bar: XxmBar) -> None:
        previous = self.previous.dif if self.previous else None
        self._decision_context = {
            "time": bar.time, "rawSign": (bar.hist > 0) - (bar.hist < 0),
            "before": {"state": self.state, "reference": self.reference.reference() if self.reference else None,
                       "wave": asdict(self.wave) if self.wave else None, "previousDif": previous,
                       "activeStructureId": self.active_structure["id"] if self.active_structure else None},
            "referenceChecks": [], "selectionCalls": [], "selectionStage": "activation",
            "turn": {"previousDif": previous, "currentDif": bar.dif, "threshold": None,
                     "referenceBroken": None, "checked": False, "reason": "未进入相邻DIF转折分支"},
            "switched": False,
        }

    def _observed_branch(self, result: XxmStep, work: ParsedXxmSnapshot) -> tuple[str, str]:
        context = self._decision_context
        assert context is not None
        if result.events:
            branch = result.events[0]["route"]
            reason = "实际普通事件：" + result.events[0]["type"] + "/" + branch
        elif result.structures and result.structures[-1]["status"] == "LOCKED":
            branch, reason = "structure_locked", "首次真实反色，原结构锁死"
        elif context["switched"]:
            branch, reason = "reference_switch", "B已突破且A合格，当根切换并保持钝化"
        elif work.wave is None:
            branch, reason = "leading_zero", "开头零柱尚无逻辑色段"
        elif context["before"]["wave"] and context["before"]["wave"]["sign"] != work.wave.sign:
            branch, reason = "segment_changed", "真实柱色改变，本根无普通事件"
        elif work.reference is not None:
            branch, reason = "retained", "沿用已有参照，本根无普通事件"
        else:
            branch, reason = "no_activation", "未达到首次钝化条件"
        return branch, reason

    def _finish_step(self, result: XxmStep, work: ParsedXxmSnapshot) -> XxmStep:
        context = self._decision_context
        if context is None:
            return result
        branch, reason = self._observed_branch(result, work)
        if not context["selectionCalls"] and work.wave is not None:
            for index, candidate in enumerate(reversed(work.history[work.wave.sign])):
                self._record_reference_check("not_entered", "B" if index == 0 else "A", candidate,
                                             reason="未调用参照选择：" + reason)
        decision = {key: context[key] for key in (
            "time", "rawSign", "before", "referenceChecks", "selectionCalls", "turn", "switched")}
        record = result.structures[-1] if result.structures else None
        decision.update(wave=asdict(work.wave) if work.wave else None,
                        referenceAfter=work.reference.reference() if work.reference else None,
                        structureId=record["id"] if record else None,
                        structureStatus=record["status"] if record else None, branch=branch, reason=reason)
        return replace(result, decision=deepcopy(decision))

    def _validate_step(self, result: XxmStep, work: ParsedXxmSnapshot, bar: XxmBar) -> None:
        """Validate the already constructed result before any progress is published."""
        validate_xxm_progress(work, period=self.period, max_refs=self.spec.max_refs,
                              min_bars=self.spec.min_bars, id_factory=self._id)
        expected_point = {"time": bar.time, "close": bar.close, "dif": bar.dif, "dea": bar.dea, "hist": bar.hist,
                          "ordinaryState": work.state,
                          "ordinaryDirection": ("TOP" if work.wave.sign == 1 else "BOTTOM")
                          if work.state != "NONE" and work.wave is not None else None,
                          "activeReference": work.reference.reference() if work.reference else None,
                          "activeStructureId": work.active_structure["id"] if work.active_structure else None}
        if (not _same_facts(result.point, expected_point) or type(result.events) is not tuple
                or type(result.structures) is not tuple or len(result.events) > 1 or len(result.structures) > 1):
            raise ValueError("Invalid complete XXM step")
        true_flip = self.wave is not None and (bar.hist > 0) - (bar.hist < 0) == -self.wave.sign
        if true_flip:
            broken = self.reference is not None and self.wave.sign * (bar.dif - self.reference.dif) > 0
            expected_event = "CANCEL" if broken else "STRUCTURE" if self.state == "DULL" else None
        else:
            expected_event = {("NONE", "DULL"): "DULL", ("DULL", "STRUCTURE"): "STRUCTURE",
                              ("STRUCTURE", "DULL"): "DULL", ("DULL", "NONE"): "CANCEL",
                              ("STRUCTURE", "NONE"): "CANCEL"}.get((self.state, work.state))
        if tuple(event["type"] for event in result.events) != ((expected_event,) if expected_event else ()):
            raise ValueError("XXM step omitted or invented its state transition event")
        changed_structure = self.active_structure != work.active_structure or expected_event == "STRUCTURE"
        if len(result.structures) != int(changed_structure):
            raise ValueError("XXM step omitted or invented its structure change")
        for record in result.structures:
            validate_structure_record(record, period=self.period, upper=bar.time, id_factory=self._id)
            if record["status"] == "ASSESSING" and not _same_facts(record, work.active_structure):
                raise ValueError("Structure creation differs from active progress")
            if record["status"] != "ASSESSING" and work.active_structure is not None:
                raise ValueError("A terminal structure cannot remain active")
            if self.active_structure is not None:
                changed = {"status", "lockedAt", "disappearedAt", "disappearanceReason"}
                if any(not _same_facts(record[key], self.active_structure[key]) for key in record if key not in changed):
                    raise ValueError("A structure finalization rewrote its original facts")
                if result.events:
                    event = result.events[0]
                    reason = "dif_return" if event["route"] == "dif_return" else "reference_dif_break"
                    if (record["status"] != "DISAPPEARED" or record["disappearedAt"] != bar.time
                            or record["disappearanceReason"] != reason):
                        raise ValueError("Structure finalization differs from the actual event")
                elif (record["status"] != "LOCKED" or record["lockedAt"] != bar.time
                      or self.wave is None or (bar.hist > 0) - (bar.hist < 0) != -self.wave.sign):
                    raise ValueError("A structure can lock only on the actual first opposite bar")
            elif (not result.events or result.events[0]["type"] != "STRUCTURE"
                  or record["formedAt"] != bar.time
                  or record["status"] != ("LOCKED" if record["formationRoute"] == "color_flip" else "ASSESSING")):
                raise ValueError("Invalid newly formed structure")
        routes = {"activation": ("DULL", "NONE"), "dif_turn": ("STRUCTURE", "DULL"),
                  "dif_return": ("DULL", "STRUCTURE"), "color_flip": ("STRUCTURE", "DULL")}
        event_fields = {"id", "time", "direction", "type", "route", "fromState", "eventReference", "relatedStructureId"}
        for event in result.events:
            if set(event) != event_fields or event["time"] != bar.time or event["fromState"] != self.state:
                raise ValueError("Invalid XXM event fields or prior state")
            sign = 1 if event["direction"] == "TOP" else -1 if event["direction"] == "BOTTOM" else 0
            true_flip = self.wave is not None and (bar.hist > 0) - (bar.hist < 0) == -self.wave.sign
            origin = self.wave if true_flip else work.wave
            ref = event["eventReference"]
            if (origin is None or sign != origin.sign
                    or event["id"] != self._id(bar.time, event["type"], sign, ref["startTime"])
                    or not _same_facts(ref, work.reference.reference() if event["route"] == "activation" and work.reference
                                       else self.reference.reference() if self.reference else None)):
                raise ValueError("Invalid XXM event identity or reference")
            if event["route"] in routes:
                if (event["type"], event["fromState"]) != routes[event["route"]]:
                    raise ValueError("Invalid XXM event transition")
            elif (event["route"] not in ("dif_break", "dif_break_on_flip") or event["type"] != "CANCEL"
                  or event["fromState"] not in ("DULL", "STRUCTURE")):
                raise ValueError("Invalid XXM cancellation")
            related = event["relatedStructureId"]
            needs_structure = event["type"] == "STRUCTURE" or event["fromState"] == "STRUCTURE"
            if needs_structure:
                if len(result.structures) != 1 or related != result.structures[0]["id"]:
                    raise ValueError("Missing step structure association")
                record = result.structures[0]
                if (record["direction"] != event["direction"] or not _same_facts(record["originalReference"], ref)
                        or (event["type"] == "STRUCTURE" and record["structureEventId"] != event["id"])):
                    raise ValueError("Invalid step structure association")
            elif related is not None or result.structures:
                raise ValueError("An activation or dull cancellation cannot change a structure")
            expected_state = "NONE" if true_flip or event["type"] == "CANCEL" else event["type"]
            if work.state != expected_state:
                raise ValueError("Event differs from the resulting ordinary state")
        if self.record_decisions != (result.decision is not None):
            raise ValueError("Invalid XXM observation mode")
        if result.decision is not None:
            decision = result.decision
            fields = {"time", "rawSign", "before", "wave", "referenceAfter", "referenceChecks", "selectionCalls",
                      "turn", "switched", "structureId", "structureStatus", "branch", "reason"}
            if (set(decision) != fields or decision["time"] != bar.time
                    or not _same_facts(decision["wave"], asdict(work.wave) if work.wave else None)
                    or not _same_facts(decision["referenceAfter"], work.reference.reference() if work.reference else None)):
                raise ValueError("Invalid complete XXM decision")
            context = self._decision_context
            if context is None or any(not _same_facts(decision[key], context[key]) for key in (
                    "time", "rawSign", "before", "referenceChecks", "selectionCalls", "turn", "switched")):
                raise ValueError("XXM decision differs from the checks actually performed")
            record = result.structures[-1] if result.structures else None
            if (decision["structureId"] != (record["id"] if record else None)
                    or decision["structureStatus"] != (record["status"] if record else None)):
                raise ValueError("XXM observation structure differs from the result")
            if (decision["branch"], decision["reason"]) != self._observed_branch(result, work):
                raise ValueError("Invalid observed branch")

    def step(self, bar: XxmBar) -> XxmStep:
        bar.validate(self.period)
        if self.previous is not None and bar.time <= self.previous.time:
            raise ValueError("Duplicate or unordered XXM input")
        # Never mutate old facts; a failure discards only this bounded work copy.
        work = deepcopy(self._progress())
        if self.record_decisions:
            self._begin_decision(bar)
        try:
            raw_sign = (bar.hist > 0) - (bar.hist < 0)
            old_wave, old_state, old_ref, old_structure = self.wave, self.state, self.reference, self.active_structure
            events: list[dict[str, Any]] = []
            structures: list[XxmStructureRecord] = []
            if old_wave is None:
                if raw_sign != 0:
                    work.wave = Wave(raw_sign, bar.time, bar.time, 1, bar.close, bar.dif, bar.time, bar.time)
            elif raw_sign == -old_wave.sign:
                if old_ref is not None:
                    broken = old_wave.sign * (bar.dif - old_ref.dif) > 0
                    if self._decision_context is not None:
                        self._decision_context["turn"].update(referenceBroken=broken, reason="真实反色，未检查相邻转折")
                    if broken:
                        related = old_structure["id"] if old_structure else None
                        events.append(self._event(bar, "CANCEL", "dif_break_on_flip", old_wave.sign,
                                                  old_ref, old_state, related))
                        if old_structure is not None:
                            structures.append(self._finish_structure(old_structure, bar, "DISAPPEARED", "reference_dif_break"))
                    elif old_state == "STRUCTURE":
                        assert old_structure is not None
                        structures.append(self._finish_structure(old_structure, bar, "LOCKED", None))
                    elif old_state == "DULL":
                        event, record = self._start_structure(bar, old_wave, old_ref, "color_flip")
                        events.append(event)
                        structures.append(record)
                work.history[old_wave.sign].append(deepcopy(old_wave))
                del work.history[old_wave.sign][:-self.spec.max_refs]
                work.wave = Wave(raw_sign, bar.time, bar.time, 1, bar.close, bar.dif, bar.time, bar.time)
                work.state, work.reference, work.active_structure = "NONE", None, None
            else:
                wave = work.wave
                assert wave is not None
                sign = wave.sign
                wave.count += int(raw_sign != 0)
                wave.end = bar.time
                if sign * (bar.close - wave.price) > 0:
                    wave.price, wave.price_at = bar.close, bar.time
                if sign * (bar.dif - wave.dif) > 0:
                    wave.dif, wave.dif_at = bar.dif, bar.time
                if old_state in ("DULL", "STRUCTURE"):
                    assert old_ref is not None
                    broken = self._reference_was_broken(wave, old_ref)
                    if self._decision_context is not None:
                        self._decision_context["turn"]["referenceBroken"] = broken
                    if broken:
                        rescued = self._rescue_dull_reference(bar, wave, old_ref, work.history[sign]) if old_state == "DULL" else None
                        if rescued is not None:
                            work.reference = rescued
                        else:
                            related = old_structure["id"] if old_structure else None
                            events.append(self._event(bar, "CANCEL", "dif_break", sign, old_ref, old_state, related))
                            if old_structure is not None:
                                structures.append(self._finish_structure(old_structure, bar, "DISAPPEARED", "reference_dif_break"))
                            work.state, work.reference, work.active_structure = "NONE", None, None
                    else:
                        assert self.previous is not None
                        basis = self.previous.dif
                        delta = sign * (bar.dif - basis)
                        gate = abs(basis) * self.spec.dif_turn_pct / 100
                        if self._decision_context is not None:
                            self._decision_context["turn"].update(threshold=gate, checked=True,
                                reason="相邻实际DIF按1%检查" if basis != 0 else "前值DIF为0，不触发转折")
                        if basis != 0 and old_state == "DULL" and delta < 0 and -delta >= gate:
                            event, record = self._start_structure(bar, wave, old_ref, "dif_turn")
                            events.append(event)
                            structures.append(record)
                            work.state, work.active_structure = "STRUCTURE", deepcopy(record)
                        elif basis != 0 and old_state == "STRUCTURE" and delta > 0 and delta >= gate:
                            assert old_structure is not None
                            structures.append(self._finish_structure(old_structure, bar, "DISAPPEARED", "dif_return"))
                            events.append(self._event(bar, "DULL", "dif_return", sign, old_ref, "STRUCTURE", old_structure["id"]))
                            work.state, work.active_structure = "DULL", None
                else:
                    candidate = self._select_eligible_reference(bar, wave, work.history[sign])
                    if candidate is not None:
                        work.reference, work.state = deepcopy(candidate), "DULL"
                        events.append(self._event(bar, "DULL", "activation", sign, candidate, "NONE", None))
            work.previous, work.processed = bar, self.processed + 1
            result = deepcopy(self._finish_step(XxmStep(self._point(bar, work), tuple(events), tuple(structures)), work))
            self._validate_step(result, work, bar)
            self._publish(work)
            return result
        finally:
            self._decision_context = None

    def snapshot(self) -> dict[str, Any]:
        return deepcopy({"specHash": self.spec.spec_hash, "tsCode": self.ts_code, "period": self.period,
                         "sourceIdentity": self.source_identity, "processed": self.processed,
                         "wave": asdict(self.wave) if self.wave else None,
                         "history": {str(k): [asdict(w) for w in waves] for k, waves in self.history.items()},
                         "state": self.state, "reference": asdict(self.reference) if self.reference else None,
                         "previous": asdict(self.previous) if self.previous else None,
                         "activeStructure": self.active_structure})

    def restore(self, snapshot: dict[str, Any]) -> None:
        expected = (self.spec.spec_hash, self.ts_code, self.period, self.source_identity)
        parsed = parse_xxm_snapshot(snapshot, expected_identity=expected, period=self.period,
                                    max_refs=self.spec.max_refs, id_factory=self._id)
        self._publish(parsed)
        self._decision_context = None
