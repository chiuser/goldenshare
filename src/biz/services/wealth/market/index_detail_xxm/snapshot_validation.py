"""Validate independent in-memory calculation progress before publication."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any

from .types import Wave, XxmBar, XxmBottomHistory, XxmPeriod, XxmRearmRecord


_IDENTITY_FIELDS = ("specHash", "tsCode", "period", "sourceIdentity")
_SNAPSHOT_FIELDS = frozenset((*_IDENTITY_FIELDS, "processed", "wave", "history", "state",
                             "reference", "previous", "pending", "pendingBottomHistory", "pendingRearm"))
_WAVE_FIELDS = frozenset(Wave.__dataclass_fields__)
_BAR_FIELDS = frozenset(XxmBar.__dataclass_fields__)
_REFERENCE_FIELDS = frozenset(("startTime", "endTime", "price", "dif"))
_TOP_FIELDS = frozenset(("id", "confirmedAt", "confirmationRoute", "pricePeak", "pricePeakAt",
                         "originalReference", "status", "endedAt", "endReason", "observedThrough",
                         "ageBars", "negativeBars", "zeroBars", "colorChanges"))


@dataclass(slots=True)
class ParsedXxmSnapshot:
    wave: Wave | None
    history: dict[int, list[Wave]]
    state: str
    reference: Wave | None
    previous: XxmBar | None
    pending: dict[str, Any] | None
    pending_bottom_history: XxmBottomHistory | None
    pending_rearm: XxmRearmRecord | None
    processed: int


def _fields(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"Invalid {label} snapshot fields")
    return value


def _number(value: Any, *, positive: bool = False) -> None:
    if (type(value) not in (int, float) or not math.isfinite(value)
            or (positive and value <= 0)):
        raise ValueError("Invalid snapshot numeric value")


def _integer(value: Any, *, minimum: int, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError("Invalid snapshot integer")


def _text(value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid snapshot text")


def _time(value: Any, period: XxmPeriod, upper: str | None = None) -> None:
    XxmBar(value, 1., 0., 0., 0.).validate(period)
    if upper is not None and value > upper:
        raise ValueError("Snapshot contains a future time")


def _wave(value: Any, *, period: XxmPeriod, processed: int, upper: str) -> Wave:
    raw = _fields(value, _WAVE_FIELDS, "Wave")
    _integer(raw["sign"], minimum=-1, maximum=1)
    if raw["sign"] == 0:
        raise ValueError("A logical Wave must be red or green")
    _integer(raw["count"], minimum=1, maximum=processed)
    _number(raw["price"], positive=True)
    _number(raw["dif"])
    for key in ("start", "end", "price_at", "dif_at"):
        _time(raw[key], period, upper)
    if not (raw["start"] <= raw["price_at"] <= raw["end"]
            and raw["start"] <= raw["dif_at"] <= raw["end"]):
        raise ValueError("Invalid Wave snapshot chronology")
    return Wave(**raw)


def _reference(value: Any, *, period: XxmPeriod, upper: str) -> None:
    raw = _fields(value, _REFERENCE_FIELDS, "historical reference")
    _number(raw["price"], positive=True)
    _number(raw["dif"])
    _time(raw["startTime"], period, upper)
    _time(raw["endTime"], period, upper)
    if raw["startTime"] > raw["endTime"]:
        raise ValueError("Invalid historical reference chronology")


def _pending_status(raw: dict[str, Any], status: str) -> None:
    if raw["status"] != status or raw["endedAt"] is not None or raw["endReason"] is not None:
        raise ValueError("Invalid active snapshot record")


def _top(value: Any, *, period: XxmPeriod, previous: XxmBar, processed: int) -> dict[str, Any]:
    raw = _fields(value, _TOP_FIELDS, "TOP history")
    _text(raw["id"])
    _pending_status(raw, "PENDING")
    if raw["confirmationRoute"] not in ("dif_turn", "color_flip"):
        raise ValueError("Invalid TOP confirmation route")
    _number(raw["pricePeak"], positive=True)
    for key in ("confirmedAt", "pricePeakAt", "observedThrough"):
        _time(raw[key], period, previous.time)
    _reference(raw["originalReference"], period=period, upper=previous.time)
    if not (raw["pricePeakAt"] <= raw["confirmedAt"] <= raw["observedThrough"] == previous.time
            and raw["originalReference"]["endTime"] < raw["confirmedAt"]):
        raise ValueError("Invalid TOP snapshot chronology")
    for key in ("ageBars", "negativeBars", "zeroBars", "colorChanges"):
        _integer(raw[key], minimum=0, maximum=processed)
    if (raw["negativeBars"] + raw["zeroBars"] > raw["ageBars"]
            or raw["colorChanges"] > raw["ageBars"]):
        raise ValueError("Invalid TOP snapshot counters")
    return deepcopy(raw)


def _bottom(value: Any, *, period: XxmPeriod, previous: XxmBar, processed: int) -> XxmBottomHistory:
    raw = _fields(value, frozenset(XxmBottomHistory.__annotations__), "BOTTOM history")
    for key in ("id", "structureEventId"):
        _text(raw[key])
    _pending_status(raw, "PENDING")
    if raw["confirmationRoute"] not in ("dif_turn", "color_flip"):
        raise ValueError("Invalid BOTTOM confirmation route")
    _number(raw["priceLow"], positive=True)
    _integer(raw["ageBars"], minimum=0, maximum=processed)
    for key in ("confirmedAt", "originSegmentStart", "priceLowAt", "observedThrough"):
        _time(raw[key], period, previous.time)
    if raw["leftOriginAt"] is not None:
        _time(raw["leftOriginAt"], period, previous.time)
    _reference(raw["originalReference"], period=period, upper=previous.time)
    if raw["observedThrough"] != previous.time:
        raise ValueError("BOTTOM history does not reach previous input")
    return deepcopy(raw)


def _rearm(value: Any, *, period: XxmPeriod, previous: XxmBar, processed: int) -> XxmRearmRecord:
    raw = _fields(value, frozenset(XxmRearmRecord.__annotations__), "rearm")
    for key in ("id", "bottomHistoryId", "structureEventId"):
        _text(raw[key])
    _pending_status(raw, "WAITING")
    if raw["direction"] != "BOTTOM" or raw["structureRoute"] != "dif_turn":
        raise ValueError("Invalid rearm direction or route")
    _number(raw["nearestPriceGate"], positive=True)
    for key in ("structureConfirmedAt", "segmentStart", "disappearedAt", "observedThrough"):
        _time(raw[key], period, previous.time)
    _wave(raw["referenceWave"], period=period, processed=processed, upper=previous.time)
    if raw["observedThrough"] != previous.time:
        raise ValueError("Rearm does not reach previous input")
    return deepcopy(raw)


def parse_xxm_snapshot(snapshot: dict[str, Any], *, expected_identity: tuple[str, str, str, str],
                       period: XxmPeriod, max_refs: int) -> ParsedXxmSnapshot:
    """Return independent validated fields; algorithm-specific rules run later."""
    try:
        raw = _fields(snapshot, _SNAPSHOT_FIELDS, "XXM")
        if tuple(raw[key] for key in _IDENTITY_FIELDS) != expected_identity:
            raise ValueError("XXM snapshot version/source identity mismatch")
        _integer(raw["processed"], minimum=0)
        processed = raw["processed"]
        if not isinstance(raw["state"], str) or raw["state"] not in ("NONE", "DULL", "STRUCTURE"):
            raise ValueError("Invalid XXM snapshot state")
        pools = _fields(raw["history"], frozenset(("1", "-1")), "reference pool")
        if any(not isinstance(pool, list) or len(pool) > max_refs for pool in pools.values()):
            raise ValueError("Invalid reference pool size")
        previous = None
        if raw["previous"] is not None:
            values = _fields(raw["previous"], _BAR_FIELDS, "previous bar")
            previous = XxmBar(**values)
            previous.validate(period)
        if processed == 0:
            if (previous is not None or raw["state"] != "NONE" or any(pools.values())
                    or any(raw[key] is not None for key in
                           ("wave", "reference", "pending", "pendingBottomHistory", "pendingRearm"))):
                raise ValueError("Nonempty zero-progress snapshot")
            return ParsedXxmSnapshot(None, {1: [], -1: []}, "NONE", None, None, None, None, None, 0)
        if previous is None:
            raise ValueError("Processed snapshot has no previous input")
        options = dict(period=period, processed=processed, upper=previous.time)
        wave = _wave(raw["wave"], **options) if raw["wave"] is not None else None
        if wave is not None and wave.end != previous.time:
            raise ValueError("Current Wave does not reach previous input")
        history: dict[int, list[Wave]] = {1: [], -1: []}
        for sign in (1, -1):
            for value in pools[str(sign)]:
                item = _wave(value, **options)
                if (item.sign != sign or (history[sign] and history[sign][-1].end >= item.start)
                        or (wave is not None and item.end >= wave.start)):
                    raise ValueError("Invalid reference pool direction or chronology")
                history[sign].append(item)
        reference = _wave(raw["reference"], **options) if raw["reference"] is not None else None
        if raw["state"] == "NONE":
            if reference is not None:
                raise ValueError("NONE snapshot carries an active reference")
        elif (wave is None or wave.sign == 0 or reference is None or reference.sign != wave.sign
              or reference not in history[wave.sign]):
            raise ValueError("Active state has no matching historical reference")
        record_options = dict(period=period, previous=previous, processed=processed)
        pending = _top(raw["pending"], **record_options) if raw["pending"] is not None else None
        bottom = _bottom(raw["pendingBottomHistory"], **record_options) if raw["pendingBottomHistory"] is not None else None
        rearm = _rearm(raw["pendingRearm"], **record_options) if raw["pendingRearm"] is not None else None
        if raw["state"] == "STRUCTURE" and wave is not None and wave.sign == -1:
            if (bottom is None or bottom["originSegmentStart"] != wave.start
                    or bottom["leftOriginAt"] is not None or bottom["confirmationRoute"] != "dif_turn"
                    or reference is None or bottom["originalReference"] != reference.reference()):
                raise ValueError("BOTTOM structure has no matching active history")
        return ParsedXxmSnapshot(wave, history, raw["state"], reference, previous, pending, bottom, rearm, processed)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Malformed XXM snapshot") from exc
