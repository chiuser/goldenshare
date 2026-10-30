"""Validate supplied version-specific facts and describe them; never run a detector.

Contracts are taken from da4a97ee's comparison/observer and c6a845fe3's
XxmStep. Historical expectations are the independently recorded study §16.
No market reader, calculator, product import, persistence or second replay.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
import math


_OLD_KINDS = ("events", "histories", "bottomHistories", "rearmRecords")
_LINKS = {
    "relatedTopHistoryId": "histories", "pendingTopHistoryId": "histories",
    "relatedBottomHistoryId": "bottomHistories", "pendingBottomHistoryId": "bottomHistories",
    "relatedRearmId": "rearmRecords", "pendingRearmId": "rearmRecords", "rearmId": "rearmRecords",
    "bottomHistoryId": "bottomHistories", "structureEventId": "events",
    "activeStructureId": "structures", "relatedStructureId": "structures", "structureId": "structures",
}
_REF_FIELDS = {"startTime", "endTime", "price", "dif"}
_REF_NAMES = {"activeReference", "eventReference", "originalReference", "reference", "referenceAfter", "selected"}
_CATEGORIES = ("labels", "states", "references", "structures", "decisions")
_RULES = {
    "labels": "正式LLD§3、§14：首次当根价格/DIF；1%形成/回转；原参照突破；真实反色",
    "states": "正式LLD§3、§14：保持钝化、结构考核、回钝化及直接消失",
    "references": "正式LLD§3：近B优先、近处失效后当根检查远A，本轮突破记忆",
    "structures": "正式LLD§3：结构考核及首次真实反色锁死；旧历史/等待按旧含义保留",
    "decisions": "专项LLD§7：仅保留实际执行的检查，未检查不猜测通过与否",
}


def _day(value):
    if type(value) is not str or len(value) != 10:
        raise ValueError("记录日期必须为YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("记录日期非法") from None
    if parsed.isoformat() != value:
        raise ValueError("记录日期不是标准日线日期")
    return value


def _text(value):
    if type(value) is not str or not value:
        raise ValueError("记录缺少非空编号或文字")
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("记录含非有限数值或bool冒充数字")
    return value


def _same_number(a, b):
    return (type(a) is type(b) and a == b
            and (a != 0 or math.copysign(1, a) == math.copysign(1, b)))


def _input_index(input_rows, check):
    if type(input_rows) not in (list, tuple) or not input_rows:
        raise ValueError("缺少不可空的原始输入")
    result, previous = {}, None
    for row in input_rows:
        check()
        if type(row) not in (tuple, list) or len(row) != 6:
            raise ValueError("原输入必须为六项标量行")
        stamp = _day(row[0])
        if previous is not None and stamp <= previous:
            raise ValueError("原输入日期重复或倒序")
        if any(type(x) is not float or not math.isfinite(x) for x in row[1:5]):
            raise ValueError("原输入必须保留有限float")
        if row[1] <= 0 or row[5] is not True:
            raise ValueError("原输入必须为正收盘、已完成日线")
        result[stamp] = row
        previous = stamp
    return result


@dataclass
class _Index:
    name: str
    current: bool
    source: dict
    records: dict = field(default_factory=dict)
    kinds: dict = field(default_factory=dict)
    first: dict = field(default_factory=dict)
    origins: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)
    dates: dict = field(default_factory=dict)
    history_structure: dict = field(default_factory=dict)

    def reference(self, value, stamp, *, sign=None):
        if value is None:
            return None
        fields = _REF_FIELDS | ({"priceAt", "difAt"} if self.current else set())
        if type(value) is not dict or set(value) != fields:
            raise ValueError("参照字段与所属版本不符")
        start, end = _day(value["startTime"]), _day(value["endTime"])
        if start > end or end > stamp:
            raise ValueError("参照范围颠倒或引用未来")
        _number(value["price"])
        _number(value["dif"])
        if self.current:
            dates = (value["priceAt"], value["difAt"])
        else:
            keys = [(s, start, end, value["price"], value["dif"]) for s in ((sign,) if sign is not None else (-1, 0, 1))]
            matches = [self.dates[key] for key in keys if key in self.dates]
            if len(matches) != 1:
                raise ValueError("旧参照缺少唯一的本组原Wave极值日期")
            dates = matches[0]
        for which, at in zip((1, 2), dates):
            _day(at)
            if not start <= at <= end or at not in self.source:
                raise ValueError("参照极值日期不在已知本段")
            value_key = "price" if which == 1 else "dif"
            if not _same_number(value[value_key], self.source[at][which]):
                raise ValueError("参照极值与对应原输入不相等")
        return {**value, "priceAt": dates[0], "difAt": dates[1]}

    def wave(self, wave, stamp, *, remember=False):
        if wave is None:
            return
        fields = {"sign", "start", "end", "count", "price", "dif", "price_at", "dif_at"}
        if type(wave) is not dict or set(wave) != fields:
            raise ValueError("Wave字段错误")
        if (type(wave["sign"]) is not int or wave["sign"] not in (-1, 0, 1)
                or type(wave["count"]) is not int or wave["count"] < 1):
            raise ValueError("Wave方向或根数错误")
        start, end = _day(wave["start"]), _day(wave["end"])
        if start > end or end > stamp:
            raise ValueError("Wave范围错误或引用未来")
        for key, value_key, position in (("price_at", "price", 1), ("dif_at", "dif", 2)):
            at = _day(wave[key])
            if not start <= at <= end or at not in self.source:
                raise ValueError("Wave极值日期缺失或越界")
            _number(wave[value_key])
            if not _same_number(wave[value_key], self.source[at][position]):
                raise ValueError("Wave极值与源数据不一致")
        if remember:
            key = (wave["sign"], start, end, wave["price"], wave["dif"])
            value = (wave["price_at"], wave["dif_at"])
            if key in self.dates and self.dates[key] != value:
                raise ValueError("同一旧参照出现冲突极值日期")
            self.dates[key] = value


def _references(value, index, stamp, *, sign=None):
    found = []
    if type(value) is dict:
        direction = value.get("direction", value.get("ordinaryDirection"))
        if direction is not None:
            sign = 1 if direction == "TOP" else -1
        elif type(value.get("wave")) is dict:
            sign = value["wave"]["sign"]
        for key, item in value.items():
            if key in _REF_NAMES and item is not None:
                found.append(index.reference(item, stamp, sign=sign))
            elif key == "referenceWave":
                index.wave(item, stamp)
            else:
                child_sign = 1 if key == "histories" else -1 if key in ("bottomHistories", "rearmRecords") else sign
                found.extend(_references(item, index, stamp, sign=child_sign))
    elif type(value) in (tuple, list):
        for item in value:
            found.extend(_references(item, index, stamp, sign=sign))
    return found


def _finite_tree(value):
    if type(value) in (int, float):
        _number(value)
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("记录字段名必须为文字")
            _finite_tree(item)
    elif type(value) in (tuple, list):
        for item in value:
            _finite_tree(item)
    elif value is not None and type(value) not in (str, bool):
        raise ValueError("记录含非JSON类型")


def _links(value, index, stamp):
    if type(value) is dict:
        for key, item in value.items():
            if key in _LINKS and item is not None:
                _text(item)
                if index.kinds.get(item) != _LINKS[key] or index.first[item] > stamp:
                    raise ValueError("悬挂、未来或错误类型的组内关联")
            elif type(item) in (dict, tuple, list):
                _links(item, index, stamp)
    elif type(value) in (tuple, list):
        for item in value:
            _links(item, index, stamp)


def _origin(event, decision, index):
    if event["type"] == "RESEARCH_HISTORICAL_WITHDRAWAL":
        history = event.get("relatedTopHistoryId") or event.get("relatedBottomHistoryId")
        structure = index.history_structure.get(history)
        if structure not in index.origins:
            raise ValueError("旧撤销无法关联原结构")
        return index.origins[structure]
    wave = decision["before"].get("wave") if event["route"] in ("color_flip", "dif_break_on_flip") else decision["wave"]
    if not wave or wave["sign"] != (1 if event["direction"] == "TOP" else -1):
        raise ValueError("事件缺少原方向色段")
    return wave["start"]


def _new_structures(group, index, stamp):
    changed = {"status", "lockedAt", "disappearedAt", "disappearanceReason"}
    for record in group["structures"]:
        if set(record) != {"id", "direction", "structureEventId", "formedAt", "formationRoute", "originSegmentStart",
                          "originalReference", "priceExtreme", "priceExtremeAt", "status", "lockedAt", "disappearedAt", "disappearanceReason"}:
            raise ValueError("新结构字段不完整或含多余字段")
        identity = record["id"]
        formed = index.records[record["structureEventId"]]
        if (formed["type"] != "STRUCTURE" or formed["time"] != record.get("formedAt")
                or formed["route"] != record.get("formationRoute")
                or formed["direction"] != record.get("direction")
                or formed.get("relatedStructureId") != identity
                or formed.get("eventReference") != record.get("originalReference")
                or record.get("originSegmentStart") != index.origins[formed["id"]]):
            raise ValueError("新结构原形成事实关联错误")
        status = record.get("status")
        if status not in ("ASSESSING", "LOCKED", "DISAPPEARED"):
            raise ValueError("新结构状态错误")
        previous = index.records.get(identity)
        if previous is not None:
            if previous["status"] != "ASSESSING" or status == "ASSESSING":
                raise ValueError("新结构终态回退或重复更新")
            if any(previous.get(k) != record.get(k) for k in set(record) - changed):
                raise ValueError("新结构更新改写原形成事实")
        elif index.first[identity] != record.get("formedAt"):
            raise ValueError("新结构首次出现日错误")
        elif status != ("LOCKED" if record["formationRoute"] == "color_flip" else "ASSESSING"):
            raise ValueError("新结构首次状态与形成路径不一致")
        if status == "ASSESSING":
            if any(record.get(k) is not None for k in ("lockedAt", "disappearedAt", "disappearanceReason")):
                raise ValueError("考核结构不能预写终态")
        elif status == "LOCKED":
            if record.get("lockedAt") != stamp or record.get("disappearedAt") is not None or record.get("disappearanceReason") is not None:
                raise ValueError("锁死时点错误")
        elif (record.get("disappearedAt") != stamp or record.get("lockedAt") is not None
              or record.get("disappearanceReason") not in ("dif_return", "reference_dif_break")):
            raise ValueError("结构消失时点/原因错误")
        if status == "DISAPPEARED":
            matches = [e for e in group["events"] if e.get("relatedStructureId") == identity]
            if (len(matches) != 1 or matches[0]["type"] not in ("DULL", "CANCEL")
                    or (matches[0]["route"] == "dif_return") != (record["disappearanceReason"] == "dif_return")):
                raise ValueError("新结构消失与当根实际事件不对应")
        extreme_at = _day(record["priceExtremeAt"])
        if (not record["originSegmentStart"] <= extreme_at <= record["formedAt"]
                or extreme_at not in index.source or not _same_number(record["priceExtreme"], index.source[extreme_at][1])):
            raise ValueError("结构形成价格极值与原输入不对应")


def _old_histories(group, index, stamp):
    for event in group["events"]:
        if event["type"] != "STRUCTURE":
            continue
        link = "relatedTopHistoryId" if event["direction"] == "TOP" else "relatedBottomHistoryId"
        history_id = event.get(link)
        history = next((r for r in group["histories"] + group["bottomHistories"] if r["id"] == history_id), None)
        if (history is None or history.get("confirmedAt") != stamp
                or history.get("confirmationRoute") != event["route"]
                or history.get("originalReference") != event.get("eventReference")):
            raise ValueError("旧结构缺少对应历史或原事实不一致")
        if history_id in index.history_structure and index.history_structure[history_id] != event["id"]:
            raise ValueError("旧历史错误关联另一个结构")
        index.history_structure[history_id] = event["id"]
    for kind in ("histories", "bottomHistories"):
        for record in group[kind]:
            event_id = index.history_structure.get(record["id"])
            if event_id is None:
                raise ValueError("旧历史无原结构")
            event = index.records[event_id]
            if (record.get("confirmedAt") != event["time"] or record.get("confirmationRoute") != event["route"]
                    or record.get("originalReference") != event.get("eventReference")
                    or (kind == "bottomHistories" and record.get("structureEventId") != event_id)):
                raise ValueError("旧历史改写原关联")
            if record.get("status") not in ("PENDING", "ENDED"):
                raise ValueError("旧历史状态错误")
            prior = index.records.get(record["id"])
            if prior is not None and prior.get("status") == "ENDED":
                raise ValueError("已结束的旧历史被再次改写")
            price_field, date_field = ("pricePeak", "pricePeakAt") if kind == "histories" else ("priceLow", "priceLowAt")
            price_at = _day(record.get(date_field))
            if (price_at > record["confirmedAt"] or price_at not in index.source
                    or not _same_number(record.get(price_field), index.source[price_at][1])):
                raise ValueError("旧历史形成价格及日期与输入不对应")
            immutable = {"confirmedAt", "confirmationRoute", "originalReference", price_field, date_field}
            if kind == "bottomHistories":
                immutable |= {"structureEventId", "originSegmentStart"}
            if prior is not None and any(prior.get(k) != record.get(k) for k in immutable):
                raise ValueError("旧历史更新改写原形成事实")
            if record["status"] == "PENDING":
                if record.get("endedAt") is not None or record.get("endReason") is not None:
                    raise ValueError("旧待观察历史不能预写结束")
            elif record.get("endedAt") != stamp or not record.get("endReason"):
                raise ValueError("旧历史结束日期/原因错误")
    for event in group["events"]:
        if event["type"] == "RESEARCH_HISTORICAL_WITHDRAWAL":
            target = event.get("relatedTopHistoryId") or event.get("relatedBottomHistoryId")
            matches = [r for r in group["histories"] + group["bottomHistories"] if r["id"] == target]
            if (len(matches) != 1 or matches[0]["status"] != "ENDED"
                    or matches[0]["endReason"] != "historical_price_break"
                    or matches[0]["originalReference"] != event.get("eventReference")):
                raise ValueError("旧价格撤销没有对应的原历史结束事实")
    for record in group["rearmRecords"]:
        event = index.records[record["structureEventId"]]
        if (event["type"] != "STRUCTURE" or event["direction"] != "BOTTOM"
                or event.get("relatedBottomHistoryId") != record["bottomHistoryId"]
                or event["time"] != record.get("structureConfirmedAt")
                or record.get("segmentStart") != index.origins[event["id"]]):
            raise ValueError("旧等待与原结构不对应")
        if record.get("status") not in ("WAITING", "REACTIVATED", "INVALIDATED", "SEGMENT_ENDED"):
            raise ValueError("旧等待状态错误")
        if index.first[record["id"]] != record.get("disappearedAt"):
            raise ValueError("旧等待首次出现日错误")
        if index.first[record["id"]] == stamp:
            matches = [e for e in group["events"] if e.get("relatedRearmId") == record["id"]
                       and e["type"] == "STRUCTURE_DISAPPEARED"]
            if len(matches) != 1 or matches[0].get("relatedBottomHistoryId") != record["bottomHistoryId"]:
                raise ValueError("旧等待缺少结构消失事件")


def _index_group(rows, name, source, check, *, current=False):
    index = _Index(name, current, source)
    kind_names = ("events", "structures") if current else _OLD_KINDS
    for raw in rows:
        check()
        stamp = raw["time"]
        group = raw if current else raw[name]
        required = {"time", "point", "events", "structures", "decision"} if current else {
            "point", "events", "histories", "bottomHistories", "rearmRecords", "decision"}
        if type(group) is not dict or set(group) != required:
            raise ValueError("组的逐根合同与版本不符")
        _finite_tree(group)
        point, decision = group["point"], group["decision"]
        point_fields = {"time", "close", "dif", "dea", "hist", "ordinaryState", "ordinaryDirection", "activeReference"}
        point_fields |= {"activeStructureId"} if current else {"pendingTopHistoryId", "pendingBottomHistoryId", "pendingRearmId"}
        if type(point) is not dict or set(point) != point_fields or point["time"] != stamp:
            raise ValueError("point字段或日期错误")
        if (point["ordinaryState"] not in ("NONE", "DULL", "STRUCTURE")
                or point["ordinaryDirection"] not in (None, "TOP", "BOTTOM")
                or (point["ordinaryState"] == "NONE") != (point["ordinaryDirection"] is None)
                or (point["ordinaryState"] != "NONE" and point["activeReference"] is None)):
            raise ValueError("普通状态/方向/活动参照不一致")
        for pos, field_name in enumerate(("close", "dif", "dea", "hist"), 1):
            if not _same_number(point[field_name], source[stamp][pos]):
                raise ValueError("计算点与同次原float输入不同")
        needed = {"before", "rawSign", "wave", "referenceChecks", "turn", "branch", "reason"}
        needed |= {"time", "referenceAfter", "selectionCalls", "switched", "structureId", "structureStatus"} if current else {"selectedReference", "countMeaning"}
        if type(decision) is not dict or set(decision) != needed or type(decision["before"]) is not dict:
            raise ValueError("判断依据缺字段或版本错误")
        before_fields = {"state", "reference", "wave"} | ({"previousDif", "activeStructureId"} if current else {"previous", "pendingRearm"})
        if set(decision["before"]) != before_fields:
            raise ValueError("进入本根前记录字段错误")
        turn = decision["turn"]
        if (type(turn) is not dict or set(turn) != {"previousDif", "currentDif", "threshold", "referenceBroken", "checked", "reason"}
                or type(turn["checked"]) is not bool or turn["referenceBroken"] is not None and type(turn["referenceBroken"]) is not bool
                or not _same_number(turn["currentDif"], point["dif"])):
            raise ValueError("相邻转折观察合同错误")
        for field_name in ("previousDif", "threshold"):
            if turn[field_name] is not None:
                _number(turn[field_name])
        if type(decision["rawSign"]) is not int or decision["rawSign"] != (point["hist"] > 0) - (point["hist"] < 0):
            raise ValueError("真实柱色观察错误")
        index.wave(decision["wave"], stamp)
        index.wave(decision["before"].get("wave"), stamp)
        if type(decision["referenceChecks"]) is not list:
            raise ValueError("缺少实际参照检查记录")
        for observed in decision["referenceChecks"]:
            check_fields = {"stage", "candidate", "wave", "checked", "pricePassed", "difPassed", "reason"}
            check_fields |= {"referenceBroken"} if current else {"reference"}
            if type(observed) is not dict or set(observed) != check_fields or type(observed.get("checked")) is not bool:
                raise ValueError("参照检查标志非法")
            if observed["candidate"] not in ("A", "B"):
                raise ValueError("参照候选名称错误")
            index.wave(observed.get("wave"), stamp, remember=not current)
            for field_name in ("pricePassed", "difPassed"):
                if observed.get(field_name) is not None and type(observed[field_name]) is not bool:
                    raise ValueError("参照检查结论必须为bool或未检查")
                if not observed["checked"] and observed.get(field_name) is not None:
                    raise ValueError("未检查的条件不得伪造结果")
        _references(group, index, stamp)
        updates = []
        for kind in kind_names:
            if type(group[kind]) is not list:
                raise ValueError("记录集合必须为列表")
            seen = set()
            for record in group[kind]:
                if type(record) is not dict:
                    raise ValueError("业务记录必须为字典")
                identity = _text(record.get("id"))
                if identity in seen or identity in index.kinds and index.kinds[identity] != kind:
                    raise ValueError("同日重复或跨类型编号冲突")
                seen.add(identity)
                if kind == "events":
                    event_fields = {"id", "time", "direction", "type", "route", "fromState", "eventReference"}
                    event_fields |= {"relatedStructureId"} if current else {"relatedTopHistoryId", "relatedBottomHistoryId", "relatedRearmId"}
                    if set(record) != event_fields:
                        raise ValueError("事件字段合同错误")
                    if identity in index.kinds or record.get("time") != stamp or record.get("direction") not in ("TOP", "BOTTOM"):
                        raise ValueError("事件日期、方向或重复编号错误")
                    _text(record.get("type")); _text(record.get("route"))
                elif not current and record.get("observedThrough") != stamp:
                    raise ValueError("旧历史/等待更新日错误")
                index.kinds[identity] = kind
                index.first.setdefault(identity, stamp)
                updates.append((identity, record))
                if kind == "events":
                    index.records[identity] = record
        _links(group, index, stamp)
        for event in group["events"]:
            if event["type"] != "RESEARCH_HISTORICAL_WITHDRAWAL":
                index.origins[event["id"]] = _origin(event, decision, index)
        if current:
            _new_structures(group, index, stamp)
        else:
            _old_histories(group, index, stamp)
        for event in group["events"]:
            if event["type"] == "RESEARCH_HISTORICAL_WITHDRAWAL":
                index.origins[event["id"]] = _origin(event, decision, index)
        for identity, record in updates:
            index.records[identity] = record
            kind = index.kinds[identity]
            if kind == "events":
                token = (kind, stamp, record["direction"], record["type"], record["route"], index.origins[identity])
            elif kind in ("histories", "bottomHistories"):
                origin = index.records[index.history_structure[identity]]
                token = (kind, index.first[identity], origin["direction"], origin["route"], index.origins[origin["id"]])
            elif kind == "rearmRecords":
                token = (kind, index.first[identity], "BOTTOM", record["segmentStart"])
            else:
                token = (kind, record["formedAt"], record["direction"], record["formationRoute"], record["originSegmentStart"])
            index.tokens[identity] = token
        if current:
            if (decision["time"] != stamp or decision["referenceAfter"] != point["activeReference"]
                    or decision["structureId"] != (group["structures"][-1]["id"] if group["structures"] else None)
                    or decision["structureStatus"] != (group["structures"][-1]["status"] if group["structures"] else None)):
                raise ValueError("新判断依据与实际点或结构不相符")
            active = point["activeStructureId"]
            if (point["ordinaryState"] == "STRUCTURE") != (active is not None):
                raise ValueError("新结构状态与活动记录不一致")
            if active is not None and index.records[active]["status"] != "ASSESSING":
                raise ValueError("活动point不能引用终态结构")
        else:
            for key in ("pendingTopHistoryId", "pendingBottomHistoryId", "pendingRearmId"):
                identity = point[key]
                if identity is not None and index.records[identity]["status"] != ("WAITING" if key == "pendingRearmId" else "PENDING"):
                    raise ValueError("旧point只能引用仍在观察或等待的记录")
    return index


def _validate_groups(old_result, new_result, input_rows, check):
    source = _input_index(input_rows, check)
    if type(old_result) is not dict or set(old_result) != {"metadata", "rows", "summary"}:
        raise ValueError("旧结果顶层字段错误")
    if type(old_result["metadata"]) is not dict or type(old_result["summary"]) is not dict:
        raise ValueError("旧结果身份或摘要错误")
    if type(old_result["rows"]) is not list or len(old_result["rows"]) != len(source):
        raise ValueError("旧组根数错误")
    for stamp, row in zip(source, old_result["rows"]):
        check()
        if type(row) is not dict or set(row) != {"time", "input", "r2", "r4"} or row["time"] != stamp:
            raise ValueError("旧组日期、重复或行合同错误")
        raw = row["input"]
        expected = dict(zip(("time", "close", "dif", "dea", "hist", "completed"), source[stamp]))
        if type(raw) is not dict or set(raw) != set(expected) or raw["time"] != stamp or raw["completed"] is not True:
            raise ValueError("旧组原输入合同错误")
        if any(not _same_number(raw[k], expected[k]) for k in ("close", "dif", "dea", "hist")):
            raise ValueError("旧组使用的原输入不同")
    indexes = {name: _index_group(old_result["rows"], name, source, check) for name in ("r2", "r4")}
    if new_result is not None:
        if (type(new_result) is not dict or set(new_result) != {"identity", "rows"}
                or type(new_result["identity"]) is not dict
                or type(new_result["rows"]) is not list or len(new_result["rows"]) != len(source)):
            raise ValueError("新组身份/根数合同错误")
        for stamp, row in zip(source, new_result["rows"]):
            if type(row) is not dict or row.get("time") != stamp:
                raise ValueError("新组日期重复、倒序或错误")
        indexes["currentR4"] = _index_group(new_result["rows"], "currentR4", source, check, current=True)
    return source, indexes


def _normal(value, index, *, key=None):
    """IDs identify group-local links; only unique same-day business tokens compare."""
    if type(value) is dict:
        return {k: _normal(v, index, key=k) for k, v in value.items() if k not in ("reason", "countMeaning")}
    if type(value) in (list, tuple):
        return [_normal(v, index) for v in value]
    if value is not None and (key == "id" or key in _LINKS):
        token = index.tokens[value]
        if sum(token == other for other in index.tokens.values()) > 1:
            return ("ambiguous", index.name, value)
        return token
    return value


def _validate_event_counts(old_result, expected_counts, check):
    """Check ledger counts and its producer summary against independent counts."""
    checks = []
    for name in ("r2", "r4"):
        check()
        count = dict(Counter(e["type"] for row in old_result["rows"] for e in row[name]["events"]))
        stated = old_result["summary"].get(name + "EventCounts")
        if type(stated) is not dict or any(type(v) is not int or v < 0 for v in stated.values()):
            raise ValueError("旧基准事件摘要必须为非负整数计数")
        for suffix, actual in (("EventCounts", count), ("SummaryEventCounts", stated)):
            if actual != expected_counts:
                raise ValueError("旧基准不复现：" + name + suffix)
            checks.append({"name": name + suffix, "expected": expected_counts, "actual": actual})
    return checks


def validate_baseline(old_result, *, input_rows, check):
    """Reject a changed real-history baseline before the new worker is started."""
    source, indexes = _validate_groups(old_result, None, input_rows, check)
    checks = []

    def expect(name, actual, expected):
        check()
        if actual != expected:
            raise ValueError("旧基准不复现：" + name)
        checks.append({"name": name, "expected": expected, "actual": actual})

    expect("inputCount", len(source), 922)
    expect("firstDate", next(iter(source)), "2023-01-03")
    expect("lastDate", next(reversed(source)), "2026-10-27")
    summary = old_result["summary"]
    expected_counts = {"DULL": 30, "STRUCTURE": 17, "CANCEL": 12, "RESEARCH_HISTORICAL_WITHDRAWAL": 7}
    checks.extend(_validate_event_counts(old_result, expected_counts, check))
    active, events = 0, 0
    by_date = {row["time"]: row for row in old_result["rows"]}
    for row in old_result["rows"]:
        check()
        a, b = row["r2"], row["r4"]
        ordinary = lambda g: [(e["type"], e["direction"], e["route"]) for e in g["events"]]
        if ordinary(a) != ordinary(b) or any(a["point"][k] != b["point"][k] for k in ("ordinaryState", "ordinaryDirection")):
            raise ValueError("旧基准逐日标签或普通状态不一致")
        active += a["point"]["activeReference"] != b["point"]["activeReference"]
        events += _normal(a["events"], indexes["r2"]) != _normal(b["events"], indexes["r4"])
    expect("activeReferenceDifferenceDays", active, 24)
    expect("eventRecordDifferenceDays", events, 13)
    if type(summary.get("differenceDateCount")) is not int:
        raise ValueError("旧基准差异日期计数必须为整数")
    expect("allDifferenceDays", summary["differenceDateCount"], 254)
    dates = summary.get("differenceDates")
    if type(dates) is not list or dates != sorted(set(dates)) or len(dates) != 254 or any(d not in source for d in dates):
        raise ValueError("旧基准差异日期列表错误")
    typical = (
        (("2023-04-14",), ("2023-01-05", "2023-02-07", 41.186, "2023-02-02"), ("2023-03-03", "2023-03-06", 24.935, "2023-03-06")),
        (("2023-08-16",), ("2023-06-26", "2023-06-30", -18.469, "2023-06-29"), ("2023-07-20", "2023-07-25", -13.515, "2023-07-24")),
        (("2024-01-10", "2024-01-16", "2024-01-17"), ("2023-10-10", "2023-10-30", -41.712, "2023-10-25"), ("2023-11-28", "2023-12-27", -32.990, "2023-12-26")),
        (("2024-07-25", "2024-07-31", "2024-08-05"), ("2024-05-23", "2024-07-01", -35.168, "2024-06-27"), ("2024-07-05", "2024-07-10", -31.670, "2024-07-08")),
        (("2024-08-06", "2024-08-13", "2024-08-14", "2024-08-15", "2024-08-22"), ("2024-07-05", "2024-07-10", -31.670, "2024-07-08"), ("2024-07-24", "2024-07-31", -30.348, "2024-07-30")),
    )
    for days, left, right in typical:
        for stamp in days:
            row = by_date.get(stamp)
            if row is None:
                raise ValueError("旧基准缺典型日期")
            for side, expected in (("r2", left), ("r4", right)):
                records = row[side]["events"]
                if len(records) != 1:
                    raise ValueError("旧基准典型事件数量不同")
                ref = indexes[side].reference(records[0]["eventReference"], stamp)
                actual = (ref["startTime"], ref["endTime"], ref["dif"], ref["difAt"])
                expect(side + ":reference:" + stamp, actual, expected)
    switches = {
        "2023-04-18": (("2023-03-03", "2023-03-06", 24.935, "2023-03-06"), ("2023-01-05", "2023-02-07", 41.186, "2023-02-02")),
        "2023-08-18": (("2023-07-20", "2023-07-25", -13.515, "2023-07-24"), ("2023-06-26", "2023-06-30", -18.469, "2023-06-29")),
        "2024-01-22": (("2023-11-28", "2023-12-27", -32.990, "2023-12-26"), ("2023-10-10", "2023-10-30", -41.712, "2023-10-25")),
    }
    for stamp, (before, after) in switches.items():
        row = by_date.get(stamp)
        if row is None:
            raise ValueError("旧基准缺少当根B到A日期")
        group = row["r4"]
        selected = group["decision"]["selectedReference"]
        expect(stamp + ":events", group["events"], [])
        expect(stamp + ":state", group["point"]["ordinaryState"], "DULL")
        if selected is None or selected.get("action") != "rescue" or selected.get("startedAt") != stamp:
            raise ValueError("旧基准当根参照切换没有保留")
        for name, value, expected in (("before", group["decision"]["before"]["reference"], before),
                                      ("after", group["point"]["activeReference"], after)):
            ref = indexes["r4"].reference(value, stamp)
            actual = (ref["startTime"], ref["endTime"], ref["dif"], ref["difAt"])
            expect(stamp + ":switch:" + name, actual, expected)
        if selected["reference"] != group["point"]["activeReference"]:
            raise ValueError("切换后的活动参照与选择观察不一致")
    for stamp in ("2023-04-18", "2023-04-19"):
        for side in ("r2", "r4"):
            expect(side + ":retained:" + stamp, by_date[stamp][side]["point"]["ordinaryState"], "DULL")
            expect(side + ":noEvent:" + stamp, by_date[stamp][side]["events"], [])
    return {"passed": True, "checks": checks}


def _views(group, index, stamp):
    point, decision = group["point"], group["decision"]
    references = {"active": index.reference(point["activeReference"], stamp),
                  "events": [index.reference(e.get("eventReference"), stamp) for e in group["events"]]}
    if index.current:
        structures = {"structures": _normal(group["structures"], index)} if group["structures"] else None
    else:
        structures = {k: _normal(group[k], index) for k in _OLD_KINDS[1:] if group[k]} or None
    checks = []
    for item in decision["referenceChecks"]:
        checks.append({k: item.get(k) for k in ("stage", "candidate", "wave", "checked", "pricePassed", "difPassed", "referenceBroken")})
    decisions = {"wave": decision["wave"], "referenceChecks": checks,
                 "turn": {k: v for k, v in decision["turn"].items() if k != "reason"},
                 "branch": decision["branch"]}
    return {
        "labels": [(e["type"], e["direction"], e["route"]) for e in group["events"] if e["type"] != "RESEARCH_HISTORICAL_WITHDRAWAL"],
        "states": (point["ordinaryState"], point["ordinaryDirection"]),
        "references": references, "structures": structures, "decisions": decisions,
    }


def compare_fact_groups(old_result, new_result, *, input_rows, check):
    """Compare the supplied full prefix; retain native structure meanings."""
    source, indexes = _validate_groups(old_result, new_result, input_rows, check)
    indexes["historyR4"] = indexes.pop("r4")
    difference_days = []
    category_days = {name: [] for name in _CATEGORIES}
    event_counts = {name: Counter() for name in indexes}
    for n, stamp in enumerate(source):
        check()
        old = old_result["rows"][n]
        groups = {"r2": old["r2"], "historyR4": old["r4"], "currentR4": new_result["rows"][n]}
        views = {name: _views(group, indexes[name], stamp) for name, group in groups.items()}
        for name, group in groups.items():
            event_counts[name].update(event["type"] for event in group["events"])
        changes = []
        for category in _CATEGORIES:
            differing = []
            for a, b in (("historyR4", "currentR4"), ("r2", "currentR4"), ("r2", "historyR4")):
                if views[a][category] != views[b][category]:
                    differing.append([a, b])
            if not differing:
                continue
            category_days[category].append(stamp)
            changes.append({"category": category, "field": category, "comparedGroups": differing,
                            "ruleSource": _RULES[category],
                            "explanation": ("实际事件类型/方向/路径不同，按当日分别列出，不跨日强配" if category == "labels" else
                                            "实际活动或事件原参照不同，保留各自价格/DIF与发生日" if category == "references" else
                                            "旧历史/等待与新结构考核/锁死分别保留，不能直接互相改名" if category == "structures" else
                                            "实际记录不同，当前证据不足以单独确定其直接原因，待核"),
                            "pendingReview": True})
        if changes:
            presented = {}
            for name, group in groups.items():
                # Original facts are shared read-only, not copied into a second ledger.
                presented[name] = {k: v for k, v in group.items() if k != "time"}
                presented[name]["references"] = views[name]["references"]
            difference_days.append({"time": stamp, "input": dict(zip(("time", "close", "dif", "dea", "hist", "completed"), source[stamp])),
                                    "groups": presented, "changes": changes})
    check()
    dates = [day["time"] for day in difference_days]
    return {"summary": {"differenceDateCount": len(dates), "differenceDates": dates,
                        "firstDifference": dates[0] if dates else None,
                        "categories": {name: {"dateCount": len(days), "dates": days,
                                               "firstDifference": days[0] if days else None}
                                       for name, days in category_days.items()},
                        "eventCounts": {name: dict(counts) for name, counts in event_counts.items()}},
            "differenceDays": difference_days}


def _reference_text(ref):
    if ref is None:
        return "无活动参照"
    return (f"{ref['startTime']}—{ref['endTime']}；收盘极值{ref['price']}（{ref['priceAt']}）；"
            f"DIF极值{ref['dif']}（{ref['difAt']}）")


def format_report(result, *, check):
    """Return text prepared inside the caller's original deadline; no printing."""
    check()
    summary = result["summary"]
    lines = ["上证日线历史r2、历史r4与修订后r4识别对比", "执行范围及三个固定版本：" + str(result["metadata"]),
             f"差异日期共{summary['differenceDateCount']}天；首次{summary['firstDifference'] or '无'}",
             "差异日期：" + ("、".join(summary["differenceDates"]) or "无"),
             "三组事件数量：" + str(summary["eventCounts"]),
             "原r2及历史r4是对照材料；差异不等于错误，不据此评价策略收益或软件一致性。"]
    states = {"NONE": "无钝化或结构", "DULL": "钝化", "STRUCTURE": "结构"}
    for row in result["differenceDays"]:
        check()
        raw = row["input"]
        lines.append(f"\n{row['time']}：收盘{raw['close']}；DIF{raw['dif']}；DEA{raw['dea']}；柱{raw['hist']}")
        for name, group in row["groups"].items():
            point = group["point"]
            events = "、".join(e["direction"] + "/" + e["type"] + "/" + e["route"] for e in group["events"]) or "无新事件"
            lines.append(f"  {name}：{states[point['ordinaryState']]}；{point['ordinaryDirection'] or '无方向'}；{events}")
            lines.append("    活动参照：" + _reference_text(group["references"]["active"]))
            for ref in group["references"]["events"]:
                lines.append("    事件原参照：" + _reference_text(ref))
            for kind in ("histories", "bottomHistories", "rearmRecords", "structures"):
                for record in group.get(kind, ()):
                    check()
                    lines.append("    " + kind + "：" + str(record))
            decision = group["decision"]
            for observed in decision["referenceChecks"]:
                check()
                lines.append("    实际参照检查：" + str(observed))
            lines.append("    实际相邻DIF检查：" + str(decision["turn"]))
            lines.append("    当根分支：" + decision["branch"] + "；" + decision["reason"])
        for change in row["changes"]:
            lines.append("  差异：" + change["category"] + "；" + change["explanation"] + "；依据：" + change["ruleSource"])
    check()
    return "\n".join(lines)
