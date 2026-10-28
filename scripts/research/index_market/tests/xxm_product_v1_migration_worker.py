"""Disposable P2 worker.  Only stdin inputs, stdlib and formal XXM code.

No research wrapper, expected outcome, restore state or algorithm selector is
accepted.  P5 removes this module together with the temporary parent entry.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import resource
import signal
import sys
import time

PERIODS = ("day", "m60", "m90", "m120")
MAX_CASES = 148
MAX_BARS = 1000
MAX_BYTES = 16 * 1024 * 1024
MAX_MEMORY = 256 * 1024 * 1024
MAX_STDERR = 64 * 1024
MAX_JSON_NODES = 300_000
STATE_FIELDS = frozenset(("wave", "history", "state", "reference", "previous", "processed",
                          "pending", "pendingBottomHistory", "pendingRearm"))
BAR_FIELDS = frozenset(("time", "close", "dif", "dea", "hist", "completed"))
POINT_FIELDS = frozenset(("time", "close", "dif", "dea", "hist", "ordinaryState", "ordinaryDirection",
                          "activeReference", "pendingTopHistoryId", "pendingBottomHistoryId", "pendingRearmId"))
EVENT_FIELDS = frozenset(("id", "time", "direction", "type", "route", "fromState", "eventReference",
                          "relatedTopHistoryId", "relatedBottomHistoryId", "relatedRearmId"))
TOP_FIELDS = frozenset(("id", "confirmedAt", "confirmationRoute", "pricePeak", "pricePeakAt", "originalReference",
                        "status", "endedAt", "endReason", "observedThrough", "ageBars", "negativeBars", "zeroBars", "colorChanges"))
BOTTOM_FIELDS = frozenset(("id", "structureEventId", "confirmedAt", "confirmationRoute", "originSegmentStart",
                           "leftOriginAt", "priceLow", "priceLowAt", "originalReference", "status", "endedAt",
                           "endReason", "observedThrough", "ageBars"))
REARM_FIELDS = frozenset(("id", "direction", "bottomHistoryId", "structureEventId", "structureConfirmedAt", "structureRoute",
                          "segmentStart", "nearestPriceGate", "referenceWave", "disappearedAt", "observedThrough", "status", "endedAt", "endReason"))
WAVE_FIELDS = frozenset(("sign", "start", "end", "count", "price", "dif", "price_at", "dif_at"))
REFERENCE_FIELDS = frozenset(("startTime", "endTime", "price", "dif"))
STEP_FIELDS = frozenset(("point", "events", "histories", "bottomHistories", "rearmRecords", "stateBefore", "stateAfter"))
CASE_FIELDS = frozenset(("caseName", "period", "sourceIdentity", "bars"))
ID_FIELDS = frozenset(("id", "structureEventId", "bottomHistoryId", "relatedTopHistoryId", "relatedBottomHistoryId",
                       "relatedRearmId", "pendingTopHistoryId", "pendingBottomHistoryId", "pendingRearmId"))
# Exact approved formal object, from LLD 2.2.  This is algorithm identity,
# never a source-code hash or an alternate engine configuration.
FORMAL_SPEC = dict(algorithm_version="xxm-direction-v0.1-r4", dif_turn_pct=1.0, max_refs=2, min_bars=2,
                   reference_policy="nearest_then_farther_two", active_reference_policy="same_bar_near_to_far_on_dull_break",
                   zero_policy="neutral_real_opposite", allow_zero_activation=True, allow_zero_reactivation=True,
                   macd_parameters=(12, 26, 9), histogram_multiplier=2, color_flip=True, flip_requires_turn=False,
                   historical_price_only=True, fixed_expiry=None, bottom_history_policy="closed_origin_close_break_v1",
                   same_segment_bottom_policy="current_close_rearm_v1")


def formal_hash():
    return hashlib.sha256(json.dumps(FORMAL_SPEC, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class MigrationError(ValueError):
    """A bounded, human-readable failure; never embeds a business record."""


def check_memory(location="initialization"):
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if (rss if sys.platform == "darwin" else rss * 1024) > MAX_MEMORY:
        raise MigrationError(f"stage={location}: process exceeded 256 MiB")


class Budget:
    def __init__(self, seconds=20.0, reserve=1.0, *, work_end=None, end=None):
        self.started = time.monotonic()
        self.end = self.started + seconds if end is None else end
        self.work_end = self.end - reserve if work_end is None else work_end
        if not (math.isfinite(self.end) and math.isfinite(self.work_end)
                and self.work_end < self.end and self.end - self.work_end <= 1.000001
                and self.end - self.started <= seconds + .000001):
            raise MigrationError("invalid shared deadline")
        self.location = "initialization"
        self.timings = {}

    @contextmanager
    def stage(self, name, case=None):
        previous = self.location
        if case is None:
            self.location = name
        elif isinstance(case, dict):
            self.location = f"{name}/case={case['caseName']}/period={case['period']}"
        else:
            self.location = f"{name}/case={case}"
        started = time.monotonic()
        try:
            self.check()
            yield
            self.check()
        except (MigrationError, TimeoutError) as exc:
            if "stage=" in str(exc):
                raise
            raise type(exc)(f"stage={self.location}: {exc}") from exc
        finally:
            self.timings[name] = self.timings.get(name, 0.0) + time.monotonic() - started
            self.location = previous

    def check(self):
        if time.monotonic() >= self.work_end:
            raise TimeoutError(f"stage={self.location}: phase exceeded its work deadline")
        check_memory(self.location)

    @contextmanager
    def interrupt_at_deadline(self):
        def expired(_signum, _frame):
            raise TimeoutError(f"stage={self.location}: phase exceeded its work deadline")
        old_handler = signal.signal(signal.SIGALRM, expired)
        old_timer = signal.setitimer(signal.ITIMER_REAL, max(.000001, self.work_end - time.monotonic()))
        try:
            self.check()
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
            if old_timer[0]:
                signal.setitimer(signal.ITIMER_REAL, *old_timer)


def fields(value, expected, path):
    if type(value) is not dict or set(value) != expected:
        raise MigrationError(f"{path}: missing or extra fields")


def _measure(values, *, excluded=(), budget=None, retain=False):
    """Visit only new objects; never copy the already registered identity set."""
    seen = {}
    total = 0
    stack = [(v, 0) for v in values]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > 40 or nodes > 1_000_000:
            raise MigrationError("structure count/depth exceeded")
        if nodes % 256 == 0 and budget is not None:
            budget.check()
        identity = id(item)
        if identity in excluded or identity in seen:
            continue
        size = sys.getsizeof(item)
        # Strong references in a retained registry prevent object-ID reuse.
        seen[identity] = (item, size) if retain else None
        total += size
        if total > MAX_BYTES:
            raise MigrationError("retained data exceeded 16 MiB")
        if type(item) is dict:
            stack.extend((v, depth + 1) for pair in item.items() for v in pair)
        elif type(item) in (list, tuple):
            stack.extend((v, depth + 1) for v in item)
        elif type(item) not in (str, bytes, bytearray, int, float, bool, type(None)):
            raise MigrationError("non-standard value in protocol")
        elif type(item) is float and not math.isfinite(item):
            raise MigrationError("non-finite number in protocol")
    return total, seen


def bounded_size(*values):
    """Count actual retained Python objects, including containers, once each."""
    return _measure(values)[0]


class RetainedSize:
    """Exact shared-object accounting for live, unchanged registered records.

    Completed records stay immutable.  Only registered outer containers grow;
    callers register their new contents and refresh the container's own size.
    Temporary indexes/copies are measured against, never added to, this graph.
    """
    def __init__(self, *values, budget=None):
        self.objects = {}
        self.total = 0
        self.budget = budget
        self.add(*values)

    def add(self, *values):
        added, objects = _measure(values, excluded=self.objects, budget=self.budget, retain=True)
        self._limit(self.total + added)
        self.objects.update(objects)
        self.total += added
        return self.total

    def refresh(self, value):
        if type(value) not in (dict, list, bytearray):
            raise MigrationError("only mutable containers can be refreshed")
        identity = id(value)
        if identity not in self.objects:
            raise MigrationError("unregistered growing container")
        size = sys.getsizeof(value)
        self.total += size - self.objects[identity][1]
        self.objects[identity] = (value, size)
        self._limit(self.total)
        return self.total

    def check(self, *values):
        added, _ = _measure(values, excluded=self.objects, budget=self.budget)
        self._limit(self.total + added)
        return self.total + added

    def check_buffers(self, *values):
        extra = {}
        for value in values:
            if type(value) not in (bytes, bytearray):
                raise MigrationError("invalid protocol buffer")
            if id(value) not in self.objects:
                extra[id(value)] = sys.getsizeof(value)
        total = self.total + sum(extra.values())
        self._limit(total)
        return total

    @staticmethod
    def _limit(total):
        if total > MAX_BYTES:
            raise MigrationError("retained data exceeded 16 MiB")


def encode(value, budget, retained=None):
    bounded_size(value)
    if retained is not None and not isinstance(retained, RetainedSize):
        raise MigrationError("invalid retained-data registry")
    data = bytearray()
    checked_at = 0
    for part in json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(value):
        chunk = part.encode("utf-8")
        if len(data) + len(chunk) > MAX_BYTES:
            raise MigrationError("message exceeded 16 MiB")
        data.extend(chunk)
        if len(data) - checked_at >= 65536:
            if retained is not None:
                retained.check_buffers(data)
            budget.check()
            checked_at = len(data)
    if retained is not None:
        retained.check_buffers(data)
    budget.check()
    return data


def decode(data, budget):
    if len(data) > MAX_BYTES:
        raise MigrationError("message exceeded 16 MiB")
    # Check JSON nesting before decoding to avoid an unbounded nested object.
    depth = nodes = 0
    quoted = escaped = False
    for offset, char in enumerate(data):
        if offset % 65536 == 0:
            budget.check()
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            nodes += 1
            if depth > 40:
                raise MigrationError("JSON nesting exceeded")
        elif char in (93, 125):
            depth -= 1
        elif char in (44, 58):
            # Every member/value needs a separator; count before json.loads
            # can allocate containers or scalar objects for the whole message.
            nodes += 1
        if nodes > MAX_JSON_NODES:
            raise MigrationError("JSON structure count exceeded")
    budget.check()
    try:
        value = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(MigrationError("non-finite JSON")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise MigrationError("invalid result JSON") from exc
    bounded_size(value)
    budget.check()
    return value


def stamp(value, period, upper=None):
    if type(value) is not str:
        raise MigrationError("invalid date type")
    try:
        if period == "day":
            valid = date.fromisoformat(value).isoformat() == value
        else:
            parsed = datetime.fromisoformat(value)
            valid = parsed.utcoffset() == timedelta(hours=8) and parsed.isoformat() == value
    except (ValueError, TypeError, OverflowError) as exc:
        raise MigrationError("invalid date") from exc
    if not valid or (upper is not None and value > upper):
        raise MigrationError("invalid or future date")


def number(value, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise MigrationError("invalid finite numeric value")


def reference(value, period, upper):
    fields(value, REFERENCE_FIELDS, "reference")
    stamp(value["startTime"], period, upper)
    stamp(value["endTime"], period, upper)
    if value["startTime"] > value["endTime"]:
        raise MigrationError("reversed reference dates")
    number(value["price"], True)
    number(value["dif"])


def wave(value, period, upper, processed):
    if value is None:
        return
    fields(value, WAVE_FIELDS, "wave")
    if type(value["sign"]) is not int or value["sign"] not in (-1, 1):
        raise MigrationError("invalid wave sign")
    if type(value["count"]) is not int or not 1 <= value["count"] <= processed:
        raise MigrationError("invalid wave count")
    for key in ("start", "end", "price_at", "dif_at"):
        stamp(value[key], period, upper)
    if not (value["start"] <= value["price_at"] <= value["end"] and value["start"] <= value["dif_at"] <= value["end"]):
        raise MigrationError("invalid wave chronology")
    number(value["price"], True)
    number(value["dif"])


def validate_inputs(cases, budget, *, full_batch=True):
    bounded_size(cases)
    if type(cases) is not list or (len(cases) != MAX_CASES if full_batch else not 1 <= len(cases) <= MAX_CASES):
        raise MigrationError("wrong case count")
    identities = set()
    for item in cases:
        budget.check()
        fields(item, CASE_FIELDS, "input case")
        name, period = item["caseName"], item["period"]
        if type(name) is not str or not name or period not in PERIODS or item["sourceIdentity"] != f"p1:{period}:{name}":
            raise MigrationError("invalid input identity")
        key = period, name
        if key in identities:
            raise MigrationError("duplicate input case")
        identities.add(key)
        bars = item["bars"]
        if type(bars) is not list or not 1 <= len(bars) <= MAX_BARS:
            raise MigrationError("case exceeded bar count")
        previous = None
        for bar in bars:
            fields(bar, BAR_FIELDS, "input bar")
            stamp(bar["time"], period)
            if bar["completed"] is not True or (previous is not None and bar["time"] <= previous):
                raise MigrationError("unordered or incomplete bars")
            for key in ("close", "dif", "dea", "hist"):
                number(bar[key], key == "close")
            previous = bar["time"]
    if full_batch:
        order = [c["period"] for c in cases]
        if order != [p for p in PERIODS for _ in range(37)]:
            raise MigrationError("wrong period order")
        names = [c["caseName"] for c in cases[:37]]
        if any([c["caseName"] for c in cases[i:i + 37]] != names for i in (37, 74, 111)):
            raise MigrationError("wrong per-period case order")


def state_from_snapshot(snapshot):
    # Identity is validated separately.  Preserve every business field exactly,
    # including Wave.price_at/dif_at and string history keys from the snapshot.
    fields(snapshot, STATE_FIELDS | {"specHash", "tsCode", "period", "sourceIdentity"}, "snapshot")
    return deepcopy({key: snapshot[key] for key in STATE_FIELDS})


def step_record(step, before, after):
    return deepcopy(dict(point=step.point, events=list(step.events), histories=list(step.histories),
                         bottomHistories=list(step.bottom_histories), rearmRecords=list(step.rearm_records),
                         stateBefore=before, stateAfter=after))


def validate_record(record, budget):
    """Validate all stored fields before mapping; never invokes a detector."""
    fields(record, CASE_FIELDS | {"steps"}, "record")
    validate_inputs([{k: record[k] for k in CASE_FIELDS}], budget, full_batch=False)
    steps, bars, period = record["steps"], record["bars"], record["period"]
    if type(steps) is not list or len(steps) != len(bars):
        raise MigrationError("wrong step count")
    for i, (step, bar) in enumerate(zip(steps, bars, strict=True)):
        budget.check()
        fields(step, STEP_FIELDS, f"bar={i + 1}")
        point = step["point"]
        fields(point, POINT_FIELDS, f"bar={i + 1}.point")
        for key in ("time", "close", "dif", "dea", "hist"):
            if point[key] != bar[key] or type(point[key]) is bool:
                raise MigrationError(f"bar={i + 1}.point.{key}: differs from input")
        if point["ordinaryState"] not in ("NONE", "DULL", "STRUCTURE") or point["ordinaryDirection"] not in (None, "TOP", "BOTTOM"):
            raise MigrationError(f"bar={i + 1}: invalid point state/direction")
        if (point["ordinaryState"] == "NONE") != (point["ordinaryDirection"] is None):
            raise MigrationError(f"bar={i + 1}: inconsistent point state/direction")
        if point["activeReference"] is not None:
            reference(point["activeReference"], period, bar["time"])
        for group, expected in (("events", EVENT_FIELDS), ("histories", TOP_FIELDS),
                                ("bottomHistories", BOTTOM_FIELDS), ("rearmRecords", REARM_FIELDS)):
            values = step[group]
            if type(values) is not list or len(values) > 4:
                raise MigrationError(f"bar={i + 1}.{group}: invalid count")
            for value in values:
                fields(value, expected, f"bar={i + 1}.{group}")
                validate_object(value, group, period, bar["time"], i + 1)
        for state_key, count in (("stateBefore", i), ("stateAfter", i + 1)):
            state = step[state_key]
            fields(state, STATE_FIELDS, state_key)
            if type(state["processed"]) is not int or state["processed"] != count:
                raise MigrationError(f"bar={i + 1}.{state_key}.processed")
            if state["state"] not in ("NONE", "DULL", "STRUCTURE"):
                raise MigrationError("invalid progress state")
            fields(state["history"], {"1", "-1"}, "history")
            for sign, pool in state["history"].items():
                if type(pool) is not list or len(pool) > 2:
                    raise MigrationError("invalid reference-pool count")
                for old in pool:
                    wave(old, period, bar["time"], count)
                    if old["sign"] != int(sign):
                        raise MigrationError("reference-pool sign mismatch")
            for key in ("wave", "reference"):
                wave(state[key], period, bar["time"], count)
            previous = None if count == 0 else bars[count - 1]
            if state["previous"] != previous:
                raise MigrationError(f"bar={i + 1}.{state_key}.previous")
            for key, group in (("pending", "histories"), ("pendingBottomHistory", "bottomHistories"), ("pendingRearm", "rearmRecords")):
                if state[key] is not None:
                    expected = {"histories": TOP_FIELDS, "bottomHistories": BOTTOM_FIELDS, "rearmRecords": REARM_FIELDS}[group]
                    fields(state[key], expected, key)
                    validate_object(state[key], group, period, bar["time"], count)
            if i and state_key == "stateBefore" and state != steps[i - 1]["stateAfter"]:
                raise MigrationError(f"bar={i + 1}.stateBefore: progress discontinuity")
        if point["ordinaryState"] != step["stateAfter"]["state"]:
            raise MigrationError(f"bar={i + 1}.point.ordinaryState: progress mismatch")
    bounded_size(record)


def validate_object(value, group, period, upper, processed):
    for key in ID_FIELDS & value.keys():
        if value[key] is not None and (type(value[key]) is not str or not value[key] or len(value[key]) > 128):
            raise MigrationError("invalid ID")
    for key in ("id",):
        if value.get(key) is None:
            raise MigrationError("missing ID")
    time_keys = ("time", "confirmedAt", "pricePeakAt", "priceLowAt", "originSegmentStart", "leftOriginAt",
                 "endedAt", "observedThrough", "structureConfirmedAt", "segmentStart", "disappearedAt")
    for key in time_keys:
        if key in value and value[key] is not None:
            stamp(value[key], period, upper)
    for key in ("eventReference", "originalReference"):
        if key in value and value[key] is not None:
            reference(value[key], period, upper)
    for key in ("pricePeak", "priceLow", "nearestPriceGate"):
        if key in value:
            number(value[key], True)
    for key in ("ageBars", "negativeBars", "zeroBars", "colorChanges"):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= processed):
            raise MigrationError("invalid history counter")
    if "referenceWave" in value:
        wave(value["referenceWave"], period, upper, processed)
    if group == "events":
        if (value["time"] != upper or value["direction"] not in ("TOP", "BOTTOM")
                or value["type"] not in ("DULL", "STRUCTURE", "CANCEL", "STRUCTURE_DISAPPEARED", "RESEARCH_HISTORICAL_WITHDRAWAL")
                or value["route"] not in ("activation", "dif_turn", "dif_return", "color_flip", "dif_break", "dif_break_on_flip", "reactivation", "historical_price_break")
                or value["fromState"] not in ("NONE", "DULL", "STRUCTURE")):
            raise MigrationError("invalid event fields")
    else:
        allowed = ("WAITING", "REACTIVATED", "INVALIDATED", "SEGMENT_ENDED") if group == "rearmRecords" else ("PENDING", "ENDED")
        if value["status"] not in allowed:
            raise MigrationError("invalid history/wait status")
        active = value["status"] in ("WAITING", "PENDING")
        if active != (value["endedAt"] is None and value["endReason"] is None):
            raise MigrationError("inconsistent history/wait ending")
        if value["observedThrough"] > upper:
            raise MigrationError("future observation")


def calculate(cases, budget):
    validate_inputs(cases, budget)
    # Delayed imports keep collection/help/protocol tests free of computation.
    from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
    from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
    from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
    actual = asdict(MAIN_SPEC)
    if (actual != FORMAL_SPEC or any(type(actual[k]) is not type(value) for k, value in FORMAL_SPEC.items())
            or MAIN_SPEC.spec_hash != formal_hash()):
        raise MigrationError("worker requires formal r4 Spec")
    records = []
    retained = RetainedSize(cases, records, budget=budget)
    for case in cases:
        with budget.stage("formal calculation", case):
            calculator = XxmCalculator(period=case["period"], source_identity=case["sourceIdentity"], ts_code="000001.SH")
            record = deepcopy(case)
            record["steps"] = []
            retained.add(record)
            for number_on_case, bar in enumerate(case["bars"], 1):
                budget.location = f"formal calculation/case={case['caseName']}/period={case['period']}/bar={number_on_case}"
                budget.check()
                raw_before = calculator.snapshot()
                expected = (MAIN_SPEC.spec_hash, "000001.SH", case["period"], case["sourceIdentity"])
                if tuple(raw_before.get(k) for k in ("specHash", "tsCode", "period", "sourceIdentity")) != expected:
                    raise MigrationError("formal snapshot identity mismatch")
                before = state_from_snapshot(raw_before)
                step = calculator.step(XxmBar(**bar))
                raw_after = calculator.snapshot()
                if tuple(raw_after.get(k) for k in ("specHash", "tsCode", "period", "sourceIdentity")) != expected:
                    raise MigrationError("formal snapshot identity mismatch")
                stored = step_record(step, before, state_from_snapshot(raw_after))
                retained.add(stored)
                record["steps"].append(stored)
                retained.refresh(record["steps"])
            validate_record(record, budget)
            records.append(record)
            retained.refresh(records)
            del calculator
    result = dict(algorithmVersion=MAIN_SPEC.algorithm_version, specHash=MAIN_SPEC.spec_hash, tsCode="000001.SH", records=records)
    retained.add(result)
    if bounded_size(cases, result) != retained.total:
        raise MigrationError("retained accounting differs")
    return result


def child_budget(argv):
    if len(argv) != 2:
        raise MigrationError("expected shared work and cleanup deadlines")
    try:
        return Budget(work_end=float(argv[0]), end=float(argv[1]))
    except (ValueError, OverflowError) as exc:
        raise MigrationError("invalid shared deadline") from exc


def main(argv=None):
    budget = None
    try:
        if not sys.dont_write_bytecode:
            raise MigrationError("formal interpreter requires -B at startup")
        budget = child_budget(sys.argv[1:] if argv is None else argv)
        with budget.interrupt_at_deadline():
            with budget.stage("formal input"):
                data = bytearray()
                while True:
                    budget.check()
                    chunk = sys.stdin.buffer.read1(65536)
                    if not chunk:
                        break
                    if len(data) + len(chunk) > MAX_BYTES:
                        raise MigrationError("input message exceeded 16 MiB")
                    data.extend(chunk)
                cases = decode(data, budget)
                del data, chunk
            result = calculate(cases, budget)
            with budget.stage("formal output"):
                retained = RetainedSize(cases, result, budget=budget)
                data = encode(result, budget, retained=retained)
                bounded_size(cases, result, data)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        sys.stderr.write((f"{type(exc).__name__}: {str(exc)[:500]}\n")[:MAX_STDERR])
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
