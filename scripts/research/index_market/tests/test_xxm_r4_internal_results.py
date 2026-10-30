"""P3 step 1: RC72 internal aggregation and historical-prefix regressions.

Literal inputs/expectations are from the approved LLD 14.2, RC47/55/56/63,
and 14.13. Only the calendar/reader boundary is replaced; the real calculator,
snapshot restoration, aggregation and complete internal schema run unchanged.
No database, Lake, API, prediction, source replay or result file is used.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
import hashlib

import pytest
from pydantic import ValidationError

from src.biz.queries.wealth.market.index_detail_xxm import query_service
from src.biz.queries.wealth.market.index_detail_xxm.query_service import IndexDetailXxmQueryService, XxmCache
from src.biz.queries.wealth.market.index_detail_xxm.source import CN_ZONE
from src.biz.schemas.wealth.market.index_detail_xxm import InternalXxmResponseDto
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC


DATES = ("2023-01-03", "2023-01-04", "2023-01-05", "2023-01-06", "2023-01-09",
         "2023-01-10", "2023-01-11", "2023-01-12", "2023-01-13", "2023-01-16")
TOP = ((100, 200, 2), (90, 0, -2), (101, 100, 2), (102, 100, 2), (103, 99, 2), (104, 98, -2))
BOTTOM = ((100, -200, -2), (110, 0, 2), (99, -100, -2), (98, -100, -2), (97, -99, -2), (96, -98, 2))


def source(monkeypatch, values):
    rows = [XxmBar(stamp, close, dif, dif - hist / 2, hist)
            for stamp, (close, dif, hist) in zip(DATES, values)]
    reads = []

    def calendar(session, *, end):
        assert session is None
        return tuple(date.fromisoformat(stamp) for stamp in DATES if date.fromisoformat(stamp) <= end)

    def read(session, *, completed, check):
        assert session is None
        reads.append(completed)
        check()
        return tuple(row for row in rows if row.time <= completed)

    monkeypatch.setattr(query_service, "calendar_dates", calendar)
    monkeypatch.setattr(query_service, "read_daily", read)
    service, key = IndexDetailXxmQueryService(cache=XxmCache()), ("r4-internal", "day")

    def load(count):
        day = date.fromisoformat(DATES[count - 1])
        return service._load_series(None, key=key, period="day",
                                    now=datetime(day.year, day.month, day.day, 16, tzinfo=CN_ZONE),
                                    business_date=day, remaining=lambda: None)[0]

    return service, key, rows, reads, load


def response(entry, count, *, start=None, limit=1000):
    return IndexDetailXxmQueryService._response(entry, period="day", expected=DATES[count - 1],
                                               start_date=start, limit=limit, check=lambda: None)


@pytest.mark.parametrize("values,direction,extreme", [(TOP, "TOP", 103), (BOTTOM, "BOTTOM", 97)])
def test_rc72_append_preserves_earlier_assessing_result(monkeypatch, values, direction, extreme):
    service, key, _, reads, load = source(monkeypatch, values)
    old = load(5)
    old_state = deepcopy(old.calculator.snapshot())
    old_result = response(old, 5)
    old_body = old_result.model_dump()
    record = old_result.structures[0]
    assert (record.direction, record.status, record.formedAt, record.priceExtreme) == (
        direction, "ASSESSING", DATES[4], extreme)
    assert record.lockedAt is None
    new = load(6)
    locked = response(new, 6).structures[0]
    assert locked.id == record.id and locked.status == "LOCKED" and locked.lockedAt == DATES[5]
    assert [(event.type, event.route) for event in response(new, 6).events] == [
        ("DULL", "activation"), ("STRUCTURE", "dif_turn")]
    assert new.points[-1]["ordinaryState"] == "NONE" and new.points[-1]["activeStructureId"] is None
    assert old_result.model_dump() == old_body and old.calculator.snapshot() == old_state
    assert old.structure_records[record.id]["status"] == "ASSESSING"
    assert new is not old and new.calculator is not old.calculator and service.cache.get(key) is new
    assert reads == [DATES[4], DATES[5]]


@pytest.mark.parametrize("values", [TOP, BOTTOM])
def test_rc72_asof_projection_is_causal_and_window_keeps_referenced_record(monkeypatch, values):
    _, _, _, _, load = source(monkeypatch, values)
    entry = load(6)
    complete_before = deepcopy(entry.structure_records)
    assert response(entry, 4).structures == []
    early = response(entry, 5)
    assert early.structures[0].status == "ASSESSING" and early.structures[0].lockedAt is None
    assert early.points[-1].activeStructureId == early.structures[0].id
    assert entry.calculator_at(5, lambda: None).active_structure["status"] == "ASSESSING"
    terminal = response(entry, 6)
    assert terminal.structures[0].status == "LOCKED"
    # The older point may legally reference a record terminal at query cutoff.
    assert terminal.points[4].activeStructureId == terminal.structures[0].id
    window = response(entry, 6, start=date.fromisoformat(DATES[5]), limit=1)
    assert len(window.points) == 1 and window.events == []
    assert window.structures[0].id == terminal.structures[0].id
    assert window.structures[0].formedAt == DATES[4]
    assert entry.structure_records == complete_before


def test_rc72_disappearance_projection_restores_assessing_at_earlier_cutoff(monkeypatch):
    values = ((100, -200, -2), (110, 0, 2), (99, -102, -2), (98, -102, -2),
              (97, -100, -2), (101, -101, -2))  # RC47: price must not create WAIT.
    _, _, _, _, load = source(monkeypatch, values)
    entry = load(6)
    old = response(entry, 5).structures[0]
    new = response(entry, 6)
    assert old.status == "ASSESSING" and old.disappearedAt is None
    ended = new.structures[0]
    assert (ended.status, ended.disappearedAt, ended.disappearanceReason) == ("DISAPPEARED", DATES[5], "dif_return")
    assert new.points[-1].ordinaryState == "DULL" and new.points[-1].activeStructureId is None
    assert (new.events[-1].type, new.events[-1].route, new.events[-1].relatedStructureId) == (
        "DULL", "dif_return", ended.id)


@pytest.mark.parametrize("values,revised_close,original", [(TOP, 104, 103), (BOTTOM, 96, 97)])
def test_rc72_source_revision_rebuilds_without_overwriting_old_terminal(monkeypatch, values, revised_close, original):
    service, key, rows, _, load = source(monkeypatch, values)
    old = load(6)
    old_state, old_points = deepcopy(old.calculator.snapshot()), deepcopy(old.points)
    old_output = response(old, 6).model_dump()
    old_record = deepcopy(next(iter(old.structure_records.values())))
    assert old_record["priceExtreme"] == original and old_record["status"] == "LOCKED"
    rows[4] = replace(rows[4], close=revised_close)
    new = load(6)
    new_record = next(iter(new.structure_records.values()))
    assert new_record["id"] == old_record["id"]  # Same identity, revised source, separate entry.
    assert (new_record["priceExtreme"], new_record["formedAt"], new_record["lockedAt"]) == (
        revised_close, DATES[4], DATES[5])
    assert old.structure_records[old_record["id"]] == old_record
    assert old.calculator.snapshot() == old_state and old.points == old_points
    assert response(old, 6).model_dump() == old_output
    assert new.fingerprints[4] != old.fingerprints[4]
    assert new is not old and service.cache.get(key) is new


def test_rc72_two_cycles_keep_two_locked_records(monkeypatch):
    values = TOP[:5] + ((90, 0, -2), (110, 95, 2), (111, 96, 2), (112, 95, 2), (100, 94, -2))
    _, _, _, _, load = source(monkeypatch, values)
    result = response(load(10), 10)
    assert [(r.formedAt, r.lockedAt, r.status, r.priceExtreme) for r in result.structures] == [
        (DATES[4], DATES[5], "LOCKED", 103), (DATES[8], DATES[9], "LOCKED", 112)]
    assert result.structures[0].id != result.structures[1].id
    assert result.structures[1].originalReference.price == 103
    assert result.structures[1].originalReference.dif == 100


@pytest.mark.parametrize("fault", ["reopen", "formedAt", "lockedAt", "originalReference"])
def test_rc71_terminal_structure_cannot_be_reopened_or_overwritten(monkeypatch, fault):
    _, _, _, _, load = source(monkeypatch, TOP)
    entry = load(6)
    original = deepcopy(entry.structure_records)
    bad = deepcopy(next(iter(original.values())))
    if fault == "reopen":
        bad.update(status="ASSESSING", lockedAt=None)
    elif fault == "originalReference":
        bad[fault]["price"] = 99
    else:
        bad[fault] = DATES[3]
    with pytest.raises(ValueError):
        IndexDetailXxmQueryService._merge_structure_updates(entry, (bad,), through=DATES[5])
    assert entry.structure_records == original


@pytest.mark.parametrize("failure", ["aggregation", "complete_validation"])
def test_rc72_post_step_failure_discards_candidate_preserves_published_cache(monkeypatch, failure):
    service, key, _, _, load = source(monkeypatch, TOP)
    old = load(5)
    old_state, old_records = deepcopy(old.calculator.snapshot()), deepcopy(old.structure_records)
    old_points, old_events = deepcopy(old.points), deepcopy(old.events)
    candidates = []
    real_merge = service._merge_structure_updates

    def merge(candidate, updates, *, through):
        candidates.append(candidate)
        assert candidate.calculator.processed == 6
        if failure == "aggregation":
            raise ValueError("intentional post-step aggregation failure")
        real_merge(candidate, updates, through=through)

    with monkeypatch.context() as local:
        local.setattr(service, "_merge_structure_updates", merge)
        if failure == "complete_validation":
            def fail_model(**kwargs):
                assert kwargs["structures"][0]["status"] == "LOCKED"
                raise ValueError("intentional complete validation failure")
            local.setattr(query_service, "InternalXxmResponseDto", fail_model)
        with pytest.raises(ValueError):
            load(6)
    assert len(candidates) == 1 and candidates[0] is not old
    assert candidates[0].calculator.processed == 6  # Discarded work need not roll back.
    assert service.cache.get(key) is old
    assert old.calculator.snapshot() == old_state and old.structure_records == old_records
    assert old.points == old_points and old.events == old_events
    assert next(iter(load(6).structure_records.values()))["status"] == "LOCKED"


@pytest.mark.parametrize("bad", [True, "103", float("nan"), float("inf")])
def test_internal_model_rejects_invalid_original_numbers(monkeypatch, bad):
    _, _, _, _, load = source(monkeypatch, TOP)
    body = response(load(6), 6).model_dump()
    body["points"][4]["close"] = bad
    with pytest.raises(ValidationError):
        InternalXxmResponseDto.model_validate(body)


@pytest.mark.parametrize("fault", ["old_wait", "missing_reference_date", "dangling", "duplicate_formation", "future_lock"])
def test_internal_model_rejects_legacy_or_broken_structure_associations(monkeypatch, fault):
    _, _, _, _, load = source(monkeypatch, TOP)
    body = response(load(6), 6).model_dump()
    if fault == "old_wait":
        body["rearmRecords"] = []
    elif fault == "missing_reference_date":
        del body["structures"][0]["originalReference"]["difAt"]
    elif fault == "dangling":
        body["points"][4]["activeStructureId"] = "not-a-record"
    elif fault == "duplicate_formation":
        body["events"].append(deepcopy(body["events"][-1]))
    else:
        body["structures"][0]["lockedAt"] = DATES[6]
    with pytest.raises(ValidationError):
        InternalXxmResponseDto.model_validate(body)


def test_internal_model_accepts_integer_prices_without_coercing_string_or_bool(monkeypatch):
    _, _, _, _, load = source(monkeypatch, TOP)
    body = response(load(6), 6).model_dump()
    body["points"][4]["close"] = 103
    assert InternalXxmResponseDto.model_validate(body).points[4].close == 103


def test_rc72_checkpoint_and_zero_prefix_do_not_use_latest_terminal_facts(monkeypatch):
    # Only the batch interval is shortened; literal bars remain unchanged.
    monkeypatch.setattr(query_service, "BUDGET", replace(query_service.BUDGET, source_batch_rows=3))
    _, _, _, _, load = source(monkeypatch, TOP)
    entry = load(6)
    before = deepcopy(entry.checkpoints)
    empty = entry.calculator_at(0, lambda: None)
    assert empty.processed == 0 and empty.previous is None and empty.active_structure is None
    early = entry.calculator_at(5, lambda: None)
    assert early.processed == 5 and early.active_structure["status"] == "ASSESSING"
    assert early.active_structure["lockedAt"] is None
    assert entry.calculator.active_structure is None
    early.active_structure["priceExtreme"] = 999
    assert next(iter(entry.structure_records.values()))["priceExtreme"] == 103
    assert entry.checkpoints == before
    for invalid in (True, 1.0, -1, 7):
        with pytest.raises(ValueError):
            entry.calculator_at(invalid, lambda: None)


@pytest.mark.parametrize("fault", ["future_event", "future_structure", "point_value", "cardinality"])
def test_complete_entry_validation_does_not_hide_invalid_facts_with_window_filter(monkeypatch, fault):
    _, _, _, _, load = source(monkeypatch, TOP)
    original = load(6)
    entry = replace(original, points=deepcopy(original.points), events=deepcopy(original.events),
                    structure_records=deepcopy(original.structure_records), fingerprints=list(original.fingerprints))
    if fault == "future_event":
        entry.events[-1]["time"] = DATES[6]
    elif fault == "future_structure":
        next(iter(entry.structure_records.values()))["lockedAt"] = DATES[6]
    elif fault == "point_value":
        entry.points[4]["close"] = 999
    else:
        entry.fingerprints.pop()
    with pytest.raises(ValueError):
        IndexDetailXxmQueryService._validate_entry(entry, check=lambda: None)
    assert original.points[4]["close"] == 103


@pytest.mark.parametrize("expires_in", ["size", "lock"])
def test_rc72_cache_publication_checks_original_deadline_after_size_and_lock(monkeypatch, expires_in):
    service, key, _, _, load = source(monkeypatch, TOP)
    old = load(5)
    previous_entries = list(service.cache.entries.items())
    old_snapshot = deepcopy(old.calculator.snapshot())
    clock = {"now": 0., "size_finished": False}
    deadline = 1.
    original_size = query_service._deep_size
    original_lock = service.cache.lock

    def size(value, seen=None):
        result = original_size(value, seen)
        if seen is None:
            clock["size_finished"] = True
            if expires_in == "size":
                clock["now"] = 2.
        return result

    class LockWait:
        # Keep the real lock; only model elapsed waiting time deterministically.
        def __enter__(self):
            original_lock.acquire()
            if clock["size_finished"] and expires_in == "lock":
                clock["now"] = 2.
            return self

        def __exit__(self, *args):
            original_lock.release()

    def remaining():
        if clock["now"] >= deadline:
            raise query_service.XxmQueryError("XXM_BUDGET_EXCEEDED", "original request expired", 503)
        return deadline - clock["now"]

    monkeypatch.setattr(query_service, "_deep_size", size)
    service.cache.lock = LockWait()
    day = date.fromisoformat(DATES[5])
    with pytest.raises(query_service.XxmQueryError, match="original request expired"):
        service._load_series(None, key=key, period="day",
                             now=datetime(day.year, day.month, day.day, 16, tzinfo=CN_ZONE),
                             business_date=day, remaining=remaining)
    assert clock["size_finished"] and list(service.cache.entries.items()) == previous_entries
    assert service.cache.entries[key][0] is old and old.calculator.snapshot() == old_snapshot


def test_rc72_normal_size_and_lock_checks_allow_complete_candidate_publication(monkeypatch):
    service, key, _, _, load = source(monkeypatch, TOP)
    old = load(5)
    checks = []
    original_put = service.cache.put

    def put(cache_key, candidate, *, check=None):
        assert check is not None
        def observed_check():
            checks.append(True)
            return check()
        original_put(cache_key, candidate, check=observed_check)

    monkeypatch.setattr(service.cache, "put", put)
    new = load(6)
    assert len(checks) == 2 and service.cache.get(key) is new and new is not old
    assert next(iter(new.structure_records.values()))["status"] == "LOCKED"


@pytest.mark.parametrize("values", [TOP, BOTTOM])
def test_internal_model_rejects_same_bar_dif_turn_lock_when_formation_is_outside_window(monkeypatch, values):
    _, _, _, _, load = source(monkeypatch, values)
    result = response(load(6), 6, start=date.fromisoformat(DATES[5]), limit=1)
    body = result.model_dump()
    # Formation is outside the visible window, so point/event relationships
    # cannot accidentally reject this invalid chronology on the model's behalf.
    assert [point["time"] for point in body["points"]] == [DATES[5]] and body["events"] == []
    assert body["structures"][0]["formedAt"] == DATES[4]
    assert body["structures"][0]["lockedAt"] == DATES[5]
    assert InternalXxmResponseDto.model_validate(body).structures[0].status == "LOCKED"
    body["structures"][0]["lockedAt"] = DATES[4]
    with pytest.raises(ValidationError, match="later bar"):
        InternalXxmResponseDto.model_validate(body)


def test_internal_model_rejects_color_flip_extreme_from_confirmation_bar(monkeypatch):
    values = TOP[:4] + ((90, 100, -2),)
    _, _, _, _, load = source(monkeypatch, values)
    result = response(load(5), 5, start=date.fromisoformat(DATES[4]), limit=1)
    body = result.model_dump()
    record = body["structures"][0]
    assert record["formationRoute"] == "color_flip" and record["formedAt"] == record["lockedAt"] == DATES[4]
    assert record["priceExtremeAt"] == DATES[3] and record["priceExtreme"] == 102
    assert InternalXxmResponseDto.model_validate(body).structures[0].status == "LOCKED"
    record["priceExtremeAt"] = DATES[4]
    with pytest.raises(ValidationError, match="old segment"):
        InternalXxmResponseDto.model_validate(body)


def test_internal_model_rejects_fake_activation_on_existing_structure_outside_formation_window(monkeypatch):
    values = TOP[:5] + ((104, 98.5, 2),)
    _, _, _, _, load = source(monkeypatch, values)
    body = response(load(6), 6, start=date.fromisoformat(DATES[5]), limit=1).model_dump()
    assert body["events"] == [] and body["points"][0]["ordinaryState"] == "STRUCTURE"
    assert body["structures"][0]["formedAt"] == DATES[4]
    # Legal event identity alone cannot turn an existing structure into a new
    # activation. This window has no previous point to catch the contradiction.
    assert InternalXxmResponseDto.model_validate(body).points[0].ordinaryState == "STRUCTURE"
    reference = deepcopy(body["points"][0]["activeReference"])
    parts = (MAIN_SPEC.algorithm_version, MAIN_SPEC.spec_hash, "000001.SH", "day",
             DATES[5], "DULL", 1, reference["startTime"])
    identity = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]
    body["events"] = [{"id": identity, "time": DATES[5], "direction": "TOP", "type": "DULL",
                       "route": "activation", "fromState": "NONE", "eventReference": reference,
                       "relatedStructureId": None}]
    with pytest.raises(ValidationError, match="final point"):
        InternalXxmResponseDto.model_validate(body)


@pytest.mark.parametrize("route", ["color_flip", "dif_break_on_flip"])
def test_internal_model_accepts_real_flip_event_with_new_segment_none_point(monkeypatch, route):
    values = TOP[:4] + ((90, 100 if route == "color_flip" else 201, -2),)
    _, _, _, _, load = source(monkeypatch, values)
    body = response(load(5), 5).model_dump()
    assert body["events"][-1]["route"] == route
    assert body["points"][-1]["ordinaryState"] == "NONE"
    assert body["points"][-1]["ordinaryDirection"] is None
    assert InternalXxmResponseDto.model_validate(body).events[-1].direction == "TOP"


def test_internal_model_checks_from_state_when_preceding_point_is_visible(monkeypatch):
    _, _, _, _, load = source(monkeypatch, TOP)
    body = response(load(5), 5).model_dump()
    # STRUCTURE/dif_turn correctly says from DULL, but the earlier visible
    # point is changed into NONE. Cross-point facts must catch the mismatch.
    body["points"][3].update(ordinaryState="NONE", ordinaryDirection=None, activeReference=None)
    # Trim the activation event so the failure cannot be caught at that bar.
    body["events"] = [event for event in body["events"] if event["type"] == "STRUCTURE"]
    with pytest.raises(ValidationError, match="preceding visible point"):
        InternalXxmResponseDto.model_validate(body)
