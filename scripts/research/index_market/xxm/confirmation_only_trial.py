"""Isolated two-digit confirmation experiment, next-stage LLD 0.6.

Only ``step``'s adjacent-DIF turn predicates differ from the pinned r2 kernel.
No market input is loaded and no experiment is run on import or construction.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import inspect
import json
from pathlib import Path
import textwrap
from typing import Any

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import Wave, XxmBar, XxmStep

from .near_first_review import quantize_dif


ROOT = Path(__file__).resolve().parents[4]
_BASE_SPEC_HASH = "6db425730c72f22ea756c121a832f27c966d1324ef0a72a2312a3c572038724d"
_BASELINE_SHA256 = (
    ("src/biz/services/wealth/market/index_detail_xxm/calculator.py", "30fe9fa940ccfd046fd58b4866893d65ba7d98d6f9affa6993210b0d8b84b2c8"),
    ("src/biz/services/wealth/market/index_detail_xxm/spec.py", "df4be50a39e8ea09526c272f5a533eb9ff0ba72cda07d1f52a7f730509050764"),
    ("src/biz/services/wealth/market/index_detail_xxm/types.py", "415e578965deea2944fdec7fc24988948eb034e9b19131bced626f53dc4033ac"),
)
_Q_POLICY = "Decimal(str(actual_float)); truncate toward zero to two significant digits; Q(0)=0"
_TURN_POLICY = "DULL: sign*(Q(current)-Q(previous))<0; STRUCTURE: >0; no nonzero-previous guard"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfirmationTrialSpec:
    research_version: str = "xxm-research-two-digit-confirmation-v1"
    default_start_date: str = "2023-10-24"
    default_end_date: str = "2026-10-13"
    source_start_date: str = "2023-01-03"
    source_end_date: str = "2026-10-13"
    source_path: str = "reports/xxm_source_audit_20261013_213852/daily_source.csv"
    calendar_path: str = "reports/xxm_source_audit_20261013_213852/sse_calendar.json"
    source_sha256: str = "be56f2af173a40767fa52e47e2593dcac6ce524c1e1eda01074a23bc263a8b3a"
    calendar_sha256: str = "ee16d75040b188d3fac838dd5339de289542c10e61ebd5ae49168577ffe39a4f"
    max_bars: int = 1000
    max_csv_bytes: int = 1048576
    max_calendar_rows: int = 2000
    max_calendar_bytes: int = 131072
    timeout_seconds: float = 20.0
    max_memory_bytes: int = 268435456
    max_result_bytes: int = 16777216
    macd_tolerance: str = "0.0021"
    baseline_sha256: tuple[tuple[str, str], ...] = _BASELINE_SHA256

    @property
    def research_hash(self) -> str:
        return _hash({"researchVersion": self.research_version, "baseSpecHash": MAIN_SPEC.spec_hash,
                      "baselineSha256": self.baseline_sha256, "qDefinition": _Q_POLICY,
                      "turnPolicy": _TURN_POLICY})


TRIAL_SPEC = ConfirmationTrialSpec()


def calculator_source_identity(mode: str, input_identity: str, *, spec: ConfirmationTrialSpec = TRIAL_SPEC) -> str:
    if mode not in ("r2", "two_digit") or not isinstance(input_identity, str) or not input_identity:
        raise ValueError("Expected a comparison mode and nonempty common input identity")
    rule = MAIN_SPEC.spec_hash if mode == "r2" else spec.research_hash
    return f"xxm-confirmation:{mode}:" + _hash({"mode": mode, "inputIdentity": input_identity, "rule": rule})


def _dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def _expression(text: str) -> ast.AST:
    return ast.parse(text, mode="eval").body


def _step_node(source: str) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(source))
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "step"]
    if len(matches) != 1:
        raise ValueError("Expected exactly one step definition")
    return matches[0]


def validate_step_copy(base_source: str, trial_source: str) -> None:
    """Reject every AST change except the two documented turn predicates.

    Inputs are source strings so negative tests can change the copied body
    without executing, monkeypatching, or modifying the product implementation.
    """
    base, trial = _step_node(base_source), _step_node(trial_source)
    position = _dump(_expression("sign and ref is not None and self.previous is not None"))
    for node, is_trial in ((base, False), (trial, True)):
        blocks = [item for item in ast.walk(node) if isinstance(item, ast.If) and _dump(item.test) == position]
        if len(blocks) != 1:
            raise ValueError("The original adjacent-DIF branch was moved or modified")
        block = blocks[0]
        prefix = ("basis = self.previous.dif\n"
                  "delta = sign * (quantize_dif(Decimal(str(bar.dif))) - quantize_dif(Decimal(str(basis))))") if is_trial else (
                  "basis = self.previous.dif\ndelta = sign * (bar.dif - basis)\n"
                  "gate = abs(basis) * self.spec.dif_turn_pct / 100")
        assignments = ast.parse(prefix).body
        if (len(block.body) <= len(assignments)
                or [_dump(item) for item in block.body[:len(assignments)]] != [_dump(item) for item in assignments]
                or not isinstance(block.body[len(assignments)], ast.If)):
            raise ValueError("Unexpected adjacent-DIF calculations or extra statements")
        first = block.body[len(assignments)]
        first_condition = ('self.state == "DULL" and delta < 0' if is_trial else
                           'basis != 0 and self.state == "DULL" and delta < 0 and -delta >= gate')
        second_condition = ('self.state == "STRUCTURE" and delta > 0' if is_trial else
                            'basis != 0 and self.state == "STRUCTURE" and delta > 0 and delta >= gate')
        if (_dump(first.test) != _dump(_expression(first_condition))
                or len(first.orelse) != 1 or not isinstance(first.orelse[0], ast.If)
                or _dump(first.orelse[0].test) != _dump(_expression(second_condition))):
            raise ValueError("Unexpected formation or return predicate")
        # Replace only the validated sites in local ASTs, then compare the rest.
        first.test = ast.Constant(value=True)
        first.orelse[0].test = ast.Constant(value=True)
        block.body = [ast.Pass(), *block.body[len(assignments):]]
    if _dump(base) != _dump(trial):
        raise ValueError("Copied step changed behavior outside the allowed turn block")


def verify_baseline(*, spec: ConfirmationTrialSpec = TRIAL_SPEC, root: Path = ROOT) -> dict[str, str]:
    if (not isinstance(spec, ConfirmationTrialSpec) or not isinstance(spec.research_version, str)
            or not spec.research_version or spec.baseline_sha256 != _BASELINE_SHA256
            or MAIN_SPEC.spec_hash != _BASE_SPEC_HASH):
        raise ValueError("The approved baseline Spec or source identity changed")
    actual = {}
    for relative, expected in spec.baseline_sha256:
        path = Path(root) / relative
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"Missing baseline source: {relative}") from exc
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected:
            raise ValueError(f"Baseline source changed: {relative}")
        actual[relative] = digest
    validate_step_copy(inspect.getsource(XxmCalculator.step), inspect.getsource(TwoDigitTurnCalculator.step))
    return actual


class TwoDigitTurnCalculator(XxmCalculator):
    def __init__(self, *, source_identity: str, period: str = "day", ts_code: str = "000001.SH",
                 trial_spec: ConfirmationTrialSpec = TRIAL_SPEC) -> None:
        if period != "day" or ts_code != "000001.SH":
            raise ValueError("The confirmation experiment only supports 000001.SH/day")
        verify_baseline(spec=trial_spec)
        self.trial_spec = trial_spec
        self.input_identity = source_identity
        super().__init__(period="day", ts_code=ts_code, spec=MAIN_SPEC,
                         source_identity=calculator_source_identity("two_digit", source_identity, spec=trial_spec))

    def _id(self, *parts: Any) -> str:
        return hashlib.sha256((self.trial_spec.research_hash + "|" + super()._id(*parts)).encode()).hexdigest()[:24]

    def snapshot(self) -> dict[str, Any]:
        return {"researchSpecHash": self.trial_spec.research_hash, "baseSpecHash": self.spec.spec_hash,
                "mode": "two_digit", "sourceIdentity": self.source_identity,
                "state": deepcopy(super().snapshot())}

    def restore(self, snapshot: dict[str, Any]) -> None:
        fields = {"researchSpecHash", "baseSpecHash", "mode", "sourceIdentity", "state"}
        if (not isinstance(snapshot, dict) or set(snapshot) != fields
                or snapshot["researchSpecHash"] != self.trial_spec.research_hash
                or snapshot["baseSpecHash"] != self.spec.spec_hash or snapshot["mode"] != "two_digit"
                or snapshot["sourceIdentity"] != self.source_identity or not isinstance(snapshot["state"], dict)):
            raise ValueError("Research snapshot rule/mode/source identity mismatch")
        # The parent validates its entire copied payload before publishing state.
        super().restore(deepcopy(snapshot["state"]))

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
        blocked, reactivated, rearm_records = self._advance_rearm(bar)
        if reactivated is not None:
            event_type, route, direction, event_ref = "DULL", "reactivation", -1, reactivated
        if not event_type and not blocked:
            if reactivated is None:
                self._rescue_bottom_dull_reference(bar, old_wave, old_state)
            ref = self.reference
            if sign and ref is not None and sign * (wave.dif - ref.dif) > 0:
                event_type, route, direction, event_ref = "CANCEL", "dif_break", sign, ref
                self.state, self.reference = "NONE", None
            elif sign and ref is not None and self.previous is not None:
                basis = self.previous.dif
                delta = sign * (quantize_dif(Decimal(str(bar.dif))) - quantize_dif(Decimal(str(basis))))
                if self.state == "DULL" and delta < 0:
                    event_type, route, self.state = "STRUCTURE", "dif_turn", "STRUCTURE"
                elif self.state == "STRUCTURE" and delta > 0:
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
            elif (sign and wave.count >= self.spec.min_bars and self.history[sign]
                  and (sign != 1 or bar.dif > 0)):
                candidate = self._select_eligible_reference(wave, self.history[sign])
                if candidate is not None:
                    self.reference = deepcopy(candidate)
                    event_type, route, direction, event_ref = "DULL", "activation", sign, self.reference
                    self.state = "DULL"
        events: list[dict[str, Any]] = []
        if event_type:
            events.append({"id": self._id(bar.time, event_type, direction, event_ref.start if event_ref else ""), "time": bar.time,
                           "direction": "TOP" if direction == 1 else "BOTTOM", "type": event_type, "route": route,
                           "fromState": old_state, "eventReference": event_ref.reference() if event_ref else None,
                           "relatedTopHistoryId": None, "relatedBottomHistoryId": None,
                           "relatedRearmId": rearm_records[-1]["id"] if event_type == "STRUCTURE_DISAPPEARED" or route == "reactivation" else None})
            if event_type == "STRUCTURE_DISAPPEARED":
                events[0]["relatedBottomHistoryId"] = rearm_records[-1]["bottomHistoryId"]
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
                               "relatedTopHistoryId": pending["id"], "relatedBottomHistoryId": None, "relatedRearmId": None})
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
                 "pendingBottomHistoryId": self.pending_bottom_history["id"] if self.pending_bottom_history else None,
                 "pendingRearmId": self.pending_rearm["id"] if self.pending_rearm else None}
        self.previous = bar
        self.processed += 1
        return XxmStep(point, tuple(events), tuple(histories), tuple(bottom_histories), rearm_records)
