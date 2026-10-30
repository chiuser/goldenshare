"""Current r4 LLD 2–4: independent literal progress and safe restoration.

The contract is written out here. Identity values use the registered ID formula;
business snapshots are not obtained from a detector. Legacy wait/price-withdrawal
states appear only as explicit rejection inputs, never as valid progress.
"""
from copy import deepcopy
import hashlib

import pytest

from src.biz.services.wealth.market.index_detail_xxm.calculator import XxmCalculator
from src.biz.services.wealth.market.index_detail_xxm.forecast_detector import clone
from src.biz.services.wealth.market.index_detail_xxm.snapshot_validation import parse_xxm_snapshot
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from scripts.research.index_market.tests.xxm_product_v1_cases import CASES, PERIODS

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
                previous=None, activeStructure=None)


def reference(ref):
    return dict(startTime=ref["start"], endTime=ref["end"], price=ref["price"], dif=ref["dif"],
                priceAt=ref["price_at"], difAt=ref["dif_at"])


def structure(sign, formed_at, origin, ref, price, price_at):
    event = ident(formed_at, "STRUCTURE", sign, ref["start"])
    return dict(id=ident("structure", event), direction="TOP" if sign == 1 else "BOTTOM",
                structureEventId=event, formedAt=formed_at, formationRoute="dif_turn",
                originSegmentStart=origin, originalReference=reference(ref), priceExtreme=price,
                priceExtremeAt=price_at, status="ASSESSING", lockedAt=None,
                disappearedAt=None, disappearanceReason=None)


def top_dull_snapshot():
    raw = empty_snapshot()
    ref = wave(1, D[0], D[1], 2, 101, 12, D[1], D[1])
    raw.update(processed=5, wave=wave(1, D[3], D[4], 2, 102, 10, D[4], D[4]),
               history={"1": [ref], "-1": [wave(-1, D[2], D[2], 1, 99, 9, D[2], D[2])]},
               state="DULL", reference=deepcopy(ref), previous=previous(D[4], 102, 10, 9, 2))
    return raw


def top_structure_snapshot():
    raw = top_dull_snapshot()
    raw.update(processed=6, state="STRUCTURE", previous=previous(D[5], 103, 9.8, 8.8, 2),
               wave=wave(1, D[3], D[5], 3, 103, 10, D[5], D[4]),
               activeStructure=structure(1, D[5], D[3], raw["reference"], 103, D[5]))
    return raw


def bottom_structure_snapshot():
    raw = empty_snapshot()
    ref = wave(-1, D[0], D[0], 1, 100, -8, D[0], D[0])
    raw.update(processed=5, state="STRUCTURE", reference=deepcopy(ref),
               wave=wave(-1, D[2], D[4], 3, 98, -6, D[3], D[2]),
               history={"-1": [ref], "1": [wave(1, D[1], D[1], 1, 110, -4, D[1], D[1])]},
               previous=previous(D[4], 101, -5.9, -4.9, -2),
               activeStructure=structure(-1, D[4], D[2], ref, 98, D[3]))
    return raw


def calculator():
    return XxmCalculator(period="day", source_identity=SOURCE)


def assert_bad_rejected(raw):
    calc = calculator()
    calc.restore(top_dull_snapshot())
    before, incoming = calc.snapshot(), repr(raw)
    with pytest.raises(ValueError):
        calc.restore(raw)
    assert calc.snapshot() == before and repr(raw) == incoming
    calc.restore(empty_snapshot())
    calc.step(XxmBar(D[0], 100, 0, 0, 0))
    assert calc.processed == 1 and calc.wave is None


@pytest.mark.parametrize("factory", [empty_snapshot, top_dull_snapshot, top_structure_snapshot, bottom_structure_snapshot])
def test_literal_snapshot_shapes_restore_without_changing_producer_contract(factory):
    raw = factory()
    frozen = deepcopy(raw)
    calc = calculator()
    calc.restore(raw)
    assert calc.snapshot() == frozen and raw == frozen


def test_dull_and_structure_continue_with_hand_checked_events_and_links():
    calc = calculator()
    calc.restore(top_dull_snapshot())
    result = calc.step(XxmBar(D[5], 103, 9.8, 8.8, 2))
    assert calc.snapshot() == top_structure_snapshot()
    record = result.structures[0]
    assert [(e["type"], e["route"], e["direction"]) for e in result.events] == [("STRUCTURE", "dif_turn", "TOP")]
    assert result.events[0]["relatedStructureId"] == record["id"] == ident("structure", record["structureEventId"])
    assert record["priceExtreme"] == 103 and record["status"] == "ASSESSING"
    frozen = deepcopy(result)
    calc.step(XxmBar(D[6], 102, 9.7, 8.7, 2))
    assert result == frozen


def test_bottom_return_restores_dull_directly_without_a_waiting_contract():
    calc = calculator()
    raw = bottom_structure_snapshot()
    calc.restore(raw)
    result = calc.step(XxmBar(D[5], 101, -6, -5, -2))
    assert calc.state == "DULL" and calc.reference.reference() == reference(raw["reference"])
    assert calc.active_structure is None
    assert [(e["type"], e["route"]) for e in result.events] == [("DULL", "dif_return")]
    assert result.structures[0]["status"] == "DISAPPEARED"
    assert result.structures[0]["disappearanceReason"] == "dif_return"
    assert result.structures[0]["disappearedAt"] == D[5]
    assert set(calc.snapshot()) == set(empty_snapshot())
    resumed = calculator()
    resumed.restore(calc.snapshot())
    assert resumed.state == "DULL" and resumed.active_structure is None


def test_structures_are_locked_on_flip_and_not_retained_as_active_progress():
    for raw, item in [(top_structure_snapshot(), XxmBar(D[6], 104, 9.7, 10.7, -2)),
                      (bottom_structure_snapshot(), XxmBar(D[5], 102, -5.8, -6.8, 2))]:
        calc = calculator()
        calc.restore(raw)
        result = calc.step(item)
        assert not result.events and result.structures[0]["status"] == "LOCKED"
        assert result.structures[0]["lockedAt"] == item.time
        assert result.structures[0]["id"] == raw["activeStructure"]["id"]
        assert calc.state == "NONE" and calc.active_structure is None
        child = calculator()
        child.restore(calc.snapshot())
        assert child.snapshot() == calc.snapshot()


def test_parse_returns_seven_independent_progress_fields():
    raw = top_structure_snapshot()
    parsed = parse_xxm_snapshot(raw, expected_identity=(MAIN_SPEC.spec_hash, "000001.SH", "day", SOURCE),
                                period="day", max_refs=2)
    assert parsed.processed == 6 and parsed.state == "STRUCTURE"
    assert parsed.wave.price == 103 and parsed.reference.dif == 12
    assert parsed.active_structure["priceExtreme"] == 103
    parsed.history[1][0].price = -10
    parsed.wave.price = -11
    parsed.active_structure["originalReference"]["dif"] = -12
    assert raw["history"]["1"][0]["price"] == 101
    assert raw["wave"]["price"] == 103 and raw["activeStructure"]["originalReference"]["dif"] == 12


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
    ("sign", True), ("sign", 2), ("start", "2025-3-06"), ("end", D[5]),
    ("price_at", D[2]), ("dif_at", D[6])])
def test_wave_dates_count_and_direction_are_strict(field, value):
    raw = top_dull_snapshot()
    raw["wave"][field] = value
    assert_bad_rejected(raw)


@pytest.mark.parametrize("fault", ["not_in_pool", "over_limit", "duplicate_time", "wrong_direction"])
def test_reference_must_be_in_its_pool_and_pool_order_remains_causal(fault):
    raw = top_dull_snapshot()
    if fault == "not_in_pool":
        raw["reference"]["price"] = 100
    elif fault == "over_limit":
        raw["history"]["1"] *= 3
    elif fault == "duplicate_time":
        raw["history"]["1"].append(deepcopy(raw["history"]["1"][0]))
    else:
        raw["history"]["1"][0]["sign"] = -1
    assert_bad_rejected(raw)


@pytest.mark.parametrize("factory", [top_structure_snapshot, bottom_structure_snapshot])
@pytest.mark.parametrize("path,value", [(("priceExtreme",), float("nan")), (("priceExtreme",), True),
    (("id",), "wrong"), (("formedAt",), D[6]), (("originalReference", "dif"), float("inf")),
    (("originalReference", "price"), False), (("originalReference", "difAt"), D[5]),
    (("originSegmentStart",), D[0]), (("formationRoute",), "color_flip")])
def test_active_structure_numbers_dates_direction_and_ids_are_checked(factory, path, value):
    raw = factory()
    current = raw["activeStructure"]
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    assert_bad_rejected(raw)


@pytest.mark.parametrize("factory", [top_structure_snapshot, bottom_structure_snapshot])
@pytest.mark.parametrize("status", ["LOCKED", "DISAPPEARED"])
def test_terminal_structure_cannot_masquerade_as_an_active_snapshot(factory, status):
    raw = factory()
    record = raw["activeStructure"]
    record.update(status=status)
    if status == "LOCKED":
        record["lockedAt"] = record["formedAt"]
    else:
        record.update(disappearedAt=record["formedAt"], disappearanceReason="dif_return")
    assert_bad_rejected(raw)


@pytest.mark.parametrize("factory", [top_structure_snapshot, bottom_structure_snapshot])
def test_structure_and_event_ids_cannot_be_changed_together(factory):
    raw = factory()
    record = raw["activeStructure"]
    record["structureEventId"] = ident("different-structure-event")
    record["id"] = ident("structure", record["structureEventId"])
    assert_bad_rejected(raw)


@pytest.mark.parametrize("extra", ["pending", "pendingBottomHistory", "pendingRearm"])
def test_removed_wait_and_history_fields_are_explicitly_rejected(extra):
    raw = top_structure_snapshot()
    raw[extra] = None
    assert_bad_rejected(raw)


@pytest.mark.parametrize("path,key", [((), "processed"), (("wave",), "dif"),
                                     (("activeStructure",), "priceExtreme"),
                                     (("activeStructure", "originalReference"), "difAt")])
def test_missing_fields_are_not_defaulted(path, key):
    raw = top_structure_snapshot()
    current = raw
    for item in path:
        current = current[item]
    del current[key]
    assert_bad_rejected(raw)


def test_empty_snapshot_and_legal_rewind_work_on_used_calculator():
    calc = calculator()
    calc.restore(top_structure_snapshot())
    calc.restore(top_dull_snapshot())
    assert calc.processed == 5 and calc.state == "DULL"
    assert calc.step(XxmBar(D[5], 103, 9.8, 8.8, 2)).events[0]["type"] == "STRUCTURE"
    calc.restore(empty_snapshot())
    assert calc.snapshot() == empty_snapshot()


def test_independent_zero_segment_is_rejected_without_mutation():
    raw = empty_snapshot()
    raw.update(processed=1, wave=wave(0, D[0], D[0], 1, 100, 0, D[0], D[0]),
               previous=previous(D[0], 100, 0, 0, 0))
    assert_bad_rejected(raw)


def test_forecast_clone_uses_normal_snapshot_and_does_not_share_state():
    calc = calculator()
    calc.restore(top_structure_snapshot())
    copied = clone(calc)
    assert copied.snapshot() == top_structure_snapshot()
    copied.step(XxmBar(D[6], 102, 9.7, 8.7, 2))
    copied.active_structure["originalReference"]["dif"] = -999
    assert calc.snapshot() == top_structure_snapshot()


def test_unknown_program_errors_are_not_swallowed_or_published(monkeypatch):
    from src.biz.services.wealth.market.index_detail_xxm import calculator as kernel

    calc = calculator()
    calc.restore(top_dull_snapshot())
    before = calc.snapshot()

    def fail(*args, **kwargs):
        raise RuntimeError("test unexpected program error")

    with monkeypatch.context() as local:
        local.setattr(kernel, "parse_xxm_snapshot", fail)
        with pytest.raises(RuntimeError, match="unexpected program error"):
            calc.restore(top_structure_snapshot())
    assert calc.snapshot() == before
    calc.restore(top_structure_snapshot())
    assert calc.state == "STRUCTURE"


@pytest.mark.parametrize("state", ["DULL", "STRUCTURE"])
def test_active_state_cannot_restore_with_only_one_colored_bar(state):
    raw = top_dull_snapshot() if state == "DULL" else top_structure_snapshot()
    raw["wave"]["count"] = 1
    assert_bad_rejected(raw)
    calc = calculator()
    good = top_dull_snapshot() if state == "DULL" else top_structure_snapshot()
    calc.restore(good)
    assert calc.snapshot() == good


@pytest.mark.parametrize("factory,close,dif,hist", [(top_structure_snapshot, 102, 9.7, 0),
                                                    (bottom_structure_snapshot, 101, -5.85, 0)])
def test_zero_after_structure_retains_logical_wave_and_original_structure(factory, close, dif, hist):
    raw = factory()
    next_index = raw["processed"]
    raw["processed"] += 1
    raw["wave"]["end"] = D[next_index]
    raw["previous"] = previous(D[next_index], close, dif, dif, hist)
    calc = calculator()
    calc.restore(raw)
    assert calc.snapshot() == raw
    assert calc.active_structure["status"] == "ASSESSING"
    assert calc.active_structure["lockedAt"] is None
    assert calc.wave.count == raw["wave"]["count"]


def test_all_zero_prefix_restores_without_creating_a_wave():
    raw = empty_snapshot()
    raw.update(processed=2, previous=previous(D[1], 101, 7, 7, 0))
    calc = calculator()
    calc.restore(raw)
    result = calc.step(XxmBar(D[2], 102, 8, 7, 2))
    assert not result.events and calc.wave.start == D[2] and calc.wave.count == 1
    assert calc.history == {1: [], -1: []}


@pytest.mark.parametrize("corruption", ["previous_color", "history", "wave_direction"])
def test_logical_wave_and_leading_zero_relations_are_not_repaired(corruption):
    if corruption == "wave_direction":
        raw = top_dull_snapshot()
        raw["previous"]["hist"] = -2
    else:
        raw = empty_snapshot()
        raw.update(processed=2, previous=previous(D[1], 101, 7, 7, 0))
        if corruption == "previous_color":
            raw["previous"]["hist"] = 2
        else:
            raw["history"]["1"] = [wave(1, D[0], D[0], 1, 100, 8, D[0], D[0])]
    assert_bad_rejected(raw)


@pytest.mark.parametrize("old_hash", ["legacy-r2-spec", "legacy-r4-v1-spec", "legacy-research-r4-v2-spec"])
def test_old_spec_hash_and_research_wrapper_are_rejected(old_hash):
    raw = top_dull_snapshot()
    raw["specHash"] = old_hash
    assert_bad_rejected(raw)
    assert_bad_rejected({"researchVersion": "xxm-research-r4-v2", "researchHash": "old-research-hash",
                         "tsCode": "000001.SH", "period": "day", "inputIdentity": SOURCE,
                         "parentState": top_dull_snapshot()})


def test_previous_registered_r4_rule_identity_is_not_the_new_identity():
    import json

    # Independent registered old rule content; it is rejection data only.
    # No old calculator, source-code hash or legacy execution is involved.
    old_rules = {
        "algorithm_version": "xxm-direction-v0.1-r4", "dif_turn_pct": 1.0,
        "max_refs": 2, "min_bars": 2, "reference_policy": "nearest_then_farther_two",
        "active_reference_policy": "same_bar_near_to_far_on_dull_break",
        "zero_policy": "neutral_real_opposite", "allow_zero_activation": True,
        "allow_zero_reactivation": True, "macd_parameters": (12, 26, 9),
        "histogram_multiplier": 2, "color_flip": True, "flip_requires_turn": False,
        "historical_price_only": True, "fixed_expiry": None,
        "bottom_history_policy": "closed_origin_close_break_v1",
        "same_segment_bottom_policy": "current_close_rearm_v1",
    }
    old_hash = hashlib.sha256(json.dumps(old_rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert old_hash != MAIN_SPEC.spec_hash
    raw = top_dull_snapshot()
    raw["specHash"] = old_hash
    assert_bad_rejected(raw)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("period", PERIODS)
def test_handwritten_input_prefixes_restore_and_continue_in_all_four_periods(case, period):
    # These legacy literal INPUTS still exercise safe continuation. This does
    # not assert their obsolete wait/withdrawal BUSINESS expected values.
    source_id = f"progress:{period}:{case.name}"
    bars = tuple(XxmBar(**row) for row in case.inputs(period))
    original = XxmCalculator(period=period, source_identity=source_id)
    snapshots, steps = [original.snapshot()], []
    for item in bars:
        steps.append(original.step(item))
        snapshots.append(original.snapshot())
    for cutoff, snapshot in enumerate(snapshots):
        incoming = deepcopy(snapshot)
        child = XxmCalculator(period=period, source_identity=source_id)
        child.step(XxmBar("2022-01-04" if period == "day" else "2022-01-04T15:00:00+08:00", 1, 0, 0, 0))
        child.restore(incoming)
        assert incoming == snapshot
        assert [child.step(item) for item in bars[cutoff:]] == steps[cutoff:]
        assert child.snapshot() == original.snapshot()
