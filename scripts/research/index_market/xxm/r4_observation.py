"""Read-only observations of the real r2/r4 methods, not a second detector."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.types import Wave, XxmBar, XxmStep

from .r4_reference_trial import R4Calculator


def _wave(value: Wave | None) -> dict[str, Any] | None:
    return asdict(value) if value is not None else None


def _reference(value: Wave | None) -> dict[str, Any] | None:
    return value.reference() if value is not None else None


class _ObservationMixin:
    """Delegate every business operation exactly once, retaining its return."""

    _near_first = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_decision: dict[str, Any] | None = None
        self._observation: dict[str, Any] | None = None
        self._reference_started_at: str | None = None
        self._reference_rearm_id: str | None = None

    @staticmethod
    def _candidate_record(stage, name, candidate, *, checked=False, price=None, dif=None, reason):
        return {"stage": stage, "candidate": name, "reference": candidate.reference(),
                "wave": asdict(candidate), "checked": checked,
                "pricePassed": price, "difPassed": dif, "reason": reason}

    def _select_eligible_reference(self, wave, history):
        current = deepcopy(wave)
        pool = deepcopy(list(reversed(history)))
        if self._near_first:
            pool = pool[:self.spec.max_refs]
        selected = super()._select_eligible_reference(wave, history)
        context = self._observation
        if context is None:
            return selected
        stage = context["selectionStage"]
        if not pool or current.count < self.spec.min_bars:
            context["selectionCalls"].append({"stage": stage, "selected": _reference(selected)})
            return selected
        names = {(item.start, item.end): "B" if i == 0 else "A" for i, item in enumerate(pool)}
        gate = current.sign * (current.price - pool[0].price) > 0
        checks = [self._candidate_record("nearest_price_gate", "B", pool[0], checked=True,
                                        price=gate, reason="最近B收盘门槛通过" if gate else "未严格突破最近B收盘门槛")]
        ordered = (pool if self._near_first or not gate else
                   sorted(pool, key=lambda item: current.sign * item.dif, reverse=True))
        stopped = not gate
        for item in ordered:
            name = names[(item.start, item.end)]
            if stopped:
                checks.append(self._candidate_record(stage, name, item,
                    reason="最近B价格门槛未过" if not gate else "此前参照已选中，未继续检查"))
                continue
            price = current.sign * (current.price - item.price) > 0
            dif = current.sign * (current.dif - item.dif) < 0 if price else None
            checks.append(self._candidate_record(stage, name, item, checked=True, price=price, dif=dif,
                reason="参照已选中" if price and dif else "DIF未严格背离" if price else "未严格突破该参照收盘"))
            if selected is not None and item.start == selected.start and item.end == selected.end:
                stopped = True
        context["referenceChecks"].extend(checks)
        context["selectionCalls"].append({"stage": stage, "selected": _reference(selected)})
        return selected

    def _observe_rescue_call(self, operation, bar, old_wave, old_state, stage):
        context = self._observation
        if context is None:
            return operation(bar, old_wave, old_state)
        prior_stage = context["selectionStage"]
        context["selectionStage"] = stage
        before = _reference(self.reference)
        try:
            result = operation(bar, old_wave, old_state)
        finally:
            context["selectionStage"] = prior_stage
        context["afterRescue"] = {"reference": _reference(self.reference), "wave": _wave(self.wave)}
        context["rescued"] = before != _reference(self.reference)
        return result

    def _rescue_bottom_dull_reference(self, bar, old_wave, old_state):
        return self._observe_rescue_call(super()._rescue_bottom_dull_reference,
                                         bar, old_wave, old_state, "bottom_rescue")

    def _advance_rearm(self, bar):
        saved = deepcopy(self.pending_rearm)
        result = super()._advance_rearm(bar)
        if self._observation is not None:
            self._observation["rearm"] = deepcopy(result)
            if saved is not None and result[2] and result[2][-1]["status"] != "SEGMENT_ENDED":
                self._observation["rearmReferenceBroken"] = bar.dif < saved["referenceWave"]["dif"]
        return result

    def _before(self):
        return {"state": self.state, "reference": _reference(self.reference), "wave": _wave(self.wave),
                "previous": asdict(self.previous) if self.previous is not None else None,
                "pendingRearm": deepcopy(self.pending_rearm)}

    def _turn(self, before, context, bar, raw_sign):
        previous = before["previous"]
        basis = previous["dif"] if previous is not None else None
        turn = {"previousDif": basis, "currentDif": bar.dif,
                "threshold": abs(basis) * self.spec.dif_turn_pct / 100 if basis is not None else None,
                "referenceBroken": None, "checked": False, "reason": "未进入相邻DIF转折分支"}
        old_wave, old_reference = before["wave"], before["reference"]
        if old_wave is not None and old_wave["sign"] and raw_sign == -old_wave["sign"]:
            if old_reference is not None:
                turn["referenceBroken"] = old_wave["sign"] * (bar.dif - old_reference["dif"]) > 0
            turn["reason"] = "真实翻色，未检查相邻DIF转折"
            return turn
        after_rescue = context.get("afterRescue")
        if after_rescue is not None:
            wave, reference = after_rescue["wave"], after_rescue["reference"]
            if wave is not None and wave["sign"] and reference is not None:
                broken = wave["sign"] * (wave["dif"] - reference["dif"]) > 0
                turn["referenceBroken"] = broken
                if broken:
                    turn["reason"] = "原参照DIF已严格突破，优先取消"
                elif previous is not None:
                    turn["checked"] = True
                    turn["reason"] = "相邻实际DIF按1%检查" if basis != 0 else "前值DIF为0，原保护不触发转折"
        elif context.get("rearm", (False, None, ()))[0]:
            turn["referenceBroken"] = context.get("rearmReferenceBroken")
            turn["reason"] = ("等待的原参照DIF已严格突破，未检查相邻转折"
                              if turn["referenceBroken"] else "等待处理阻断相邻DIF转折分支")
        return turn

    def _decision(self, before, context, bar, result):
        raw_sign = (bar.hist > 0) - (bar.hist < 0)
        ordinary = next((event for event in result.events if event["type"] != "RESEARCH_HISTORICAL_WITHDRAWAL"), None)
        rearm = context.get("rearm", (False, None, ()))
        switched = self._near_first and context.get("rescued")
        switch_reason = "B已突破，A价格/DIF合格，当根切换并保持钝化"
        if ordinary is not None:
            branch = ordinary["route"]
            reason = "实际普通事件：" + ordinary["type"] + "/" + branch
            if switched:
                reason = "B已突破，A价格/DIF合格，当根切换；" + reason
        elif rearm[0]:
            branch, reason = "waiting", "等待处理结束，本根未进入首次或相邻转折判断"
        elif switched:
            branch, reason = "reference_switch", switch_reason
        elif self.wave is None:
            branch, reason = "leading_zero", "开头零柱尚无逻辑色段"
        elif before["wave"] is not None and before["wave"]["sign"] != self.wave.sign:
            branch, reason = "segment_changed", "柱色段改变；本根无普通事件"
        elif self.reference is not None:
            branch, reason = "retained", "沿用已有参照；本根无普通事件"
        else:
            branch, reason = "no_activation", "未形成首次钝化；未达到入口或参照条件"
        selected = None
        if self.reference is not None:
            if ordinary is not None and ordinary["route"] == "activation":
                action = "activation"
            elif ordinary is not None and ordinary["route"] == "reactivation":
                action = "reactivation"
            elif context.get("rescued"):
                action = "rescue"
            else:
                action = "retained"
            if action != "retained":
                self._reference_started_at = bar.time
                self._reference_rearm_id = ordinary["relatedRearmId"] if action == "reactivation" else None
            selected = {"reference": self.reference.reference(), "startedAt": self._reference_started_at,
                        "action": action, "rearmId": self._reference_rearm_id}
        else:
            self._reference_started_at = None
            self._reference_rearm_id = None
        checks = context["referenceChecks"]
        if not context["selectionCalls"] and self.wave is not None and self.wave.sign:
            checks = [self._candidate_record("not_entered", "B" if i == 0 else "A", candidate,
                      reason="未调用选择方法：" + reason)
                      for i, candidate in enumerate(reversed(self.history[self.wave.sign]))]
        return {"before": before, "rawSign": raw_sign, "wave": _wave(self.wave),
                "countMeaning": "逻辑色段有色柱根数，零柱不计入" if self._near_first else "当前色段根数，零柱单独成段",
                "referenceChecks": checks, "selectedReference": selected,
                "turn": self._turn(before, context, bar, raw_sign), "branch": branch, "reason": reason}

    def step(self, bar: XxmBar) -> XxmStep:
        before = self._before()
        context = {"selectionStage": "activation", "referenceChecks": [], "selectionCalls": []}
        self._observation = context
        try:
            result = super().step(bar)
            decision = self._decision(before, context, bar, result)
        finally:
            self._observation = None
        self.last_decision = decision
        return result


class ObservedR2Calculator(_ObservationMixin, XxmCalculator):
    """Observe the unchanged product r2 calculation."""


class ObservedR4Calculator(_ObservationMixin, R4Calculator):
    """Observe the independently identified r4 calculation."""

    _near_first = True

    def _rescue_dull_reference(self, bar, old_wave, old_state):
        stage = "top_rescue" if self.wave.sign == 1 else "bottom_rescue"
        return self._observe_rescue_call(super()._rescue_dull_reference,
                                         bar, old_wave, old_state, stage)
