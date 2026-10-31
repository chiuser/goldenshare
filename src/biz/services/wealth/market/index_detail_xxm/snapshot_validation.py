"""Strict, independent in-memory progress validation for the unique r4 kernel."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import math
from typing import Any

from .spec import MAIN_SPEC
from .types import Wave, XxmBar, XxmPeriod, XxmStructureRecord


_IDENTITY_FIELDS = ("specHash", "tsCode", "period", "sourceIdentity")
_SNAPSHOT_FIELDS = frozenset((*_IDENTITY_FIELDS, "processed", "wave", "history", "state",
                             "reference", "previous", "activeStructure", "followedStructures"))
_WAVE_FIELDS = frozenset(Wave.__dataclass_fields__)
_BAR_FIELDS = frozenset(XxmBar.__dataclass_fields__)
_REFERENCE_FIELDS = frozenset(("startTime", "endTime", "price", "dif", "priceAt", "difAt"))
_STRUCTURE_FIELDS = frozenset(XxmStructureRecord.__annotations__)
IdFactory = Callable[..., str]


@dataclass(slots=True)
class ParsedXxmSnapshot:
    wave: Wave | None
    history: dict[int, list[Wave]]
    state: str
    reference: Wave | None
    previous: XxmBar | None
    active_structure: XxmStructureRecord | None
    processed: int
    followed_structures: dict[str, XxmStructureRecord | None]


def _fields(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"Invalid {label} snapshot fields")
    return value


def _number(value: Any, *, positive: bool = False) -> None:
    try:
        if (type(value) not in (int, float) or not math.isfinite(value)
                or (positive and value <= 0)):
            raise ValueError("Invalid snapshot numeric value")
    except OverflowError as exc:
        raise ValueError("Invalid snapshot numeric value") from exc


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


def _wave(value: Any, *, period: XxmPeriod, processed: int | None, upper: str) -> Wave:
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


def _reference(value: Any, *, period: XxmPeriod, upper: str) -> dict[str, Any]:
    raw = _fields(value, _REFERENCE_FIELDS, "structure reference")
    _number(raw["price"], positive=True)
    _number(raw["dif"])
    for key in ("startTime", "endTime", "priceAt", "difAt"):
        _time(raw[key], period, upper)
    if not (raw["startTime"] <= raw["priceAt"] <= raw["endTime"]
            and raw["startTime"] <= raw["difAt"] <= raw["endTime"]):
        raise ValueError("Invalid structure reference chronology")
    return raw


def validate_structure_facts(value: Any, *, period: XxmPeriod, upper: str) -> XxmStructureRecord:
    """Shared shape/lifecycle checks; the enclosing identity is checked separately."""
    raw = _fields(value, _STRUCTURE_FIELDS, "structure")
    for key in ("id", "structureEventId"):
        _text(raw[key])
    if raw["direction"] not in ("TOP", "BOTTOM"):
        raise ValueError("Invalid structure direction")
    if raw["formationRoute"] not in ("dif_turn", "color_flip"):
        raise ValueError("Invalid structure formation route")
    if raw["status"] not in ("ASSESSING", "FOLLOWING", "FINISHED", "DISAPPEARED"):
        raise ValueError("Invalid structure status")
    for key in ("formedAt", "originSegmentStart", "priceExtremeAt"):
        _time(raw[key], period, upper)
    _number(raw["priceExtreme"], positive=True)
    ref = _reference(raw["originalReference"], period=period, upper=upper)
    if not (ref["endTime"] < raw["originSegmentStart"]
            <= raw["priceExtremeAt"] <= raw["formedAt"]):
        raise ValueError("Invalid structure chronology")
    sign = 1 if raw["direction"] == "TOP" else -1
    first, same, end = (raw[key] for key in ("firstOppositeAt", "nextSameColorStart", "trackingEndedAt"))
    for stamp in (first, same, end, raw["disappearedAt"]):
        if stamp is not None:
            _time(stamp, period, upper)
    if first is None:
        if (raw["originWave"] is not None or same is not None or raw["formationRoute"] != "dif_turn"
                or raw["status"] not in ("ASSESSING", "DISAPPEARED")):
            raise ValueError("Invalid pre-opposite structure")
    else:
        origin = _wave(raw["originWave"], period=period, processed=None, upper=upper)
        if (origin.sign != sign or origin.start != raw["originSegmentStart"]
                or not raw["priceExtremeAt"] <= origin.end < first
                or sign * (raw["priceExtreme"] - origin.price) > 0
                or raw["formedAt"] > first
                or (raw["formationRoute"] == "dif_turn" and origin.end < raw["formedAt"])
                or (raw["formationRoute"] == "color_flip") != (first == raw["formedAt"])):
            raise ValueError("Invalid closed origin Wave")
        if same is not None and same <= first:
            raise ValueError("Invalid next same-color start")
        if raw["status"] == "ASSESSING":
            raise ValueError("A structure after first opposite cannot remain assessing")
    if raw["status"] in ("ASSESSING", "FOLLOWING"):
        if any(value is not None for value in (end, raw["disappearedAt"], raw["disappearanceReason"])):
            raise ValueError("Live structure contains terminal facts")
    elif raw["status"] == "FINISHED":
        if (same is None or end is None or end <= same
                or raw["disappearedAt"] is not None or raw["disappearanceReason"] is not None):
            raise ValueError("Invalid normally finished structure")
    elif (end is None or end != raw["disappearedAt"] or end <= raw["formedAt"]
          or (first is None and raw["disappearanceReason"] not in ("dif_return", "reference_dif_break"))
          or (first is not None and (same is None or end < same
                                    or raw["disappearanceReason"] != "structure_price_break"))):
        raise ValueError("Invalid disappeared structure")
    if raw["formationRoute"] == "color_flip" and raw["priceExtremeAt"] >= raw["formedAt"]:
        raise ValueError("Opposite-color input cannot change the old segment price extreme")
    return deepcopy(raw)


def validate_structure_record(value: Any, *, period: XxmPeriod, upper: str,
                              id_factory: IdFactory) -> XxmStructureRecord:
    """Validate all structure facts and the caller's actual registered identity."""
    raw = validate_structure_facts(value, period=period, upper=upper)
    sign = 1 if raw['direction'] == 'TOP' else -1
    ref = raw['originalReference']
    event_id = id_factory(raw["formedAt"], "STRUCTURE", sign, ref["startTime"])
    if raw["structureEventId"] != event_id or raw["id"] != id_factory("structure", event_id):
        raise ValueError("Invalid structure/event identity")
    return raw


def validate_xxm_progress(parsed: ParsedXxmSnapshot, *, period: XxmPeriod,
                          id_factory: IdFactory, max_refs: int = 2, min_bars: int = 2) -> None:
    """Check bounded work progress directly; no snapshot encoding or self writes."""
    _integer(parsed.processed, minimum=0)
    _fields(parsed.followed_structures, frozenset(("TOP", "BOTTOM")), "followed structures")
    if not isinstance(parsed.state, str) or parsed.state not in ("NONE", "DULL", "STRUCTURE"):
        raise ValueError("Invalid XXM snapshot state")
    if (not isinstance(parsed.history, dict) or set(parsed.history) != {1, -1}
            or any(type(key) is not int for key in parsed.history)):
        raise ValueError("Invalid parsed reference pool keys")
    if any(not isinstance(pool, list) or len(pool) > max_refs for pool in parsed.history.values()):
        raise ValueError("Invalid reference pool size")
    if parsed.previous is not None:
        if not isinstance(parsed.previous, XxmBar):
            raise ValueError("Invalid previous bar")
        parsed.previous.validate(period)
    if parsed.processed == 0:
        if (parsed.previous is not None or parsed.wave is not None or any(parsed.history.values())
                or parsed.state != "NONE" or parsed.reference is not None or parsed.active_structure is not None or any(record is not None for record in parsed.followed_structures.values())):
            raise ValueError("Nonempty zero-progress snapshot")
        return
    if parsed.previous is None:
        raise ValueError("Processed snapshot has no previous input")
    if parsed.wave is None:
        if (parsed.previous.hist != 0 or parsed.state != "NONE" or parsed.reference is not None
                or any(parsed.history.values()) or parsed.active_structure is not None or any(record is not None for record in parsed.followed_structures.values())):
            raise ValueError("Leading-zero snapshot carries an active segment")
        return
    options = dict(period=period, processed=parsed.processed, upper=parsed.previous.time)
    if not isinstance(parsed.wave, Wave):
        raise ValueError("Invalid current Wave")
    wave = _wave(asdict(parsed.wave), **options)
    raw_sign = (parsed.previous.hist > 0) - (parsed.previous.hist < 0)
    if wave.end != parsed.previous.time or raw_sign not in (0, wave.sign):
        raise ValueError("Current Wave does not match the previous input")
    if (wave.sign * (parsed.previous.close - wave.price) > 0
            or wave.sign * (parsed.previous.dif - wave.dif) > 0
            or (wave.price_at == parsed.previous.time and wave.price != parsed.previous.close)
            or (wave.dif_at == parsed.previous.time and wave.dif != parsed.previous.dif)):
        raise ValueError("Current Wave extremes contradict the previous input")
    for sign in (1, -1):
        prior = None
        for item in parsed.history[sign]:
            if not isinstance(item, Wave):
                raise ValueError("Invalid historical Wave")
            _wave(asdict(item), **options)
            if (item.sign != sign or item.end >= wave.start
                    or (prior is not None and prior.end >= item.start)):
                raise ValueError("Invalid reference pool direction or chronology")
            prior = item
    followed_ids = set()
    for direction, record in parsed.followed_structures.items():
        if record is None:
            continue
        validate_structure_record(record, period=period, upper=parsed.previous.time, id_factory=id_factory)
        sign = 1 if direction == "TOP" else -1
        if (record["direction"] != direction or record["status"] != "FOLLOWING"
                or record["id"] in followed_ids
                or (parsed.active_structure is not None and record["id"] == parsed.active_structure["id"])
                or not parsed.history[sign]
                or record["originWave"] != asdict(parsed.history[sign][-1])):
            raise ValueError("Invalid followed structure slot or closed origin")
        followed_ids.add(record["id"])
        same = record["nextSameColorStart"]
        if same is None:
            if wave.sign != -sign or wave.start != record["firstOppositeAt"]:
                raise ValueError("Invalid separator progress")
        else:
            separator = parsed.history[-sign][-1] if parsed.history[-sign] else None
            if (wave.sign != sign or same != wave.start or separator is None
                    or separator.start != record["firstOppositeAt"] or separator.end >= same
                    or sign * (wave.price - record["originWave"]["price"]) > 0):
                raise ValueError("Invalid next-same progress or an already broken followed price")
    if parsed.state == "NONE":
        if parsed.reference is not None or parsed.active_structure is not None:
            raise ValueError("NONE snapshot carries an active relationship")
        return
    ref = parsed.reference
    if not isinstance(ref, Wave):
        raise ValueError("Active state has no historical reference")
    _wave(asdict(ref), **options)
    if (wave.count < min_bars or ref.sign != wave.sign or ref not in parsed.history[wave.sign]
            or wave.sign * (wave.dif - ref.dif) > 0):
        raise ValueError("Active relationship is not supported by its reference")
    nearest = parsed.history[wave.sign][-1]
    if (wave.sign * (wave.price - ref.price) <= 0
            or wave.sign * (wave.price - nearest.price) <= 0):
        raise ValueError("Active relationship never passed its price gates")
    if parsed.state == "DULL":
        if parsed.active_structure is not None:
            raise ValueError("DULL snapshot carries an active structure")
        return
    structure = validate_structure_record(parsed.active_structure, period=period,
                                          upper=parsed.previous.time, id_factory=id_factory)
    if (structure["status"] != "ASSESSING" or structure["formationRoute"] != "dif_turn"
            or structure["direction"] != ("TOP" if wave.sign == 1 else "BOTTOM")
            or structure["originSegmentStart"] != wave.start
            or structure["originalReference"] != ref.reference()
            or wave.sign * (structure["priceExtreme"] - wave.price) > 0):
        raise ValueError("STRUCTURE snapshot has no matching active structure")


def parse_xxm_snapshot(snapshot: dict[str, Any], *, expected_identity: tuple[str, str, str, str],
                       period: XxmPeriod, max_refs: int,
                       id_factory: IdFactory | None = None) -> ParsedXxmSnapshot:
    """Return independent, fully checked progress; never publish partial parsing."""
    try:
        raw = _fields(snapshot, _SNAPSHOT_FIELDS, "XXM")
        if tuple(raw[key] for key in _IDENTITY_FIELDS) != expected_identity:
            raise ValueError("XXM snapshot version/source identity mismatch")
        _integer(raw["processed"], minimum=0)
        processed = raw["processed"]
        pools = _fields(raw["history"], frozenset(("1", "-1")), "reference pool")
        if any(not isinstance(pool, list) or len(pool) > max_refs for pool in pools.values()):
            raise ValueError("Invalid reference pool size")
        previous = None
        if raw["previous"] is not None:
            previous = XxmBar(**_fields(raw["previous"], _BAR_FIELDS, "previous bar"))
            previous.validate(period)
        if previous is None:
            if any(raw[key] is not None for key in ("wave", "reference", "activeStructure")) or any(pools.values()):
                raise ValueError("Missing previous input for nonempty progress")
            parsed = ParsedXxmSnapshot(None, {1: [], -1: []}, raw["state"], None, None, None, processed, deepcopy(raw["followedStructures"]))
        else:
            options = dict(period=period, processed=processed, upper=previous.time)
            wave = _wave(raw["wave"], **options) if raw["wave"] is not None else None
            history = {sign: [_wave(item, **options) for item in pools[str(sign)]] for sign in (1, -1)}
            reference = _wave(raw["reference"], **options) if raw["reference"] is not None else None
            parsed = ParsedXxmSnapshot(wave, history, raw["state"], reference, previous,
                                       deepcopy(raw["activeStructure"]), processed, deepcopy(raw["followedStructures"]))
        if id_factory is None:
            def id_factory(*parts: Any) -> str:
                identity = [MAIN_SPEC.algorithm_version, expected_identity[0], expected_identity[1], period, *parts]
                return hashlib.sha256("|".join(map(str, identity)).encode()).hexdigest()[:24]
        validate_xxm_progress(parsed, period=period, max_refs=max_refs, id_factory=id_factory)
        return parsed
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Malformed XXM snapshot") from exc
