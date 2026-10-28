"""Handwritten r4 target HTTP materials for P1, not product output.

Authority: recognition LLD v1 sections 5, 11.2.5 and 16.  Field types were
checked against the current index_detail_xxm{,_forecast}.py producers.  The
ordinary/debug split and removal of old zero reasons are the approved target.

No calculator, projection, adapter, schema, current Spec, file or data reader is
imported here.  Prices and IDs illustrate the response contract, not the output
of an actual market prefix.  The algorithm cases and independent arithmetic are
separate P1 materials.  P2 supplies its real hashes explicitly; fixture IDs are
literal relationship examples, never claimed to be official generated IDs.
"""

from copy import deepcopy
import re


PERIODS = ("day", "m60", "m90", "m120")
RECOGNITION_CASES = (
    "empty", "ready_none", "top_structure", "switched_dull", "waiting",
    "reactivated", "delayed",
)
FORECAST_STATUSES = (
    "READY", "CONDITIONAL_ENTRY", "ENTRY_ONLY", "NO_CANDIDATE", "CONFIRMED",
    "PRECISION_PENDING", "DELAYED", "EMPTY",
)
# Handwritten future completed slots after Friday 2025-01-10 close.  These
# follow source.py:ENDPOINTS (60:10:30/11:30/14:00/15:00;
# 90:11:00/14:00/15:00; 120:11:30/15:00).  No calendar or source reader runs.
FUTURE_ENDPOINTS = {
    "day": ("2025-01-13", "2025-01-14", "2025-01-15"),
    "m60": ("2025-01-13T10:30:00+08:00", "2025-01-13T11:30:00+08:00", "2025-01-13T14:00:00+08:00"),
    "m90": ("2025-01-13T11:00:00+08:00", "2025-01-13T14:00:00+08:00", "2025-01-13T15:00:00+08:00"),
    "m120": ("2025-01-13T11:30:00+08:00", "2025-01-13T15:00:00+08:00", "2025-01-14T11:30:00+08:00"),
}


def _identity(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Pass an explicit 64-character identity, not a placeholder")
    return value


def _period_times(value, period):
    """Only adapt literal dates to the shared completed 15:00 minute endpoint."""
    if period not in PERIODS:
        raise ValueError("Unsupported fixture period")
    if isinstance(value, dict):
        return {key: _period_times(item, period) for key, item in value.items()}
    if isinstance(value, list):
        return [_period_times(item, period) for item in value]
    if period != "day" and isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value + "T15:00:00+08:00"
    return value


def _forecast_times(value, period):
    """Format historical dates at 15:00, future dates by literal slot ordinal."""
    if period not in PERIODS:
        raise ValueError("Unsupported fixture period")
    if isinstance(value, dict):
        return {key: _forecast_times(item, period) for key, item in value.items()}
    if isinstance(value, list):
        return [_forecast_times(item, period) for item in value]
    if isinstance(value, str) and value in ("2025-01-13", "2025-01-14", "2025-01-15"):
        ordinal = {"2025-01-13": 0, "2025-01-14": 1, "2025-01-15": 2}[value]
        return FUTURE_ENDPOINTS[period][ordinal]
    return _period_times(value, period)


def recognition_response(case: str, *, detector_hash: str, period: str = "day", debug: bool = False) -> dict:
    """Build one independent contract example; no default/current product hash."""
    detector_hash = _identity(detector_hash)
    if case not in RECOGNITION_CASES:
        raise ValueError("Unknown recognition fixture")
    b = {"startTime": "2024-12-26", "endTime": "2024-12-27", "price": 100, "dif": 20}
    a = {"startTime": "2024-12-23", "endTime": "2024-12-24", "price": 110, "dif": 30}
    bottom_ref = {"startTime": "2024-12-26", "endTime": "2024-12-27", "price": 100, "dif": -20}
    ordinary = {
        "tsCode": "000001.SH", "period": period,
        "algorithmVersion": "xxm-direction-v0.1-r4", "specHash": detector_hash,
        "source": {"kind": "daily_factor", "startTime": "2024-12-23", "computedThrough": "2025-01-10",
                   "initialHistoryIncomplete": True, "indicatorVersion": None},
        "points": [{"time": "2025-01-10", "close": 101, "dif": 10, "dea": 9, "hist": 2,
                    "ordinaryState": "NONE", "ordinaryDirection": None}],
        "events": [], "meta": {"count": 1, "responseStart": "2025-01-10", "responseEnd": "2025-01-10"},
        "dataStatus": {"status": "READY", "message": None, "asOf": "2025-01-10"},
    }
    detail = {
        "sourceInputId": "4000000000000000000000000000000000000000000000000000000000000001",
        "points": [{"time": "2025-01-10", "activeReference": None, "pendingTopHistoryId": None,
                    "pendingBottomHistoryId": None, "pendingRearmId": None}],
        "events": [], "topHistories": [], "bottomHistories": [], "rearmRecords": [],
    }
    if case == "empty":
        ordinary["source"].update(startTime=None, computedThrough=None)
        ordinary.update(points=[], events=[], meta={"count": 0, "responseStart": None, "responseEnd": None},
                        dataStatus={"status": "EMPTY", "message": "顶底识别暂无数据", "asOf": None})
        # Existing recognition empty source identity: SHA256 of the literal empty bytes.
        detail.update(sourceInputId="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", points=[])
    elif case == "top_structure":
        ordinary["points"][0].update(close=111, dif=18.5, dea=18, hist=1,
                                      ordinaryState="STRUCTURE", ordinaryDirection="TOP")
        ordinary["events"] = [{"id": "100000000000000000000001", "time": "2025-01-10", "direction": "TOP", "type": "STRUCTURE"}]
        detail["points"][0].update(activeReference=b, pendingTopHistoryId="200000000000000000000001")
        detail["events"] = [{"id": "100000000000000000000001", "route": "dif_turn", "fromState": "DULL",
                             "eventReference": b, "relatedTopHistoryId": "200000000000000000000001",
                             "relatedBottomHistoryId": None, "relatedRearmId": None}]
        detail["topHistories"] = [{"id": "200000000000000000000001", "confirmedAt": "2025-01-10",
            "confirmationRoute": "dif_turn", "pricePeak": 112, "pricePeakAt": "2025-01-09",
            "originalReference": b, "status": "PENDING", "endedAt": None, "endReason": None,
            "observedThrough": "2025-01-10", "ageBars": 0}]
    elif case == "switched_dull":
        ordinary["points"] = [
            {"time": "2025-01-09", "close": 111, "dif": 19, "dea": 18, "hist": 2,
             "ordinaryState": "DULL", "ordinaryDirection": "TOP"},
            {"time": "2025-01-10", "close": 112, "dif": 21, "dea": 19, "hist": 4,
             "ordinaryState": "DULL", "ordinaryDirection": "TOP"},
        ]
        ordinary["events"] = [{"id": "100000000000000000000002", "time": "2025-01-09", "direction": "TOP", "type": "DULL"}]
        ordinary["meta"] = {"count": 2, "responseStart": "2025-01-09", "responseEnd": "2025-01-10"}
        detail["points"] = [
            {"time": "2025-01-09", "activeReference": b, "pendingTopHistoryId": None,
             "pendingBottomHistoryId": None, "pendingRearmId": None},
            {"time": "2025-01-10", "activeReference": a, "pendingTopHistoryId": None,
             "pendingBottomHistoryId": None, "pendingRearmId": None},
        ]
        detail["events"] = [{"id": "100000000000000000000002", "route": "activation", "fromState": "NONE",
            "eventReference": b, "relatedTopHistoryId": None, "relatedBottomHistoryId": None, "relatedRearmId": None}]
    elif case in ("waiting", "reactivated"):
        ordinary["points"] = [
            {"time": "2025-01-09", "close": 101, "dif": -11, "dea": -8, "hist": -6,
             "ordinaryState": "NONE", "ordinaryDirection": None},
            {"time": "2025-01-10", "close": 101, "dif": -11, "dea": -11, "hist": 0,
             "ordinaryState": "NONE", "ordinaryDirection": None},
        ]
        ordinary["events"] = [{"id": "100000000000000000000004", "time": "2025-01-09", "direction": "BOTTOM", "type": "STRUCTURE_DISAPPEARED"}]
        ordinary["meta"] = {"count": 2, "responseStart": "2025-01-09", "responseEnd": "2025-01-10"}
        detail["points"] = [
            {"time": "2025-01-09", "activeReference": None, "pendingTopHistoryId": None,
             "pendingBottomHistoryId": None, "pendingRearmId": "300000000000000000000001"},
            {"time": "2025-01-10", "activeReference": None, "pendingTopHistoryId": None,
             "pendingBottomHistoryId": None, "pendingRearmId": "300000000000000000000001"},
        ]
        detail["events"] = [{"id": "100000000000000000000004", "route": "dif_return", "fromState": "STRUCTURE",
            "eventReference": bottom_ref, "relatedTopHistoryId": None,
            "relatedBottomHistoryId": "200000000000000000000002", "relatedRearmId": "300000000000000000000001"}]
        # The original structure event is outside this visible two-day window.
        detail["bottomHistories"] = [{"id": "200000000000000000000002", "structureEventId": "100000000000000000000003",
            "confirmedAt": "2025-01-08", "confirmationRoute": "dif_turn", "originSegmentStart": "2025-01-06",
            "leftOriginAt": None, "priceLow": 98, "priceLowAt": "2025-01-07", "originalReference": bottom_ref,
            "status": "ENDED", "endedAt": "2025-01-09", "endReason": "structure_disappeared",
            "observedThrough": "2025-01-09", "ageBars": 1}]
        detail["rearmRecords"] = [{"id": "300000000000000000000001", "direction": "BOTTOM",
            "bottomHistoryId": "200000000000000000000002", "structureEventId": "100000000000000000000003",
            "structureConfirmedAt": "2025-01-08", "structureRoute": "dif_turn", "segmentStart": "2025-01-06",
            "nearestPriceGate": 100, "reference": bottom_ref, "disappearedAt": "2025-01-09",
            "observedThrough": "2025-01-10", "status": "WAITING", "endedAt": None, "endReason": None}]
        if case == "reactivated":
            ordinary["points"][1].update(close=99, ordinaryState="DULL", ordinaryDirection="BOTTOM")
            ordinary["events"].append({"id": "100000000000000000000005", "time": "2025-01-10", "direction": "BOTTOM", "type": "DULL"})
            detail["points"][1].update(activeReference=bottom_ref, pendingRearmId=None)
            detail["events"].append({"id": "100000000000000000000005", "route": "reactivation", "fromState": "NONE",
                "eventReference": bottom_ref, "relatedTopHistoryId": None,
                "relatedBottomHistoryId": None, "relatedRearmId": "300000000000000000000001"})
            detail["rearmRecords"][0].update(status="REACTIVATED", endedAt="2025-01-10", endReason="price_requalified")
    if case == "delayed":
        ordinary["dataStatus"].update(status="DELAYED", message="顶底识别数据截至 2025-01-10")
    if period != "day":
        ordinary["source"].update(kind="minute_gold", indicatorVersion=1)
    if debug:
        ordinary["debug"] = detail
    return _period_times(ordinary, period)


def forecast_response(status: str, *, detector_hash: str, forecast_hash: str,
                      period: str = "day", debug: bool = False, mode: str = "LATEST") -> dict:
    """Independent response-shape examples, not a price solver/oracle.

    The simple affine conditions below exercise the published expression and
    association fields.  They make no claim that these prices are the forecast
    for an actual input prefix; separate Fraction cases supply arithmetic goldens.
    """
    detector_hash, forecast_hash = _identity(detector_hash), _identity(forecast_hash)
    if status not in FORECAST_STATUSES:
        raise ValueError("Unknown forecast fixture")
    if mode not in ("LATEST", "REPLAY"):
        raise ValueError("Unknown fixture request mode")
    b = {"startTime": "2024-12-26", "endTime": "2024-12-27", "price": 100, "dif": 20}
    price_range = {"lower": 100, "upper": 120, "lowerInclusive": False, "upperInclusive": False}
    ordinary = {
        "tsCode": "000001.SH", "period": period, "forecastVersion": "xxm-key-point-forecast-v0.3-r4",
        "forecastSpecHash": forecast_hash, "detectorSpecHash": detector_hash,
        "computedThrough": "2025-01-10", "requestedAsOf": None, "mode": "LATEST", "dataStatus": "READY",
        "ordinaryState": "NONE", "direction": "TOP", "status": status, "reasonCode": None,
        "forecastId": {
            "READY": "5000000000000000000000000000000000000000000000000000000000000001",
            "CONDITIONAL_ENTRY": "5000000000000000000000000000000000000000000000000000000000000002",
            "ENTRY_ONLY": "5000000000000000000000000000000000000000000000000000000000000003",
            "NO_CANDIDATE": "5000000000000000000000000000000000000000000000000000000000000004",
            "CONFIRMED": "5000000000000000000000000000000000000000000000000000000000000005",
            "PRECISION_PENDING": "5000000000000000000000000000000000000000000000000000000000000006",
            "DELAYED": "5000000000000000000000000000000000000000000000000000000000000007",
            "EMPTY": "5000000000000000000000000000000000000000000000000000000000000008",
        }[status],
        "targetEndpoint": None, "barsAhead": None, "confirmedAt": None, "confirmedDirection": None,
        "display": {"statusLabel": "人工合同样例", "targetText": "暂无形成日期", "conditionsText": "暂无确定形成条件", "asOfText": "截至01/10"},
        "applicabilityText": "仅适用于本次完成K线后的条件推算。", "invalidationText": "后续行情改变须重新计算。", "refreshAfterMs": 60000,
    }
    detail = {
        "sourceInputId": "4000000000000000000000000000000000000000000000000000000000000001",
        "calendarInputId": "4000000000000000000000000000000000000000000000000000000000000002",
        "precisionPolicy": "rounded3_guarded" if period == "day" else "full_float",
        "rearmContext": None, "nextBarOutcomes": None, "activation": None, "assumption": None,
        "targetEntryRanges": [], "targetEntryExclusions": [], "relations": [], "commonConditions": [], "examples": [],
    }
    if status in ("CONDITIONAL_ENTRY", "ENTRY_ONLY"):
        detail["activation"] = {"endpoint": "2025-01-13", "ranges": [
            {"entryRangeId": "entry-B", "priceRange": deepcopy(price_range), "reference": b}], "exclusions": [
            {"priceRange": {"lower": 0, "upper": 100, "lowerInclusive": False, "upperInclusive": True}, "reason": "PRICE_NOT_EXTREME"},
            {"priceRange": {"lower": 120, "upper": None, "lowerInclusive": True, "upperInclusive": False}, "reason": "DIF_NOT_DIVERGENT"}]}
    if status in ("READY", "CONDITIONAL_ENTRY"):
        entry_ids = ["entry-B"] if status == "CONDITIONAL_ENTRY" else []
        entry_domain = deepcopy(price_range) if entry_ids else None
        ordinary.update(ordinaryState="NONE" if entry_ids else "DULL", targetEndpoint="2025-01-14" if entry_ids else "2025-01-13",
                        barsAhead=2 if entry_ids else 1)
        ordinary["display"].update(targetText="下一目标完成K线", conditionsText="收盘必须严格高于100点且低于120点。")
        detail["assumption"] = {"policy": "entry_range_then_flat", "activationEndpoint": "2025-01-13" if entry_ids else None,
            "intermediateEndpoints": ["2025-01-13"] if entry_ids else [],
            "intermediateCloseExpression": {"op": "affine", "pCoefficient": 1 if entry_ids else 0, "cCoefficient": 0, "constant": 0 if entry_ids else 111}}
        detail["relations"] = [{"relationId": "relation-B", "entryRangeIds": entry_ids, "entryDomain": entry_domain,
            "reference": b, "initialReference": b, "referenceTransitions": [], "route": "dif_turn", "prefixConditions": [],
            "targetConditions": [{"left": {"op": "affine", "pCoefficient": 0, "cCoefficient": 1, "constant": 0}, "op": "gt",
                                  "right": {"op": "affine", "pCoefficient": 0, "cCoefficient": 0, "constant": 100}},
                                 {"left": {"op": "affine", "pCoefficient": 0, "cCoefficient": 1, "constant": 0}, "op": "lt",
                                  "right": {"op": "affine", "pCoefficient": 0, "cCoefficient": 0, "constant": 120}}]}]
        close_range = {"lower": 100, "upper": 120, "lowerInclusive": False, "upperInclusive": False,
                       "route": "dif_turn", "displayLower": 101, "displayUpper": 119, "displayPlaces": 2}
        detail["commonConditions"] = [{"relationId": "relation-B", "entryRangeIds": list(entry_ids), "entryDomain": deepcopy(entry_domain),
                                       "reference": b, "route": "dif_turn", "closeRanges": [close_range]}]
        if entry_ids:
            detail["targetEntryRanges"] = [{"entryRangeIds": ["entry-B"], "priceRange": deepcopy(price_range)}]
            detail["examples"] = [{"preClose": 110, "entryRangeId": "entry-B", "closeRanges": [{**deepcopy(close_range), "relationId": "relation-B"}]}]
    elif status == "ENTRY_ONLY":
        ordinary["reasonCode"] = "NO_CONFIRMATION_IN_HORIZON"
    elif status == "NO_CANDIDATE":
        ordinary["reasonCode"] = "NO_REFERENCE"
    elif status == "CONFIRMED":
        ordinary.update(ordinaryState="STRUCTURE", confirmedAt="2025-01-10", confirmedDirection="TOP")
        ordinary["display"].update(statusLabel="结构已形成", targetText="01/10已形成", conditionsText="实际完成K线已确认。")
    elif status == "PRECISION_PENDING":
        ordinary["reasonCode"] = "ROUNDING_BOUNDARY"
    elif status == "DELAYED":
        ordinary.update(dataStatus="DELAYED", reasonCode="SOURCE_DELAYED", ordinaryState=None, direction=None)
    elif status == "EMPTY":
        ordinary.update(dataStatus="EMPTY", reasonCode="SOURCE_EMPTY", computedThrough=None, ordinaryState=None, direction=None)
        detail.update(sourceInputId=None, calendarInputId=None)
    if mode == "REPLAY":
        ordinary.update(mode="REPLAY", requestedAsOf="2025-01-10")
    if debug:
        ordinary["debug"] = detail
    return _forecast_times(ordinary, period)


def invalid_recognition_response(defect: str, *, detector_hash: str) -> dict:
    """Deliberately invalid target bodies for P3 rejection tests, not accepted facts."""
    result = recognition_response("waiting", detector_hash=detector_hash, debug=True)
    if defect == "duplicate_event":
        result["events"].append(deepcopy(result["events"][0]))
        result["debug"]["events"].append(deepcopy(result["debug"]["events"][0]))
    elif defect == "dangling_rearm":
        result["debug"]["rearmRecords"] = []
    elif defect == "future_history":
        result["debug"]["bottomHistories"][0]["endedAt"] = "2025-01-13"
    elif defect == "null_debug":
        result["debug"] = None
    elif defect == "missing_debug":
        del result["debug"]
    elif defect == "normal_with_debug":
        # This body is invalid for request mode 0, even though mode 1 permits it.
        result = recognition_response("ready_none", detector_hash=detector_hash, debug=True)
    elif defect == "old_zero_reason":
        result["debug"]["rearmRecords"][0].update(status="SEGMENT_ENDED", endedAt="2025-01-10", endReason="zero")
        result["debug"]["points"][1]["pendingRearmId"] = None
    elif defect == "old_identity":
        result["algorithmVersion"] = "xxm-direction-v0.1-r2"
    else:
        raise ValueError("Unknown intentional defect")
    return result


def bottom_forecast_response(*, detector_hash: str, forecast_hash: str,
                             period: str = "day", debug: bool = False) -> dict:
    """Existing BOTTOM DULL contract example including nextBarOutcomes."""
    value = forecast_response("READY", detector_hash=detector_hash, forecast_hash=forecast_hash, period=period, debug=True)
    value["direction"] = "BOTTOM"
    reference = _period_times({"startTime": "2024-12-26", "endTime": "2024-12-27", "price": 100, "dif": -20}, period)
    value["debug"]["relations"][0].update(reference=deepcopy(reference), initialReference=deepcopy(reference))
    value["debug"]["commonConditions"][0]["reference"] = deepcopy(reference)
    value["debug"]["nextBarOutcomes"] = {
        "endpoint": FUTURE_ENDPOINTS[period][0], "initialReference": deepcopy(reference),
        "branches": [{"branchId": "branch-preserved", "priceRange": {"lower": 0, "upper": None, "lowerInclusive": False, "upperInclusive": False},
                      "outcome": "PRESERVED", "reference": deepcopy(reference), "route": None}],
    }
    if not debug:
        del value["debug"]
    return value


def waiting_forecast_response(*, detector_hash: str, forecast_hash: str,
                              period: str = "day", debug: bool = False) -> dict:
    """Existing waiting context reuses its saved reference, not a newly chosen A."""
    value = forecast_response("ENTRY_ONLY", detector_hash=detector_hash, forecast_hash=forecast_hash, period=period, debug=True)
    rearm = recognition_response("waiting", detector_hash=detector_hash, period=period, debug=True)["debug"]["rearmRecords"][0]
    value["direction"] = "BOTTOM"
    value["debug"]["rearmContext"] = rearm
    value["debug"]["activation"]["ranges"] = [{"entryRangeId": "entry-saved", "priceRange": {"lower": 0, "upper": 100, "lowerInclusive": False, "upperInclusive": False},
                                                "reference": deepcopy(rearm["reference"])}]
    value["debug"]["activation"]["exclusions"] = [{"priceRange": {"lower": 100, "upper": None, "lowerInclusive": True, "upperInclusive": False},
                                                   "reason": "PRICE_NOT_EXTREME"}]
    if not debug:
        del value["debug"]
    return value


def invalid_forecast_response(defect: str, *, detector_hash: str, forecast_hash: str) -> dict:
    """One intentional change to a contract example; rejection belongs to P3."""
    result = bottom_forecast_response(detector_hash=detector_hash, forecast_hash=forecast_hash, debug=True)
    if defect == "zero_reset":
        result["debug"]["nextBarOutcomes"]["branches"][0]["outcome"] = "ZERO_RESET"
    elif defect == "old_identity":
        result["forecastVersion"] = "xxm-key-point-forecast-v0.3-r2"
    elif defect == "dangling_relation":
        result["debug"]["commonConditions"][0]["relationId"] = "missing-relation"
    elif defect == "null_debug":
        result["debug"] = None
    elif defect == "missing_debug":
        del result["debug"]
    elif defect == "normal_with_debug":
        pass  # Invalid for request mode 0; a mode-1 root must retain this object.
    else:
        raise ValueError("Unknown intentional forecast defect")
    return result


def switched_forecast_response(*, detector_hash: str, forecast_hash: str,
                               period: str = "day", debug: bool = False) -> dict:
    """TOP B-to-A path exercises a nonempty referenceTransitions contract.

    The second future slot switches reference before the third-slot target;
    the initial and final reference
    must not be flattened to one peak by the consumer.  This is a shape example,
    not independently established price-domain output for a real source prefix.
    """
    value = forecast_response("READY", detector_hash=detector_hash, forecast_hash=forecast_hash, period=period, debug=True)
    value.update(targetEndpoint=FUTURE_ENDPOINTS[period][2], barsAhead=3,
                 forecastId="5000000000000000000000000000000000000000000000000000000000000009")
    relation = value["debug"]["relations"][0]
    initial = deepcopy(relation["initialReference"])
    farther = _period_times({"startTime": "2024-12-23", "endTime": "2024-12-24", "price": 110, "dif": 30}, period)
    relation.update(reference=farther, referenceTransitions=[{
        "endpoint": FUTURE_ENDPOINTS[period][1], "fromReference": initial, "toReference": deepcopy(farther),
    }])
    value["debug"]["assumption"]["intermediateEndpoints"] = list(FUTURE_ENDPOINTS[period][:2])
    value["debug"]["commonConditions"][0]["reference"] = deepcopy(farther)
    if not debug:
        del value["debug"]
    return value
