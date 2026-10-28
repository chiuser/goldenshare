"""Compare supplied r2/r4 records without loading input or running calculators."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable


_KINDS = ("events", "histories", "bottomHistories", "rearmRecords")
_LINKS = {
    "relatedTopHistoryId": "histories", "pendingTopHistoryId": "histories",
    "relatedBottomHistoryId": "bottomHistories", "pendingBottomHistoryId": "bottomHistories",
    "relatedRearmId": "rearmRecords", "pendingRearmId": "rearmRecords", "rearmId": "rearmRecords",
    "bottomHistoryId": "bottomHistories", "structureEventId": "events",
}
_DECISION_KEYS = {"before", "rawSign", "wave", "referenceChecks", "selectedReference", "turn", "branch", "reason"}
_POINT_KEYS = {"time", "close", "dif", "dea", "hist", "ordinaryState", "ordinaryDirection",
               "activeReference", "pendingTopHistoryId", "pendingBottomHistoryId", "pendingRearmId"}


def _day(value: Any) -> str:
    if not isinstance(value, str) or len(value) < 10:
        raise ValueError("记录缺少有效日期")
    part = value[:10]
    if date.fromisoformat(part).isoformat() != part:
        raise ValueError("记录日期格式错误")
    return part


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"缺少{label}")
    return value


@dataclass
class _Index:
    records: dict[str, dict[str, dict]] = field(default_factory=lambda: {kind: {} for kind in _KINDS})
    kinds: dict[str, str] = field(default_factory=dict)
    first: dict[str, str] = field(default_factory=dict)
    origins: dict[str, str] = field(default_factory=dict)
    structure_for_history: dict[str, str] = field(default_factory=dict)


def _walk_links(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _LINKS and item is not None:
                yield key, item, _LINKS[key]
            elif key == "id" and item is not None:
                yield key, item, None
            elif isinstance(item, (dict, list, tuple)):
                yield from _walk_links(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_links(item)


def _check_links(value: Any, index: _Index, stamp: str) -> None:
    for key, identity, expected in _walk_links(value):
        _text(identity, "关联编号")
        if identity not in index.kinds or (expected is not None and index.kinds[identity] != expected):
            raise ValueError(f"悬挂或错误类型关联：{key}")
        if index.first[identity] > stamp:
            raise ValueError(f"提前引用未来记录：{key}")


def _origin(event: dict, decision: dict, index: _Index) -> str:
    if event["type"] == "RESEARCH_HISTORICAL_WITHDRAWAL":
        history = event.get("relatedTopHistoryId") or event.get("relatedBottomHistoryId")
        structure = index.structure_for_history.get(history)
        if structure is None or structure not in index.origins:
            raise ValueError("历史撤销无法追溯原结构")
        return index.origins[structure]
    before = decision["before"]
    wave = before.get("wave") if event["route"] in ("color_flip", "dif_break_on_flip") else decision["wave"]
    sign = 1 if event["direction"] == "TOP" else -1
    if not isinstance(wave, dict) or wave.get("sign") != sign:
        raise ValueError("事件缺少对应方向的来源色段")
    start = _text(wave.get("start"), "来源色段起点")
    _day(start)
    if start > event["time"]:
        raise ValueError("来源色段晚于事件")
    return start


def _history_links(index: _Index, values: dict[str, list], stamp: str) -> None:
    events = index.records["events"]
    for event in values["events"]:
        if event["type"] != "STRUCTURE":
            continue
        kind, link = ("histories", "relatedTopHistoryId") if event["direction"] == "TOP" else (
            "bottomHistories", "relatedBottomHistoryId")
        identity = event.get(link)
        if identity is None:
            raise ValueError("结构事件缺少对应历史")
        record = index.records[kind][identity]
        if (record.get("confirmedAt") != stamp or record.get("confirmationRoute") != event["route"]
                or record.get("originalReference") != event.get("eventReference")):
            raise ValueError("结构与历史的形成日期、路径或参照不一致")
        if kind == "bottomHistories" and record.get("structureEventId") != event["id"]:
            raise ValueError("底部历史指向另一结构")
        prior = index.structure_for_history.get(identity)
        if prior is not None and prior != event["id"]:
            raise ValueError("同一历史关联多个结构")
        index.structure_for_history[identity] = event["id"]
    for kind in ("histories", "bottomHistories"):
        for record in values[kind]:
            structure = index.structure_for_history.get(record["id"])
            if structure is None:
                raise ValueError("历史没有已发生的原结构")
            event = events[structure]
            if (record.get("confirmedAt") != event["time"]
                    or record.get("confirmationRoute") != event["route"]
                    or record.get("originalReference") != event.get("eventReference")
                    or (kind == "bottomHistories" and record.get("structureEventId") != structure)):
                raise ValueError("历史更新改变了原结构关联")
    for record in values["rearmRecords"]:
        structure = events[record["structureEventId"]]
        if (structure["type"] != "STRUCTURE" or structure["direction"] != "BOTTOM"
                or structure.get("relatedBottomHistoryId") != record["bottomHistoryId"]
                or structure["time"] != record.get("structureConfirmedAt")
                or index.origins.get(structure["id"]) != record.get("segmentStart")):
            raise ValueError("等待记录与原底部结构不对应")
        if index.first[record["id"]] != record.get("disappearedAt"):
            raise ValueError("等待记录首次出现日期错误")
        matching = [event for event in values["events"]
                    if event.get("relatedRearmId") == record["id"] and event["type"] == "STRUCTURE_DISAPPEARED"]
        if index.first[record["id"]] == stamp and (len(matching) != 1
                or matching[0].get("relatedBottomHistoryId") != record["bottomHistoryId"]):
            raise ValueError("等待缺少对应的结构消失事件")


def _build_index(rows: list[dict], side: str, check: Callable[[], None]) -> _Index:
    index = _Index()
    for row in rows:
        check()
        stamp, group = row["time"], row[side]
        if not isinstance(group, dict) or not isinstance(group.get("decision"), dict):
            raise ValueError("逐根记录缺少判断依据")
        if not _DECISION_KEYS <= set(group["decision"]):
            raise ValueError("逐根记录缺少判断依据")
        point, decision = group.get("point"), group["decision"]
        if not isinstance(point, dict) or not _POINT_KEYS <= set(point) or point["time"] != stamp:
            raise ValueError("逐根point字段或日期错误")
        if not isinstance(decision["before"], dict):
            raise ValueError("缺少进入本根前状态")
        for name in ("close", "dif", "dea", "hist"):
            if point[name] != row["input"].get(name):
                raise ValueError("两组记录使用的实际行情不一致")
        values = {}
        for kind in _KINDS:
            if not isinstance(group.get(kind), (tuple, list)):
                raise ValueError(f"逐根记录缺少{kind}")
            values[kind] = group[kind]
            on_bar = set()
            for item in values[kind]:
                if not isinstance(item, dict):
                    raise ValueError("记录必须是字典")
                identity = _text(item.get("id"), "记录编号")
                if identity in on_bar or (identity in index.kinds and index.kinds[identity] != kind):
                    raise ValueError("同根重复编号或跨类型编号冲突")
                on_bar.add(identity)
                if kind == "events":
                    if (identity in index.kinds or item.get("time") != stamp
                            or item.get("direction") not in ("TOP", "BOTTOM")):
                        raise ValueError("事件编号、日期或方向错误")
                    for key in ("type", "route"):
                        _text(item.get(key), key)
                elif item.get("observedThrough") != stamp:
                    raise ValueError("历史或等待更新日期错误")
                index.kinds[identity] = kind
                index.first.setdefault(identity, stamp)
                index.records[kind][identity] = item
        _check_links(group, index, stamp)
        for event in values["events"]:
            if event["type"] != "RESEARCH_HISTORICAL_WITHDRAWAL":
                index.origins[event["id"]] = _origin(event, decision, index)
        _history_links(index, values, stamp)
        for event in values["events"]:
            if event["type"] == "RESEARCH_HISTORICAL_WITHDRAWAL":
                index.origins[event["id"]] = _origin(event, decision, index)
    return index


def _event_key(event: dict, index: _Index) -> tuple:
    reference = event.get("eventReference")
    return (event["time"], event["direction"], event["type"], event["route"],
            reference.get("startTime") if reference else None,
            reference.get("endTime") if reference else None, index.origins[event["id"]])


def _pairs(left: _Index, right: _Index, check):
    mappings, details = ({}, {}), []
    indexes = (left, right)
    ambiguous = (set(), set())

    def bind(a, b, kind, basis):
        check()
        if a in mappings[0] or b in mappings[1]:
            raise ValueError("同一记录发生多义对应")
        token = f"{kind}:{len(details)}"
        mappings[0][a] = mappings[1][b] = token
        record = left.records[kind][a]
        if kind == "events":
            direction, origin = record["direction"], left.origins[a]
        elif kind == "rearmRecords":
            direction, origin = "BOTTOM", record["segmentStart"]
        else:
            structure = left.structure_for_history[a]
            direction, origin = left.records["events"][structure]["direction"], left.origins[structure]
        details.append({"kind": kind, "r2Id": a, "r4Id": b, "status": "matched", "basis": basis,
                        "direction": direction, "sourceSegmentStart": origin,
                        "reason": "同日业务记录唯一对应"})

    def unique(kind, key, accept=lambda a, b: True):
        groups = ({}, {})
        for side in (0, 1):
            for identity, record in indexes[side].records[kind].items():
                check()
                if identity not in mappings[side]:
                    value = key(record, side)
                    if value is not None:
                        groups[side].setdefault(value, []).append(identity)
        for value in sorted(groups[0].keys() & groups[1].keys(), key=repr):
            a, b = groups[0][value], groups[1][value]
            if len(a) == len(b) == 1 and accept(a[0], b[0]):
                bind(a[0], b[0], kind, value)
            elif len(a) != 1 or len(b) != 1:
                ambiguous[0].update(a)
                ambiguous[1].update(b)

    def initial(event, side):
        if event["type"] != "STRUCTURE" and any(event.get(link) for link in
                ("relatedTopHistoryId", "relatedBottomHistoryId", "relatedRearmId")):
            return None
        return _event_key(event, indexes[side])

    unique("events", initial)
    for item in list(details):
        check()
        event_a, event_b = left.records["events"][item["r2Id"]], right.records["events"][item["r4Id"]]
        if event_a["type"] == "STRUCTURE":
            kind, link = ("histories", "relatedTopHistoryId") if event_a["direction"] == "TOP" else (
                "bottomHistories", "relatedBottomHistoryId")
            bind(event_a[link], event_b[link], kind, ("original_structure", item["r2Id"], item["r4Id"]))

    def waiting(record, side):
        structure = mappings[side].get(record["structureEventId"])
        return None if structure is None else (structure, record["disappearedAt"], record["segmentStart"])

    unique("rearmRecords", waiting)

    def related(event, side):
        links = []
        for field_name in ("relatedTopHistoryId", "relatedBottomHistoryId", "relatedRearmId"):
            identity = event.get(field_name)
            if identity is not None:
                if identity not in mappings[side]:
                    return None
                links.append((field_name, mappings[side][identity]))
        return (*_event_key(event, indexes[side]), tuple(links)) if links else None

    unique("events", related)
    for side, name in enumerate(("r2", "r4")):
        for kind in _KINDS:
            for identity in indexes[side].records[kind]:
                check()
                if identity not in mappings[side]:
                    multiple = identity in ambiguous[side]
                    details.append({"kind": kind, "r2Id": identity if side == 0 else None,
                                    "r4Id": identity if side == 1 else None,
                                    "status": "ambiguous" if multiple else name + "_only", "basis": None,
                                    "reason": "存在多个候选，不强行对应" if multiple else "未找到同日唯一业务记录"})
    return mappings, details


def _normal(value, mappings, side, key=None):
    if isinstance(value, dict):
        return {name: _normal(item, mappings, side, name) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normal(item, mappings, side) for item in value]
    if value is not None and (key == "id" or key in _LINKS):
        return mappings[side].get(value, f"unmatched:{side}:{value}")
    return value


def _cause(row, mappings, prior, field_name):
    a, b = row["r2"]["decision"], row["r4"]["decision"]
    before_equal = _normal(a["before"], mappings, 0) == _normal(b["before"], mappings, 1)
    if not before_equal and prior is not None:
        return "prior_difference", "进入本根前状态或参照已经不同，可能是此前差异的后续影响", prior
    if before_equal and a["rawSign"] == b["rawSign"] == 0:
        return "current_rule", "本根为真实零柱，两组零柱处理不同", None
    if before_equal and field_name.startswith("decision.referenceChecks"):
        return "current_rule", "本日实际参照检查的顺序或结果不同", None
    if before_equal and a["referenceChecks"] != b["referenceChecks"]:
        if a.get("selectedReference") != b.get("selectedReference"):
            return "current_rule", "本日实际选择的参照不同", None
    return "unknown", "尚不能确定该字段差异的直接原因", None


def compare_records(rows, *, start_date, end_date, check):
    """Validate full-prefix relations, then report only the requested date range."""
    if (not isinstance(rows, (list, tuple)) or _day(start_date) != start_date
            or _day(end_date) != end_date or start_date > end_date):
        raise ValueError("比较记录或报告日期错误")
    previous = None
    for row in rows:
        check()
        if not isinstance(row, dict) or not {"time", "input", "r2", "r4"} <= set(row):
            raise ValueError("缺少两组逐根记录")
        stamp = row["time"]
        if _day(stamp) > end_date or (previous is not None and stamp <= previous):
            raise ValueError("比较记录日期倒序、重复或晚于截止日")
        if not isinstance(row["input"], dict):
            raise ValueError("缺少原始输入")
        previous = stamp
    left, right = (_build_index(rows, side, check) for side in ("r2", "r4"))
    mappings, pairs = _pairs(left, right, check)
    differences, dates, counts = [], set(), Counter()
    prefix_first = first = None
    event_counts = (Counter(), Counter())
    for row in rows:
        check()
        stamp, a, b = row["time"], row["r2"], row["r4"]
        inside = start_date <= _day(stamp) <= end_date
        fields = []
        for name in sorted(_POINT_KEYS - {"time", "close", "dif", "dea", "hist"}):
            category = "referenceDecision" if name == "activeReference" else (
                "historyWaiting" if name.startswith("pending") else "ordinaryState")
            fields.append(("point." + name, a["point"][name], b["point"][name], category))
        for kind in _KINDS:
            fields.append((kind, a[kind], b[kind], "events" if kind == "events" else "historyWaiting"))
        for name in ("wave", "referenceChecks", "selectedReference", "turn", "branch"):
            fields.append(("decision." + name, a["decision"][name], b["decision"][name], "referenceDecision"))
        changed = []
        for field_name, x, y, category in fields:
            check()
            name = field_name.rsplit(".", 1)[-1]
            if _normal(x, mappings, 0, name) == _normal(y, mappings, 1, name):
                continue
            effect, reason, prior = _cause(row, mappings, prefix_first, field_name)
            changed.append({"time": stamp, "field": field_name, "r2": deepcopy(x), "r4": deepcopy(y),
                            "r2Decision": a["decision"], "r4Decision": b["decision"],
                            "effect": effect, "reason": reason, "previousDifferenceAt": prior,
                            "category": category})
        if changed:
            if prefix_first is None:
                prefix_first = stamp
            if inside:
                first = first or stamp
                dates.add(_day(stamp))
                differences.extend(changed)
                counts.update(item["category"] for item in changed)
        if inside:
            for side, group in enumerate((a, b)):
                event_counts[side].update(event["type"] for event in group["events"])
    check()
    return {"differences": differences, "idPairs": pairs,
            "summary": {"r2EventCounts": dict(event_counts[0]), "r4EventCounts": dict(event_counts[1]),
                        "differenceDates": sorted(dates), "differenceDateCount": len(dates),
                        "differenceCounts": dict(counts), "prefixFirstDifference": prefix_first,
                        "firstDifference": first}}
