"""LLD R4-16A: independent literal r2 progress, entirely in memory.

These fixtures state the snapshot producer's actual field contract explicitly.
IDs are derived independently from the registered r2 ID format, never by
calling calculator._id or by replaying the calculator to create expected data.
"""
from copy import deepcopy
import hashlib

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone
from src.biz.services.wealth.market.index_detail_xxm.snapshot_validation import parse_xxm_snapshot
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


SOURCE = "snapshot-unit"
D = ("2025-03-03", "2025-03-04", "2025-03-05", "2025-03-06", "2025-03-07",
     "2025-03-10", "2025-03-11", "2025-03-12", "2025-03-13", "2025-03-14", "2025-03-17")


def ident(*parts):
    values = [MAIN_SPEC.algorithm_version, MAIN_SPEC.spec_hash, "000001.SH", "day", *parts]
    return hashlib.sha256("|".join(map(str, values)).encode()).hexdigest()[:24]


def wave(sign, start, end, count, price, dif, price_at, dif_at):
    return dict(sign=sign, start=start, end=end, count=count, price=price, dif=dif,
                price_at=price_at, dif_at=dif_at)


def previous(stamp, close, dif, dea, hist):
    return dict(time=stamp, close=close, dif=dif, dea=dea, hist=hist, completed=True)


def empty_snapshot():
    return dict(specHash=MAIN_SPEC.spec_hash, tsCode="000001.SH", period="day", sourceIdentity=SOURCE,
                processed=0, wave=None, history={"1": [], "-1": []}, state="NONE", reference=None,
                previous=None, pending=None, pendingBottomHistory=None, pendingRearm=None)


def top_dull_snapshot():
    result = empty_snapshot()
    ref = wave(1, D[0], D[1], 2, 101, 12, D[1], D[1])
    result.update(processed=5, wave=wave(1, D[3], D[4], 2, 102, 10, D[4], D[4]),
        history={"1": [ref], "-1": [wave(-1, D[2], D[2], 1, 99, 9, D[2], D[2])]},
        state="DULL", reference=deepcopy(ref), previous=previous(D[4], 102, 10, 9, 2))
    return result


def top_structure_snapshot():
    result = top_dull_snapshot()
    result.update(processed=6, state="STRUCTURE", previous=previous(D[5], 103, 9.8, 8.8, 2),
        wave=wave(1, D[3], D[5], 3, 103, 10, D[5], D[4]), pending={
            "id": ident("history", D[5], "dif_turn", D[0]), "confirmedAt": D[5],
            "confirmationRoute": "dif_turn", "pricePeak": 103, "pricePeakAt": D[5],
            "originalReference": {"startTime": D[0], "endTime": D[1], "price": 101, "dif": 12},
            "status": "PENDING", "endedAt": None, "endReason": None, "observedThrough": D[5],
            "ageBars": 0, "negativeBars": 0, "zeroBars": 0, "colorChanges": 0})
    return result


def bottom_structure_snapshot():
    result = empty_snapshot()
    ref = wave(-1, D[0], D[0], 1, 100, -8, D[0], D[0])
    event = ident(D[4], "STRUCTURE", -1, D[0])
    result.update(processed=5, state="STRUCTURE", reference=deepcopy(ref),
        wave=wave(-1, D[2], D[4], 3, 98, -6, D[3], D[2]),
        history={"-1": [ref], "1": [wave(1, D[1], D[1], 1, 110, -4, D[1], D[1])]},
        previous=previous(D[4], 101, -5.9, -4.9, -2), pendingBottomHistory={
            "id": ident("bottom-history", event), "structureEventId": event, "confirmedAt": D[4],
            "confirmationRoute": "dif_turn", "originSegmentStart": D[2], "leftOriginAt": None,
            "priceLow": 98, "priceLowAt": D[3],
            "originalReference": {"startTime": D[0], "endTime": D[0], "price": 100, "dif": -8},
            "status": "PENDING", "endedAt": None, "endReason": None,
            "observedThrough": D[4], "ageBars": 0})
    return result


def bottom_color_flip_snapshot():
    result = bottom_structure_snapshot()
    # Five literal bars: old green, red, two new greens, then red confirms
    # the previous DULL by color_flip. The new red is outside the frozen low.
    result.update(state="NONE", reference=None,
        wave=wave(1, D[4], D[4], 1, 101, -5.9, D[4], D[4]),
        previous=previous(D[4], 101, -5.9, -6.9, 2))
    result["history"]["-1"].append(wave(-1, D[2], D[3], 2, 98, -6, D[3], D[2]))
    result["pendingBottomHistory"].update(confirmationRoute="color_flip", leftOriginAt=D[4])
    return result


def waiting_snapshot():
    result = bottom_structure_snapshot()
    event = ident(D[4], "STRUCTURE", -1, D[0])
    ref = deepcopy(result["reference"])
    result.update(processed=6, state="NONE", reference=None, pendingBottomHistory=None,
        wave=wave(-1, D[2], D[5], 4, 98, -6, D[3], D[2]),
        previous=previous(D[5], 100, -6, -5, -2), pendingRearm={
            "id": ident("rearm", event, D[5]), "direction": "BOTTOM",
            "bottomHistoryId": ident("bottom-history", event), "structureEventId": event,
            "structureConfirmedAt": D[4], "structureRoute": "dif_turn", "segmentStart": D[2],
            "nearestPriceGate": 100, "referenceWave": ref, "disappearedAt": D[5],
            "observedThrough": D[5], "status": "WAITING", "endedAt": None, "endReason": None})
    return result


def calculator():
    return XxmCalculator(period="day", source_identity=SOURCE)


def assert_bad_rejected(snapshot):
    calc = calculator()
    calc.restore(top_dull_snapshot())
    before = deepcopy(calc.snapshot())
    incoming = repr(snapshot)
    with pytest.raises(ValueError):
        calc.restore(snapshot)
    assert calc.snapshot() == before
    assert repr(snapshot) == incoming
    calc.restore(empty_snapshot())
    assert calc.processed == 0 and calc.state == "NONE"
    calc.step(XxmBar(D[0], 100, 0, 0, 0))
    assert calc.processed == 1 and calc.wave.sign == 0


@pytest.mark.parametrize("factory", [empty_snapshot, top_dull_snapshot, top_structure_snapshot,
                                     bottom_structure_snapshot, waiting_snapshot])
def test_literal_snapshot_shapes_restore_without_changing_producer_contract(factory):
    raw = factory()
    original = deepcopy(raw)
    calc = calculator()
    calc.restore(raw)
    assert calc.snapshot() == original
    assert raw == original


def test_dull_and_structure_continue_with_hand_checked_events_and_links():
    calc = calculator()
    calc.restore(top_dull_snapshot())
    result = calc.step(XxmBar(D[5], 103, 9.8, 8.8, 2))
    assert calc.snapshot() == top_structure_snapshot()
    assert [(e["type"], e["route"], e["direction"]) for e in result.events] == [("STRUCTURE", "dif_turn", "TOP")]
    assert result.events[0]["relatedTopHistoryId"] == ident("history", D[5], "dif_turn", D[0])
    assert result.histories[0]["pricePeak"] == 103 and result.histories[0]["ageBars"] == 0
    before = deepcopy(result)
    calc.step(XxmBar(D[6], 102, 9.7, 8.7, 2))
    assert result == before


def test_waiting_restore_reactivates_saved_reference_with_original_links():
    calc = calculator()
    raw = waiting_snapshot()
    calc.restore(raw)
    step = calc.step(XxmBar(D[6], 99, -6, -5, -2))
    assert step.point["ordinaryState"] == "DULL"
    assert step.point["activeReference"] == {"startTime": D[0], "endTime": D[0], "price": 100, "dif": -8}
    assert [(e["type"], e["route"]) for e in step.events] == [("DULL", "reactivation")]
    assert step.events[0]["relatedRearmId"] == raw["pendingRearm"]["id"]
    assert step.events[0]["relatedBottomHistoryId"] is None
    assert step.rearm_records[0]["status"] == "REACTIVATED"
    assert step.rearm_records[0]["bottomHistoryId"] == raw["pendingRearm"]["bottomHistoryId"]


@pytest.mark.parametrize("corruption", ["missing_history", "already_left_origin", "wrong_route", "different_reference"])
def test_bottom_structure_requires_its_original_history_before_publication(corruption):
    raw = bottom_structure_snapshot()
    if corruption == "missing_history":
        raw["pendingBottomHistory"] = None
    elif corruption == "already_left_origin":
        raw["pendingBottomHistory"]["leftOriginAt"] = D[4]
    elif corruption == "wrong_route":
        raw["pendingBottomHistory"]["confirmationRoute"] = "color_flip"
    else:
        raw["pendingBottomHistory"]["originalReference"]["dif"] = -7
    # Each altered copy is scalar/chronologically valid; the missing relation
    # would otherwise fail only on the next BOTTOM correction, after publishing.
    assert_bad_rejected(raw)


def test_top_structure_may_remain_after_its_history_has_exited():
    # March 11 closes above the frozen 103 peak without a 1% DIF turn, so the
    # TOP price history has ended but the ordinary STRUCTURE remains valid.
    raw = top_structure_snapshot()
    raw.update(processed=7, pending=None,
        wave=wave(1, D[3], D[6], 4, 104, 10, D[6], D[4]),
        previous=previous(D[6], 104, 9.75, 8.75, 2))
    calc = calculator()
    calc.restore(raw)
    assert calc.state == "STRUCTURE" and calc.pending is None
    assert calc.reference.reference() == {"startTime": D[0], "endTime": D[1], "price": 101, "dif": 12}
    step = calc.step(XxmBar(D[7], 103, 9.74, 8.74, 2))
    assert not step.events and calc.state == "STRUCTURE" and calc.pending is None


def test_parse_returns_independent_nine_progress_fields():
    raw = top_structure_snapshot()
    parsed = parse_xxm_snapshot(raw, expected_identity=(MAIN_SPEC.spec_hash, "000001.SH", "day", SOURCE),
                                period="day", max_refs=2)
    assert parsed.processed == 6 and parsed.state == "STRUCTURE"
    assert parsed.wave.price == 103 and parsed.reference.dif == 12
    assert parsed.previous.time == D[5] and parsed.pending["pricePeak"] == 103
    assert parsed.pending_bottom_history is None and parsed.pending_rearm is None
    parsed.history[1][0].price = -10
    parsed.wave.price = -11
    parsed.pending["originalReference"]["dif"] = -12
    assert raw["history"]["1"][0]["price"] == 101
    assert raw["wave"]["price"] == 103 and raw["pending"]["originalReference"]["dif"] == 12


@pytest.mark.parametrize("key,value", [("specHash", "wrong"), ("tsCode", "000002.SH"),
    ("period", "m60"), ("sourceIdentity", "other"), ("processed", True), ("processed", -1),
    ("state", "UNKNOWN"), ("wave", {}), ("history", {"1": []}), ("previous", None)])
def test_identity_shape_and_progress_corruption_are_atomic(key, value):
    raw = top_dull_snapshot()
    raw[key] = value
    assert_bad_rejected(raw)


@pytest.mark.parametrize("state", ["DULL", "STRUCTURE"])
def test_activity_without_reference_is_not_silently_repaired(state):
    raw = top_dull_snapshot() if state == "DULL" else top_structure_snapshot()
    raw["reference"] = None
    assert_bad_rejected(raw)


def test_none_with_active_reference_is_rejected():
    raw = top_dull_snapshot()
    raw["state"] = "NONE"
    assert_bad_rejected(raw)


@pytest.mark.parametrize("path", [("wave", "dif"), ("wave", "price"), ("reference", "dif"),
                                 ("reference", "price"), ("history", "1", 0, "dif")])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "10"])
def test_wave_pool_and_reference_bad_numbers_are_rejected(path, value):
    raw = top_dull_snapshot()
    current = raw
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    assert_bad_rejected(raw)


@pytest.mark.parametrize("field,value", [("count", True), ("count", 0), ("count", 7),
    ("sign", True), ("sign", 2), ("start", "2025-3-06"), ("end", D[5]), ("price_at", D[2]),
    ("dif_at", D[6])])
def test_wave_dates_count_and_direction_are_strict(field, value):
    raw = top_dull_snapshot()
    raw["wave"][field] = value
    assert_bad_rejected(raw)


def test_reference_must_be_in_its_pool_and_pool_order_remains_causal():
    raw = top_dull_snapshot()
    raw["reference"]["price"] = 100
    assert_bad_rejected(raw)
    raw = top_dull_snapshot()
    raw["history"]["1"] *= 3
    assert_bad_rejected(raw)
    raw = top_dull_snapshot()
    raw["history"]["1"].append(deepcopy(raw["history"]["1"][0]))
    assert_bad_rejected(raw)
    raw = top_dull_snapshot()
    raw["history"]["1"][0]["sign"] = -1
    assert_bad_rejected(raw)


@pytest.mark.parametrize("path,value", [(("pricePeak",), float("nan")), (("pricePeak",), True),
    (("ageBars",), True), (("negativeBars",), 1), (("id",), "wrong"), (("observedThrough",), D[6]),
    (("originalReference", "dif"), float("inf")), (("originalReference", "price"), False)])
def test_top_pending_numbers_dates_counts_and_id_are_checked(path, value):
    raw = top_structure_snapshot()
    current = raw["pending"]
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    assert_bad_rejected(raw)


@pytest.mark.parametrize("factory,field,path,value", [
    (bottom_structure_snapshot, "pendingBottomHistory", ("priceLow",), float("nan")),
    (bottom_structure_snapshot, "pendingBottomHistory", ("priceLow",), True),
    (bottom_structure_snapshot, "pendingBottomHistory", ("ageBars",), True),
    (bottom_structure_snapshot, "pendingBottomHistory", ("originalReference", "dif"), float("inf")),
    (waiting_snapshot, "pendingRearm", ("nearestPriceGate",), True),
    (waiting_snapshot, "pendingRearm", ("referenceWave", "dif"), float("nan")),
    (waiting_snapshot, "pendingRearm", ("structureEventId",), "wrong"),
    (waiting_snapshot, "pendingRearm", ("observedThrough",), D[6]),
])
def test_bottom_and_waiting_internal_corruption_is_atomic(factory, field, path, value):
    raw = factory()
    current = raw[field]
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    assert_bad_rejected(raw)


@pytest.mark.parametrize("factory", [bottom_structure_snapshot, bottom_color_flip_snapshot])
def test_bottom_event_and_history_ids_cannot_be_changed_together(factory):
    raw = factory()
    record = raw["pendingBottomHistory"]
    # Both IDs remain well-formed and internally match, but the event no
    # longer identifies the literal formation date/direction/reference.
    record["structureEventId"] = ident("different-structure-event")
    record["id"] = ident("bottom-history", record["structureEventId"])
    assert_bad_rejected(raw)


@pytest.mark.parametrize("route,factory", [("dif_turn", bottom_structure_snapshot),
                                          ("color_flip", bottom_color_flip_snapshot)])
def test_bottom_history_ids_follow_real_formation_for_both_routes(route, factory):
    raw = factory()
    calc = calculator()
    calc.restore(raw)
    event = ident(D[4], "STRUCTURE", -1, D[0])
    assert calc.pending_bottom_history["structureEventId"] == event
    assert calc.pending_bottom_history["id"] == ident("bottom-history", event)
    assert calc.pending_bottom_history["confirmationRoute"] == route
    assert calc.snapshot() == raw
    if route == "dif_turn":
        result = calc.step(XxmBar(D[5], 100, -6, -5, -2))
        assert [(e["type"], e["route"]) for e in result.events] == [
            ("STRUCTURE_DISAPPEARED", "dif_return")]
        assert result.events[0]["relatedBottomHistoryId"] == ident("bottom-history", event)
        assert calc.pending_rearm["structureEventId"] == event
        assert calc.pending_rearm["id"] == ident("rearm", event, D[5])
    else:
        result = calc.step(XxmBar(D[5], 102, -5.8, -6.8, 2))
        assert not result.events and calc.state == "NONE"
        assert calc.pending_bottom_history["leftOriginAt"] == D[4]
        assert calc.pending_bottom_history["priceLow"] == 98
    child = calculator()
    child.restore(calc.snapshot())
    assert child.snapshot() == calc.snapshot()


def test_bottom_historical_event_identity_does_not_require_reference_in_recent_pool():
    raw = bottom_color_flip_snapshot()
    # Two later green segments have displaced the original reference; its
    # existing history still uses the original formation and reference IDs.
    raw.update(processed=8, wave=wave(1, D[7], D[7], 1, 102, -5.6, D[7], D[7]),
        previous=previous(D[7], 102, -5.6, -6.6, 2), history={
            "-1": [wave(-1, D[2], D[3], 2, 98, -6, D[3], D[2]),
                   wave(-1, D[6], D[6], 1, 101, -5.7, D[6], D[6])],
            "1": [wave(1, D[1], D[1], 1, 110, -4, D[1], D[1]),
                  wave(1, D[4], D[5], 2, 102, -5.8, D[5], D[5])]})
    raw["pendingBottomHistory"].update(observedThrough=D[7], ageBars=3)
    calc = calculator()
    calc.restore(raw)
    assert all(w.start != D[0] for w in calc.history[-1])
    assert calc.pending_bottom_history["originalReference"]["startTime"] == D[0]
    assert calc.pending_bottom_history["structureEventId"] == ident(D[4], "STRUCTURE", -1, D[0])
    result = calc.step(XxmBar(D[8], 103, -5.5, -6.5, 2))
    assert not result.events and calc.pending_bottom_history["priceLow"] == 98
    assert calc.pending_bottom_history["observedThrough"] == D[8]


def test_missing_and_extra_fields_are_not_defaulted():
    for base, path, key in [(top_dull_snapshot, (), "processed"),
                            (top_dull_snapshot, ("wave",), "dif"),
                            (top_structure_snapshot, ("pending",), "pricePeak"),
                            (waiting_snapshot, ("pendingRearm",), "referenceWave")]:
        raw = base()
        current = raw
        for item in path:
            current = current[item]
        del current[key]
        assert_bad_rejected(raw)
    raw = top_dull_snapshot()
    raw["extra"] = 1
    assert_bad_rejected(raw)


def test_empty_snapshot_and_legal_rewind_work_on_used_calculator():
    calc = calculator()
    calc.restore(top_structure_snapshot())
    calc.restore(top_dull_snapshot())
    assert calc.processed == 5 and calc.state == "DULL"
    assert calc.step(XxmBar(D[5], 103, 9.8, 8.8, 2)).events[0]["type"] == "STRUCTURE"
    calc.restore(empty_snapshot())
    assert calc.snapshot() == empty_snapshot()


def test_r2_independent_zero_segment_is_legal_and_keeps_pending_history():
    raw = top_structure_snapshot()
    raw.update(processed=7, state="NONE", reference=None,
        wave=wave(0, D[6], D[6], 1, 102, 9.7, D[6], D[6]),
        previous=previous(D[6], 102, 9.7, 9.7, 0))
    raw["history"]["1"].append(wave(1, D[3], D[5], 3, 103, 10, D[5], D[4]))
    raw["pending"].update(observedThrough=D[6], ageBars=1, zeroBars=1, colorChanges=1)
    calc = calculator()
    calc.restore(raw)
    assert calc.wave.sign == 0 and calc.pending["pricePeak"] == 103
    assert calc.snapshot() == raw


def test_historical_original_reference_may_have_left_recent_pool():
    raw = top_structure_snapshot()
    raw.update(processed=10, state="NONE", reference=None,
        wave=wave(-1, D[9], D[9], 1, 101, 9, D[9], D[9]),
        previous=previous(D[9], 101, 9, 10, -2), history={
            "1": [wave(1, D[3], D[5], 3, 103, 10, D[5], D[4]),
                  wave(1, D[7], D[8], 2, 102, 9.5, D[7], D[7])],
            "-1": [wave(-1, D[2], D[2], 1, 99, 9, D[2], D[2]),
                   wave(-1, D[6], D[6], 1, 101, 9, D[6], D[6])]})
    raw["pending"].update(observedThrough=D[9], ageBars=4, negativeBars=2, colorChanges=3)
    calc = calculator()
    calc.restore(raw)
    result = calc.step(XxmBar(D[10], 102, 9, 10, -2))
    assert not result.events and calc.state == "NONE"
    assert calc.pending["originalReference"]["startTime"] == D[0]
    assert calc.pending["observedThrough"] == D[10]


def test_forecast_clone_uses_normal_snapshot_and_does_not_share_state():
    calc = calculator()
    calc.restore(top_structure_snapshot())
    copied = clone(calc)
    assert copied.snapshot() == top_structure_snapshot()
    copied.step(XxmBar(D[6], 102, 9.7, 8.7, 2))
    copied.pending["originalReference"]["dif"] = -999
    assert calc.snapshot() == top_structure_snapshot()


def test_unknown_program_errors_are_not_swallowed_or_published(monkeypatch):
    calc = calculator()
    calc.restore(top_dull_snapshot())
    before = deepcopy(calc.snapshot())
    def fail(_parsed):
        raise RuntimeError("test unexpected program error")
    with monkeypatch.context() as local:
        local.setattr(calc, "_validate_restored_state", fail)
        with pytest.raises(RuntimeError, match="unexpected program error"):
            calc.restore(top_structure_snapshot())
    assert calc.snapshot() == before
    calc.restore(top_structure_snapshot())
    assert calc.state == "STRUCTURE"
