"""B2 orchestration uses independent literal inputs, never frozen data."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import json
import math
import time

import pytest

from scripts.research.index_market.xxm import r4_comparison as comparison
from scripts.research.index_market.xxm.r4_comparison import compare_r4, format_report
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar


def bars(values, period="day"):
    output = []
    for i, (close, dif, hist) in enumerate(values):
        stamp = (date(2023, 1, 3) + timedelta(days=i)).isoformat()
        if period != "day":
            stamp += "T15:00:00+08:00"
        output.append(XxmBar(stamp, close, dif, dif - hist / 2, hist))
    return tuple(output)


def run(values, period="day", **kwargs):
    defaults = dict(period=period, source_identity="b2-artificial", start_date="2023-01-03",
                    end_date="2023-01-31", deadline=time.monotonic() + 20)
    defaults.update(kwargs)
    return compare_r4(values, **defaults)


@pytest.mark.parametrize("period", ["day", "m60", "m90", "m120"])
def test_same_literal_input_groups_keep_business_results_equal(period):
    values = bars([(100, 10, 2), (101, 12, 2), (99, 9, -2), (100, 9, 2), (102, 10, 2)], period)
    original = deepcopy(values)
    result = run(values, period)
    assert set(result) == {"metadata", "rows", "differences", "idPairs", "summary"}
    assert result["metadata"]["calculationBarCount"] == 5
    assert "未补更早行情" in result["metadata"]["leftContextNote"]
    assert result["metadata"]["reportBarCount"] == 5
    assert [r["r2"]["point"]["ordinaryState"] for r in result["rows"]] == ["NONE"] * 4 + ["DULL"]
    assert [r["r4"]["point"]["ordinaryState"] for r in result["rows"]] == ["NONE"] * 4 + ["DULL"]
    for group in ("r2", "r4"):
        assert result["rows"][-1][group]["point"]["activeReference"] == {
            "startTime": values[0].time, "endTime": values[1].time, "price": 101, "dif": 12}
    assert not result["differences"] and result["summary"]["differenceDateCount"] == 0
    assert result["rows"][-1]["r2"]["events"][0]["id"] != result["rows"][-1]["r4"]["events"][0]["id"]
    assert values == original
    # Mutating one returned group must not change the other or the input.
    result["rows"][-1]["r4"]["point"]["activeReference"]["price"] = 1
    assert result["rows"][-1]["r2"]["point"]["activeReference"]["price"] == 101
    assert values == original


def test_date_end_stops_calculation_and_start_only_filters_report():
    values = bars([(100, 10, 2), (101, 12, 2), (99, 9, -2), (100, 9, 2), (102, 10, 2), (103, 9.8, 2)])
    result = run(values, start_date="2023-01-07", end_date="2023-01-07")
    assert len(result["rows"]) == 5 and result["metadata"]["inputBarCount"] == 6
    assert result["metadata"]["calculationStart"] == "2023-01-03"
    assert result["metadata"]["calculationEnd"] == "2023-01-07"
    assert result["metadata"]["reportBarCount"] == 1
    assert result["summary"]["r2EventCounts"] == {"DULL": 1}
    assert result["summary"]["r4EventCounts"] == {"DULL": 1}
    assert all(r["time"] <= "2023-01-07" for r in result["rows"])


def test_nearest_and_strongest_reference_difference_is_reported_with_literal_refs():
    # Old A has price100/DIF30, B price110/DIF20, C price120/DIF15.
    # Both qualify: r2 chooses the stronger A; r4 the nearer B.
    values = bars([(100, 30, 2), (90, 0, -2), (110, 20, 2),
                   (90, 0, -2), (115, 14, 2), (120, 15, 2)])
    result = run(values)
    last = result["rows"][-1]
    assert last["r2"]["point"]["ordinaryState"] == last["r4"]["point"]["ordinaryState"] == "DULL"
    assert last["r2"]["point"]["activeReference"]["startTime"] == "2023-01-03"
    assert last["r4"]["point"]["activeReference"]["startTime"] == "2023-01-05"
    assert "2023-01-08" in result["summary"]["differenceDates"]
    assert any("Reference" in d["field"] or "reference" in d["field"] for d in result["differences"])
    report = format_report(result)
    assert "2023-01-08：不同字段" in report
    assert "2023-01-03—2023-01-03，收盘极值100，DIF极值30" in report
    assert "2023-01-05—2023-01-05，收盘极值110，DIF极值20" in report
    assert "activation/B" in report and "价格通过，DIF通过" in report
    assert "未检查" in report and "原因：" in report


def test_report_explains_literal_same_bar_reference_switch_without_new_events():
    """Formatter fixture follows the inspected step/decision fields, not a replay."""
    near = {"startTime": "2023-03-03", "endTime": "2023-03-06", "price": 120, "dif": 24.935}
    far = {"startTime": "2023-01-05", "endTime": "2023-02-07", "price": 100, "dif": 41.186}
    raw = {"time": "2023-04-18", "close": 130, "dif": 26.754, "dea": 25.754, "hist": 2}
    wave = dict(sign=1, start="2023-04-12", end=raw["time"], count=5, price=130,
                dif=26.754, price_at=raw["time"], dif_at=raw["time"])
    def group(old, action, started, branch, reason):
        checks = ([{"stage": "top_rescue", "candidate": "A", "reference": deepcopy(far),
                    "wave": deepcopy(wave), "checked": True, "pricePassed": True,
                    "difPassed": True, "reason": "A价格/DIF合格"}] if action == "rescue" else
                  [{"stage": "not_entered", "candidate": "A", "reference": deepcopy(far),
                    "wave": deepcopy(wave), "checked": False, "pricePassed": None,
                    "difPassed": None, "reason": "已有参照仍有效，未调用选择方法"}])
        return {"point": {**raw, "ordinaryState": "DULL", "ordinaryDirection": "TOP",
                          "activeReference": deepcopy(far), "pendingTopHistoryId": None,
                          "pendingBottomHistoryId": None, "pendingRearmId": None},
                "events": [], "histories": [], "bottomHistories": [], "rearmRecords": [],
                "decision": {"before": {"state": "DULL", "reference": deepcopy(old),
                                        "wave": deepcopy(wave), "previous": {"time": "2023-04-17",
                                            "close": 129, "dif": 20, "dea": 19, "hist": 2,
                                            "completed": True}, "pendingRearm": None},
                             "rawSign": 1, "wave": deepcopy(wave),
                             "referenceChecks": checks,
                             "selectedReference": {"reference": deepcopy(far), "startedAt": started,
                                                   "action": action, "rearmId": None},
                             "turn": {"previousDif": 20, "currentDif": 26.754, "threshold": .2,
                                      "referenceBroken": False, "checked": True, "reason": "相邻实际DIF按1%检查"},
                             "branch": branch, "reason": reason}}
    row = {"time": raw["time"], "input": {**raw, "completed": True},
           "r2": group(far, "retained", "2023-04-14", "retained", "沿用原参照"),
           "r4": group(near, "rescue", "2023-04-18", "reference_switch",
                       "B已突破，A价格/DIF合格，当根切换并保持钝化")}
    result = {"metadata": {"period": "day", "requestedStartDate": raw["time"],
                           "requestedEndDate": raw["time"], "calculationStart": raw["time"],
                           "calculationEnd": raw["time"], "calculationBarCount": 1, "reportBarCount": 1,
                           "elapsedSeconds": .01, "peakMemoryBytes": 1024, "resultBytes": 4096},
              "rows": [row], "differences": [{"time": raw["time"], "field": "decision.selectedReference",
                  "reason": "此前参照不同，本根使用日期亦不同"}], "idPairs": [],
              "summary": {"r2EventCounts": {}, "r4EventCounts": {}, "differenceDateCount": 1,
                          "firstDifference": raw["time"], "differenceDates": [raw["time"]]}}
    before = deepcopy(result)
    report = format_report(result)
    assert "参照切换（2023-04-18）" in report
    assert "切换前：2023-03-03—2023-03-06，收盘极值120，DIF极值24.935" in report
    assert "切换后：2023-01-05—2023-02-07，收盘极值100，DIF极值41.186" in report
    assert "本参照开始使用：2023-04-18" in report
    assert "B已突破，A价格/DIF合格，当根切换并保持钝化" in report
    assert "价格通过，DIF通过" in report and "无新事件" in report
    assert "CANCEL" not in report and "activation" not in report
    assert result == before


def test_same_bar_top_switch_is_reported_but_does_not_add_labels_or_change_original_dull():
    # LLD15.4 hand-computable artificial history: A100/41.186,
    # B120/24.935, then C first DULL17.649 -> switch26.754 -> retain27.890.
    values = bars([(100, 41.186, 2), (90, 0, -2), (120, 24.935, 2), (90, 0, -2),
                   (125, 17, 2), (130, 17.649, 2), (131, 26.754, 2), (132, 27.890, 2)])
    result = run(values)
    first, switched, later = result["rows"][5:8]
    near = {"startTime": "2023-01-05", "endTime": "2023-01-05", "price": 120, "dif": 24.935}
    far = {"startTime": "2023-01-03", "endTime": "2023-01-03", "price": 100, "dif": 41.186}
    assert result["metadata"]["r4ResearchVersion"] == "xxm-research-r4-v2"
    assert first["r2"]["point"]["activeReference"] == far
    assert first["r4"]["point"]["activeReference"] == near
    original = first["r4"]["events"][0]
    assert (original["time"], original["type"], original["eventReference"]) == ("2023-01-08", "DULL", near)
    for row in (switched, later):
        for side in ("r2", "r4"):
            assert row[side]["point"]["ordinaryState"] == "DULL"
            assert row[side]["point"]["activeReference"] == far
            assert row[side]["events"] == []
    selected = switched["r4"]["decision"]["selectedReference"]
    assert selected == {"reference": far, "startedAt": "2023-01-09", "action": "rescue", "rearmId": None}
    assert switched["r4"]["decision"]["before"]["reference"] == near
    assert switched["r4"]["decision"]["branch"] == "reference_switch"
    assert later["r4"]["decision"]["selectedReference"]["action"] == "retained"
    assert later["r4"]["decision"]["selectedReference"]["startedAt"] == "2023-01-09"
    assert result["summary"]["r2EventCounts"] == result["summary"]["r4EventCounts"] == {"DULL": 1}
    assert not any(d["category"] in ("ordinaryState", "events")
                   for d in result["differences"] if d["time"] >= "2023-01-09")
    assert any(d["category"] == "referenceDecision" and d["time"] == "2023-01-09"
               for d in result["differences"])
    report = format_report(result)
    assert "参照切换（2023-01-09）" in report
    assert "本参照开始使用：2023-01-09" in report
    assert original["time"] == "2023-01-08" and original["eventReference"] == near


def test_failed_nearest_price_gate_does_not_invent_a_sorting_difference():
    values = bars([(100, -10, -2), (99, -11, -2), (105, -5, 2),
                   (98, -9, -2), (97, -9.2, -2), (100, -9.2, 2),
                   (100, -9.5, -2), (100, -9.6, -2), (101, -9.4, 2),
                   (100, -9.5, -2), (100, -9.4, 2)])
    result = run(values)
    assert not result["differences"]
    assert result["summary"]["differenceDateCount"] == 0
    for side in ("r2", "r4"):
        checks = result["rows"][7][side]["decision"]["referenceChecks"]
        assert [c["candidate"] for c in checks] == ["B", "B", "A"]
        assert checks[0]["pricePassed"] is False
        assert [c["checked"] for c in checks[1:]] == [False, False]


def test_multiple_minute_differences_on_one_day_count_as_one_date():
    values = tuple(XxmBar("2023-01-03T" + endpoint + ":00+08:00", close, dif, dif - hist / 2, hist)
                   for endpoint, close, dif, hist in (("10:30", 100, 40, 2),
                       ("11:30", 101, 41, 2), ("14:00", 100, 40, 0), ("15:00", 102, 40.5, 2)))
    result = run(values, "m60", end_date="2023-01-03")
    assert result["summary"]["differenceDates"] == ["2023-01-03"]
    assert result["summary"]["differenceDateCount"] == 1
    assert {d["time"] for d in result["differences"]} == {
        "2023-01-03T14:00:00+08:00", "2023-01-03T15:00:00+08:00"}


@pytest.mark.parametrize("change", [
    {"period": "week"}, {"source_identity": ""}, {"start_date": "2023-1-3"},
    {"start_date": "2023-02-01", "end_date": "2023-01-03"},
    {"deadline": True}, {"deadline": math.inf}, {"source_metadata": []},
    {"source_metadata": {"precision": math.nan}},
])
def test_invalid_parameters_rejected_before_return(change):
    with pytest.raises(ValueError):
        run(bars([(100, 1, 2)]), **change)


@pytest.mark.parametrize("values", [(), [], (None,),
    (XxmBar("2023-01-03", True, 1, 0, 2),),
    (XxmBar("2023-01-03", 100, 1, 0, 2, False),),
    (XxmBar("2023-01-04", 100, 1, 0, 2), XxmBar("2023-01-03", 100, 1, 0, 2)),
    (XxmBar("2023-01-03", 100, 1, 0, 2),) * 2,
])
def test_invalid_input_is_not_silently_repaired(values):
    with pytest.raises(ValueError):
        run(values)


def test_late_timeout_memory_and_result_size_fail_without_partial_result(monkeypatch):
    values = bars([(100, 1, 2)])
    with pytest.raises(TimeoutError):
        run(values, deadline=time.monotonic() - 1)
    with monkeypatch.context() as patch:
        patch.setattr(comparison, "_memory_bytes", lambda: 256 * 1024 ** 2 + 1)
        with pytest.raises(MemoryError):
            run(values)
    with monkeypatch.context() as patch:
        original_encode = comparison._encoded
        def oversized_result(value):
            if isinstance(value, dict) and "rows" in value:
                return b"x" * (16 * 1024 ** 2 + 1)
            return original_encode(value)
        patch.setattr(comparison, "_encoded", oversized_result)
        with pytest.raises(OverflowError):
            run(values)
    with monkeypatch.context() as patch:
        original = comparison.compare_records
        def finish_late(*args, **kwargs):
            output = original(*args, **kwargs)
            patch.setattr(comparison.time, "monotonic", lambda: 1e15)
            return output
        patch.setattr(comparison, "compare_records", finish_late)
        with pytest.raises(TimeoutError):
            run(values)
    assert run(values)["metadata"]["calculationBarCount"] == 1


def test_1000_artificial_bars_complete_with_original_limits_and_1001_is_rejected():
    # All one red segment, with no history: literal expected NONE/no events.
    values = bars([(100 + i / 100, 0, 2) for i in range(1000)])
    result = run(values, end_date=values[-1].time)
    assert result["metadata"]["calculationBarCount"] == 1000
    assert result["metadata"]["reportBarCount"] == 1000
    assert result["summary"]["r2EventCounts"] == result["summary"]["r4EventCounts"] == {}
    assert result["summary"]["differenceDateCount"] == 0
    assert result["metadata"]["elapsedSeconds"] < 20
    assert result["metadata"]["peakMemoryBytes"] <= 256 * 1024 ** 2
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    assert len(encoded) == result["metadata"]["resultBytes"] <= 16 * 1024 ** 2
    assert "1000根" in format_report(result)
    print({key: result["metadata"][key] for key in
           ("calculationBarCount", "elapsedSeconds", "peakMemoryBytes", "resultBytes")})
    extra = replace(values[-1], time=(date.fromisoformat(values[-1].time) + timedelta(days=1)).isoformat())
    with pytest.raises(ValueError):
        run(values + (extra,), end_date=extra.time)


def test_compare_uses_no_external_access_and_keeps_source_notes_independent(monkeypatch):
    import builtins
    from pathlib import Path
    import socket
    notes = {"table": "manual", "precision": "literal int/float"}
    original = deepcopy(notes)
    def forbidden(*args, **kwargs):
        raise AssertionError("Pure comparison attempted external access")
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(socket.socket, "connect", forbidden)
        result = run(bars([(100, 1, 2)]), source_metadata=notes)
    result["metadata"]["sourceDescription"]["table"] = "different"
    assert notes == original


def test_all_comparison_modules_keep_calculation_only_imports():
    import ast
    from pathlib import Path
    from scripts.research.index_market.xxm import r4_comparison_records, r4_observation
    allowed = "src.biz.services.wealth.market.index_detail_xxm"
    for module in (comparison, r4_comparison_records, r4_observation):
        for node in ast.walk(ast.parse(Path(module.__file__).read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.level == 1  # Own research directory only.
                continue
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert all(name.split(".")[0] in comparison.sys.stdlib_module_names
                       or name == allowed or name.startswith(allowed + ".") for name in names)
