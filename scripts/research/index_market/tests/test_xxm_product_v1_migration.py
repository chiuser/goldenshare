"""P2 protocol-only tests; hand-written records, never actual capture.

The record field contract is calculator.snapshot / XxmStep at the P2 gate.
Lifecycle values below are literal examples checked against LLD 10.4.1.
Child-process substitutes prove bounded transport/cleanup only, not migration.
"""
from copy import deepcopy
import io
import hashlib
import os
import select
import subprocess
import sys
import time

import pytest

from . import xxm_product_v1_migration as migration
from . import xxm_product_v1_migration_worker as p
from .xxm_product_v1_cases import CASES, Check, Case

D = ("2023-01-03", "2023-01-04", "2023-01-05", "2023-01-06", "2023-01-09", "2023-01-10", "2023-01-11", "2023-01-12")
REF = dict(startTime=D[0], endTime=D[0], price=100, dif=50)


def wave(sign, start, end, count, price, dif, price_at=None, dif_at=None):
    return dict(sign=sign, start=start, end=end, count=count, price=price, dif=dif,
                price_at=price_at or end, dif_at=dif_at or end)


def empty():
    return dict(wave=None, history={"1": [], "-1": []}, state="NONE", reference=None, previous=None,
                processed=0, pending=None, pendingBottomHistory=None, pendingRearm=None)


def event(ident, at, kind, direction="TOP", route="activation", ref=None, top=None, bottom=None, wait=None, state="NONE"):
    return dict(id=ident, time=D[at - 1], direction=direction, type=kind, route=route, fromState=state,
                eventReference=deepcopy(REF if ref is None else ref), relatedTopHistoryId=top,
                relatedBottomHistoryId=bottom, relatedRearmId=wait)


def top_record(prefix="old"):
    # Literal TOP activation at4, confirmation at5, opposite-wave withdrawal at6.
    values = ((100, 50, 49, 2), (90, 0, 1, -2), (101, 40, 39, 2),
              (102, 41, 40, 2), (102, 40, 39, 2), (103, 39.9, 40.9, -2))
    bars = [dict(time=D[i], close=c, dif=d, dea=a, hist=h, completed=True) for i, (c, d, a, h) in enumerate(values)]
    red = wave(1, D[0], D[0], 1, 100, 50)
    green = wave(-1, D[1], D[1], 1, 90, 0)
    waves = [red, green, wave(1, D[2], D[2], 1, 101, 40),
             wave(1, D[2], D[3], 2, 102, 41), wave(1, D[2], D[4], 3, 102, 41, D[3], D[3]),
             wave(-1, D[5], D[5], 1, 103, 39.9)]
    top = dict(id=prefix + "-top", confirmedAt=D[4], confirmationRoute="dif_turn", pricePeak=102, pricePeakAt=D[3],
               originalReference=deepcopy(REF), status="PENDING", endedAt=None, endReason=None, observedThrough=D[4],
               ageBars=0, negativeBars=0, zeroBars=0, colorChanges=0)
    ended = dict(top, status="ENDED", endedAt=D[5], endReason="historical_price_break", observedThrough=D[5],
                 ageBars=1, negativeBars=1, colorChanges=1)
    events = [[], [], [], [event(prefix + "-dull", 4, "DULL")],
              [event(prefix + "-structure", 5, "STRUCTURE", route="dif_turn", state="DULL", top=top["id"])],
              [event(prefix + "-withdraw", 6, "RESEARCH_HISTORICAL_WITHDRAWAL", route="historical_price_break", top=top["id"])]]
    steps = []
    for i in range(6):
        before = deepcopy(steps[-1]["stateAfter"] if steps else empty())
        state = ("DULL" if i == 3 else "STRUCTURE" if i == 4 else "NONE")
        histories = [] if i < 4 else [deepcopy(top if i == 4 else ended)]
        pool = {"1": [] if i == 0 else [deepcopy(red)], "-1": [] if i < 2 else [deepcopy(green)]}
        if i == 5:
            pool["1"].append(deepcopy(waves[4]))
        after = dict(wave=deepcopy(waves[i]), history=pool, state=state, reference=deepcopy(red) if state != "NONE" else None,
                     previous=deepcopy(bars[i]), processed=i + 1, pending=deepcopy(top) if i == 4 else None,
                     pendingBottomHistory=None, pendingRearm=None)
        point = {k: bars[i][k] for k in ("time", "close", "dif", "dea", "hist")}
        point.update(ordinaryState=state, ordinaryDirection="TOP" if state != "NONE" else None,
                     activeReference=deepcopy(REF) if state != "NONE" else None, pendingTopHistoryId=top["id"] if i == 4 else None,
                     pendingBottomHistoryId=None, pendingRearmId=None)
        steps.append(dict(point=point, events=events[i], histories=histories, bottomHistories=[], rearmRecords=[],
                          stateBefore=before, stateAfter=after))
    return dict(caseName="literal_top", period="day", sourceIdentity="p1:day:literal_top", bars=bars, steps=steps)


def bottom_record(prefix="old"):
    # Literal LLD/P1 bottom sequence: structure6 -> disappearance7 -> zero rearm8.
    values = ((100, -10, -9, -2), (99, -11, -10, -2), (105, -5, -6, 2), (98, -9, -8, -2),
              (97, -9.2, -8.2, -2), (98, -8.8, -7.8, -2), (100, -9, -9, 0), (98.5, -9.2, -9.2, 0))
    bars = [dict(time=D[i], close=c, dif=d, dea=a, hist=h, completed=True) for i, (c, d, a, h) in enumerate(values)]
    green0 = wave(-1, D[0], D[0], 1, 100, -10)
    green = wave(-1, D[0], D[1], 2, 99, -11)
    red = wave(1, D[2], D[2], 1, 105, -5)
    waves = [green0, green, red, wave(-1, D[3], D[3], 1, 98, -9),
             wave(-1, D[3], D[4], 2, 97, -9.2), wave(-1, D[3], D[5], 3, 97, -9.2, D[4], D[4]),
             wave(-1, D[3], D[6], 3, 97, -9.2, D[4], D[4]), wave(-1, D[3], D[7], 3, 97, -9.2, D[4], D[4])]
    ref = dict(startTime=D[0], endTime=D[1], price=99, dif=-11)
    history = dict(id=prefix + "-bottom", structureEventId=prefix + "-structure", confirmedAt=D[5], confirmationRoute="dif_turn",
                   originSegmentStart=D[3], leftOriginAt=None, priceLow=97, priceLowAt=D[4], originalReference=deepcopy(ref),
                   status="PENDING", endedAt=None, endReason=None, observedThrough=D[5], ageBars=0)
    ended = dict(history, status="ENDED", endedAt=D[6], endReason="structure_disappeared", observedThrough=D[6], ageBars=1)
    wait = dict(id=prefix + "-wait", direction="BOTTOM", bottomHistoryId=history["id"], structureEventId=prefix + "-structure",
                structureConfirmedAt=D[5], structureRoute="dif_turn", segmentStart=D[3], nearestPriceGate=99,
                referenceWave=deepcopy(green), disappearedAt=D[6], observedThrough=D[6], status="WAITING", endedAt=None, endReason=None)
    reactivated = dict(wait, observedThrough=D[7], status="REACTIVATED", endedAt=D[7], endReason="price_requalified")
    events = [[], [], [], [], [event(prefix + "-dull", 5, "DULL", "BOTTOM", ref=ref)],
              [event(prefix + "-structure", 6, "STRUCTURE", "BOTTOM", "dif_turn", ref, bottom=history["id"], state="DULL")],
              [event(prefix + "-disappear", 7, "STRUCTURE_DISAPPEARED", "BOTTOM", "dif_return", ref, bottom=history["id"], wait=wait["id"], state="STRUCTURE")],
              [event(prefix + "-reactivated", 8, "DULL", "BOTTOM", "reactivation", ref, wait=wait["id"])]]
    steps = []
    for i in range(8):
        before = deepcopy(steps[-1]["stateAfter"] if steps else empty())
        state = "DULL" if i in (4, 7) else "STRUCTURE" if i == 5 else "NONE"
        active = state != "NONE"
        after = dict(wave=deepcopy(waves[i]), history={"1": [deepcopy(red)] if i >= 3 else [], "-1": [deepcopy(green)] if i >= 2 else []},
                     state=state, reference=deepcopy(green) if active else None, previous=deepcopy(bars[i]), processed=i + 1,
                     pending=None, pendingBottomHistory=deepcopy(history) if i == 5 else None, pendingRearm=deepcopy(wait) if i == 6 else None)
        point = {k: bars[i][k] for k in ("time", "close", "dif", "dea", "hist")}
        point.update(ordinaryState=state, ordinaryDirection="BOTTOM" if active else None, activeReference=deepcopy(ref) if active else None,
                     pendingTopHistoryId=None, pendingBottomHistoryId=history["id"] if i == 5 else None, pendingRearmId=wait["id"] if i == 6 else None)
        steps.append(dict(point=point, events=events[i], histories=[], bottomHistories=[deepcopy(history if i == 5 else ended)] if i in (5, 6) else [],
                          rearmRecords=[deepcopy(wait if i == 6 else reactivated)] if i in (6, 7) else [], stateBefore=before, stateAfter=after))
    return dict(caseName="literal_bottom", period="day", sourceIdentity="p1:day:literal_bottom", bars=bars, steps=steps)


@pytest.mark.parametrize("builder", [top_record, bottom_record])
def test_complete_mapping_changes_only_ids_and_does_not_mutate(builder):
    old, new = builder("old"), builder("new")
    before = deepcopy((old, new))
    migration.compare_records(old, new)
    assert (old, new) == before


def test_withdrawal_uses_original_top_wave_even_after_true_color_change():
    old, new = top_record(), top_record("new")
    index = migration._index(old, p.Budget())
    assert index[3]["old-withdraw"] == D[2]
    assert old["steps"][5]["stateAfter"]["wave"]["start"] == D[5]
    migration.compare_records(old, new)


@pytest.mark.parametrize("mutation,match", [
    (lambda r: r["steps"][4]["histories"][0].pop("zeroBars"), "fields"),
    (lambda r: r["steps"][4]["events"].append(deepcopy(r["steps"][4]["events"][0])), "duplicate"),
    (lambda r: r["steps"][3]["point"].update(pendingTopHistoryId="old-top"), "future"),
    (lambda r: r["steps"][4]["events"][0].update(relatedTopHistoryId="old-dull"), "wrong-type"),
    (lambda r: r["steps"][4]["events"][0].update(relatedTopHistoryId="missing"), "hanging"),
    (lambda r: r["steps"][5]["histories"][0]["originalReference"].update(dif=51), "immutable"),
    (lambda r: r["steps"][4]["histories"][0].update(id="old-structure"), "across types"),
    (lambda r: r["steps"][4]["events"].clear(), "original STRUCTURE"),
    (lambda r: r["steps"][4]["point"].update(dif=float("nan")), "input"),
])
def test_missing_ambiguous_future_hanging_cross_type_and_immutable_errors(mutation, match):
    old = top_record()
    mutation(old)
    with pytest.raises((p.MigrationError, KeyError), match=match):
        migration.compare_records(old, top_record("new"))


@pytest.mark.parametrize("field", ["pricePeak", "zeroBars", "negativeBars", "colorChanges", "endReason"])
def test_every_top_value_and_counter_is_compared_exactly(field):
    old, new = top_record(), top_record("new")
    obj = new["steps"][5]["histories"][0]
    obj[field] = "another_reason" if field == "endReason" else obj[field] + .000000000001 if field == "pricePeak" else 0
    if field == "zeroBars":
        obj[field] = 1
    with pytest.raises(p.MigrationError):
        migration.compare_records(old, new)


def test_bottom_structure_link_cannot_point_to_dull():
    old = bottom_record()
    def mutate(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "structureEventId":
                    value[key] = "old-dull"
                else:
                    mutate(item)
        elif isinstance(value, list):
            for item in value:
                mutate(item)
    mutate(old)
    with pytest.raises(p.MigrationError, match="not STRUCTURE"):
        migration.compare_records(old, bottom_record("new"))


def test_independent_bottom_facts_cover_saved_reference_ids_and_zero_reactivation():
    record = bottom_record()
    for name, stop in (("bottom_current_close_starts_waiting", 7), ("zero_day_bottom_reactivation", 8)):
        case = next(c for c in CASES if c.name == name)
        literal = deepcopy(record)
        literal["caseName"] = case.name
        literal["sourceIdentity"] = f"p1:day:{case.name}"
        literal["bars"] = literal["bars"][:stop]
        literal["steps"] = literal["steps"][:stop]
        migration.assert_case_facts(case, literal)


def test_unknown_p1_fact_is_rejected():
    record = top_record()
    check = Check(1, "NONE", None, None, facts=(("invented_fact", True),))
    case = Case(record["caseName"], (), "manual protocol counterexample", (), (), (check,))
    with pytest.raises(p.MigrationError, match="unknown P1 fact"):
        migration.assert_case_facts(case, record)


def test_literal_facts_do_not_accept_a_wrong_price():
    case = next(c for c in CASES if c.name == "bottom_current_close_starts_waiting")
    record = bottom_record()
    record["caseName"] = case.name
    record["steps"][5]["bottomHistories"][0]["priceLow"] = 98
    with pytest.raises(p.MigrationError, match="bottom_history.price"):
        migration.assert_case_facts(case, record)


def test_input_shape_order_count_dates_and_no_old_results():
    inputs = migration.artificial_inputs()
    assert len(inputs) == 148
    p.validate_inputs(inputs, p.Budget())
    bad = deepcopy(inputs)
    bad[0]["oldResult"] = {}
    with pytest.raises(p.MigrationError, match="fields"):
        p.validate_inputs(bad, p.Budget())
    bad = deepcopy(inputs)
    bad[0], bad[37] = bad[37], bad[0]
    with pytest.raises(p.MigrationError, match="period order"):
        p.validate_inputs(bad, p.Budget())
    bad = deepcopy(inputs)
    bad[0]["bars"][0]["time"] = "2023-02-30"
    with pytest.raises(p.MigrationError, match="date"):
        p.validate_inputs(bad, p.Budget())
    bad = deepcopy(inputs)
    bad[0]["bars"] *= 1001
    with pytest.raises(p.MigrationError, match="bar count"):
        p.validate_inputs(bad, p.Budget())


def test_byte_depth_nonfinite_and_memory_limits(monkeypatch):
    monkeypatch.setattr(p, "MAX_BYTES", 200)
    with pytest.raises(p.MigrationError, match="16 MiB"):
        p.encode({"x": "a" * 201}, p.Budget())
    with pytest.raises(p.MigrationError, match="16 MiB"):
        p.decode(b" " * 201, p.Budget())
    monkeypatch.setattr(p, "MAX_BYTES", 16 * 1024 * 1024)
    with pytest.raises(p.MigrationError, match="nesting"):
        p.decode(b"[" * 41 + b"]" * 41, p.Budget())
    monkeypatch.setattr(p, "MAX_JSON_NODES", 3)
    with pytest.raises(p.MigrationError, match="structure count"):
        p.decode(b"[{},{},{}]", p.Budget())
    with pytest.raises(p.MigrationError, match="non-finite"):
        p.decode(b"[NaN]", p.Budget())
    monkeypatch.setattr(p, "MAX_MEMORY", 1)
    with pytest.raises(p.MigrationError, match="256 MiB"):
        p.Budget().check()


def test_aggregate_retained_budget_counts_containers_and_shared_objects(monkeypatch):
    obj = {"large": ["q" * 1000]}
    count = p.bounded_size(obj)
    assert p.bounded_size(obj, obj) == count
    monkeypatch.setattr(p, "MAX_BYTES", count + 50)
    with pytest.raises(p.MigrationError, match="retained"):
        p.bounded_size(obj, {"new": "r" * 2000})


@pytest.mark.parametrize("command,expected", [("compare\n", "compare"), ("abort\n", "abort"), ("", "abort")])
def test_wait_command_is_one_line_and_eof_is_abort(command, expected):
    assert migration.read_command(io.StringIO(command)) == expected


def test_unknown_command_does_not_start_comparison(monkeypatch, capsys):
    monkeypatch.setattr(migration, "capture_baseline", lambda: {"records": [], "seconds": 0})
    monkeypatch.setattr(migration.sys, "stdin", io.StringIO("status\n"))
    monkeypatch.setattr(migration, "compare_baseline", lambda _: pytest.fail("must not compare"))
    assert migration.main([]) == 1
    assert "PASS" not in capsys.readouterr().out


@pytest.mark.parametrize("source,match", [
    ("import sys; sys.exit(4)", "nonzero|closed input"),
    ("import time; time.sleep(5)", "deadline"),
    ("import sys; sys.stderr.write('x' * 70000); sys.stderr.flush()", "stderr|closed input|nonzero"),
    ("import sys; sys.stdout.write('x' * 200000); sys.stdout.flush()", "retained|stdout|closed input"),
])
def test_child_failures_are_bounded_and_reaped(monkeypatch, source, match):
    original = subprocess.Popen
    children = []
    def substitute(_args, **kwargs):
        child = original([sys.executable, "-B", "-c", source], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(migration.subprocess, "Popen", substitute)
    if "200000" in source:
        monkeypatch.setattr(p, "MAX_BYTES", 100000)
        monkeypatch.setattr(migration, "artificial_inputs", lambda: [])
    inputs = migration.artificial_inputs()
    if not inputs:
        # Keep the real bounded scheduler; isolate only its input-set validator.
        monkeypatch.setattr(p, "validate_inputs", lambda *_args, **_kwargs: None)
    started = time.monotonic()
    with pytest.raises((p.MigrationError, TimeoutError), match=match):
        migration.run_worker(inputs, p.Budget(seconds=.7, reserve=.3), {})
    assert time.monotonic() - started < 1.5
    assert children and children[0].poll() is not None
    assert all(s.closed for s in (children[0].stdin, children[0].stdout, children[0].stderr))


def test_import_and_help_do_not_import_old_or_formal_engine():
    code = "import sys; from scripts.research.index_market.tests import xxm_product_v1_migration as m; assert not any(k.endswith(('index_detail_xxm.calculator', 'xxm.r4_reference_trial')) for k in sys.modules); m.main(['--help'])"
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and not any(line.startswith("CAPTURE_READY cases=") for line in result.stdout.splitlines())


def test_actual_capture_is_not_used_by_protocol_suite(monkeypatch):
    monkeypatch.setattr(migration, "capture_baseline", lambda: pytest.fail("actual capture prohibited in protocol suite"))
    # A hand-written standard record is compared; no algorithm class is loaded.
    migration.compare_records(top_record("a"), top_record("b"))


def test_substitute_child_success_reads_bounded_json_and_reaps(monkeypatch):
    original = subprocess.Popen
    children = []
    def substitute(_args, **kwargs):
        code = "import json,sys; data=sys.stdin.buffer.read(); assert len(json.loads(data)) == 148; sys.stdout.write('{\"protocolOnly\":true}')"
        child = original([sys.executable, "-B", "-c", code], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(migration.subprocess, "Popen", substitute)
    result, size = migration.run_worker(migration.artificial_inputs(), p.Budget(), {})
    assert result == {"protocolOnly": True} and size == 21
    assert children[0].poll() == 0
    assert all(s.closed for s in (children[0].stdin, children[0].stdout, children[0].stderr))


@pytest.mark.parametrize("command", ["abort\n", ""])
def test_abort_and_eof_release_retained_records_without_success(monkeypatch, capsys, command):
    retained = {"records": [top_record()], "seconds": 0}
    monkeypatch.setattr(migration, "capture_baseline", lambda: retained)
    monkeypatch.setattr(migration.sys, "stdin", io.StringIO(command))
    monkeypatch.setattr(migration, "compare_baseline", lambda _: pytest.fail("abort must not compare"))
    assert migration.main([]) == 2
    assert retained == {} and "PASS" not in capsys.readouterr().out


def test_registered_graph_is_not_rescanned_for_each_local_comparison(monkeypatch):
    # Count actual size visits, independently of wall time on this machine.
    sizes = []
    getsizeof = sys.getsizeof
    for count in (37, 74, 148):
        base = [{"value": "retained-" + str(i)} for i in range(count)]
        watched = {id(base), *(id(value) for value in base)}
        visits = []
        def measured(value, *args):
            visits.append(id(value))
            return getsizeof(value, *args)
        with monkeypatch.context() as patch:
            patch.setattr(p.sys, "getsizeof", measured)
            retained = p.RetainedSize(base)
            initial = sum(ident in watched for ident in visits)
            for i in range(count):
                retained.check({"registered": base, "local": [i, "local-" + str(i)]})
            assert sum(ident in watched for ident in visits) == initial == count + 1
            sizes.append(len(visits))
    assert sizes[1] <= 2 * sizes[0] + 10
    assert sizes[2] <= 2 * sizes[1] + 10


def test_retained_registry_counts_growth_shared_values_and_released_temporaries(monkeypatch):
    root = []
    retained = p.RetainedSize(root)
    item = {"independent": [1, 2, 3]}
    retained.add(item)
    root.append(item)
    retained.refresh(root)
    assert retained.total == p.bounded_size(root)
    for _ in range(100):
        temporary = {"shared": item, "new": [100, 200]}
        assert retained.check(temporary) == p.bounded_size(root, temporary)
        del temporary
    buffer = bytearray(b"x" * 500)
    assert retained.check_buffers(buffer, buffer) == retained.total + sys.getsizeof(buffer)
    monkeypatch.setattr(p, "MAX_BYTES", retained.total + 100)
    with pytest.raises(p.MigrationError, match="retained"):
        retained.check_buffers(buffer)


def test_json_resource_checks_are_batched_without_losing_byte_limit(monkeypatch):
    calls = []
    original = p.resource.getrusage
    monkeypatch.setattr(p.resource, "getrusage", lambda *args: (calls.append(1), original(*args))[1])
    data = p.encode([{"value": i} for i in range(5000)], p.Budget())
    assert 65536 < len(data) < 131072
    assert 1 <= len(calls) <= 4  # Byte batches and final check, not 30k tokens.


def test_encoding_checks_aggregate_live_buffers_at_each_byte_batch(monkeypatch):
    value = {"values": ["x" * 200 + str(i) for i in range(1000)]}
    retained = p.RetainedSize({"base": bytearray(100000)}, value)
    monkeypatch.setattr(p, "MAX_BYTES", retained.total + 32000)
    with pytest.raises(p.MigrationError, match="retained"):
        p.encode(value, p.Budget(), retained=retained)


@pytest.mark.parametrize("args", [[], ["1"], ["NaN", "NaN"], ["1", "1"]])
def test_formal_child_rejects_missing_or_invalid_shared_deadline(args):
    with pytest.raises(p.MigrationError, match="deadline"):
        p.child_budget(args)


def test_complete_148_case_transport_and_comparison_fits_original_budget():
    # Current formal engine on both sides is intentional: this covers real
    # full payload/transport/check cost, never old->new migration evidence.
    inputs = migration.artificial_inputs()
    budget = p.Budget()
    with budget.interrupt_at_deadline():
        sample = p.calculate(inputs, budget)
    baseline = {"records": sample["records"]}
    summary = migration.compare_baseline(baseline)
    assert summary["cases"] == 148 and summary["periods"] == "day,m60,m90,m120"
    assert summary["seconds"] < 20 and summary["resultBytes"] > 65536
    assert len(baseline["records"]) == 148
    # A change at the very end still fails full exact comparison.
    wrong = deepcopy(baseline["records"][-1])
    wrong["steps"][-1]["point"]["close"] += .001
    with pytest.raises(p.MigrationError, match="differs"):
        migration.compare_records(baseline["records"][-1], wrong)


@pytest.mark.parametrize("leader_exits", [False, True])
def test_cleanup_terminates_sleeping_descendant_even_after_leader_exits(leader_exits):
    read_fd, write_fd = os.pipe()
    source = ("import os,subprocess,sys,time; fd=int(sys.argv[1]); "
              "child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'],pass_fds=(fd,)); "
              "os.close(fd); "
              "print(child.pid,flush=True); " + ("sys.exit(0)" if leader_exits else "time.sleep(30)"))
    try:
        child = subprocess.Popen([sys.executable, "-B", "-c", source, str(write_fd)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                                 pass_fds=(write_fd,))
        os.close(write_fd)
        assert int(child.stdout.readline()) > 0
        if leader_exits:
            child.wait(timeout=2)
        budget = p.Budget(seconds=1, reserve=.5)
        migration._reap(child, budget)
        assert child.poll() is not None
        # Only the sleeping descendant holds this write end. EOF proves it
        # exited, without querying unrelated system processes or waiting on init.
        ready, _, _ = select.select([read_fd], [], [], max(0, budget.end - time.monotonic()))
        assert ready and os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)


def _synthetic_git_frame():
    body = b'"""synthetic old source, not a real calculator"""\n'
    oid = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    frame = oid.encode() + b" blob " + str(len(body)).encode() + b"\n" + body + b"\n"
    return frame, {"fake/source.py": {"oid": oid, "size": len(body)}}


def test_capture_git_protocol_and_package_checks_use_synthetic_blobs_only():
    from . import xxm_product_v1_migration_capture as capture
    frame, expected = _synthetic_git_frame()
    assert set(capture.parse_git_batch(frame, expected)) == {"fake/source.py"}
    for bad in (frame[:-2], frame + frame, frame.replace(b" blob ", b" tree "),
                frame.replace(b"synthetic", b"sYnthetic", 1), b"missing\n"):
        with pytest.raises(p.MigrationError):
            capture.parse_git_batch(bad, expected)
    capture.validate_package_source(b'"""module docs"""\npass\n')
    with pytest.raises(p.MigrationError, match="executable"):
        capture.validate_package_source(b'import os\n')
    capture.validate_parent_packages()


def test_capture_source_size_and_memory_loader_do_not_write_source_or_bytecode(monkeypatch):
    import builtins
    from types import ModuleType
    from . import xxm_product_v1_migration_capture as capture
    frame, expected = _synthetic_git_frame()
    with monkeypatch.context() as patch:
        patch.setattr(capture, "MAX_SOURCE_BYTES", 1)
        with pytest.raises(p.MigrationError, match="limit|1 MiB"):
            capture.parse_git_batch(frame, expected)
    def no_files(*args, **kwargs):
        pytest.fail("in-memory compiler must not open any source/cache file")
    monkeypatch.setattr(builtins, "open", no_files)
    module = ModuleType("synthetic_old_only")
    path = next(iter(capture.SOURCE_BLOBS))
    capture._MemoryLoader(path, b'value = 7\n', p.Budget()).exec_module(module)
    assert module.value == 7 and module.__cached__ is None
    assert module.__file__ == f"git:{capture.BASELINE_COMMIT}:{path}"


def test_capture_rejects_extra_source_dependency_and_loaded_old_module(monkeypatch):
    from . import xxm_product_v1_migration_capture as capture
    sources = {path: b'"""synthetic source"""\n' for path in capture.SOURCE_BLOBS}
    capture.validate_source_imports(sources)
    bad = dict(sources)
    bad[next(iter(bad))] = b'from src.biz.unapproved import sixth\n'
    with pytest.raises(p.MigrationError, match="dependency"):
        capture.validate_source_imports(bad)
    with pytest.raises(p.MigrationError, match="unapproved project"):
        capture.BaselineFinder(sources, p.Budget()).find_spec("src.biz.unapproved")
    monkeypatch.setitem(sys.modules, next(iter(capture._MODULES)), object())
    with pytest.raises(p.MigrationError, match="already loaded"):
        with capture.baseline_modules(sources, p.Budget()):
            pytest.fail("must reject before imports")


def test_capture_git_reads_each_fixed_blob_once_without_running_old_code(monkeypatch):
    from . import xxm_product_v1_migration_capture as capture
    frame, sample = _synthetic_git_frame()
    identity = next(iter(sample.values()))
    expected = {path: dict(identity, module=meta["module"]) for path, meta in capture.SOURCE_BLOBS.items()}
    original = subprocess.Popen
    requests = []
    def substitute(args, **kwargs):
        requests.append(args)
        # Child verifies all five unique requests. Returned sources are inert.
        code = ("import sys; r=sys.stdin.buffer.read().splitlines(); "
                "assert len(r)==len(set(r))==5; "
                "assert all(x.startswith(b'" + capture.BASELINE_COMMIT + ":') for x in r); "
                "sys.stdout.buffer.write(" + repr(frame * 5) + ")")
        return original([sys.executable, "-B", "-c", code], **kwargs)
    monkeypatch.setattr(capture, "SOURCE_BLOBS", expected)
    monkeypatch.setattr(capture, "SOURCE_BYTES", identity["size"] * 5)
    monkeypatch.setattr(capture.subprocess, "Popen", substitute)
    sources = capture.read_git_sources(p.Budget())
    assert set(sources) == set(expected)
    assert len(requests) == 1 and requests[0] == ["git", "cat-file", "--batch"]


def test_parent_uses_shared_deadline_and_bytecode_disabled_for_formal_child(monkeypatch):
    original = subprocess.Popen
    seen = []
    budget = p.Budget()
    def substitute(args, **kwargs):
        seen.append(args)
        return original([sys.executable, "-B", "-c", "import sys;sys.stdin.buffer.read();print('{}')"], **kwargs)
    monkeypatch.setattr(migration.subprocess, "Popen", substitute)
    migration.run_worker(migration.artificial_inputs(), budget, {})
    assert seen[0][:4] == [sys.executable, "-B", "-m", migration.WORKER_MODULE]
    assert list(map(float, seen[0][4:])) == [budget.work_end, budget.end]


def test_exited_leader_does_not_hide_denied_descendant_cleanup(monkeypatch):
    class ExitedLeader:
        pid = 12345
        def poll(self):
            return 0
    def denied(*args):
        raise PermissionError("cannot terminate descendant group")
    monkeypatch.setattr(migration.os, "killpg", denied)
    with pytest.raises(PermissionError, match="descendant"):
        migration._signal_group(ExitedLeader(), 15)


def test_git_cleanup_uses_reserved_time_when_term_is_ignored():
    from . import xxm_product_v1_migration_capture as capture
    source = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('READY',flush=True);time.sleep(30)"
    child = subprocess.Popen([sys.executable, "-B", "-c", source], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert child.stdout.readline() == b"READY\n"
    budget = p.Budget(seconds=.4, reserve=.1)
    try:
        with pytest.raises(p.MigrationError, match="original synthetic failure"):
            with budget.interrupt_at_deadline():
                time.sleep(.25)
                try:
                    raise p.MigrationError("original synthetic failure")
                finally:
                    capture._reap_git(child, budget)
        assert child.poll() is not None
        assert time.monotonic() < budget.end
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=1)
