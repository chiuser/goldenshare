"""LLD 4.1, RC70–72: literal progress, causal copying and atomic rejection.

The snapshot fixtures below spell out the producer contract independently.
Only the registered hash/ID formula is computed; no calculator output supplies
business expected values. Round-trip sequences use LLD RC case inputs.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone
from src.biz.services.wealth.market.index_detail_xxm.snapshot_validation import (
    parse_xxm_snapshot, validate_structure_record, validate_xxm_progress,
)
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar

PERIODS = ("day", "m60", "m90", "m120")
DATES = ("2023-01-03", "2023-01-04", "2023-01-05", "2023-01-06", "2023-01-09",
         "2023-01-10", "2023-01-11", "2023-01-12", "2023-01-13", "2023-01-16",
         "2023-01-17", "2023-01-18")
SOURCE = "r4-restore-literal"
T = ((100, 200, 2), (90, 0, -2), (101, 100, 2), (102, 100, 2))
B = ((100, -200, -2), (110, 0, 2), (99, -100, -2), (98, -100, -2))


def stamp(i, period):
    return DATES[i] if period == "day" else DATES[i] + "T15:00:00+08:00"


def ident(period, *parts):
    raw = [MAIN_SPEC.algorithm_version, MAIN_SPEC.spec_hash, "000001.SH", period, *parts]
    return hashlib.sha256("|".join(map(str, raw)).encode()).hexdigest()[:24]


def literal_wave(sign, start, end, count, price, dif, price_at, dif_at, period):
    return dict(sign=sign, start=stamp(start, period), end=stamp(end, period), count=count,
                price=price, dif=dif, price_at=stamp(price_at, period), dif_at=stamp(dif_at, period))


def bar(i, values, period):
    close, dif, hist = values
    return XxmBar(stamp(i, period), close, dif, dif - hist / 2, hist)


def literal_snapshot(period="day", *, sign=1, state="DULL"):
    raw = dict(specHash=MAIN_SPEC.spec_hash, tsCode="000001.SH", period=period,
               sourceIdentity=SOURCE, processed=0, wave=None, history={"1": [], "-1": []},
               state="NONE", reference=None, previous=None, activeStructure=None)
    if state == "EMPTY":
        return raw
    if state == "ZERO":
        raw.update(processed=2, previous=asdict(bar(1, (101, 1, 0), period)))
        return raw
    ref = literal_wave(sign, 0, 0, 1, 100, sign * 200, 0, 0, period)
    opposite = literal_wave(-sign, 1, 1, 1, 90 if sign == 1 else 110, 0, 1, 1, period)
    close = 102 if sign == 1 else 98
    current = literal_wave(sign, 2, 3, 2, close, sign * 100, 3, 2, period)
    raw.update(processed=4, wave=current, state=state, reference=deepcopy(ref),
               previous=asdict(bar(3, (close, sign * 100, sign * 2), period)))
    raw["history"][str(sign)] = [ref]
    raw["history"][str(-sign)] = [opposite]
    if state == "STRUCTURE":
        extreme = 103 if sign == 1 else 97
        event_id = ident(period, stamp(4, period), "STRUCTURE", sign, stamp(0, period))
        raw.update(processed=5, wave=literal_wave(sign, 2, 4, 3, extreme, sign * 100, 4, 2, period),
                   previous=asdict(bar(4, (extreme, sign * 99, sign * 2), period)),
                   activeStructure=dict(
                       id=ident(period, "structure", event_id), direction="TOP" if sign == 1 else "BOTTOM",
                       structureEventId=event_id, formedAt=stamp(4, period), formationRoute="dif_turn",
                       originSegmentStart=stamp(2, period),
                       originalReference=dict(startTime=stamp(0, period), endTime=stamp(0, period),
                                              price=100, dif=sign * 200, priceAt=stamp(0, period), difAt=stamp(0, period)),
                       priceExtreme=extreme, priceExtremeAt=stamp(4, period), status="ASSESSING",
                       lockedAt=None, disappearedAt=None, disappearanceReason=None))
    return raw


def new_calc(period="day", **kwargs):
    return XxmCalculator(period=period, source_identity=SOURCE, **kwargs)


def replay(values, period):
    calc = new_calc(period)
    return calc, [calc.step(bar(i, value, period)) for i, value in enumerate(values)]


def put(raw, path, value):
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("sign,state", [(1, "EMPTY"), (1, "ZERO"), (1, "DULL"), (-1, "DULL"),
                                         (1, "STRUCTURE"), (-1, "STRUCTURE")])
def test_rc71_literal_progress_restores_exactly(period, sign, state):
    raw = literal_snapshot(period, sign=sign, state=state)
    frozen = deepcopy(raw)
    calc = new_calc(period)
    calc.restore(raw)
    assert raw == frozen
    assert calc.snapshot() == frozen
    parsed = parse_xxm_snapshot(raw, expected_identity=(MAIN_SPEC.spec_hash, "000001.SH", period, SOURCE),
                                period=period, max_refs=2)
    assert parsed.processed == frozen["processed"]
    assert parsed.state == frozen["state"]
    if parsed.wave:
        parsed.wave.price += 10
        assert raw == frozen and calc.snapshot() == frozen


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("sign", [1, -1])
def test_rc71_literal_structure_is_the_actual_kernel_contract(period, sign):
    calc = new_calc(period)
    raw = literal_snapshot(period, sign=sign)
    calc.restore(raw)
    result = calc.step(bar(4, (103 if sign == 1 else 97, sign * 99, sign * 2), period))
    assert calc.snapshot() == literal_snapshot(period, sign=sign, state="STRUCTURE")
    assert result.structures[0] == literal_snapshot(period, sign=sign, state="STRUCTURE")["activeStructure"]


BAD_PATHS = [
    (("processed",), True), (("processed",), -1), (("state",), "WAITING"),
    (("specHash",), "old-r4"), (("sourceIdentity",), "different-source"),
    (("period",), "week"), (("tsCode",), "399001.SZ"),
    (("wave", "sign"), True), (("wave", "sign"), 0), (("wave", "count"), True),
    (("wave", "count"), 0), (("wave", "count"), 999),
    (("wave", "price"), 0), (("wave", "dif"), float("nan")),
    (("wave", "price_at"), "2024-01-01"), (("wave", "dif_at"), "bad-date"),
    (("reference", "dif"), float("inf")), (("reference", "price"), True),
    (("previous", "completed"), False), (("previous", "hist"), True),
    (("previous", "close"), float("nan")), (("history",), {"1": [], "-1": [], "0": []}),
    (("history",), {1: [], -1: []}), (("reference",), None),
]


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("path,value", BAD_PATHS)
def test_rc71_bad_progress_is_rejected_before_replacing_self(period, path, value):
    calc = new_calc(period)
    calc.restore(literal_snapshot(period, state="STRUCTURE"))
    before = deepcopy(calc.snapshot())
    raw = literal_snapshot(period)
    put(raw, path, value)
    incoming = deepcopy(raw)
    with pytest.raises(ValueError):
        calc.restore(raw)
    assert calc.snapshot() == before
    assert repr(raw) == repr(incoming)


@pytest.mark.parametrize("field", ["pending", "pendingBottomHistory", "pendingRearm", "activeStructure"])
def test_rc71_old_extra_or_missing_fields_are_not_defaulted(field):
    raw = literal_snapshot()
    if field == "activeStructure":
        del raw[field]
    else:
        raw[field] = None
    calc = new_calc()
    before = calc.snapshot()
    with pytest.raises(ValueError):
        calc.restore(raw)
    assert calc.snapshot() == before


STRUCTURE_BAD_PATHS = [
    (("id",), "wrong"), (("structureEventId",), "wrong"), (("direction",), "BOTTOM"),
    (("formationRoute",), "color_flip"), (("status",), "LOCKED"),
    (("status",), "DISAPPEARED"), (("lockedAt",), "2023-01-10"),
    (("disappearedAt",), "2023-01-10"), (("disappearanceReason",), "dif_return"),
    (("formedAt",), "2023-01-10"), (("originSegmentStart",), "2023-01-04"),
    (("priceExtreme",), float("nan")), (("priceExtreme",), True), (("priceExtreme",), 0),
    (("priceExtremeAt",), "2023-01-04"),
    (("originalReference", "priceAt"), "2023-01-04"),
    (("originalReference", "difAt"), "2023-01-04"),
    (("originalReference", "price"), 99), (("originalReference", "dif"), 199),
]


@pytest.mark.parametrize("path,value", STRUCTURE_BAD_PATHS)
def test_rc71_active_structure_shape_chronology_and_ids_are_strict(path, value):
    calc = new_calc()
    calc.restore(literal_snapshot(state="STRUCTURE"))
    before = calc.snapshot()
    raw = literal_snapshot(state="STRUCTURE")
    put(raw["activeStructure"], path, value)
    with pytest.raises(ValueError):
        calc.restore(raw)
    assert calc.snapshot() == before


def test_rc71_reference_dates_required_and_full_wave_identity_matters():
    calc = new_calc()
    raw = literal_snapshot(state="STRUCTURE")
    del raw["activeStructure"]["originalReference"]["difAt"]
    with pytest.raises(ValueError):
        calc.restore(raw)
    raw = literal_snapshot()
    # Same price/DIF but a different complete historical Wave cannot be substituted.
    raw["reference"]["count"] = 2
    with pytest.raises(ValueError):
        calc.restore(raw)


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("sign", [1, -1])
def test_rc71_price_recovery_dif_equality_and_legal_rewind_are_accepted(period, sign):
    calc = new_calc(period)
    raw = literal_snapshot(period, sign=sign)
    # Existing DULL is allowed on the inside/equal side of the original price gate.
    raw.update(processed=5, previous=asdict(bar(4, (99 if sign == 1 else 101, sign * 200, sign * 2), period)))
    raw["wave"].update(end=stamp(4, period), count=3, dif=sign * 200, dif_at=stamp(4, period))
    calc.restore(raw)
    assert calc.state == "DULL"
    assert calc.previous.close == (99 if sign == 1 else 101)
    calc.step(bar(5, (103 if sign == 1 else 97, sign * 200.01, sign * 2), period))
    assert calc.state == "NONE"  # RC45: the first strict break cancels.
    calc.restore(raw)            # A genuinely earlier, valid prefix is legal.
    assert calc.processed == 5
    calc.restore(literal_snapshot(period, state="EMPTY"))
    assert calc.processed == 0 and calc.wave is None


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("values", [
    T + ((103, 99, 2), (99, 100, 2), (104, 99, 2), (98, 100, 2)),
    B + ((97, -99, -2), (101, -100, -2), (96, -99, -2), (102, -100, -2)),
    T + ((103, 99, 2), (90, 0, -2), (110, 95, 2), (111, 96, 2), (112, 95, 2), (100, 94, -2)),
    B + ((97, -99, -2), (110, 0, 2), (90, -95, -2), (89, -96, -2), (88, -95, -2), (100, -94, 2)),
])
def test_rc71_every_rc49_rc63_split_preserves_complete_business_steps(period, values):
    _, continuous = replay(values, period)
    for cut in range(len(values) + 1):
        first, before = replay(values[:cut], period)
        raw = first.snapshot()
        saved = deepcopy(raw)
        continued = new_calc(period)
        continued.restore(raw)
        after = [continued.step(bar(i, value, period)) for i, value in enumerate(values) if i >= cut]
        assert before + after == continuous
        assert raw == saved
        assert first.snapshot() == saved


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("sign", [1, -1])
def test_rc71_strict_break_and_only_equality_have_different_restored_memory(period, sign):
    prefix = T[:2] if sign == 1 else B[:2]
    for first_dif, expected in [(sign * 201, "NONE"), (sign * 200, "DULL")]:
        first, _ = replay(prefix + ((101 if sign == 1 else 99, first_dif, sign * 2),), period)
        resumed = new_calc(period)
        resumed.restore(first.snapshot())
        result = resumed.step(bar(3, (102 if sign == 1 else 98, sign * 100, sign * 2), period))
        assert result.point["ordinaryState"] == expected
        assert [event["type"] for event in result.events] == ([] if expected == "NONE" else ["DULL"])


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("sign", [1, -1])
def test_rc71_both_reference_breaks_survive_restoration(period, sign):
    values = (((100, 300, 2), (90, 0, -2), (120, 200, 2), (110, 0, -2),
               (131, 250, 2), (132, 250, 2), (133, 301, 2)) if sign == 1 else
              ((100, -300, -2), (110, 0, 2), (80, -200, -2), (90, 0, 2),
               (69, -250, -2), (68, -250, -2), (67, -301, -2)))
    first, _ = replay(values, period)
    resumed = new_calc(period)
    resumed.restore(first.snapshot())
    result = resumed.step(bar(7, (134 if sign == 1 else 66, sign * 190, sign * 2), period))
    assert result.point["ordinaryState"] == "NONE" and not result.events


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("sign", [1, -1])
def test_rc71_clone_and_returned_snapshots_share_no_mutable_progress(period, sign):
    calc = new_calc(period, record_decisions=True)
    calc.restore(literal_snapshot(period, sign=sign, state="STRUCTURE"))
    original = calc.snapshot()
    child = clone(calc)
    assert child.snapshot() == original
    assert child.wave is not calc.wave and child.reference is not calc.reference
    assert child.history is not calc.history and child.history[sign] is not calc.history[sign]
    assert child.active_structure is not calc.active_structure
    child.active_structure["originalReference"]["price"] += 1
    child.wave.price += 1
    exported = calc.snapshot()
    exported["history"][str(sign)][0]["price"] += 1
    exported["activeStructure"]["priceExtreme"] += 1
    assert calc.snapshot() == original
    assert calc.record_decisions is True


@pytest.mark.parametrize("status,route", [("ASSESSING", "dif_turn"), ("LOCKED", "dif_turn"),
                                         ("LOCKED", "color_flip"), ("DISAPPEARED", "dif_turn")])
def test_structure_record_validator_checks_both_live_and_terminal_contract(status, route):
    raw = literal_snapshot(state="STRUCTURE")["activeStructure"]
    raw.update(status=status, formationRoute=route)
    if status == "LOCKED":
        raw["lockedAt"] = stamp(4 if route == "color_flip" else 5, "day")
        if route == "color_flip":
            raw.update(priceExtreme=102, priceExtremeAt=stamp(3, "day"))
    if status == "DISAPPEARED":
        raw.update(disappearedAt=stamp(5, "day"), disappearanceReason="dif_return")
    before = deepcopy(raw)
    record = validate_structure_record(raw, period="day", upper=stamp(5, "day"),
                                       id_factory=lambda *parts: ident("day", *parts))
    assert record == before and raw == before
    record["originalReference"]["price"] += 1
    assert raw == before


@pytest.mark.parametrize("corruption", ["same_lock_time", "future_lock", "both_terminal_times", "old_reason", "color_flip_unlocked"])
def test_terminal_structure_invalid_transitions_are_rejected(corruption):
    raw = literal_snapshot(state="STRUCTURE")["activeStructure"]
    raw.update(status="LOCKED", lockedAt=stamp(5, "day"))
    if corruption == "same_lock_time":
        raw["lockedAt"] = raw["formedAt"]
    elif corruption == "future_lock":
        raw["lockedAt"] = stamp(6, "day")
    elif corruption == "both_terminal_times":
        raw.update(disappearedAt=stamp(5, "day"), disappearanceReason="dif_return")
    elif corruption == "old_reason":
        raw.update(status="DISAPPEARED", lockedAt=None, disappearedAt=stamp(5, "day"),
                   disappearanceReason="historical_price_break")
    else:
        raw.update(status="ASSESSING", lockedAt=None, formationRoute="color_flip")
    with pytest.raises(ValueError):
        validate_structure_record(raw, period="day", upper=stamp(5, "day"),
                                   id_factory=lambda *parts: ident("day", *parts))


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("sign", [1, -1])
def test_rc70_failure_after_event_and_structure_construction_keeps_self_and_outputs(period, sign, monkeypatch):
    prefix = T if sign == 1 else B
    calc, earlier = replay(prefix, period)
    before, returned = calc.snapshot(), deepcopy(earlier)
    original_validate = calc._validate_step
    observed = []

    def reject(result, work, item):
        original_validate(result, work, item)
        observed.append((result.events[0]["type"], result.structures[0]["status"]))
        raise ValueError("test failure after complete construction")

    monkeypatch.setattr(calc, "_validate_step", reject)
    with pytest.raises(ValueError, match="after complete construction"):
        calc.step(bar(4, (103 if sign == 1 else 97, sign * 99, sign * 2), period))
    assert observed == [("STRUCTURE", "ASSESSING")]
    assert calc.snapshot() == before and earlier == returned
    assert calc._decision_context is None
    monkeypatch.setattr(calc, "_validate_step", original_validate)
    assert calc.step(bar(4, (103 if sign == 1 else 97, sign * 99, sign * 2), period)).events[0]["type"] == "STRUCTURE"


def test_rc70_leading_zero_also_uses_final_validation_before_publication(monkeypatch):
    calc = new_calc()
    before = calc.snapshot()

    def reject(*args):
        raise RuntimeError("injected validation failure")

    monkeypatch.setattr(calc, "_validate_step", reject)
    with pytest.raises(RuntimeError, match="injected"):
        calc.step(bar(0, (100, 0, 0), "day"))
    assert calc.snapshot() == before and calc._decision_context is None


def test_bad_direct_work_validation_does_not_change_the_supplied_work():
    raw = literal_snapshot(state="STRUCTURE")
    parsed = parse_xxm_snapshot(raw, expected_identity=(MAIN_SPEC.spec_hash, "000001.SH", "day", SOURCE),
                                period="day", max_refs=2)
    parsed.active_structure["status"] = "LOCKED"
    before = deepcopy(parsed)
    with pytest.raises(ValueError):
        validate_xxm_progress(parsed, period="day", id_factory=lambda *parts: ident("day", *parts))
    assert parsed == before


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("field", ["previous_close", "previous_dif", "price_at", "dif_at", "formed_extreme"])
def test_rc71_current_wave_extremes_cannot_contradict_known_input(period, sign, field):
    raw = literal_snapshot(period, sign=sign, state="STRUCTURE")
    if field == "previous_close":
        raw["previous"]["close"] = 104 if sign == 1 else 96
    elif field == "previous_dif":
        raw["previous"]["dif"] = sign * 201  # Must not hide a real reference break behind a false Wave extreme.
    elif field == "price_at":
        raw["wave"].update(price=104 if sign == 1 else 96, price_at=stamp(4, period))
    elif field == "dif_at":
        raw["wave"]["dif_at"] = stamp(4, period)  # D100/-100 cannot occur at a known D99/-99 root.
    else:
        raw["activeStructure"]["priceExtreme"] = 104 if sign == 1 else 96
    calc = new_calc(period)
    before = calc.snapshot()
    with pytest.raises(ValueError):
        calc.restore(raw)
    assert calc.snapshot() == before


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("sign", [1, -1])
def test_rc71_structure_formed_extreme_need_not_equal_later_wave_extreme(period, sign):
    prefix = T if sign == 1 else B
    calc, _ = replay(prefix + ((103 if sign == 1 else 97, sign * 99, sign * 2),
                              (104 if sign == 1 else 96, sign * 98.5, sign * 2)), period)
    raw = calc.snapshot()
    assert raw["activeStructure"]["priceExtreme"] == (103 if sign == 1 else 97)
    assert raw["wave"]["price"] == (104 if sign == 1 else 96)
    resumed = new_calc(period)
    resumed.restore(raw)
    assert resumed.snapshot() == raw


@pytest.mark.parametrize("path,value", [
    (("rawSign",), 999), (("before", "state"), "STRUCTURE"),
    (("before", "activeStructureId"), "missing"), (("turn", "currentDif"), 0),
    (("turn", "threshold"), float("nan")),
    (("referenceChecks", 0, "checked"), 1),
    (("referenceChecks", 0, "referenceBroken"), False),
    (("selectionCalls",), [{"stage": "activation", "selected": None}]),
    (("structureId",), "wrong-structure"), (("structureStatus",), "LOCKED"),
])
def test_rc70_corrupt_constructed_decision_is_rejected_before_publication(path, value, monkeypatch):
    calc = new_calc(record_decisions=True)
    earlier = [calc.step(bar(i, values, "day")) for i, values in enumerate(T)]
    before, old_outputs = calc.snapshot(), deepcopy(earlier)
    original_finish = calc._finish_step

    def corrupt(result, work):
        finished = original_finish(result, work)
        decision = deepcopy(finished.decision)
        put(decision, path, value)
        return replace(finished, decision=decision)

    monkeypatch.setattr(calc, "_finish_step", corrupt)
    with pytest.raises(ValueError):
        calc.step(bar(4, (103, 99, 2), "day"))
    assert calc.snapshot() == before and earlier == old_outputs
    assert calc._decision_context is None


@pytest.mark.parametrize("sign", [1, -1])
def test_rc70_turn_return_cannot_publish_a_locked_structure_record(sign, monkeypatch):
    calc, earlier = replay((T if sign == 1 else B) + ((103 if sign == 1 else 97, sign * 99, sign * 2),), "day")
    before, old_outputs = calc.snapshot(), deepcopy(earlier)
    original_finish = calc._finish_structure

    def wrong_terminal(record, item, status, reason):
        result = original_finish(record, item, status, reason)
        result.update(status="LOCKED", lockedAt=item.time, disappearedAt=None, disappearanceReason=None)
        return result

    monkeypatch.setattr(calc, "_finish_structure", wrong_terminal)
    with pytest.raises(ValueError):
        calc.step(bar(5, (99 if sign == 1 else 101, sign * 100, sign * 2), "day"))
    assert calc.snapshot() == before and earlier == old_outputs


def test_rc71_unknown_restore_program_error_propagates_without_publication(monkeypatch):
    from src.biz.services.wealth.market.index_detail_xxm import snapshot_validation

    calc = new_calc()
    calc.restore(literal_snapshot())
    before = calc.snapshot()
    incoming = literal_snapshot(state="STRUCTURE")
    frozen = deepcopy(incoming)

    def fail(*args, **kwargs):
        raise RuntimeError("injected program error")

    monkeypatch.setattr(snapshot_validation, "validate_structure_record", fail)
    with pytest.raises(RuntimeError, match="injected program error"):
        calc.restore(incoming)
    assert calc.snapshot() == before and incoming == frozen


@pytest.mark.parametrize("action", ["formation", "lock"])
def test_rc70_missing_complete_structure_result_is_rejected_before_publication(action, monkeypatch):
    values = T if action == "formation" else T + ((103, 99, 2),)
    calc, earlier = replay(values, "day")
    before, old_outputs = calc.snapshot(), deepcopy(earlier)
    original_finish = calc._finish_step

    def drop_structure_and_event(result, work):
        result = original_finish(result, work)
        return replace(result, events=(), structures=())

    monkeypatch.setattr(calc, "_finish_step", drop_structure_and_event)
    item = bar(4, (103, 99, 2), "day") if action == "formation" else bar(5, (104, 98, -2), "day")
    with pytest.raises(ValueError):
        calc.step(item)
    assert calc.snapshot() == before and earlier == old_outputs


def test_rc70_missing_cancellation_event_is_rejected_before_publication(monkeypatch):
    calc, earlier = replay(T, "day")
    before, old_outputs = calc.snapshot(), deepcopy(earlier)
    original_finish = calc._finish_step

    def drop_event(result, work):
        result = original_finish(result, work)
        return replace(result, events=())

    monkeypatch.setattr(calc, "_finish_step", drop_event)
    with pytest.raises(ValueError):
        calc.step(bar(4, (103, 201, 2), "day"))
    assert calc.snapshot() == before and earlier == old_outputs


def test_rc70_constructed_decision_wave_count_rejects_bool_for_integer_one(monkeypatch):
    calc = new_calc(record_decisions=True)
    before = calc.snapshot()
    original_finish = calc._finish_step

    def corrupt(result, work):
        result = original_finish(result, work)
        decision = deepcopy(result.decision)
        assert decision["wave"]["count"] == 1
        decision["wave"]["count"] = True
        return replace(result, decision=decision)

    monkeypatch.setattr(calc, "_finish_step", corrupt)
    with pytest.raises(ValueError):
        calc.step(bar(0, (100, 10, 2), "day"))
    assert calc.snapshot() == before and calc._decision_context is None


def test_rc70_constructed_event_reference_rejects_bool_for_price_one(monkeypatch):
    prefix = ((1, 200, 2), (2, 0, -2), (2, 100, 2))
    calc, earlier = replay(prefix, "day")
    before, old_outputs = calc.snapshot(), deepcopy(earlier)
    original_finish = calc._finish_step

    def corrupt(result, work):
        result = original_finish(result, work)
        events = deepcopy(result.events)
        assert events[0]["type"] == "DULL" and events[0]["eventReference"]["price"] == 1
        events[0]["eventReference"]["price"] = True
        return replace(result, events=events)

    monkeypatch.setattr(calc, "_finish_step", corrupt)
    with pytest.raises(ValueError):
        calc.step(bar(3, (3, 100, 2), "day"))
    assert calc.snapshot() == before and earlier == old_outputs
