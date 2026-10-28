"""Literal records from the current step/decision contract, no calculator runs."""
from copy import deepcopy

import pytest

from scripts.research.index_market.xxm.r4_comparison_records import compare_records


DAYS = ("2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09")
REF = {"startTime": "2025-01-02", "endTime": "2025-01-03", "price": 100, "dif": 20}


def wave(day, sign=1):
    return dict(sign=sign, start=DAYS[0], end=day, count=DAYS.index(day) + 2,
                price=102 if sign == 1 else 98, dif=10 if sign == 1 else -10,
                price_at=DAYS[0], dif_at=DAYS[0])


def event(identity, day, kind, *, direction="TOP", route="dif_turn", top=None, bottom=None, rearm=None):
    return dict(id=identity, time=day, direction=direction, type=kind, route=route,
                fromState="DULL", eventReference=deepcopy(REF), relatedTopHistoryId=top,
                relatedBottomHistoryId=bottom, relatedRearmId=rearm)


def group(day, *, state="NONE", direction=None, events=(), histories=(), bottom=(), rearm=(),
          pending_top=None, pending_bottom=None, pending_rearm=None, sign=1):
    raw = dict(close=102 if sign == 1 else 98, dif=10 * sign, dea=9 * sign, hist=2 * sign)
    reference = deepcopy(REF) if state != "NONE" else None
    return dict(point={"time": day, **raw, "ordinaryState": state, "ordinaryDirection": direction,
                       "activeReference": reference, "pendingTopHistoryId": pending_top,
                       "pendingBottomHistoryId": pending_bottom, "pendingRearmId": pending_rearm},
                events=list(events), histories=list(histories), bottomHistories=list(bottom),
                rearmRecords=list(rearm), decision={
                    "before": {"state": "NONE", "reference": None, "wave": None,
                               "previous": None, "pendingRearm": None},
                    "rawSign": sign, "wave": wave(day, sign), "referenceChecks": [],
                    "selectedReference": None if reference is None else {
                        "reference": reference, "startedAt": DAYS[0], "action": "retained", "rearmId": None},
                    "turn": {"previousDif": 10, "currentDif": 10, "threshold": .1,
                             "referenceBroken": False, "checked": False, "reason": "未到转折"},
                    "branch": "retained", "reason": "人工字面记录"})


def row(day, a=None, b=None):
    a = group(day) if a is None else a
    b = group(day) if b is None else b
    return dict(time=day, input={name: a["point"][name] for name in ("close", "dif", "dea", "hist")},
                r2=a, r4=b)


def top_records():
    result = []
    for n, day in enumerate(DAYS[:3]):
        sides = []
        for p in ("left", "right"):
            history = dict(id=p + "-history", confirmedAt=DAYS[1], confirmationRoute="dif_turn",
                           pricePeak=102, pricePeakAt=DAYS[0], originalReference=deepcopy(REF),
                           status="PENDING" if n == 1 else "ENDED", endedAt=None if n == 1 else day,
                           endReason=None if n == 1 else "historical_price_break", observedThrough=day,
                           ageBars=max(0, n - 1), negativeBars=0, zeroBars=0, colorChanges=0)
            if n == 0:
                g = group(day, state="DULL", direction="TOP",
                          events=[event(p + "-dull", day, "DULL", route="activation")])
            elif n == 1:
                g = group(day, state="STRUCTURE", direction="TOP", pending_top=p + "-history",
                          events=[event(p + "-structure", day, "STRUCTURE", top=p + "-history")],
                          histories=[history])
                g["decision"]["before"].update(state="DULL", reference=deepcopy(REF), wave=wave(DAYS[0]))
            else:
                g = group(day, state="STRUCTURE", direction="TOP",
                          events=[event(p + "-withdraw", day, "RESEARCH_HISTORICAL_WITHDRAWAL",
                                        route="historical_price_break", top=p + "-history")], histories=[history])
                g["decision"]["before"].update(state="STRUCTURE", reference=deepcopy(REF), wave=wave(DAYS[1]))
            sides.append(g)
        result.append(row(day, *sides))
    return result


def compare(rows, start=DAYS[0], end=DAYS[3]):
    return compare_records(rows, start_date=start, end_date=end, check=lambda: None)


def bottom_records():
    records = []
    for n, day in enumerate(DAYS):
        sides = []
        for p in ("left", "right"):
            history = dict(id=p + "-bottom", structureEventId=p + "-structure", confirmedAt=DAYS[1],
                           confirmationRoute="dif_turn", originSegmentStart=DAYS[0], leftOriginAt=None,
                           priceLow=98, priceLowAt=DAYS[0], originalReference=deepcopy(REF),
                           status="PENDING" if n == 1 else "ENDED", endedAt=None if n == 1 else DAYS[2],
                           endReason=None if n == 1 else "structure_disappeared", observedThrough=day,
                           ageBars=max(0, n - 1))
            waiting = dict(id=p + "-wait", direction="BOTTOM", bottomHistoryId=p + "-bottom",
                           structureEventId=p + "-structure", structureConfirmedAt=DAYS[1],
                           structureRoute="dif_turn", segmentStart=DAYS[0], nearestPriceGate=100,
                           referenceWave=wave(DAYS[0], -1), disappearedAt=DAYS[2], observedThrough=day,
                           status="WAITING" if n == 2 else "REACTIVATED",
                           endedAt=None if n == 2 else day, endReason=None if n == 2 else "price_requalified")
            if n == 0:
                g = group(day, state="DULL", direction="BOTTOM", sign=-1,
                          events=[event(p + "-dull", day, "DULL", direction="BOTTOM", route="activation")])
            elif n == 1:
                g = group(day, state="STRUCTURE", direction="BOTTOM", sign=-1, pending_bottom=p + "-bottom",
                          events=[event(p + "-structure", day, "STRUCTURE", direction="BOTTOM",
                                        bottom=p + "-bottom")], bottom=[history])
            elif n == 2:
                g = group(day, sign=-1, pending_rearm=p + "-wait",
                          events=[event(p + "-disappear", day, "STRUCTURE_DISAPPEARED", direction="BOTTOM",
                                        route="dif_return", bottom=p + "-bottom", rearm=p + "-wait")],
                          bottom=[history], rearm=[waiting])
            else:
                g = group(day, state="DULL", direction="BOTTOM", sign=-1,
                          events=[event(p + "-reactivated", day, "DULL", direction="BOTTOM",
                                        route="reactivation", rearm=p + "-wait")], rearm=[waiting])
                g["decision"]["selectedReference"].update(startedAt=day, action="reactivation", rearmId=p + "-wait")
            if n:
                g["decision"]["before"].update(state=("NONE" if n == 3 else "DULL" if n == 1 else "STRUCTURE"),
                                               wave=wave(DAYS[n - 1], -1), reference=deepcopy(REF) if n < 3 else None)
            sides.append(g)
        records.append(row(day, *sides))
    return records


def test_same_business_with_different_ids_does_not_report_changes_or_mutate_records():
    records = top_records()
    before = deepcopy(records)
    result = compare(records)
    assert result["differences"] == []
    assert result["summary"] == {
        "r2EventCounts": {"DULL": 1, "STRUCTURE": 1, "RESEARCH_HISTORICAL_WITHDRAWAL": 1},
        "r4EventCounts": {"DULL": 1, "STRUCTURE": 1, "RESEARCH_HISTORICAL_WITHDRAWAL": 1},
        "differenceDates": [], "differenceDateCount": 0, "differenceCounts": {},
        "prefixFirstDifference": None, "firstDifference": None}
    assert len(result["idPairs"]) == 4 and all(p["status"] == "matched" for p in result["idPairs"])
    assert records == before


def test_same_label_but_different_reference_is_reported_with_original_values():
    records = [row(DAYS[0], group(DAYS[0], state="DULL", direction="TOP"),
                   group(DAYS[0], state="DULL", direction="TOP"))]
    records[0]["r4"]["point"]["activeReference"]["dif"] = 30
    records[0]["r4"]["decision"]["selectedReference"]["reference"]["dif"] = 30
    result = compare(records)
    assert result["summary"]["differenceDates"] == [DAYS[0]]
    assert result["summary"]["differenceDateCount"] == 1
    item = next(d for d in result["differences"] if d["field"] == "point.activeReference")
    assert item["r2"]["dif"] == 20 and item["r4"]["dif"] == 30
    assert item["effect"] == "unknown" and item["previousDifferenceAt"] is None


def test_reference_check_order_and_unchecked_null_are_preserved():
    g = group(DAYS[0])
    checks = [dict(stage="activation", candidate=name, reference=deepcopy(REF), wave=wave(DAYS[0]),
                   checked=False, pricePassed=None, difPassed=None, reason="前一候选已选") for name in ("A", "B")]
    a, b = deepcopy(g), deepcopy(g)
    a["decision"]["referenceChecks"] = checks
    b["decision"]["referenceChecks"] = list(reversed(deepcopy(checks)))
    result = compare([row(DAYS[0], a, b)])
    changed = result["differences"]
    assert [item["field"] for item in changed] == ["decision.referenceChecks"]
    assert changed[0]["effect"] == "current_rule"
    assert changed[0]["r2"][0]["pricePassed"] is None
    assert changed[0]["r4"][0]["candidate"] == "B"


def test_description_only_rule_and_count_text_does_not_create_permanent_difference():
    records = [row(DAYS[0])]
    records[0]["r2"]["decision"].update(countMeaning="所有本段K线", reason="r2说明", rule="r2")
    records[0]["r4"]["decision"].update(countMeaning="有色K线", reason="r4说明", rule="r4")
    assert not compare(records)["differences"]


def test_ambiguous_same_day_events_remain_unpaired():
    a = group(DAYS[0], events=[event("left-a", DAYS[0], "DULL"), event("left-b", DAYS[0], "DULL")])
    b = group(DAYS[0], events=[event("right-a", DAYS[0], "DULL")])
    result = compare([row(DAYS[0], a, b)])
    assert len(result["idPairs"]) == 3
    assert {p["status"] for p in result["idPairs"]} == {"ambiguous"}
    assert result["summary"]["r2EventCounts"] == {"DULL": 2}
    assert result["summary"]["r4EventCounts"] == {"DULL": 1}


def test_no_cross_day_early_or_late_matching():
    records = [row(DAYS[0], group(DAYS[0], events=[event("left", DAYS[0], "DULL")]), group(DAYS[0])),
               row(DAYS[1], group(DAYS[1]), group(DAYS[1], events=[event("right", DAYS[1], "DULL")]))]
    result = compare(records)
    assert [p["status"] for p in result["idPairs"]] == ["r2_only", "r4_only"]
    assert result["summary"]["differenceDates"] == list(DAYS[:2])


def test_bottom_history_waiting_and_reactivation_keep_their_original_structure_pair():
    result = compare(bottom_records(), start=DAYS[2])
    assert result["differences"] == []
    assert result["summary"]["r2EventCounts"] == {"STRUCTURE_DISAPPEARED": 1, "DULL": 1}
    assert result["summary"]["r4EventCounts"] == {"STRUCTURE_DISAPPEARED": 1, "DULL": 1}
    pairs = {item["r2Id"]: item for item in result["idPairs"]}
    assert len(pairs) == 6 and all(item["status"] == "matched" for item in pairs.values())
    assert pairs["left-bottom"]["r4Id"] == "right-bottom"
    assert pairs["left-wait"]["r4Id"] == "right-wait"
    assert pairs["left-reactivated"]["r4Id"] == "right-reactivated"
    assert pairs["left-bottom"]["direction"] == "BOTTOM"
    assert pairs["left-wait"]["sourceSegmentStart"] == DAYS[0]


@pytest.mark.parametrize("record_type", ["bottomHistories", "rearmRecords"])
def test_bottom_or_waiting_cannot_link_to_another_non_structure_event(record_type):
    records = bottom_records()
    day = 1 if record_type == "bottomHistories" else 2
    records[day]["r2"][record_type][0]["structureEventId"] = "left-dull"
    with pytest.raises(ValueError, match="另一结构|不对应"):
        compare(records)


def test_later_withdrawal_does_not_pair_different_original_structure_dates():
    base = top_records()
    records = deepcopy(base[:2])
    # The right structure forms one day later. A common later withdrawal
    # cannot retroactively make the two original structures the same event.
    records[1]["r4"] = group(DAYS[1], state="DULL", direction="TOP")
    middle = deepcopy(base[1])
    middle["time"] = DAYS[2]
    middle["r2"] = deepcopy(base[2]["r2"])
    middle["r2"]["events"] = []
    middle["r2"]["histories"][0].update(status="PENDING", endedAt=None, endReason=None)
    middle["r2"]["point"]["pendingTopHistoryId"] = "left-history"
    middle["r4"]["point"]["time"] = DAYS[2]
    middle["r4"]["events"][0]["time"] = DAYS[2]
    middle["r4"]["histories"][0].update(confirmedAt=DAYS[2], observedThrough=DAYS[2])
    middle["r4"]["decision"]["wave"] = wave(DAYS[2])
    records.append(middle)
    last = deepcopy(base[2])
    last["time"] = DAYS[3]
    for side in ("r2", "r4"):
        g = last[side]
        g["point"]["time"] = DAYS[3]
        g["events"][0]["time"] = DAYS[3]
        g["histories"][0].update(observedThrough=DAYS[3], endedAt=DAYS[3])
        g["decision"]["wave"] = wave(DAYS[3])
    last["r4"]["histories"][0]["confirmedAt"] = DAYS[2]
    records.append(last)
    result = compare(records)
    related = [pair for pair in result["idPairs"] if pair["kind"] == "histories"
               or pair["r2Id"] == "left-withdraw" or pair["r4Id"] == "right-withdraw"]
    assert len(related) == 4 and all(pair["status"] != "matched" for pair in related)


@pytest.mark.parametrize("field", ["pendingTopHistoryId", "pendingBottomHistoryId", "pendingRearmId"])
def test_hanging_or_future_point_reference_is_rejected(field):
    records = top_records()
    records[0]["r2"]["point"][field] = "left-history"
    with pytest.raises(ValueError, match="悬挂|错误类型"):
        compare(records)


def test_history_link_wrong_record_type_is_rejected():
    records = top_records()
    records[1]["r2"]["events"][0]["relatedTopHistoryId"] = "left-dull"
    with pytest.raises(ValueError, match="错误类型"):
        compare(records)


def test_id_cannot_be_reused_across_record_types():
    records = top_records()
    records[1]["r2"]["histories"][0]["id"] = "left-structure"
    with pytest.raises(ValueError, match="跨类型"):
        compare(records)


def test_history_cannot_be_created_without_its_original_structure():
    records = top_records()
    records[1]["r2"]["events"] = []
    with pytest.raises(ValueError, match="历史没有"):
        compare(records)


def test_history_updates_cannot_change_original_structure_reference():
    records = top_records()
    records[2]["r2"]["histories"][0]["originalReference"]["dif"] = 21
    with pytest.raises(ValueError, match="改变了原结构"):
        compare(records)


def test_start_filter_keeps_prefix_pairing_and_distinguishes_first_difference():
    records = top_records()
    records[0]["r4"]["decision"]["wave"]["price"] = 103
    records[2]["r4"]["decision"]["before"]["wave"]["price"] = 103
    records[2]["r4"]["point"]["ordinaryState"] = "NONE"
    result = compare(records, start=DAYS[2])
    assert result["summary"]["prefixFirstDifference"] == DAYS[0]
    assert result["summary"]["firstDifference"] == DAYS[2]
    assert result["summary"]["differenceDates"] == [DAYS[2]]
    assert result["summary"]["r2EventCounts"] == {"RESEARCH_HISTORICAL_WITHDRAWAL": 1}
    assert len(result["idPairs"]) == 4
    assert all(item["time"] == DAYS[2] for item in result["differences"])
    item = next(d for d in result["differences"] if d["field"] == "point.ordinaryState")
    assert item["effect"] == "prior_difference" and item["previousDifferenceAt"] == DAYS[0]


def test_zero_change_has_actual_zero_explanation_and_no_invented_video_claim():
    records = [row(DAYS[0])]
    for side in ("r2", "r4"):
        records[0][side]["decision"]["rawSign"] = 0
    records[0]["r4"]["decision"]["wave"]["count"] = 1
    result = compare(records)
    assert result["differences"][0]["effect"] == "current_rule"
    assert "零柱" in result["differences"][0]["reason"]


@pytest.mark.parametrize("start,end", [("2025-1-06", DAYS[1]), (DAYS[1], DAYS[0]), (None, DAYS[1])])
def test_bad_report_range_is_rejected(start, end):
    with pytest.raises(ValueError):
        compare([], start=start, end=end)


def test_empty_observation_and_empty_prefix_are_explicit():
    assert compare([])["summary"]["firstDifference"] is None
    result = compare(top_records(), start=DAYS[3])
    assert not result["differences"] and result["summary"]["r2EventCounts"] == {}


def test_same_day_minute_differences_count_one_date_without_losing_exact_times():
    stamps = (DAYS[0] + "T10:30:00+08:00", DAYS[0] + "T11:30:00+08:00")
    records = []
    for stamp in stamps:
        a, b = group(DAYS[0]), group(DAYS[0])
        for value in (a, b):
            value["point"]["time"] = stamp
            value["decision"]["wave"].update(start=stamps[0], end=stamp,
                                               price_at=stamps[0], dif_at=stamps[0])
        b["decision"]["wave"]["price"] = 103
        records.append(row(stamp, a, b))
    result = compare(records)
    assert result["summary"]["differenceDates"] == [DAYS[0]]
    assert result["summary"]["differenceDateCount"] == 1
    assert result["summary"]["prefixFirstDifference"] == stamps[0]
    assert result["summary"]["firstDifference"] == stamps[0]
    assert [item["time"] for item in result["differences"]] == list(stamps)


def test_check_is_called_through_index_pairing_and_comparison_and_failure_does_not_mutate():
    records = top_records()
    original = deepcopy(records)
    calls = []
    def check():
        calls.append(1)
        if len(calls) == 15:
            raise TimeoutError("deadline")
    with pytest.raises(TimeoutError):
        compare_records(records, start_date=DAYS[0], end_date=DAYS[3], check=check)
    assert len(calls) == 15 and records == original
