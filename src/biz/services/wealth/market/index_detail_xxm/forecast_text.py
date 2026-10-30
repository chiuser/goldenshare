"""Describe already-proved next-bar conditions without choosing prices."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import math

from .types import ForecastKernelResult, ForecastPrecheck


_OUTCOME_ORDER = {
    "NONE": ("DULL_FORMED",),
    "DULL": ("STRUCTURE_FORMED", "STRUCTURE_FORMED_AND_LOCKED",
             "SIGNAL_DISAPPEARED", "REFERENCE_INVALIDATED", "DULL_HELD"),
    "STRUCTURE": ("SIGNAL_DISAPPEARED", "RETURNED_TO_DULL",
                  "STRUCTURE_LOCKED", "STRUCTURE_HELD"),
}
_RANGE_FIELDS = {"lower", "upper", "lowerInclusive", "upperInclusive",
                 "displayLower", "displayUpper"}


def _finite_number(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _validate_time(value: str | None, period: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError("Forecast display time must be a string")
    try:
        if period == "day":
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("Invalid daily display time")
        else:
            stamp = datetime.fromisoformat(value)
            if stamp.utcoffset() != timedelta(hours=8):
                raise ValueError("Invalid minute display time")
    except (TypeError, OverflowError) as exc:
        raise ValueError("Malformed forecast display time") from exc


def _time_text(value: str, period: str) -> str:
    return value + " 收盘" if period == "day" else value[:10] + " " + value[11:16] + " 收盘"


def _range_text(value: dict) -> str:
    """Read the already-checked integers; do not derive or move a boundary."""
    if type(value) is not dict or set(value) != _RANGE_FIELDS:
        raise ValueError("Invalid next-bar display range fields")
    lower, upper = value["lower"], value["upper"]
    if (not _finite_number(lower) or lower < 0
            or type(value["lowerInclusive"]) is not bool
            or type(value["upperInclusive"]) is not bool
            or (lower == 0 and value["lowerInclusive"])
            or (upper is None and value["upperInclusive"])
            or (upper is not None and (not _finite_number(upper) or upper < lower))):
        raise ValueError("Invalid next-bar display range")
    singleton = upper is not None and lower == upper
    if singleton and not (lower > 0 and value["lowerInclusive"] and value["upperInclusive"]):
        raise ValueError("Invalid singleton display range")
    lo, hi = value["displayLower"], value["displayUpper"]
    for bound in (lo, hi):
        if bound is not None and (type(bound) is not int or bound <= 0):
            raise ValueError("Display boundaries must be positive integers")
    if lo is None:
        if hi is not None:
            raise ValueError("Incomplete integer display range")
        prefix = "仅单一收盘点满足条件；" if singleton else ""
        return prefix + "已算出条件范围，暂未生成可用整数点位"
    if singleton:
        if hi != lo or lo != lower:
            raise ValueError("A singleton must display only its own integer")
        return f"收盘等于{lo}点"
    if upper is None:
        if hi is not None:
            raise ValueError("An unbounded range cannot have a display upper boundary")
        return f"收盘不低于{lo}点"
    if hi is None or lo > hi:
        raise ValueError("Incomplete integer display range")
    if lo == hi:
        return f"收盘等于{lo}点"
    return f"收盘不低于{lo}点且不高于{hi}点"


def _outcome_text(outcome: str, state: str, direction: str, rescue: bool) -> str:
    side = "顶" if direction == "TOP" else "底"
    name = "顶部" if direction == "TOP" else "底部"
    return {
        "DULL_FORMED": f"形成{side}钝化",
        "DULL_HELD": f"转用远参照并保持{side}钝化" if rescue else f"保持{side}钝化",
        "STRUCTURE_FORMED": f"形成{name}结构，进入结构形成考核期",
        "STRUCTURE_FORMED_AND_LOCKED": f"形成{name}结构并锁死",
        "STRUCTURE_HELD": f"保持{name}结构",
        "RETURNED_TO_DULL": f"{name}结构消失，退回{side}钝化",
        "STRUCTURE_LOCKED": f"{name}结构锁死",
        "SIGNAL_DISAPPEARED": f"{name}结构直接消失" if state == "STRUCTURE" else f"{side}钝化消失",
        "REFERENCE_INVALIDATED": "近参照失效，远参照本次未计算，真实收盘按r4同根规则检查",
    }[outcome]


def _no_candidate_text(result: ForecastKernelResult, prepared: ForecastPrecheck, state: str, side: str) -> str:
    if result.reason_code == "ZERO_WAVE":
        return "当前尚无有效红绿柱段，下一根不足以形成钝化。"
    if result.reason_code == "NO_REFERENCE":
        return "当前方向没有可用的历史同色峰谷，暂不能计算钝化条件。"
    if state == "DULL" and prepared.active_role == "NEAR":
        if result.references["farther"] is None:
            farther = "远参照不存在"
        elif not result.far_evaluated:
            farther = "远参照已失效"
        else:
            farther = "远参照没有救援范围"
        return f"近参照没有有效延续范围；{farther}。这不表示当前真实钝化已经消失。"
    return f"当前没有可形成{side}钝化的下一根收盘范围。"


def make_display(result, *, prepared, period, through, mode, check):
    """Return only the original four strings, using one actual prefix context."""
    check()
    if type(result) is not ForecastKernelResult or type(prepared) is not ForecastPrecheck:
        raise ValueError("Display requires the next-bar kernel result and its precheck")
    snapshot = prepared.snapshot
    if (period not in ("day", "m60", "m90", "m120") or mode not in ("LATEST", "REPLAY")
            or type(snapshot) is not dict or snapshot.get("period") != period):
        raise ValueError("Forecast display context differs from its precheck")
    previous = snapshot.get("previous")
    if (previous is not None and (type(previous) is not dict or "time" not in previous)
            or through != (previous["time"] if previous is not None else None)):
        raise ValueError("Forecast display through differs from its precheck")
    state, direction = snapshot.get("state"), prepared.direction
    if (type(state) is not str or state not in _OUTCOME_ORDER or direction not in (None, "TOP", "BOTTOM")
            or (state != "NONE" and direction is None)
            or result.references != prepared.references
            or result.status not in ("READY", "NO_CANDIDATE", "PRECISION_PENDING")):
        raise ValueError("Invalid next-bar display facts")
    _validate_time(through, period)
    _validate_time(result.target_endpoint, period)
    if ((result.target_endpoint is None) != (result.bars_ahead is None)
            or (result.target_endpoint is not None and (type(result.bars_ahead) is not int or result.bars_ahead != 1))
            or (result.target_endpoint is not None and through is not None and result.target_endpoint <= through)):
        raise ValueError("Display requires one future completed-bar target")
    if result.status == "READY" and (not result.conditions or result.target_endpoint is None):
        raise ValueError("READY display needs a proved condition")
    if result.status == "NO_CANDIDATE" and (result.conditions or result.precision_ranges):
        raise ValueError("NO_CANDIDATE cannot display condition ranges")
    side = "顶" if direction == "TOP" else "底" if direction == "BOTTOM" else ""
    name = "顶部" if direction == "TOP" else "底部" if direction == "BOTTOM" else ""
    labels = {
        "READY": (f"可形成{side}钝化" if state == "NONE" else
                  f"{side}钝化有效" if state == "DULL" else f"{name}结构考核中"),
        "NO_CANDIDATE": "暂无可用条件",
        "PRECISION_PENDING": "条件待核验",
    }
    lines = []
    if result.status == "NO_CANDIDATE":
        lines.append(_no_candidate_text(result, prepared, state, side))
    elif result.status == "PRECISION_PENDING":
        lines.append("来源MACD与投影计算未能通过校准，暂不能给出下一根点位条件。"
                     if result.reason_code == "CALIBRATION_FAILED" else
                     "临界取值尚不能确定，不能当作无解；仅以下已证明条件可用。"
                     if result.conditions else "临界取值尚不能确定，不能当作无解。")
    if result.conditions and result.selected_reference == "FAR":
        lines.append("本次按远参照给出条件。")
    elif result.conditions and result.selected_reference == "NEAR":
        lines.append("本次只计算近参照条件。")
    order = _OUTCOME_ORDER[state]
    conditions = result.conditions
    outcomes = [condition.outcome for condition in conditions]
    if len(set(outcomes)) != len(outcomes) or any(outcome not in order for outcome in outcomes):
        raise ValueError("Condition outcomes do not match the actual display state")
    rescue = state == "DULL" and prepared.active_role == "NEAR" and result.selected_reference == "FAR"
    for condition in sorted(conditions, key=lambda item: order.index(item.outcome)):
        check()
        if condition.reference_role != result.selected_reference or not condition.price_ranges:
            raise ValueError("Condition display reference differs from the selected reference")
        action = _outcome_text(condition.outcome, state, direction, rescue)
        for price_range in condition.price_ranges:
            check()
            lines.append(f"{_range_text(price_range)}：{action}。")
    if result.precision_ranges:
        lines.append("另有临界价格范围尚不能确定，未并入以上条件；新完成收盘后重新计算。")
    if state == "STRUCTURE":
        lines.append("首次真实反色且结构仍有效时锁死；已锁死的旧结构不再预测撤销。")
    if result.target_endpoint is not None:
        target = f"{_time_text(result.target_endpoint, period)} · 下一根条件"
    else:
        target = "下一根完成收盘条件尚未确定"
    as_of = (f"{'历史核对' if mode == 'REPLAY' else '截至'} {_time_text(through, period)}"
             if through is not None else "暂无完成行情")
    display = {"statusLabel": labels[result.status], "targetText": target,
               "conditionsText": "\n".join(lines), "asOfText": as_of}
    check()
    return display
