"""P1 material checks only: no detector, old/new DTO or source replay runs here.

The field sets below are independently transcribed from LLD v1 section 5, not
read from the fixture builder or generated from the current product models.
The literal test identities are parameter-handoff examples, not official hashes.
"""

from copy import deepcopy
from inspect import Parameter, signature
import json
import re

import pytest

from scripts.research.index_market.tests.xxm_product_v1_responses import (
    FORECAST_STATUSES, PERIODS, RECOGNITION_CASES, bottom_forecast_response,
    forecast_response, invalid_forecast_response, invalid_recognition_response,
    recognition_response, switched_forecast_response, waiting_forecast_response,
)


DETECTOR = "1111111111111111111111111111111111111111111111111111111111111111"
FORECAST = "2222222222222222222222222222222222222222222222222222222222222222"
RECOGNITION_KEYS = set("tsCode period algorithmVersion specHash source points events meta dataStatus".split())
POINT_KEYS = set("time close dif dea hist ordinaryState ordinaryDirection".split())
EVENT_KEYS = set("id time direction type".split())
POINT_DEBUG_KEYS = set("time activeReference pendingTopHistoryId pendingBottomHistoryId pendingRearmId".split())
EVENT_DEBUG_KEYS = set("id route fromState eventReference relatedTopHistoryId relatedBottomHistoryId relatedRearmId".split())
RECOGNITION_DEBUG_KEYS = set("sourceInputId points events topHistories bottomHistories rearmRecords".split())
FORECAST_KEYS = set("tsCode period forecastVersion forecastSpecHash detectorSpecHash computedThrough requestedAsOf mode dataStatus ordinaryState direction status reasonCode forecastId targetEndpoint barsAhead confirmedAt confirmedDirection display applicabilityText invalidationText refreshAfterMs".split())
FORECAST_DEBUG_KEYS = set("sourceInputId calendarInputId precisionPolicy rearmContext nextBarOutcomes activation assumption targetEntryRanges targetEntryExclusions relations commonConditions examples".split())
# Independent expected slots, transcribed from the real source endpoint contract.
# Do not derive expected target times from fixture FUTURE_ENDPOINTS.
EXPECTED_FUTURE = {
    "day": ("2025-01-13", "2025-01-14", "2025-01-15"),
    "m60": ("2025-01-13T10:30:00+08:00", "2025-01-13T11:30:00+08:00", "2025-01-13T14:00:00+08:00"),
    "m90": ("2025-01-13T11:00:00+08:00", "2025-01-13T14:00:00+08:00", "2025-01-13T15:00:00+08:00"),
    "m120": ("2025-01-13T11:30:00+08:00", "2025-01-13T15:00:00+08:00", "2025-01-14T11:30:00+08:00"),
}


def test_identity_is_explicit_and_no_default_can_silently_borrow_r2():
    for function, required in ((recognition_response, ("detector_hash",)),
                               (forecast_response, ("detector_hash", "forecast_hash"))):
        for name in required:
            assert signature(function).parameters[name].default is Parameter.empty
    with pytest.raises(TypeError):
        recognition_response("empty")
    for invalid in (None, "", "$D", "r4", "g" * 64, 1):
        with pytest.raises(ValueError):
            recognition_response("empty", detector_hash=invalid)
    assert recognition_response("empty", detector_hash=DETECTOR)["specHash"] == DETECTOR


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("case", RECOGNITION_CASES)
def test_recognition_closed_field_sets_and_common_values(period, case):
    normal = recognition_response(case, detector_hash=DETECTOR, period=period)
    debug = recognition_response(case, detector_hash=DETECTOR, period=period, debug=True)
    assert set(normal) == RECOGNITION_KEYS
    assert set(debug) == RECOGNITION_KEYS | {"debug"}
    assert {key: debug[key] for key in RECOGNITION_KEYS} == normal
    assert normal["algorithmVersion"] == "xxm-direction-v0.1-r4"
    assert set(normal["source"]) == {"kind", "startTime", "computedThrough", "initialHistoryIncomplete", "indicatorVersion"}
    assert normal["source"]["indicatorVersion"] == (None if period == "day" else 1)
    assert normal["source"]["kind"] == ("daily_factor" if period == "day" else "minute_gold")
    assert set(debug["debug"]) == RECOGNITION_DEBUG_KEYS
    for point in normal["points"]:
        assert set(point) == POINT_KEYS
        assert point["time"].endswith("T15:00:00+08:00") if period != "day" else len(point["time"]) == 10
    assert all(set(event) == EVENT_KEYS for event in normal["events"])
    assert all(set(point) == POINT_DEBUG_KEYS for point in debug["debug"]["points"])
    assert all(set(event) == EVENT_DEBUG_KEYS for event in debug["debug"]["events"])
    assert [p["time"] for p in normal["points"]] == [p["time"] for p in debug["debug"]["points"]]
    assert [e["id"] for e in normal["events"]] == [e["id"] for e in debug["debug"]["events"]]
    assert normal["meta"]["count"] == len(normal["points"])
    assert json.loads(json.dumps(normal, allow_nan=False)) == normal


def test_empty_none_and_original_numeric_values_are_not_filled_or_rounded():
    value = recognition_response("empty", detector_hash=DETECTOR, debug=True)
    assert value["points"] == value["events"] == []
    assert value["source"]["startTime"] is value["source"]["computedThrough"] is value["dataStatus"]["asOf"] is None
    assert value["meta"] == {"count": 0, "responseStart": None, "responseEnd": None}
    assert value["debug"]["sourceInputId"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    point = recognition_response("top_structure", detector_hash=DETECTOR)["points"][0]
    assert (point["close"], point["dif"], point["dea"], point["hist"]) == (111, 18.5, 18, 1)
    delayed = recognition_response("delayed", detector_hash=DETECTOR)
    assert delayed["dataStatus"]["status"] == "DELAYED"
    assert delayed["source"]["computedThrough"] == "2025-01-10"


def test_switch_keeps_original_event_reference_b_and_latest_active_a():
    value = recognition_response("switched_dull", detector_hash=DETECTOR, debug=True)
    assert [e["type"] for e in value["events"]] == ["DULL"]
    assert value["debug"]["events"][0]["eventReference"]["dif"] == 20
    assert value["debug"]["points"][0]["activeReference"]["dif"] == 20
    assert value["debug"]["points"][1]["activeReference"]["dif"] == 30
    assert all(p["ordinaryState"] == "DULL" for p in value["points"])


@pytest.mark.parametrize("case", ("waiting", "reactivated"))
def test_bottom_history_and_rearm_have_explicit_cross_window_links(case):
    value = recognition_response(case, detector_hash=DETECTOR, debug=True)
    detail = value["debug"]
    history, rearm = detail["bottomHistories"][0], detail["rearmRecords"][0]
    assert set(history) == set("id structureEventId confirmedAt confirmationRoute originSegmentStart leftOriginAt priceLow priceLowAt originalReference status endedAt endReason observedThrough ageBars".split())
    assert set(rearm) == set("id direction bottomHistoryId structureEventId structureConfirmedAt structureRoute segmentStart nearestPriceGate reference disappearedAt observedThrough status endedAt endReason".split())
    assert history["structureEventId"] == rearm["structureEventId"] == "100000000000000000000003"
    assert history["confirmedAt"] == rearm["structureConfirmedAt"] == "2025-01-08"
    assert history["id"] == rearm["bottomHistoryId"] == "200000000000000000000002"
    assert history["endedAt"] == rearm["disappearedAt"] == "2025-01-09"
    assert history["endReason"] == "structure_disappeared"
    assert history["originalReference"] == rearm["reference"]
    assert history["structureEventId"] not in {e["id"] for e in value["events"]}
    assert detail["events"][0]["relatedRearmId"] == rearm["id"]
    if case == "waiting":
        assert rearm["status"] == "WAITING" and rearm["endedAt"] is rearm["endReason"] is None
        assert detail["points"][1]["pendingRearmId"] == rearm["id"]
    else:
        assert rearm["status"] == "REACTIVATED" and rearm["endReason"] == "price_requalified"
        assert detail["points"][1]["pendingRearmId"] is None
        assert value["points"][1]["hist"] == 0


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("status", FORECAST_STATUSES)
def test_forecast_all_statuses_and_modes_have_complete_closed_roots(period, status):
    normal = forecast_response(status, detector_hash=DETECTOR, forecast_hash=FORECAST, period=period)
    debug = forecast_response(status, detector_hash=DETECTOR, forecast_hash=FORECAST, period=period, debug=True)
    assert set(normal) == FORECAST_KEYS
    assert set(debug) == FORECAST_KEYS | {"debug"}
    assert {key: debug[key] for key in FORECAST_KEYS} == normal
    assert set(debug["debug"]) == FORECAST_DEBUG_KEYS
    assert set(normal["display"]) == {"statusLabel", "targetText", "conditionsText", "asOfText"}
    assert (normal["detectorSpecHash"], normal["forecastSpecHash"]) == (DETECTOR, FORECAST)
    assert normal["forecastVersion"] == "xxm-key-point-forecast-v0.3-r4"
    assert re.fullmatch("[0-9a-f]{64}", normal["forecastId"])
    assert normal["refreshAfterMs"] == 60000
    assert normal["requestedAsOf"] is None and normal["mode"] == "LATEST"
    assert debug["debug"]["precisionPolicy"] == ("rounded3_guarded" if period == "day" else "full_float")
    if status in ("READY", "CONDITIONAL_ENTRY"):
        assert normal["targetEndpoint"] is not None and normal["barsAhead"] == (1 if status == "READY" else 2)
        assert debug["debug"]["relations"][0]["relationId"] == debug["debug"]["commonConditions"][0]["relationId"] == "relation-B"
    else:
        assert normal["targetEndpoint"] is normal["barsAhead"] is None
        assert debug["debug"]["relations"] == debug["debug"]["commonConditions"] == debug["debug"]["examples"] == []
    if status == "CONFIRMED":
        assert normal["ordinaryState"] == "STRUCTURE" and normal["confirmedAt"] is not None and normal["confirmedDirection"] == "TOP"
    if status == "EMPTY":
        assert normal["computedThrough"] is normal["ordinaryState"] is normal["direction"] is None
        assert debug["debug"]["sourceInputId"] is debug["debug"]["calendarInputId"] is None
    assert json.loads(json.dumps(debug, allow_nan=False)) == debug


def test_activation_example_and_target_bind_the_same_explicit_entry_relation():
    value = forecast_response("CONDITIONAL_ENTRY", detector_hash=DETECTOR, forecast_hash=FORECAST, debug=True)["debug"]
    assert value["activation"]["ranges"][0]["entryRangeId"] == "entry-B"
    assert value["relations"][0]["entryRangeIds"] == value["targetEntryRanges"][0]["entryRangeIds"] == ["entry-B"]
    assert value["examples"][0]["entryRangeId"] == "entry-B"
    assert value["examples"][0]["closeRanges"][0]["relationId"] == "relation-B"
    assert value["assumption"]["intermediateEndpoints"] == ["2025-01-13"]
    assert value["assumption"]["intermediateCloseExpression"] == {"op": "affine", "pCoefficient": 1, "cCoefficient": 0, "constant": 0}
    assert value["activation"]["exclusions"][0]["priceRange"] == {"lower": 0, "upper": 100, "lowerInclusive": False, "upperInclusive": True}


def test_bottom_forecast_and_waiting_context_keep_saved_reference_and_partition():
    bottom = bottom_forecast_response(detector_hash=DETECTOR, forecast_hash=FORECAST, debug=True)
    assert bottom["direction"] == "BOTTOM" and bottom["ordinaryState"] == "DULL"
    outcomes = bottom["debug"]["nextBarOutcomes"]
    assert outcomes["initialReference"]["dif"] == -20
    assert outcomes["branches"][0]["priceRange"] == {"lower": 0, "upper": None, "lowerInclusive": False, "upperInclusive": False}
    assert outcomes["branches"][0]["outcome"] == "PRESERVED"
    waiting = waiting_forecast_response(detector_hash=DETECTOR, forecast_hash=FORECAST, debug=True)
    assert (waiting["ordinaryState"], waiting["direction"], waiting["status"]) == ("NONE", "BOTTOM", "ENTRY_ONLY")
    assert waiting["debug"]["rearmContext"]["status"] == "WAITING"
    assert waiting["debug"]["activation"]["ranges"][0]["reference"] == waiting["debug"]["rearmContext"]["reference"]


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("status", FORECAST_STATUSES)
def test_replay_request_is_retained_even_when_no_source_prefix(period, status):
    value = forecast_response(status, detector_hash=DETECTOR, forecast_hash=FORECAST, period=period, mode="REPLAY")
    assert value["mode"] == "REPLAY"
    assert value["requestedAsOf"] == ("2025-01-10" if period == "day" else "2025-01-10T15:00:00+08:00")
    if status == "EMPTY":
        assert value["computedThrough"] is None


@pytest.mark.parametrize("period", PERIODS)
def test_forecast_top_path_retains_initial_b_and_final_a_before_target(period):
    value = switched_forecast_response(detector_hash=DETECTOR, forecast_hash=FORECAST, period=period, debug=True)
    relation = value["debug"]["relations"][0]
    assert value["direction"] == "TOP" and value["barsAhead"] == 3
    assert set(relation) == set("relationId entryRangeIds entryDomain reference initialReference referenceTransitions route prefixConditions targetConditions".split())
    transition = relation["referenceTransitions"][0]
    assert set(transition) == {"endpoint", "fromReference", "toReference"}
    assert transition["fromReference"] == relation["initialReference"]
    assert transition["toReference"] == relation["reference"] == value["debug"]["commonConditions"][0]["reference"]
    assert relation["initialReference"]["dif"] == 20 and relation["reference"]["dif"] == 30
    assert value["computedThrough"] < transition["endpoint"] < value["targetEndpoint"]
    assert transition["endpoint"] == EXPECTED_FUTURE[period][1]
    assert value["targetEndpoint"] == EXPECTED_FUTURE[period][2]
    assert value["debug"]["assumption"]["intermediateEndpoints"] == list(EXPECTED_FUTURE[period][:2])
    normal = switched_forecast_response(detector_hash=DETECTOR, forecast_hash=FORECAST, period=period)
    assert {key: value[key] for key in FORECAST_KEYS} == normal


@pytest.mark.parametrize("period", PERIODS)
def test_future_targets_and_all_auxiliary_endpoints_match_bars_ahead(period):
    first, second, third = EXPECTED_FUTURE[period]
    ready = forecast_response("READY", detector_hash=DETECTOR, forecast_hash=FORECAST, period=period, debug=True)
    conditional = forecast_response("CONDITIONAL_ENTRY", detector_hash=DETECTOR, forecast_hash=FORECAST, period=period, debug=True)
    entry = forecast_response("ENTRY_ONLY", detector_hash=DETECTOR, forecast_hash=FORECAST, period=period, debug=True)
    bottom = bottom_forecast_response(detector_hash=DETECTOR, forecast_hash=FORECAST, period=period, debug=True)
    waiting = waiting_forecast_response(detector_hash=DETECTOR, forecast_hash=FORECAST, period=period, debug=True)
    switched = switched_forecast_response(detector_hash=DETECTOR, forecast_hash=FORECAST, period=period, debug=True)
    assert (ready["barsAhead"], ready["targetEndpoint"]) == (1, first)
    assert ready["debug"]["assumption"]["activationEndpoint"] is None
    assert ready["debug"]["assumption"]["intermediateEndpoints"] == []
    assert (conditional["barsAhead"], conditional["targetEndpoint"]) == (2, second)
    assert conditional["debug"]["activation"]["endpoint"] == first
    assert conditional["debug"]["assumption"]["activationEndpoint"] == first
    assert conditional["debug"]["assumption"]["intermediateEndpoints"] == [first]
    assert entry["targetEndpoint"] is None and entry["barsAhead"] is None
    assert entry["debug"]["activation"]["endpoint"] == first
    assert bottom["debug"]["nextBarOutcomes"]["endpoint"] == first
    assert waiting["debug"]["activation"]["endpoint"] == first
    assert (switched["barsAhead"], switched["targetEndpoint"]) == (3, third)
    through = "2025-01-10" if period == "day" else "2025-01-10T15:00:00+08:00"
    assert all(value["computedThrough"] == through for value in (ready, conditional, entry, bottom, waiting, switched))
    assert waiting["debug"]["rearmContext"]["observedThrough"] == through


def test_material_factories_do_not_share_mutable_results():
    first = recognition_response("waiting", detector_hash=DETECTOR, debug=True)
    original = deepcopy(first)
    other = recognition_response("waiting", detector_hash=DETECTOR, debug=True)
    first["debug"]["rearmRecords"][0]["reference"]["price"] = 999
    assert other == original
    first_f = forecast_response("READY", detector_hash=DETECTOR, forecast_hash=FORECAST, debug=True)
    other_f = forecast_response("READY", detector_hash=DETECTOR, forecast_hash=FORECAST, debug=True)
    first_f["debug"]["relations"].clear()
    assert len(other_f["debug"]["relations"]) == 1


def test_intentional_rejection_materials_expose_named_defects_without_running_decoder():
    # These assertions establish what P3 must reject; no P3 rejection is claimed.
    make = lambda name: invalid_recognition_response(name, detector_hash=DETECTOR)
    duplicate = make("duplicate_event")
    assert len(duplicate["events"]) == 2 and duplicate["events"][0]["id"] == duplicate["events"][1]["id"]
    assert make("dangling_rearm")["debug"]["rearmRecords"] == []
    assert make("future_history")["debug"]["bottomHistories"][0]["endedAt"] > "2025-01-10"
    assert make("null_debug")["debug"] is None
    assert "debug" not in make("missing_debug")
    assert "debug" in make("normal_with_debug")  # invalid only when request mode is 0
    assert make("old_identity")["algorithmVersion"].endswith("-r2")
    assert make("old_zero_reason")["debug"]["rearmRecords"][0]["endReason"] == "zero"
    old_zero = invalid_forecast_response("zero_reset", detector_hash=DETECTOR, forecast_hash=FORECAST)
    assert old_zero["debug"]["nextBarOutcomes"]["branches"][0]["outcome"] == "ZERO_RESET"
    dangling = invalid_forecast_response("dangling_relation", detector_hash=DETECTOR, forecast_hash=FORECAST)
    assert dangling["debug"]["commonConditions"][0]["relationId"] == "missing-relation"
