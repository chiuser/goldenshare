"""Research-only r2/two-digit comparison; no product integration or saved results.

The valid CLI/replay path is implemented for a later, separately authorized run.
Development acceptance exercises the reader, literal ledgers and error/help paths
without running the two calculators together. Plan 0.17.2 / LLD 0.6.8.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import resource
import sys
import time
from typing import Any

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from .confirmation_only_trial import (
    ROOT, TRIAL_SPEC, ConfirmationTrialSpec, TwoDigitTurnCalculator,
    calculator_source_identity, verify_baseline,
)
from .near_first_review import quantize_dif


SOURCE_COLUMNS = (
    "ts_code", "trade_date", "close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq",
)
RECORD_LISTS = ("events", "histories", "bottomHistories", "rearmRecords")
HISTORY_LINKS = {
    "relatedTopHistoryId": "histories", "pendingTopHistoryId": "histories",
    "relatedBottomHistoryId": "bottomHistories", "pendingBottomHistoryId": "bottomHistories",
    "relatedRearmId": "rearmRecords", "pendingRearmId": "rearmRecords",
    "bottomHistoryId": "bottomHistories", "structureEventId": "events",
}


@dataclass(frozen=True, slots=True)
class ComparisonRange:
    requested_start: str
    requested_end: str


@dataclass(frozen=True, slots=True)
class ConfirmationInput:
    bars: tuple[XxmBar, ...]
    source_rows: tuple[tuple[str, ...], ...]
    source_identity: str
    open_dates: tuple[str, ...]


def _date(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("日期必须为YYYY-MM-DD文本")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"非法日期：{value!r}；要求YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"非法日期格式：{value!r}；要求YYYY-MM-DD")
    return parsed


def resolve_comparison_range(start_date=None, end_date=None, *, spec=TRIAL_SPEC) -> ComparisonRange:
    start = spec.default_start_date if start_date is None else start_date
    end = spec.default_end_date if end_date is None else end_date
    left, right = _date(start), _date(end)
    lower, upper = _date(spec.source_start_date), _date(spec.source_end_date)
    if lower > upper:
        raise ValueError("研究参数中的来源日期倒序")
    if left > right:
        raise ValueError(f"开始日期{start}晚于结束日期{end}")
    for label, value in (("开始", left), ("结束", right)):
        if not lower <= value <= upper:
            raise ValueError(f"{label}日期{value}越界；可用范围{lower}至{upper}")
    return ComparisonRange(start, end)


def _memory_bytes() -> int:
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(maximum if sys.platform == "darwin" else maximum * 1024)


def _check(deadline: float, spec: ConfirmationTrialSpec, cancelled=None) -> None:
    if cancelled is not None and cancelled():
        raise InterruptedError("本次研究计算已取消")
    if time.monotonic() >= deadline:
        raise TimeoutError("本次研究读取及计算已超过共同截止时间")
    if _memory_bytes() > spec.max_memory_bytes:
        raise MemoryError("本次研究进程内存超过上限")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _bounded_read(path: Path, limit: int, *, deadline, spec, cancelled) -> bytes:
    _check(deadline, spec, cancelled)
    if path.stat().st_size > limit:
        raise ValueError(f"输入文件超过字节上限：{path.name}")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _check(deadline, spec, cancelled)
    if len(raw) > limit:
        raise ValueError(f"输入文件超过字节上限：{path.name}")
    return raw


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"日历存在重复字段：{key}")
        result[key] = value
    return result


def _number(text: str) -> Decimal:
    if not isinstance(text, str) or not text or text != text.strip():
        raise ValueError("源数字必须为非空且未修饰的文本")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"非法源数字：{text!r}") from exc
    if not number.is_finite():
        raise ValueError("源数字必须有限")
    return number


def read_confirmation_input(*, spec=TRIAL_SPEC, root=ROOT, deadline=None, cancelled=None) -> ConfirmationInput:
    """Read only the two declared files; tests supply their own immutable Spec."""
    deadline = time.monotonic() + spec.timeout_seconds if deadline is None else deadline
    root = Path(root)
    for relative in (spec.source_path, spec.calendar_path):
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("输入路径必须位于已声明的研究根目录内")
    raw = _bounded_read(root / spec.source_path, spec.max_csv_bytes,
                        deadline=deadline, spec=spec, cancelled=cancelled)
    if hashlib.sha256(raw).hexdigest() != spec.source_sha256:
        raise ValueError("日线输入SHA不符")
    calendar_raw = _bounded_read(root / spec.calendar_path, spec.max_calendar_bytes,
                                 deadline=deadline, spec=spec, cancelled=cancelled)
    if hashlib.sha256(calendar_raw).hexdigest() != spec.calendar_sha256:
        raise ValueError("SSE日历SHA不符")
    reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
    if tuple(next(reader, ())) != SOURCE_COLUMNS:
        raise ValueError("日线输入列或列顺序不符")
    bars, source_rows = [], []
    lower, upper = _date(spec.source_start_date), _date(spec.source_end_date)
    for row in reader:
        _check(deadline, spec, cancelled)
        if len(bars) >= spec.max_bars or len(row) != len(SOURCE_COLUMNS):
            raise ValueError("日线输入行数超限或字段数量错误")
        if row[0] != "000001.SH":
            raise ValueError("研究只支持000001.SH日线")
        stamp = _date(row[1])
        if not lower <= stamp <= upper or (bars and row[1] <= bars[-1].time):
            raise ValueError("日线日期越界、重复或倒序")
        close, dif, dea, hist = map(_number, row[2:])
        if close <= 0 or abs(hist - 2 * (dif - dea)) > Decimal(spec.macd_tolerance):
            raise ValueError("日线收盘价或MACD两倍关系不符")
        bar = XxmBar(row[1], *(float(v) for v in (close, dif, dea, hist)))
        bar.validate("day")
        bars.append(bar)
        source_rows.append(tuple(row))
    if not bars:
        raise ValueError("固定日线输入为空")
    calendar = json.loads(calendar_raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(calendar, list) or not calendar or len(calendar) > spec.max_calendar_rows:
        raise ValueError("SSE日历容器或行数不符")
    previous, opened = None, []
    for row in calendar:
        _check(deadline, spec, cancelled)
        if (not isinstance(row, dict) or set(row) != {"exchange", "trade_date", "is_open"}
                or row["exchange"] != "SSE" or type(row["is_open"]) is not bool):
            raise ValueError("SSE日历字段、交易所或开市标志不符")
        stamp = _date(row["trade_date"])
        if (previous is None and stamp != lower) or (previous is not None and stamp != previous + timedelta(days=1)):
            raise ValueError("SSE日历缺自然日、重复、倒序或起点不符")
        previous = stamp
        if row["is_open"]:
            opened.append(row["trade_date"])
    if previous != upper or tuple(opened) != tuple(bar.time for bar in bars):
        raise ValueError("SSE日历覆盖不足或日线缺少应有交易日/包含休市日")
    _check(deadline, spec, cancelled)
    return ConfirmationInput(tuple(bars), tuple(source_rows),
                             _digest({"csv": spec.source_sha256, "calendar": spec.calendar_sha256,
                                      "columns": SOURCE_COLUMNS, "tsCode": "000001.SH", "period": "day"}),
                             tuple(opened))


def _validate_bars(bars, spec, deadline, cancelled) -> None:
    if not isinstance(bars, tuple) or not bars or len(bars) > spec.max_bars:
        raise ValueError("对照输入须为非空且有界的不可变日线序列")
    if (not isinstance(bars[0], XxmBar) or not isinstance(bars[-1], XxmBar)
            or bars[0].time != spec.source_start_date or bars[-1].time != spec.source_end_date):
        raise ValueError("对照输入必须包含声明的完整物理源首末日，不能从短窗重新初始化")
    previous = None
    for bar in bars:
        _check(deadline, spec, cancelled)
        if (not isinstance(bar, XxmBar) or bar.completed is not True
                or any(type(v) not in (int, float) for v in (bar.close, bar.dif, bar.dea, bar.hist))):
            raise ValueError("对照输入字段或完成标志不符")
        bar.validate("day")
        if not spec.source_start_date <= bar.time <= spec.source_end_date or (previous and bar.time <= previous):
            raise ValueError("对照输入日期越界、重复或倒序")
        previous = bar.time


def _checked_result(result: dict, *, deadline, spec, cancelled):
    _check(deadline, spec, cancelled)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > spec.max_result_bytes:
        raise ValueError("研究内存结果超过大小上限")
    _check(deadline, spec, cancelled)
    return result


def _business_point(point: dict) -> dict:
    return {key: deepcopy(value) for key, value in point.items()
            if key not in {"time", "close", "dif", "dea", "hist"}}


def _reference_key(reference):
    if reference is None:
        return None
    return tuple(reference[key] for key in ("startTime", "endTime", "price", "dif"))


def _ledger_index(records, trading_dates, *, deadline, spec, cancelled):
    """Index the producer's point/event/history records; never infer missing IDs."""
    if len(records) != len(trading_dates):
        raise ValueError("逐根记录与交易日数量不符")
    indexes = {key: {} for key in RECORD_LISTS}
    events, segments = [], {}
    points = {"time", "close", "dif", "dea", "hist", "ordinaryState", "ordinaryDirection",
              "activeReference", "pendingTopHistoryId", "pendingBottomHistoryId", "pendingRearmId"}
    event_fields = {"id", "time", "direction", "type", "route", "fromState", "eventReference",
                    "relatedTopHistoryId", "relatedBottomHistoryId", "relatedRearmId"}
    known_dates = set(trading_dates)
    seen = {key: set() for key in RECORD_LISTS}
    for record, stamp in zip(records, trading_dates):
        _check(deadline, spec, cancelled)
        if not isinstance(record, dict) or not points <= set(record.get("point", {})):
            raise ValueError("缺少现行逐根point字段")
        point = record["point"]
        if point["time"] != stamp:
            raise ValueError("逐根记录日期与交易日不对应")
        XxmBar(stamp, point["close"], point["dif"], point["dea"], point["hist"]).validate("day")
        if point["ordinaryState"] not in {"NONE", "DULL", "STRUCTURE"}:
            raise ValueError("非法逐根状态")
        for key in RECORD_LISTS:
            values = record.get(key)
            if not isinstance(values, (tuple, list)):
                raise ValueError(f"逐根记录缺少{key}")
            for item in values:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                    raise ValueError("记录缺少有效编号")
                identity = item["id"]
                if key == "events":
                    if (set(item) != event_fields or identity in seen[key] or item["time"] != stamp
                            or item["direction"] not in {"TOP", "BOTTOM"}):
                        raise ValueError("事件字段、日期或编号不符")
                    origin = record.get("eventSegmentStarts", {}).get(identity)
                    if origin not in known_dates or origin > stamp:
                        raise ValueError("事件缺少已发生的来源柱色区间")
                    _reference_key(item["eventReference"])
                    events.append(item)
                    segments[identity] = origin
                else:
                    if item.get("observedThrough") != stamp:
                        raise ValueError("历史/等待更新日期不符")
                seen[key].add(identity)
                indexes[key][identity] = item
        # References may point to earlier records or records produced on this bar,
        # but never to a not-yet-created record in the future.
        for item in [point, *[item for key in RECORD_LISTS for item in record[key]]]:
            for field, target in HISTORY_LINKS.items():
                identity = item.get(field)
                if identity is not None and identity not in seen[target]:
                    raise ValueError(f"悬挂或提前引用：{field}")
    return indexes, events, segments


def _normal(value, mappings, side, field=None):
    if isinstance(value, dict):
        return {key: _normal(item, mappings, side, key) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normal(item, mappings, side) for item in value]
    if value is not None and (field == "id" or field in HISTORY_LINKS):
        return mappings.get(value, f"{side}:{value}")
    return value


def _cause(left, right, mappings):
    previous_left, previous_right = left.get("before"), right.get("before")
    if previous_left is None or previous_right is None:
        return "待解释；当前记录仅供比较结果，未提供计算前状态"
    equal = _normal(previous_left, mappings[0], "r2") == _normal(previous_right, mappings[1], "two_digit")
    turn = left.get("turn", {})
    state = previous_left.get("ordinaryState")
    if equal and state in {"DULL", "STRUCTURE"}:
        key = "Formation" if state == "DULL" else "Return"
        route = "dif_turn" if state == "DULL" else "dif_return"
        executed_routes = {event["route"] for record in (left, right) for event in record["events"]}
        if turn.get("r2" + key) != turn.get("twoDigit" + key) and route in executed_routes:
            return "相邻DIF转折门槛直接不同"
    if not equal:
        return "此前状态或参照变化的后续影响"
    if any(_normal(left[kind], mappings[0], "r2") != _normal(right[kind], mappings[1], "two_digit")
           for kind in RECORD_LISTS[1:]):
        return "历史记录不同；需沿创建记录核对前段原因"
    return "待解释；不能仅凭标签差异断定原因"


def compare_ledgers(baseline, trial, *, comparison_range, trading_dates,
                    spec=TRIAL_SPEC, deadline=None, cancelled=None) -> dict:
    """Compare literal/previously computed records without running a calculator."""
    deadline = time.monotonic() + spec.timeout_seconds if deadline is None else deadline
    requested = resolve_comparison_range(comparison_range.requested_start,
                                         comparison_range.requested_end, spec=spec)
    dates = tuple(trading_dates)
    if not dates or len(dates) > spec.max_bars:
        raise ValueError("比较记录须有非空且有界的交易日序列")
    for i, stamp in enumerate(dates):
        _date(stamp)
        if (not spec.source_start_date <= stamp <= requested.requested_end
                or (i and stamp <= dates[i - 1])):
            raise ValueError("比较交易日越界、重复、倒序或包含结束日之后")
    indexes, events, segments = [], [], []
    for records in (baseline, trial):
        index, sequence, origins = _ledger_index(records, dates, deadline=deadline,
                                               spec=spec, cancelled=cancelled)
        indexes.append(index)
        events.append(sequence)
        segments.append(origins)
    for left, right in zip(baseline, trial):
        if any(left["point"][field] != right["point"][field]
               for field in ("time", "close", "dif", "dea", "hist")):
            raise ValueError("两组实际行情不同，不能归因于确认门槛")

    def same_day(event):
        reference = event["eventReference"]
        return (event["time"], event["direction"], event["type"], event["route"],
                reference["startTime"] if reference else None)

    def across_days(event, side):
        return (event["direction"], event["type"], event["route"],
                _reference_key(event["eventReference"]), segments[side][event["id"]])

    pairs, used = [], [set(), set()]
    # Exact-day matching first. Ambiguous groups are left unpaired, not zipped.
    for key_function in (same_day, None):
        groups = [{}, {}]
        for side in (0, 1):
            for event in events[side]:
                _check(deadline, spec, cancelled)
                if event["id"] not in used[side]:
                    key = key_function(event) if key_function else across_days(event, side)
                    groups[side].setdefault(key, []).append(event)
        for key in groups[0].keys() & groups[1].keys():
            if len(groups[0][key]) == len(groups[1][key]) == 1:
                left, right = groups[0][key][0], groups[1][key][0]
                pairs.append((left, right))
                used[0].add(left["id"])
                used[1].add(right["id"])
    pairs.extend((event, None) for event in events[0] if event["id"] not in used[0])
    pairs.extend((None, event) for event in events[1] if event["id"] not in used[1])
    mappings, bound_pairs = [{}, {}], [{}, {}]

    def bind(left_id, right_id, record_type):
        if left_id is None or right_id is None:
            return
        token = f"{record_type}:{left_id}"
        if (left_id in bound_pairs[0] and bound_pairs[0][left_id] != right_id) or (
                right_id in bound_pairs[1] and bound_pairs[1][right_id] != left_id):
            raise ValueError("事件和历史存在多义关联")
        bound_pairs[0][left_id], bound_pairs[1][right_id] = right_id, left_id
        mappings[0][left_id] = mappings[1][right_id] = token

    for left, right in pairs:
        if left is not None and right is not None:
            bind(left["id"], right["id"], "events")
    # Only matched creation events establish corresponding history identities.
    # A later withdrawal must not make two different original structures equal.
    for left, right in pairs:
        if left is not None and right is not None and left["type"] == "STRUCTURE":
            for field in ("relatedTopHistoryId", "relatedBottomHistoryId"):
                bind(left[field], right[field], HISTORY_LINKS[field])
    for left, right in pairs:
        if left is not None and right is not None and left["type"] == "STRUCTURE_DISAPPEARED":
            left_id, right_id = left["relatedRearmId"], right["relatedRearmId"]
            if left_id is not None and right_id is not None:
                left_record, right_record = indexes[0]["rearmRecords"][left_id], indexes[1]["rearmRecords"][right_id]
                a = mappings[0].get(left_record["structureEventId"])
                b = mappings[1].get(right_record["structureEventId"])
                if a is not None and a == b:
                    bind(left_id, right_id, "rearmRecords")

    def inside(stamp):
        return requested.requested_start <= stamp <= requested.requested_end

    position = {stamp: i for i, stamp in enumerate(dates)}
    changed_dates, comparisons = set(), []
    for left, right in pairs:
        _check(deadline, spec, cancelled)
        delta, changed = None, []
        if left is not None and right is not None:
            left_business = {key: value for key, value in left.items() if key not in {"id", "time"}}
            right_business = {key: value for key, value in right.items() if key not in {"id", "time"}}
            a, b = _normal(left_business, mappings[0], "r2"), _normal(right_business, mappings[1], "two_digit")
            changed = sorted(key for key in a if a[key] != b[key])
            delta = position[right["time"]] - position[left["time"]]
            classification = "提前" if delta < 0 else "推后" if delta > 0 else "参照/历史等事件内容变化" if changed else "相同"
        else:
            classification = "相对r2减少" if right is None else "相对r2新增"
        if classification != "相同":
            changed_dates.update(event["time"] for event in (left, right) if event is not None)
        if any(inside(event["time"]) for event in (left, right) if event is not None):
            stamp = min(event["time"] for event in (left, right) if event is not None)
            i = position[stamp]
            left_context = baseline[position[left["time"] if left is not None else right["time"]]]
            right_context = trial[position[right["time"] if right is not None else left["time"]]]
            comparisons.append({"classification": classification, "r2": deepcopy(left), "twoDigit": deepcopy(right),
                                "r2OutsideRange": left is not None and not inside(left["time"]),
                                "twoDigitOutsideRange": right is not None and not inside(right["time"]),
                                "tradingBarShift": delta, "changedFields": changed,
                                "cause": None if classification == "相同" else _cause(baseline[i], trial[i], mappings),
                                "causeAt": stamp,
                                "r2Context": {"time": left_context["point"]["time"],
                                              "before": deepcopy(left_context.get("before")),
                                              "turn": deepcopy(left_context.get("turn"))},
                                "twoDigitContext": {"time": right_context["point"]["time"],
                                                    "before": deepcopy(right_context.get("before")),
                                                    "turn": deepcopy(right_context.get("turn"))},
                                "unpairedNote": None if left is not None and right is not None else
                                "截至本次结束日期未见可唯一对应事件"})
    point_differences, history_differences = [], []
    for left, right in zip(baseline, trial):
        _check(deadline, spec, cancelled)
        stamp = left["point"]["time"]
        a = _normal(_business_point(left["point"]), mappings[0], "r2")
        b = _normal(_business_point(right["point"]), mappings[1], "two_digit")
        fields = sorted(key for key in a if a[key] != b[key])
        if fields:
            changed_dates.add(stamp)
            if inside(stamp):
                point_differences.append({"time": stamp, "fields": fields,
                                          "r2": deepcopy(left["point"]), "twoDigit": deepcopy(right["point"]),
                                          "r2Before": deepcopy(left.get("before")),
                                          "twoDigitBefore": deepcopy(right.get("before")),
                                          "turn": deepcopy(left.get("turn")), "cause": _cause(left, right, mappings)})
        for kind in RECORD_LISTS[1:]:
            a, b = _normal(left[kind], mappings[0], "r2"), _normal(right[kind], mappings[1], "two_digit")
            if a != b:
                changed_dates.add(stamp)
                if inside(stamp):
                    history_differences.append({"time": stamp, "kind": kind,
                                                "r2": deepcopy(left[kind]), "twoDigit": deepcopy(right[kind]),
                                                "cause": _cause(left, right, mappings)})
    comparisons.sort(key=lambda item: (min(event["time"] for event in (item["r2"], item["twoDigit"]) if event),
                                       (item["r2"] or item["twoDigit"])["id"]))
    actual = [stamp for stamp in dates if inside(stamp)]
    in_window = sorted(stamp for stamp in changed_dates if inside(stamp))
    result = {
        "status": "ready" if actual else "empty",
        "requestedStart": requested.requested_start, "requestedEnd": requested.requested_end,
        "observationStart": actual[0] if actual else None, "observationEnd": actual[-1] if actual else None,
        "observationBarCount": len(actual),
        "firstDivergenceInPrefix": min(changed_dates) if changed_dates else None,
        "firstDivergenceInObservation": in_window[0] if in_window else None,
        "eventComparisons": comparisons, "pointDifferences": point_differences,
        "historyDifferences": history_differences,
        "summary": {"eventComparisons": dict(Counter(item["classification"] for item in comparisons)),
                    "pointDifferenceCount": len(point_differences), "historyDifferenceCount": len(history_differences),
                    "r2EventCounts": dict(Counter(event["type"] for event in events[0] if inside(event["time"]))),
                    "twoDigitEventCounts": dict(Counter(event["type"] for event in events[1] if inside(event["time"])))},
    }
    return _checked_result(result, deadline=deadline, spec=spec, cancelled=cancelled)


def _before(calculator):
    sign = calculator.wave.sign if calculator.wave else 0
    return {"ordinaryState": calculator.state,
            "ordinaryDirection": ("TOP" if sign == 1 else "BOTTOM") if calculator.state != "NONE" else None,
            "activeReference": calculator.reference.reference() if calculator.reference else None,
            "pendingTopHistoryId": calculator.pending["id"] if calculator.pending else None,
            "pendingBottomHistoryId": calculator.pending_bottom_history["id"] if calculator.pending_bottom_history else None,
            "pendingRearmId": calculator.pending_rearm["id"] if calculator.pending_rearm else None}


def _turn(previous: XxmBar | None, bar: XxmBar) -> dict:
    sign = (bar.hist > 0) - (bar.hist < 0)
    previous_dif = previous.dif if previous else None
    current_q = quantize_dif(Decimal(str(bar.dif)))
    previous_q = quantize_dif(Decimal(str(previous_dif))) if previous is not None else None
    raw_delta = sign * (bar.dif - previous_dif) if previous is not None else 0
    gate = abs(previous_dif) * MAIN_SPEC.dif_turn_pct / 100 if previous is not None else 0
    delta = sign * (current_q - previous_q) if previous_q is not None else Decimal(0)
    return {"p": previous_dif, "c": bar.dif,
            "Qp": str(previous_q) if previous_q is not None else None, "Qc": str(current_q),
            "r2Formation": previous_dif not in (None, 0) and raw_delta < 0 and -raw_delta >= gate,
            "r2Return": previous_dif not in (None, 0) and raw_delta > 0 and raw_delta >= gate,
            "twoDigitFormation": delta < 0, "twoDigitReturn": delta > 0,
            "numericOnly": True}


def _replay_one(calculator, bars, *, deadline, spec, cancelled):
    """Later execution path. No development test invokes the dual replay caller."""
    records, history_origins = [], {}
    for bar in bars:
        _check(deadline, spec, cancelled)
        before, turn = _before(calculator), _turn(calculator.previous, bar)
        previous_start = calculator.wave.start if calculator.wave else None
        step = calculator.step(bar)
        _check(deadline, spec, cancelled)
        current_start = calculator.wave.start
        origins = {}
        for event in step.events:
            if event["type"] == "RESEARCH_HISTORICAL_WITHDRAWAL":
                history_id = event["relatedTopHistoryId"] or event["relatedBottomHistoryId"]
                if history_id not in history_origins:
                    raise ValueError("历史事件无法追溯原柱色区间")
                origin = history_origins[history_id]
            else:
                origin = previous_start if event["route"] in {"color_flip", "dif_break_on_flip"} else current_start
            origins[event["id"]] = origin
            if event["type"] == "STRUCTURE":
                for field in ("relatedTopHistoryId", "relatedBottomHistoryId"):
                    if event[field] is not None:
                        history_origins[event[field]] = origin
        records.append(deepcopy({"before": before, "turn": turn, "point": step.point,
                                 "events": list(step.events), "histories": list(step.histories),
                                 "bottomHistories": list(step.bottom_histories),
                                 "rearmRecords": list(step.rearm_records), "eventSegmentStarts": origins}))
        _check(deadline, spec, cancelled)
    return records


def compare_confirmation(bars, source_identity, *, start_date=None, end_date=None,
                         spec=TRIAL_SPEC, deadline=None, cancelled=None) -> dict:
    """Implemented dual-calculator entry; intentionally not run at this delivery."""
    requested = resolve_comparison_range(start_date, end_date, spec=spec)
    deadline = time.monotonic() + spec.timeout_seconds if deadline is None else deadline
    if not isinstance(source_identity, str) or not source_identity:
        raise ValueError("缺少已验证的输入来源身份")
    verify_baseline(spec=spec)
    _validate_bars(bars, spec, deadline, cancelled)
    prefix = tuple(bar for bar in bars if bar.time <= requested.requested_end)
    input_identity = _digest({"sourceIdentity": source_identity, "tsCode": "000001.SH", "period": "day",
                              "requestedStart": requested.requested_start, "requestedEnd": requested.requested_end})
    identities = {mode: calculator_source_identity(mode, input_identity, spec=spec) for mode in ("r2", "two_digit")}
    # Both objects start empty. Never restore a page or another experiment's state.
    r2 = XxmCalculator(period="day", source_identity=identities["r2"])
    two_digit = TwoDigitTurnCalculator(period="day", source_identity=input_identity, trial_spec=spec)
    left = _replay_one(r2, prefix, deadline=deadline, spec=spec, cancelled=cancelled)
    right = _replay_one(two_digit, prefix, deadline=deadline, spec=spec, cancelled=cancelled)
    if prefix:
        result = compare_ledgers(left, right, comparison_range=requested,
                                 trading_dates=tuple(bar.time for bar in prefix),
                                 spec=spec, deadline=deadline, cancelled=cancelled)
    else:
        result = {"status": "empty", "requestedStart": requested.requested_start,
                  "requestedEnd": requested.requested_end, "observationStart": None, "observationEnd": None,
                  "observationBarCount": 0, "firstDivergenceInPrefix": None, "firstDivergenceInObservation": None,
                  "eventComparisons": [], "pointDifferences": [], "historyDifferences": [],
                  "summary": {"eventComparisons": {}, "pointDifferenceCount": 0, "historyDifferenceCount": 0,
                              "r2EventCounts": {}, "twoDigitEventCounts": {}}}
    result.update({"sourceIdentity": source_identity, "inputIdentity": input_identity,
                   "baseSpecHash": MAIN_SPEC.spec_hash, "researchSpecHash": spec.research_hash,
                   "availableStart": bars[0].time, "availableEnd": bars[-1].time, "sourceBarCount": len(bars),
                   "calculationStart": prefix[0].time if prefix else None,
                   "calculationEnd": prefix[-1].time if prefix else None, "calculationBarCount": len(prefix),
                   "contextBarCount": sum(bar.time < requested.requested_start for bar in prefix),
                   "contextWarnings": ["以源首日空状态为试验前提；不声称此前历史状态已完整恢复"],
                   "r2": {"mode": "r2", "sourceIdentity": identities["r2"], "records": left},
                   "twoDigit": {"mode": "two_digit", "sourceIdentity": identities["two_digit"], "records": right}})
    return _checked_result(result, deadline=deadline, spec=spec, cancelled=cancelled)


def format_report(result: dict) -> str:
    """Render program differences only. This function performs no I/O or replay."""
    lines = [
        "r2与两位确认：程序输出对比",
        f"请求区间：{result['requestedStart']} 至 {result['requestedEnd']}",
        f"实际观察：{result['observationStart']} 至 {result['observationEnd']}，{result['observationBarCount']}根",
        f"来源范围：{result['availableStart']} 至 {result['availableEnd']}，{result['sourceBarCount']}根",
        f"实际计算：{result['calculationStart']} 至 {result['calculationEnd']}，{result['calculationBarCount']}根；前段{result['contextBarCount']}根",
        f"r2规则：{result['baseSpecHash']}；两位规则：{result['researchSpecHash']}",
        f"首次前缀差异：{result['firstDivergenceInPrefix']}；观察区间首差异：{result['firstDivergenceInObservation']}",
        "程序差异汇总：" + json.dumps(result["summary"], ensure_ascii=False, sort_keys=True),
        *result.get("contextWarnings", []),
    ]
    if result["status"] == "empty":
        lines.append("所选区间无交易日，未作该区间标签比较")
    for kind, key in (("事件", "eventComparisons"), ("逐根状态", "pointDifferences"), ("历史更新", "historyDifferences")):
        for item in result[key]:
            if item.get("classification") == "相同":
                continue
            lines.append(kind + "差异：" + json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="仅比较r2与两位确认的日线程序输出，不保存结果")
    parser.add_argument("--start-date", help=f"比较开始日YYYY-MM-DD，默认{TRIAL_SPEC.default_start_date}")
    parser.add_argument("--end-date", help=f"比较结束日YYYY-MM-DD，默认{TRIAL_SPEC.default_end_date}")
    args = parser.parse_args(argv)
    try:
        requested = resolve_comparison_range(args.start_date, args.end_date)
        deadline = time.monotonic() + TRIAL_SPEC.timeout_seconds
        verify_baseline()
        inputs = read_confirmation_input(deadline=deadline)
        result = compare_confirmation(inputs.bars, inputs.source_identity,
                                      start_date=requested.requested_start, end_date=requested.requested_end,
                                      deadline=deadline)
        # Preserve source text and the exact float supplied to both calculators.
        result["sourcePoints"] = [
            {"time": bar.time, "sourceText": dict(zip(SOURCE_COLUMNS, row)),
             "passedValues": {"close": bar.close, "dif": bar.dif, "dea": bar.dea, "hist": bar.hist}}
            for bar, row in zip(inputs.bars, inputs.source_rows) if bar.time <= requested.requested_end
        ]
        _checked_result(result, deadline=deadline, spec=TRIAL_SPEC, cancelled=None)
        report = format_report(result)
        _check(deadline, TRIAL_SPEC)
        print(report)
    except KeyboardInterrupt:
        print("本次研究已取消；未发布成功结果，下次从头计算", file=sys.stderr)
        return 130
    except (ValueError, OSError, TimeoutError, MemoryError, InterruptedError, csv.Error) as exc:
        print(f"研究计算失败：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
