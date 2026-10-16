from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from typing import Any

from .spec import MAIN_SPEC, XxmSpec
from .types import Wave, XxmBar, XxmBottomHistory, XxmPeriod, XxmStep


class XxmCalculator:
    """Causal bounded state. Callers keep the immutable event/point ledger."""

    def __init__(self, *, period: XxmPeriod, source_identity: str, ts_code: str = "000001.SH", spec: XxmSpec = MAIN_SPEC) -> None:
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
        self.processed = 0

    def _id(self, *parts: Any) -> str:
        identity = [self.spec.algorithm_version, self.spec.spec_hash, self.ts_code, self.period, *parts]
        return hashlib.sha256("|".join(map(str, identity)).encode()).hexdigest()[:24]

    def step(self, bar: XxmBar) -> XxmStep:
        bar.validate(self.period)
        if self.previous is not None and bar.time <= self.previous.time:
            raise ValueError("Duplicate or unordered XXM input")
        sign = (bar.hist > 0) - (bar.hist < 0)
        old_wave, old_state = self.wave, self.state
        event_type, route, direction, event_ref = "", "", 0, None
        if old_wave is None or sign != old_wave.sign:
            if old_wave is not None and old_wave.sign:
                old_sign = old_wave.sign
                if sign == -old_sign and self.reference is not None:
                    if old_sign * (bar.dif - self.reference.dif) > 0:
                        event_type, route = "CANCEL", "dif_break_on_flip"
                    elif self.state == "DULL":
                        event_type, route = "STRUCTURE", "color_flip"
                    if event_type:
                        direction, event_ref = old_sign, self.reference
                pool = self.history[old_sign]
                pool.append(deepcopy(old_wave))
                del pool[:-self.spec.max_refs]
            self.wave = Wave(sign, bar.time, bar.time, 0, bar.close, bar.dif, bar.time, bar.time)
            self.state, self.reference = "NONE", None
        wave = self.wave
        assert wave is not None
        wave.count += 1
        wave.end = bar.time
        if sign * (bar.close - wave.price) > 0:
            wave.price, wave.price_at = bar.close, bar.time
        if sign * (bar.dif - wave.dif) > 0:
            wave.dif, wave.dif_at = bar.dif, bar.time
        if not event_type:
            ref = self.reference
            if sign and ref is not None and sign * (wave.dif - ref.dif) > 0:
                event_type, route, direction, event_ref = "CANCEL", "dif_break", sign, ref
                self.state, self.reference = "NONE", None
            elif sign and ref is not None and self.previous is not None:
                basis = self.previous.dif
                delta = sign * (bar.dif - basis)
                gate = abs(basis) * self.spec.dif_turn_pct / 100
                if basis != 0 and self.state == "DULL" and delta < 0 and -delta >= gate:
                    event_type, route, self.state = "STRUCTURE", "dif_turn", "STRUCTURE"
                elif basis != 0 and self.state == "STRUCTURE" and delta > 0 and delta >= gate:
                    event_type, route, self.state = "DULL", "dif_return", "DULL"
                if event_type:
                    direction, event_ref = sign, ref
            elif sign and wave.count >= self.spec.min_bars and self.history[sign]:
                pool = list(reversed(self.history[sign]))
                if sign * (wave.price - pool[0].price) > 0:
                    pool.sort(key=lambda candidate: sign * candidate.dif, reverse=True)
                    for candidate in pool:
                        if sign * (wave.price - candidate.price) > 0 and sign * (wave.dif - candidate.dif) < 0:
                            self.reference = deepcopy(candidate)
                            event_type, route, direction, event_ref = "DULL", "activation", sign, self.reference
                            self.state = "DULL"
                            break
        events: list[dict[str, Any]] = []
        if event_type:
            events.append({"id": self._id(bar.time, event_type, direction, event_ref.start if event_ref else ""), "time": bar.time,
                           "direction": "TOP" if direction == 1 else "BOTTOM", "type": event_type, "route": route,
                           "fromState": old_state, "eventReference": event_ref.reference() if event_ref else None,
                           "relatedTopHistoryId": None, "relatedBottomHistoryId": None})
        ordinary_event = events[0] if event_type else None
        histories: list[dict[str, Any]] = []
        pending = self.pending
        top_new = direction == 1 and event_type in ("DULL", "STRUCTURE")
        if pending is not None:
            pending["observedThrough"] = bar.time
            pending["ageBars"] += 1
            pending["negativeBars"] += int(sign < 0)
            pending["zeroBars"] += int(sign == 0)
            pending["colorChanges"] += int(self.previous is not None and sign != (self.previous.hist > 0) - (self.previous.hist < 0))
            reason = None
            if bar.dif > pending["originalReference"]["dif"]:
                reason = "original_reference_break"
            elif top_new:
                reason = f"new_top_{event_type}"
            elif bar.time > pending["confirmedAt"] and bar.close > pending["pricePeak"]:
                reason = "historical_price_break"
                events.append({"id": self._id(bar.time, "RESEARCH_HISTORICAL_WITHDRAWAL", pending["id"]), "time": bar.time,
                               "direction": "TOP", "type": "RESEARCH_HISTORICAL_WITHDRAWAL", "route": "historical_price_break",
                               "fromState": self.state, "eventReference": deepcopy(pending["originalReference"]),
                               "relatedTopHistoryId": pending["id"], "relatedBottomHistoryId": None})
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
                            "originalReference": event_ref.reference(), "status": "PENDING", "endedAt": None, "endReason": None,
                            "observedThrough": bar.time, "ageBars": 0, "negativeBars": 0, "zeroBars": 0, "colorChanges": 0}
            histories.append(deepcopy(self.pending))
            events[0]["relatedTopHistoryId"] = history_id
        bottom_events, bottom_histories = self._advance_bottom_history(bar, ordinary_event)
        events.extend(bottom_events)
        if ordinary_event is not None and direction == -1 and event_type == "STRUCTURE":
            negative_wave = wave if sign == -1 else old_wave
            if negative_wave is None or negative_wave.sign != -1:
                raise ValueError("BOTTOM structure requires its original negative segment")
            bottom_histories.append(self._start_bottom_history(bar, ordinary_event, negative_wave))
        point = {"time": bar.time, "close": bar.close, "dif": bar.dif, "dea": bar.dea, "hist": bar.hist,
                 "ordinaryState": self.state, "ordinaryDirection": ("TOP" if sign == 1 else "BOTTOM") if self.state != "NONE" else None,
                 "activeReference": self.reference.reference() if self.reference else None,
                 "pendingTopHistoryId": self.pending["id"] if self.pending else None,
                 "pendingBottomHistoryId": self.pending_bottom_history["id"] if self.pending_bottom_history else None}
        self.previous = bar
        self.processed += 1
        return XxmStep(point, tuple(events), tuple(histories), tuple(bottom_histories))

    def snapshot(self) -> dict[str, Any]:
        return {"specHash": self.spec.spec_hash, "tsCode": self.ts_code, "period": self.period, "sourceIdentity": self.source_identity,
                "processed": self.processed, "wave": asdict(self.wave) if self.wave else None,
                "history": {str(k): [asdict(w) for w in waves] for k, waves in self.history.items()},
                "state": self.state, "reference": asdict(self.reference) if self.reference else None,
                "previous": asdict(self.previous) if self.previous else None, "pending": deepcopy(self.pending),
                "pendingBottomHistory": deepcopy(self.pending_bottom_history)}

    def _advance_bottom_history(self, bar: XxmBar, ordinary_event: dict[str, Any] | None
                                ) -> tuple[list[dict[str, Any]], list[XxmBottomHistory]]:
        record = self.pending_bottom_history
        if record is None:
            return [], []
        record["observedThrough"] = bar.time
        record["ageBars"] += 1
        if record["leftOriginAt"] is None and bar.hist >= 0:
            record["leftOriginAt"] = bar.time
        reason = None
        events = []
        if bar.dif < record["originalReference"]["dif"]:
            reason = "original_reference_break"
        elif ordinary_event is not None and ordinary_event["direction"] == "BOTTOM" and ordinary_event["type"] in ("DULL", "STRUCTURE"):
            reason = "new_bottom_" + ordinary_event["type"]
        elif record["leftOriginAt"] is not None and bar.time > record["confirmedAt"] and bar.close < record["priceLow"]:
            reason = "historical_price_break"
            events.append({"id": self._id(bar.time, "RESEARCH_HISTORICAL_WITHDRAWAL", record["id"]),
                           "time": bar.time, "direction": "BOTTOM", "type": "RESEARCH_HISTORICAL_WITHDRAWAL",
                           "route": "historical_price_break", "fromState": self.state,
                           "eventReference": deepcopy(record["originalReference"]),
                           "relatedTopHistoryId": None, "relatedBottomHistoryId": record["id"]})
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
            "leftOriginAt": bar.time if bar.hist >= 0 else None,
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
            left = raw["leftOriginAt"]
            if left is not None:
                if not raw["confirmedAt"] <= left <= raw["observedThrough"]:
                    raise ValueError("Invalid BOTTOM origin exit")
            elif wave is None or wave.sign != -1 or wave.start != raw["originSegmentStart"]:
                raise ValueError("BOTTOM snapshot lost its original segment")
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("Malformed BOTTOM snapshot") from exc
        return deepcopy(raw)

    def restore(self, snapshot: dict[str, Any]) -> None:
        # Parse and validate everything before publishing any state, including on
        # an already-used calculator or a legal rewind to an earlier real prefix.
        try:
            expected = (self.spec.spec_hash, self.ts_code, self.period, self.source_identity)
            if tuple(snapshot[k] for k in ("specHash", "tsCode", "period", "sourceIdentity")) != expected:
                raise ValueError("XXM snapshot version/source identity mismatch")
            wave = Wave(**snapshot["wave"]) if snapshot["wave"] else None
            history = {int(k): [Wave(**w) for w in values] for k, values in snapshot["history"].items()}
            if set(history) != {1, -1} or any(len(pool) > self.spec.max_refs for pool in history.values()):
                raise ValueError("Invalid reference pool")
            state = snapshot["state"]
            reference = Wave(**snapshot["reference"]) if snapshot["reference"] else None
            previous = XxmBar(**snapshot["previous"]) if snapshot["previous"] else None
            pending = deepcopy(snapshot["pending"])
            processed = snapshot["processed"]
            if state not in ("NONE", "DULL", "STRUCTURE") or type(processed) is not int or processed < 0:
                raise ValueError("Invalid XXM snapshot state")
            if previous is not None:
                previous.validate(self.period)
            bottom = self._validate_bottom_history_snapshot(snapshot["pendingBottomHistory"],
                        previous=previous, wave=wave, processed=processed)
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("Malformed XXM snapshot") from exc
        self.wave, self.history, self.state, self.reference = wave, history, state, reference
        self.previous, self.pending, self.processed, self.pending_bottom_history = previous, pending, processed, bottom
