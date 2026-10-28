"""One-use, RAM-only r4 migration capture/compare (LLD 10.4.1; P5 removal).

Run as a module in a maintained terminal.  CAPTURE_READY is emitted only after
all independent P1 assertions.  Keep that process alive while editing; send
``compare`` once or ``abort``.  Importing this module never runs either engine.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gc
import os
import selectors
import signal
import subprocess
import sys
import time

from .xxm_product_v1_cases import CASES, PERIODS
from . import xxm_product_v1_migration_worker as protocol

MigrationError = protocol.MigrationError
WORKER_MODULE = "scripts.research.index_market.tests.xxm_product_v1_migration_worker"
CAPTURE_MODULE = "scripts.research.index_market.tests.xxm_product_v1_migration_capture"


def artificial_inputs():
    if len(CASES) != 37 or PERIODS != protocol.PERIODS:
        raise MigrationError("P1 input set changed")
    return [dict(caseName=case.name, period=period, sourceIdentity=f"p1:{period}:{case.name}",
                 bars=list(case.inputs(period))) for period in PERIODS for case in CASES]


def _equal(actual, expected, path):
    if actual != expected or (type(actual) is bool) != (type(expected) is bool):
        raise MigrationError(f"{path}: independent fact differs")


def _one(items, path):
    if len(items) != 1:
        raise MigrationError(f"{path}: missing or ambiguous association")
    return items[0]


def _reference(case, record, name):
    if name is None:
        return None
    item = _one([r for r in case.references if r.name == name], "P1 reference")
    return dict(startTime=record["bars"][item.start - 1]["time"], endTime=record["bars"][item.end - 1]["time"],
                price=item.price, dif=item.dif)


def _event_at(record, at, through, kind=None):
    if at > through:
        raise MigrationError("P1 event association points into the future")
    events = record["steps"][at - 1]["events"]
    return _one([event for event in events if kind is None or event["type"] == kind], f"event@{at}")


def assert_case_facts(case, record, budget=None):
    """Explicit P1 facts -> real stored fields.  Unknown facts always fail.

    All expected prices, extrema, states and event routes come from the literal
    Case; only event/wait IDs are resolved from their declared bar association.
    """
    if case.name != record["caseName"]:
        raise MigrationError("P1 case name differs")
    for check in case.checks:
        if budget:
            budget.check()
        step = record["steps"][check.at - 1]
        path = f"case={case.name}/period={record['period']}/bar={check.at}"
        point, state = step["point"], step["stateAfter"]
        _equal(point["ordinaryState"], check.state, path + "/point.ordinaryState")
        _equal(point["ordinaryDirection"], check.direction, path + "/point.ordinaryDirection")
        _equal(point["activeReference"], _reference(case, record, check.reference), path + "/point.activeReference")
        actual_events = [(event["type"], event["route"], event["direction"], event["eventReference"]) for event in step["events"]]
        expected_events = [(kind, route, direction, _reference(case, record, ref)) for kind, route, direction, ref in check.events]
        _equal(actual_events, expected_events, path + "/events")
        observed = record["steps"][:check.at]

        def latest(group):
            return next((r for s in reversed(observed) for r in reversed(s[group])), None)

        def when(index):
            return None if index is None else record["bars"][index - 1]["time"]

        def linked_event(token, kind=None):
            if type(token) is not str or not token.startswith("event@"):
                raise MigrationError("invalid P1 event token")
            return _event_at(record, int(token[6:]), check.at, kind)

        top, bottom, wait = latest("histories"), latest("bottomHistories"), latest("rearmRecords")
        for fact, expected in check.facts:
            fact_path = path + "/" + fact
            wave = state["wave"]
            if fact == "count":
                actual = wave["count"] if wave else 0
            elif fact == "wave_start":
                actual, expected = wave["start"] if wave else None, when(expected)
            elif fact in ("wave_price", "wave_dif"):
                actual = wave[{"wave_price": "price", "wave_dif": "dif"}[fact]] if wave else None
            elif fact in ("wave_price_at", "wave_dif_at"):
                actual, expected = wave[{"wave_price_at": "price_at", "wave_dif_at": "dif_at"}[fact]] if wave else None, when(expected)
            elif fact == "completed_same_color_count":
                actual = len(state["history"][str(wave["sign"])]) if wave else 0
            elif fact == "pool_starts":
                actual = tuple(w["start"] for w in state["history"][str(wave["sign"])]) if wave else ()
                expected = tuple(when(i) for i in expected)
            elif fact == "old_wave_end":
                old = step["stateBefore"]["wave"]
                actual, expected = state["history"][str(old["sign"])][-1]["end"], when(expected)
            elif fact == "top_history_exists":
                actual = top is not None
            elif fact in ("top_history.status", "top_history.end_reason", "top_history.price", "top_history.price_at", "top_history.original_reference", "top_history.confirmed_event"):
                if top is None:
                    raise MigrationError(fact_path + ": missing history")
                key = {"status": "status", "end_reason": "endReason", "price": "pricePeak", "price_at": "pricePeakAt", "original_reference": "originalReference"}.get(fact.split(".")[1])
                if fact.endswith("confirmed_event"):
                    event = linked_event(expected, "STRUCTURE")
                    actual, expected = top["id"], event["relatedTopHistoryId"]
                else:
                    actual = top[key]
                    if fact.endswith("price_at"):
                        expected = when(expected)
                    elif fact.endswith("original_reference"):
                        expected = _reference(case, record, expected)
            elif fact in ("bottom_history.price", "bottom_history.price_at", "bottom_history.original_reference", "bottom_history.structure_event", "bottom_history.end_reason", "bottom_history.left_origin_at"):
                if bottom is None:
                    raise MigrationError(fact_path + ": missing history")
                key = {"price": "priceLow", "price_at": "priceLowAt", "original_reference": "originalReference", "structure_event": "structureEventId", "end_reason": "endReason", "left_origin_at": "leftOriginAt"}[fact.split(".")[1]]
                actual = bottom[key]
                if fact.endswith(("price_at", "left_origin_at")):
                    expected = when(expected)
                elif fact.endswith("original_reference"):
                    expected = _reference(case, record, expected)
                elif fact.endswith("structure_event"):
                    expected = linked_event(expected, "STRUCTURE")["id"]
            elif fact in ("wait.status", "wait.reference", "wait.nearest_price", "wait.structure_event", "wait.disappeared_event", "wait.end_reason"):
                if wait is None:
                    raise MigrationError(fact_path + ": missing wait")
                suffix = fact.split(".")[1]
                if suffix == "disappeared_event":
                    event = linked_event(expected, "STRUCTURE_DISAPPEARED")
                    actual, expected = wait["id"], event["relatedRearmId"]
                    _equal(wait["disappearedAt"], event["time"], fact_path + "/time")
                elif suffix == "reference":
                    ref = wait["referenceWave"]
                    actual = dict(startTime=ref["start"], endTime=ref["end"], price=ref["price"], dif=ref["dif"])
                    expected = _reference(case, record, expected)
                else:
                    key = {"status": "status", "nearest_price": "nearestPriceGate", "structure_event": "structureEventId", "end_reason": "endReason"}[suffix]
                    actual = wait[key]
                    if suffix == "structure_event":
                        expected = linked_event(expected, "STRUCTURE")["id"]
            elif fact.startswith("original_event@") and fact.endswith(".reference"):
                at = int(fact[len("original_event@"):].split(".")[0])
                actual = _event_at(record, at, check.at)["eventReference"]
                expected = _reference(case, record, expected)
            elif fact.startswith("preserve_event@"):
                at = int(fact[len("preserve_event@"):])
                event = _event_at(record, at, check.at)
                actual = any(e["id"] == event["id"] for s in observed for e in s["events"])
            elif fact.startswith("event@") and fact.endswith((".related_wait", ".related_bottom_history")):
                at = int(fact[len("event@"):].split(".")[0])
                event = _event_at(record, at, check.at)
                actual = event["relatedRearmId" if fact.endswith(".related_wait") else "relatedBottomHistoryId"]
                if expected is not None:
                    if not expected.startswith("wait@") or not fact.endswith(".related_wait"):
                        raise MigrationError("unsupported P1 relation token")
                    at = int(expected[len("wait@"):])
                    if at > check.at:
                        raise MigrationError("future P1 wait relation")
                    expected = _one(record["steps"][at - 1]["rearmRecords"], "P1 wait")["id"]
            else:
                raise MigrationError(fact_path + ": unknown P1 fact")
            _equal(actual, expected, fact_path)


def _freeze(value):
    if type(value) is dict:
        return tuple((key, _freeze(item)) for key, item in sorted(value.items()))
    if type(value) is list:
        return tuple(map(_freeze, value))
    return value


def _index(record, budget):
    """Index first creation, immutable origin and all typed references."""
    objects, kinds, created, occurrences, events_at = {}, {}, {}, {}, {}
    structures = {}
    for i, step in enumerate(record["steps"]):
        budget.check()
        events_at[i] = step["events"]
        for group in ("events", "histories", "bottomHistories", "rearmRecords"):
            local = set()
            for obj in step[group]:
                ident = obj["id"]
                if ident in local:
                    raise MigrationError(f"bar={i + 1}/{group}: duplicate ID")
                local.add(ident)
                if ident in kinds:
                    if kinds[ident] != group:
                        raise MigrationError(f"bar={i + 1}: ID reused across types")
                    if group == "events":
                        raise MigrationError(f"bar={i + 1}: event ID repeated")
                    first = objects[ident]
                    mutable = {"status", "endedAt", "endReason", "observedThrough", "ageBars", "negativeBars", "zeroBars", "colorChanges", "leftOriginAt"}
                    if {k: v for k, v in first.items() if k not in mutable} != {k: v for k, v in obj.items() if k not in mutable}:
                        raise MigrationError(f"bar={i + 1}: changed immutable history origin")
                else:
                    kinds[ident], objects[ident], created[ident] = group, obj, i
                occurrences.setdefault(ident, set()).add(_freeze(obj))
                if group == "events" and obj["type"] == "STRUCTURE":
                    structure_key = (obj["direction"], obj["time"], obj["route"], _freeze(obj["eventReference"]))
                    structures.setdefault(structure_key, []).append(obj)
    expected_types = {"pendingTopHistoryId": "histories", "relatedTopHistoryId": "histories", "pendingBottomHistoryId": "bottomHistories",
                      "relatedBottomHistoryId": "bottomHistories", "bottomHistoryId": "bottomHistories", "pendingRearmId": "rearmRecords",
                      "relatedRearmId": "rearmRecords", "structureEventId": "events"}

    def references(value, i, path):
        if type(value) is dict:
            for key, item in value.items():
                if key in expected_types and item is not None:
                    if item not in objects or kinds[item] != expected_types[key]:
                        raise MigrationError(f"bar={i + 1}/{path}.{key}: hanging or wrong-type ID")
                    if created[item] > i:
                        raise MigrationError(f"bar={i + 1}/{path}.{key}: future ID")
                    if key == "structureEventId" and objects[item]["type"] != "STRUCTURE":
                        raise MigrationError(f"bar={i + 1}/{path}.{key}: target is not STRUCTURE")
                references(item, i, path + "." + key)
        elif type(value) is list:
            for item in value:
                references(item, i, path)

    for i, step in enumerate(record["steps"]):
        references(step, i, "step")
        # stateBefore must not refer to objects only created on this bar.
        if i == 0:
            empty = dict(wave=None, history={"1": [], "-1": []}, state="NONE", reference=None,
                         previous=None, processed=0, pending=None, pendingBottomHistory=None, pendingRearm=None)
            if step["stateBefore"] != empty:
                raise MigrationError("bar=1/stateBefore: not empty")
        for key, group, pending in (("pendingTopHistoryId", "histories", "pending"), ("pendingBottomHistoryId", "bottomHistories", "pendingBottomHistory"), ("pendingRearmId", "rearmRecords", "pendingRearm")):
            obj = step["stateAfter"][pending]
            if step["point"][key] != (obj["id"] if obj else None):
                raise MigrationError(f"bar={i + 1}/point.{key}: progress reference differs")
            if obj is not None and _freeze(obj) not in occurrences.get(obj["id"], ()):
                raise MigrationError(f"bar={i + 1}/{pending}: absent history update")
    del references

    origins = {}
    for ident, event in objects.items():
        if kinds[ident] != "events" or event["type"] == "RESEARCH_HISTORICAL_WITHDRAWAL":
            continue
        i = created[ident]
        sign = 1 if event["direction"] == "TOP" else -1
        candidates = {state["wave"]["start"] for state in (record["steps"][i]["stateBefore"], record["steps"][i]["stateAfter"])
                      if state["wave"] is not None and state["wave"]["sign"] == sign}
        origins[ident] = _one(list(candidates), f"bar={i + 1}/event origin")
    structure_for_history = {}
    for ident, obj in objects.items():
        group = kinds[ident]
        if group not in ("histories", "bottomHistories"):
            continue
        direction = "TOP" if group == "histories" else "BOTTOM"
        candidates = structures.get((direction, obj["confirmedAt"], obj["confirmationRoute"],
                                     _freeze(obj["originalReference"])), [])
        event = _one(candidates, "history original STRUCTURE")
        expected_field = "relatedTopHistoryId" if direction == "TOP" else "relatedBottomHistoryId"
        if event[expected_field] != ident or created[event["id"]] != created[ident]:
            raise MigrationError("history and STRUCTURE association differs")
        if group == "bottomHistories" and (obj["structureEventId"] != event["id"] or obj["originSegmentStart"] != origins[event["id"]]):
            raise MigrationError("BOTTOM original STRUCTURE differs")
        structure_for_history[ident] = event["id"]
    for ident, obj in objects.items():
        if kinds[ident] == "rearmRecords":
            bottom = objects[obj["bottomHistoryId"]]
            structure = objects[obj["structureEventId"]]
            disappearance = _one([e for e in events_at[created[ident]] if e["type"] == "STRUCTURE_DISAPPEARED" and e["relatedRearmId"] == ident], "wait disappearance")
            ref = obj["referenceWave"]
            ref_value = dict(startTime=ref["start"], endTime=ref["end"], price=ref["price"], dif=ref["dif"])
            if (structure_for_history[obj["bottomHistoryId"]] != obj["structureEventId"]
                    or obj["structureConfirmedAt"] != structure["time"] or obj["structureRoute"] != structure["route"]
                    or obj["segmentStart"] != bottom["originSegmentStart"] or obj["disappearedAt"] != disappearance["time"]
                    or disappearance["relatedBottomHistoryId"] != bottom["id"] or ref_value != bottom["originalReference"]):
                raise MigrationError("wait original associations differ")
        if kinds[ident] == "events" and obj["type"] == "RESEARCH_HISTORICAL_WITHDRAWAL":
            related = obj["relatedTopHistoryId"] if obj["direction"] == "TOP" else obj["relatedBottomHistoryId"]
            if related not in structure_for_history:
                raise MigrationError("withdrawal lacks original history")
            history = objects[related]
            if obj["eventReference"] != history["originalReference"]:
                raise MigrationError("withdrawal reference differs from original")
            origins[ident] = origins[structure_for_history[related]]
    return objects, kinds, created, origins, structure_for_history


def _event_key(event, origin):
    return (event["time"], event["type"], event["direction"], event["route"], _freeze(event["eventReference"]), origin)


def _pair_unique(old_items, new_items, key, mapping, label):
    left, right = {}, {}
    used_old = set(mapping.values())
    for items, index in ((old_items, left), (new_items, right)):
        for ident in items:
            value = key(ident, items is new_items)
            if value in index:
                raise MigrationError(label + ": ambiguous mapping")
            index[value] = ident
    if set(left) != set(right):
        raise MigrationError(label + ": missing mapping")
    for value, old in left.items():
        new = right[value]
        if new in mapping or old in used_old:
            raise MigrationError(label + ": non-bijective mapping")
        mapping[new] = old
        used_old.add(old)


def compare_records(old, new, budget=None, retained=()):
    """Replace only declared IDs in a comparison copy, then compare every value."""
    budget = budget or protocol.Budget()
    retained = retained if isinstance(retained, protocol.RetainedSize) else protocol.RetainedSize(retained, budget=budget)
    protocol.validate_record(old, budget)
    protocol.validate_record(new, budget)
    a, b = _index(old, budget), _index(new, budget)
    mapping = {}
    retained.check(old, new, a, b, mapping)
    def ordinary(side):
        return [ident for ident, kind in side[1].items() if kind == "events"
                and side[0][ident]["type"] not in ("RESEARCH_HISTORICAL_WITHDRAWAL", "STRUCTURE_DISAPPEARED")
                and side[0][ident]["route"] != "reactivation"]
    _pair_unique(ordinary(a), ordinary(b), lambda ident, right: _event_key((b if right else a)[0][ident], (b if right else a)[3][ident]), mapping, "ordinary event")
    for group in ("histories", "bottomHistories"):
        left, right = ([ident for ident, kind in side[1].items() if kind == group] for side in (a, b))
        _pair_unique(left, right, lambda ident, right: mapping[(b if right else a)[4][ident]] if right else a[4][ident], mapping, group)
    left, right = ([ident for ident, kind in side[1].items() if kind == "rearmRecords"] for side in (a, b))
    def wait_key(ident, right):
        obj = (b if right else a)[0][ident]
        return ((mapping[obj["structureEventId"]], mapping[obj["bottomHistoryId"]]) if right else (obj["structureEventId"], obj["bottomHistoryId"])) + (obj["disappearedAt"], obj["segmentStart"])
    _pair_unique(left, right, wait_key, mapping, "wait")
    mapped_old = set(mapping.values())
    left, right = ([ident for ident, kind in side[1].items() if kind == "events" and ident not in (mapped_old if side is a else mapping)] for side in (a, b))
    def related_key(ident, right):
        side = b if right else a
        obj = side[0][ident]
        refs = tuple(mapping[obj[k]] if right and obj[k] is not None else obj[k] for k in ("relatedTopHistoryId", "relatedBottomHistoryId", "relatedRearmId"))
        return _event_key(obj, side[3][ident]) + refs
    _pair_unique(left, right, related_key, mapping, "associated event")
    if len(mapping) != len(a[0]) or len(mapping) != len(b[0]):
        raise MigrationError("incomplete ID mapping")
    copied = deepcopy(new)
    retained.check(old, new, a, b, mapping, copied)
    visited = 0
    def replace(value):
        nonlocal visited
        visited += 1
        if visited % 256 == 0:
            budget.check()
        if type(value) is dict:
            for key, item in value.items():
                if key in protocol.ID_FIELDS and item is not None:
                    if item not in mapping:
                        raise MigrationError("unmapped ID reference")
                    value[key] = mapping[item]
                else:
                    replace(item)
        elif type(value) is list:
            for item in value:
                replace(item)
    replace(copied)
    del replace
    budget.check()
    difference = _first_difference(old, copied)
    if difference is not None:
        raise MigrationError(f"case={old['caseName']}/period={old['period']}/{difference}")


def _first_difference(a, b, path=""):
    if type(a) is dict and type(b) is dict:
        if set(a) != set(b):
            return path + ": fields differ"
        for key in a:
            difference = _first_difference(a[key], b[key], path + "/" + key)
            if difference:
                return difference
        return None
    if type(a) is list and type(b) is list:
        if len(a) != len(b):
            return path + ": count differs"
        for i, (left, right) in enumerate(zip(a, b, strict=True)):
            difference = _first_difference(left, right, path + (f"/bar={i + 1}" if path.endswith("steps") else f"/{i}"))
            if difference:
                return difference
        return None
    return None if a == b and (type(a) is bool) == (type(b) is bool) else path + ": value differs"


def capture_baseline():
    budget = protocol.Budget()
    with budget.interrupt_at_deadline():
        with budget.stage("capture inputs"):
            cases = artificial_inputs()
            protocol.validate_inputs(cases, budget)
        # Importing this disposable module exposes constants only.  Its old
        # algorithm modules are loaded solely inside the separate interpreter.
        with budget.stage("capture source identity"):
            from .xxm_product_v1_migration_capture import (
                BASELINE_COMMIT, SOURCE_BLOBS, SOURCE_BYTES, R2_SPEC_FIELDS, R4_SPEC_FIELDS,
                R2_SPEC_HASH, R4_RESEARCH_HASH,
            )
        result, _ = _run_child(CAPTURE_MODULE, cases, budget, ())
        with budget.stage("capture metadata"):
            protocol.fields(result, {"records", "metadata"}, "capture result")
            metadata = result["metadata"]
            protocol.fields(metadata, {"algorithmVersion", "specHash", "researchVersion", "researchHash", "identities",
                                       "commit", "sourceReads", "sourceBytes"}, "capture metadata")
            if (metadata["algorithmVersion"] != R2_SPEC_FIELDS["algorithm_version"]
                    or metadata["researchVersion"] != R4_SPEC_FIELDS["research_version"]
                    or metadata["specHash"] != R2_SPEC_HASH or metadata["researchHash"] != R4_RESEARCH_HASH
                    or metadata["commit"] != BASELINE_COMMIT
                    or metadata["sourceReads"] != dict.fromkeys(SOURCE_BLOBS, 1)
                    or any(type(value) is not int for value in metadata["sourceReads"].values())
                    or type(metadata["sourceBytes"]) is not int or metadata["sourceBytes"] != SOURCE_BYTES):
                raise MigrationError("capture source identity differs")
            for key in ("specHash", "researchHash"):
                if (type(metadata[key]) is not str or len(metadata[key]) != 64
                        or any(char not in "0123456789abcdef" for char in metadata[key])):
                    raise MigrationError("capture algorithm hash differs")
            records, identities = result["records"], metadata["identities"]
            if type(records) is not list or len(records) != 148 or type(identities) is not list or len(identities) != 148:
                raise MigrationError("capture case count differs")
            retained = protocol.RetainedSize(cases, result, budget=budget)
        for index, (case, record, identity) in enumerate(zip(cases, records, identities, strict=True)):
            with budget.stage("capture validation", case):
                protocol.validate_record(record, budget)
                if any(record[key] != case[key] for key in protocol.CASE_FIELDS):
                    raise MigrationError("capture input/order differs")
                expected = dict(caseName=case["caseName"], period=case["period"], inputIdentity=case["sourceIdentity"],
                                sourceIdentity=f"r4|{metadata['researchHash']}|{case['period']}|{case['sourceIdentity']}")
                if identity != expected:
                    raise MigrationError("capture per-case identity differs")
                indexed = _index(record, budget)
                retained.check(indexed)
                del indexed
                assert_case_facts(CASES[index % 37], record, budget)
        with budget.stage("capture final checks"):
            protocol.bounded_size(cases, result)
            # Drop the accounting registry before collecting the real retained
            # graph, and keep collection inside this same capture deadline.
            del retained, cases, case, record, identity, expected
            gc.collect()
        result["seconds"] = 0.0
        budget.timings["capture ready"] = 0.0
        result["timings"] = budget.timings
        protocol.bounded_size(result)
        with budget.stage("capture ready"):
            print("CAPTURE_READY cases=148 periods=day,m60,m90,m120", flush=True)
        result["seconds"] = time.monotonic() - budget.started
        protocol.bounded_size(result)
        budget.check()
        result["seconds"] = time.monotonic() - budget.started
        return result


def _signal_group(child, sig):
    # Reap an already exited leader first. Still signal the group: descendants
    # can outlive the leader, and a permission error must remain a failure.
    child.poll()
    try:
        os.killpg(child.pid, sig)
    except ProcessLookupError:
        pass


def _reap(child, budget):
    """Use the reserved second, never append a fresh timeout after the phase."""
    # The work alarm must not interrupt closing/reaping.  All blocking waits
    # below use the same absolute cleanup deadline and never a new allowance.
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    if old_timer[0]:
        signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        for pipe in (child.stdin, child.stdout, child.stderr):
            if pipe is not None:
                pipe.close()
        _signal_group(child, signal.SIGTERM)
        if child.poll() is None:
            remaining = max(0, budget.end - time.monotonic())
            try:
                child.wait(timeout=min(.4, remaining / 2))
            except subprocess.TimeoutExpired:
                pass
        # Also terminate any Git descendant left in the child's own group,
        # even if the direct child has already exited.
        _signal_group(child, signal.SIGKILL)
        child.wait(timeout=max(.000001, budget.end - time.monotonic()))
    finally:
        if old_timer[0] and time.monotonic() < budget.work_end:
            signal.setitimer(signal.ITIMER_REAL, budget.work_end - time.monotonic())


def _run_child(module, cases, budget, retained):
    if module not in (WORKER_MODULE, CAPTURE_MODULE):
        raise MigrationError("unknown disposable child")
    protocol.validate_inputs(cases, budget)
    phase = "formal" if module == WORKER_MODULE else "capture"
    retained = retained if isinstance(retained, protocol.RetainedSize) else protocol.RetainedSize(retained, budget=budget)
    retained.add(cases)
    with budget.stage(phase + " input encoding"):
        request = protocol.encode(cases, budget, retained=retained)
    child = None
    output, errors = bytearray(), bytearray()
    retained.check_buffers(request, output, errors)
    selector = selectors.DefaultSelector()
    try:
        budget.check()
        child = subprocess.Popen([sys.executable, "-B", "-m", module, str(budget.work_end), str(budget.end)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        for stream in (child.stdin, child.stdout, child.stderr):
            os.set_blocking(stream.fileno(), False)
        selector.register(child.stdin, selectors.EVENT_WRITE, "stdin")
        selector.register(child.stdout, selectors.EVENT_READ, "stdout")
        selector.register(child.stderr, selectors.EVENT_READ, "stderr")
        offset = 0
        with budget.stage(phase + " child and pipes"):
            while selector.get_map():
                budget.check()
                if child.poll() not in (None, 0):
                    try:
                        extra = os.read(child.stderr.fileno(), protocol.MAX_STDERR + 1)
                    except BlockingIOError:
                        extra = b""
                    if len(errors) + len(extra) > protocol.MAX_STDERR:
                        raise MigrationError("worker stderr exceeded limit")
                    errors.extend(extra)
                    detail = errors.decode("utf-8", errors="replace")[:500].strip()
                    raise MigrationError("worker exited nonzero" + (": " + detail if detail else ""))
                for key, _mask in selector.select(max(0, min(.05, budget.work_end - time.monotonic()))):
                    stream, kind = key.fileobj, key.data
                    if kind == "stdin":
                        try:
                            written = os.write(stream.fileno(), memoryview(request)[offset:offset + 65536])
                        except BrokenPipeError as exc:
                            raise MigrationError("worker closed input early") from exc
                        offset += written
                        if offset == len(request):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            selector.unregister(stream)
                            continue
                        target, limit = (output, protocol.MAX_BYTES) if kind == "stdout" else (errors, protocol.MAX_STDERR)
                        if len(target) + len(chunk) > limit:
                            raise MigrationError(f"worker {kind} exceeded limit")
                        target.extend(chunk)
                        del chunk
                        retained.check_buffers(request, output, errors)
            budget.check()
            if child.wait(timeout=max(.000001, budget.work_end - time.monotonic())) != 0 or errors:
                detail = errors.decode("utf-8", errors="replace")[:500].strip()
                raise MigrationError("worker failed or wrote stderr" + (": " + detail if detail else ""))
        del request
        with budget.stage(phase + " result decoding"):
            result = protocol.decode(output, budget)
            retained.check(output, errors, result)
        return result, len(output)
    finally:
        selector.close()
        if child is not None:
            cleanup_started = time.monotonic()
            try:
                _reap(child, budget)
            finally:
                name = phase + " child cleanup"
                budget.timings[name] = budget.timings.get(name, 0.0) + time.monotonic() - cleanup_started


def run_worker(cases, budget, retained):
    """The formal child receives input bars only and never imports capture."""
    return _run_child(WORKER_MODULE, cases, budget, retained)


def compare_baseline(baseline, *, release_baseline=False):
    budget = protocol.Budget()
    with budget.interrupt_at_deadline():
        with budget.stage("formal inputs"):
            cases = [{k: record[k] for k in protocol.CASE_FIELDS} for record in baseline["records"]]
            retained = protocol.RetainedSize(baseline, cases, budget=budget)
        result, result_bytes = run_worker(cases, budget, retained)
        with budget.stage("formal identity"):
            protocol.fields(result, {"algorithmVersion", "specHash", "tsCode", "records"}, "worker result")
            if (result["algorithmVersion"] != "xxm-direction-v0.1-r4" or result["tsCode"] != "000001.SH"
                    or result["specHash"] != protocol.formal_hash()):
                raise MigrationError("worker formal identity differs")
            records = result["records"]
            if type(records) is not list or len(records) != 148:
                raise MigrationError("worker case count differs")
            retained.add(result)
        for i, (old, new) in enumerate(zip(baseline["records"], records, strict=True)):
            try:
                with budget.stage("formal independent facts", old):
                    protocol.validate_record(new, budget)
                    if any(new[key] != old[key] for key in protocol.CASE_FIELDS):
                        raise MigrationError("input/order differs")
                    assert_case_facts(CASES[i % 37], new, budget)
                with budget.stage("formal exact comparison", old):
                    compare_records(old, new, budget, retained=retained)
            except (ValueError, KeyError, TypeError) as exc:
                raise MigrationError(f"case={old['caseName']}/period={old['period']}/{exc}") from exc
        with budget.stage("formal final checks"):
            if protocol.bounded_size(baseline, cases, result) != retained.total:
                raise MigrationError("retained accounting differs")
            summary = dict(cases=148, periods=",".join(PERIODS), seconds=0.0, resultBytes=result_bytes,
                           algorithmVersion=result["algorithmVersion"], specHash=result["specHash"])
            del retained, cases, result, records, old, new
            if release_baseline:
                baseline.clear()
            gc.collect()
        summary["timings"] = dict(budget.timings)
        protocol.bounded_size(baseline, summary)
        budget.check()
        summary["seconds"] = time.monotonic() - budget.started
        return summary


def read_command(stream):
    line = stream.readline(64)
    if line == "compare\n":
        return "compare"
    if line in ("", "abort\n"):
        return "abort"
    raise MigrationError("expected one line: compare or abort")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    if not sys.dont_write_bytecode:
        parser.error("start this disposable verifier with python -B")
    baseline = None
    try:
        baseline = capture_baseline()
        if read_command(sys.stdin) == "abort":
            print("ABORT cases=148", flush=True)
            return 2
        capture_seconds = baseline["seconds"]
        capture_stages = ",".join(f"{name}:{seconds:.3f}" for name, seconds in baseline.get("timings", {}).items())
        source_summary = ""
        if "metadata" in baseline:
            source_summary = (f" commit={baseline['metadata']['commit']} sourceBytes={baseline['metadata']['sourceBytes']} sourceReads="
                              + ",".join(f"{path}:{count}" for path, count in baseline["metadata"]["sourceReads"].items()))
        summary = compare_baseline(baseline, release_baseline=True)
        baseline = None
        compare_stages = ",".join(f"{name}:{seconds:.3f}" for name, seconds in summary["timings"].items())
        print(f"PASS cases=148 periods={summary['periods']} captureSeconds={capture_seconds:.3f} compareSeconds={summary['seconds']:.3f} resultBytes={summary['resultBytes']} captureStages={capture_stages} compareStages={compare_stages}{source_summary}", flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f"FAIL {type(exc).__name__}: {str(exc)[:600]}", file=sys.stderr, flush=True)
        return 1
    finally:
        if baseline is not None:
            baseline.clear()
            gc.collect()


if __name__ == "__main__":
    raise SystemExit(main())
