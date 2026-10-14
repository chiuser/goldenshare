from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
from typing import Any

from .spec import MAIN_SPEC, XxmSpec
from .types import Wave, XxmBar, XxmPeriod, XxmStep


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
                           "relatedTopHistoryId": None})
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
                               "relatedTopHistoryId": pending["id"]})
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
        point = {"time": bar.time, "close": bar.close, "dif": bar.dif, "dea": bar.dea, "hist": bar.hist,
                 "ordinaryState": self.state, "ordinaryDirection": ("TOP" if sign == 1 else "BOTTOM") if self.state != "NONE" else None,
                 "activeReference": self.reference.reference() if self.reference else None,
                 "pendingTopHistoryId": self.pending["id"] if self.pending else None}
        self.previous = bar
        self.processed += 1
        return XxmStep(point, tuple(events), tuple(histories))

    def snapshot(self) -> dict[str, Any]:
        return {"specHash": self.spec.spec_hash, "tsCode": self.ts_code, "period": self.period, "sourceIdentity": self.source_identity,
                "processed": self.processed, "wave": asdict(self.wave) if self.wave else None,
                "history": {str(k): [asdict(w) for w in waves] for k, waves in self.history.items()},
                "state": self.state, "reference": asdict(self.reference) if self.reference else None,
                "previous": asdict(self.previous) if self.previous else None, "pending": deepcopy(self.pending)}

    def restore(self, snapshot: dict[str, Any]) -> None:
        expected = (self.spec.spec_hash, self.ts_code, self.period, self.source_identity)
        if tuple(snapshot[k] for k in ("specHash", "tsCode", "period", "sourceIdentity")) != expected:
            raise ValueError("XXM snapshot version/source identity mismatch")
        self.wave = Wave(**snapshot["wave"]) if snapshot["wave"] else None
        self.history = {int(k): [Wave(**w) for w in values] for k, values in snapshot["history"].items()}
        if any(len(pool) > self.spec.max_refs for pool in self.history.values()):
            raise ValueError("Invalid reference pool")
        self.state = snapshot["state"]
        self.reference = Wave(**snapshot["reference"]) if snapshot["reference"] else None
        self.previous = XxmBar(**snapshot["previous"]) if snapshot["previous"] else None
        self.pending = deepcopy(snapshot["pending"])
        self.processed = snapshot["processed"]
