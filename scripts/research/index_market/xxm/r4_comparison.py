"""Bounded in-memory r2/r4 comparison; no reader, CLI or product integration."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import math
import resource
import sys
import time
from typing import Any, TypedDict

from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar, XxmPeriod
from .r4_comparison_records import compare_records
from .r4_observation import ObservedR2Calculator, ObservedR4Calculator
from .r4_reference_trial import R4_TRIAL_SPEC


class R4ComparisonResult(TypedDict):
    metadata: dict[str, Any]
    rows: list[dict[str, Any]]
    differences: list[dict[str, Any]]
    idPairs: list[dict[str, Any]]
    summary: dict[str, Any]


def _memory_bytes() -> int:
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(maximum if sys.platform == "darwin" else maximum * 1024)


def _date(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("比较日期必须为YYYY-MM-DD文本")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("比较日期必须为YYYY-MM-DD文本")
    return parsed


def _encoded(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    except (ValueError, TypeError) as exc:
        raise ValueError("比较结果或来源说明含非法数值/字段类型") from exc


def compare_r4(bars: tuple[XxmBar, ...], *, period: XxmPeriod, source_identity: str,
               start_date: str, end_date: str, deadline: float,
               source_metadata: dict[str, Any] | None = None) -> R4ComparisonResult:
    """Compute both groups from empty progress, retaining the full prefix."""
    started = time.monotonic()
    spec = R4_TRIAL_SPEC
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("deadline必须为有限单调时刻")
    expires = min(deadline, started + spec.deadline_seconds)

    def check() -> None:
        if time.monotonic() >= expires:
            raise TimeoutError("本次r4比较超过统一时间上限")
        if _memory_bytes() > spec.max_memory_bytes:
            raise MemoryError("本次r4比较超过进程内存上限")

    check()
    if period not in ("day", "m60", "m90", "m120"):
        raise ValueError("不支持的比较周期")
    if not isinstance(source_identity, str) or not source_identity:
        raise ValueError("比较必须提供明确的输入来源身份")
    left, right = _date(start_date), _date(end_date)
    if left > right:
        raise ValueError("比较开始日期晚于结束日期")
    if type(bars) is not tuple or not 1 <= len(bars) <= spec.max_input_bars:
        raise ValueError("比较输入必须为1至1000根不可变行情元组")
    if source_metadata is not None and type(source_metadata) is not dict:
        raise ValueError("来源说明必须为字典")
    notes = source_metadata or {}
    if len(_encoded(notes)) > spec.max_result_bytes:
        raise OverflowError("来源说明超过结果大小上限")
    previous = None
    selected: list[XxmBar] = []
    for bar in bars:
        check()
        if type(bar) is not XxmBar:
            raise ValueError("比较仅接收XxmBar行情")
        bar.validate(period)
        if previous is not None and bar.time <= previous:
            raise ValueError("比较输入时间重复或逆序")
        previous = bar.time
        if bar.time[:10] <= end_date:
            selected.append(bar)
    if not selected:
        raise ValueError("截止日期内没有可计算的行情")
    check()
    r2 = ObservedR2Calculator(period=period, source_identity=source_identity)
    r4 = ObservedR4Calculator(period=period, source_identity=source_identity)
    identities = (MAIN_SPEC.spec_hash, spec.research_hash)
    rows: list[dict[str, Any]] = []
    for bar in selected:
        row: dict[str, Any] = {
            "time": bar.time,
            "input": {"time": bar.time, "close": bar.close, "dif": bar.dif, "dea": bar.dea,
                      "hist": bar.hist, "completed": bar.completed},
        }
        for name, calculator in (("r2", r2), ("r4", r4)):
            check()
            step = calculator.step(bar)
            row[name] = {
                "point": step.point, "events": list(step.events), "histories": list(step.histories),
                "bottomHistories": list(step.bottom_histories), "rearmRecords": list(step.rearm_records),
                "decision": deepcopy(calculator.last_decision),
            }
            check()
        rows.append(row)
    check()
    compared = compare_records(rows, start_date=start_date, end_date=end_date, check=check)
    if (r2.spec is not MAIN_SPEC or r4.spec is not MAIN_SPEC or r4.trial_spec is not spec
            or (MAIN_SPEC.spec_hash, spec.research_hash) != identities
            or r2.source_identity != source_identity or r4.input_identity != source_identity
            or r2.period != period or r4.period != period):
        raise ValueError("计算期间来源或规则身份发生变化")
    metadata = {
        "tsCode": "000001.SH", "period": period, "sourceIdentity": source_identity,
        "sourceDescription": deepcopy(notes),
        "numericPrecision": "输入为同一份原始Python float/int；未提供额外源数字文本，不重算MACD",
        "requestedStartDate": start_date, "requestedEndDate": end_date,
        "actualInputStart": bars[0].time, "actualInputEnd": bars[-1].time,
        "calculationStart": selected[0].time, "calculationEnd": selected[-1].time,
        "leftContextNote": "从输入首根空状态开始，未补更早行情；左侧首段可能不完整",
        "inputBarCount": len(bars), "calculationBarCount": len(selected),
        "reportBarCount": sum(start_date <= b.time[:10] <= end_date for b in selected),
        "r2AlgorithmVersion": MAIN_SPEC.algorithm_version, "r2SpecHash": identities[0],
        "r4ResearchVersion": spec.research_version, "r4ResearchHash": identities[1],
        "cutoffReason": ("input_ends_before_requested_date" if selected[-1].time[:10] < end_date
                         else "requested_end"),
        "elapsedSeconds": time.monotonic() - started, "peakMemoryBytes": _memory_bytes(),
        "resultBytes": 0,
    }
    result: R4ComparisonResult = {"metadata": metadata, "rows": rows, **compared}
    if set(result) != {"metadata", "rows", "differences", "idPairs", "summary"}:
        raise ValueError("比较返回字段不符合约定")
    initial_size = len(_encoded(result))
    check()
    if initial_size > spec.max_result_bytes:
        raise OverflowError("本次r4比较结果超过16MiB")
    # Measure after the full result has been encoded and checked, then check
    # the final JSON size again with these measured resource figures included.
    metadata["elapsedSeconds"] = time.monotonic() - started
    metadata["peakMemoryBytes"] = _memory_bytes()
    # Encoding and the final budget check belong to the same deadline. Iterate
    # the byte-count field until it describes the actual returned JSON size.
    for _ in range(5):
        check()
        size = len(_encoded(result))
        if size > spec.max_result_bytes:
            raise OverflowError("本次r4比较结果超过16MiB")
        if metadata["resultBytes"] == size:
            break
        metadata["resultBytes"] = size
    else:
        raise ValueError("结果大小检查未收敛")
    check()
    return result


def format_report(result: R4ComparisonResult) -> str:
    """Return terminal text only; callers decide when to display it."""
    meta, summary = result["metadata"], result["summary"]
    lines = ["上证日线r2/r4独立计算比较" if meta["period"] == "day" else "上证r2/r4独立计算比较",
             f"周期：{meta['period']}；请求：{meta['requestedStartDate']}—{meta['requestedEndDate']}",
             f"实际计算：{meta['calculationStart']}—{meta['calculationEnd']}；"
             f"计算{meta['calculationBarCount']}根，报告{meta['reportBarCount']}根",
             f"r2事件：{summary['r2EventCounts']}；r4事件：{summary['r4EventCounts']}",
             f"差异日期：{summary['differenceDateCount']}天；首次：{summary['firstDifference']}",
             "差异日期列表：" + "、".join(summary["differenceDates"]),
             f"耗时：{meta['elapsedSeconds']:.3f}秒；进程峰值：{meta['peakMemoryBytes']}字节；"
             f"完整结果：{meta['resultBytes']}字节",
             "仅说明相对r2的差异，不代表r4更准确或已还原原软件。"]
    by_time: dict[str, list[dict]] = {}
    for item in result["differences"]:
        by_time.setdefault(item["time"], []).append(item)

    def reference_text(reference):
        if reference is None:
            return "无活动参照"
        return (f"{reference['startTime']}—{reference['endTime']}，"
                f"收盘极值{reference['price']}，DIF极值{reference['dif']}")

    def condition(value):
        return "未检查" if value is None else "通过" if value else "未通过"

    states = {"NONE": "无钝化或结构", "DULL": "钝化", "STRUCTURE": "结构"}
    for row in result["rows"]:
        changes = by_time.get(row["time"])
        if not changes:
            continue
        lines.append(f"{row['time']}：不同字段 " + "、".join(c["field"] for c in changes))
        for side in ("r2", "r4"):
            group = row[side]
            point, decision = group["point"], group["decision"]
            events = "、".join(e["direction"] + "/" + e["type"] + "/" + e["route"] for e in group["events"]) or "无新事件"
            lines.append(f"  {side}：{states[point['ordinaryState']]}；{events}；"
                         + reference_text(point["activeReference"]))
            selected = decision["selectedReference"]
            if selected is not None and selected["action"] == "rescue":
                lines.append(f"    参照切换（{row['time']}）")
                lines.append("    切换前：" + reference_text(decision["before"]["reference"]))
                lines.append("    切换后：" + reference_text(selected["reference"]))
                lines.append("    本参照开始使用：" + selected["startedAt"])
            for check in decision["referenceChecks"]:
                prefix = f"    {check['stage']}/{check['candidate']}："
                if not check["checked"]:
                    lines.append(prefix + "未检查；" + check["reason"])
                else:
                    lines.append(prefix + reference_text(check["reference"])
                                 + f"；价格{condition(check['pricePassed'])}，DIF{condition(check['difPassed'])}")
            turn = decision["turn"]
            if turn["checked"]:
                lines.append(f"    相邻DIF {turn['previousDif']}→{turn['currentDif']}；1%门槛{turn['threshold']}")
            if turn["referenceBroken"]:
                lines.append("    原参照DIF已被严格突破")
            lines.append("    本根判断：" + decision["reason"])
        lines.append("  原因：" + changes[0]["reason"])
    return "\n".join(lines)
