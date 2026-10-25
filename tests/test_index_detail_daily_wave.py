"""Independent daily-fact examples, next-stage LLD 14.3.1/14.4/14.6.1.

These artificial prices and indicator tuples are literal rule examples, not
EMA-derived market data or author-software expected labels. No fixture reads
the saved research cases, a database, Lake files, or an external source.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
import builtins
import socket
import sys
import time

import pytest

from src.biz.services.wealth.market.index_detail_daily_wave import calculator
from src.biz.services.wealth.market.index_detail_daily_wave.calculator import (
    DailyWaveBudgetExceeded, DailyWaveCancelled, DailyWaveInputError,
    build_basic_records, build_color_segments,
)
from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC


def row(day, close="100", indicators=("1", "0", "2")):
    """Only package independently specified literal input; no indicator formula."""
    dif, dea, macd = indicators
    return dict(tsCode="000001.SH", date=day, close=close,
                dif=dif, dea=dea, macd=macd, completed=True)


def records(rows, *, as_of="2024-01-31", **kwargs):
    return build_basic_records(rows, as_of=as_of, **kwargs).to_dict()


def turn_view(result, metric):
    return [(t["kind"], t["value"], t["firstDate"], t["lastDate"], t["confirmedAt"])
            for t in result["turns"] if t["metric"] == metric]


def test_empty_prefix_contains_only_basic_facts_and_no_fake_ready_or_candidates():
    assert records([]) == dict(
        tsCode="000001.SH", period="day", ruleId="xxm-daily-wave-review-v0.1",
        asOf=None, contextStart=None, contextEnd=None, sourcePoints=[],
        turns=[], pendingTurns=[], colorSegments=[],
    )


def test_literal_close_and_dif_turns_retain_all_small_same_color_peaks():
    rows = [
        row("2023-10-23", "100", ("4", "5", "-2")),
        row("2023-10-24", "110", ("5", "4", "2")),
        row("2023-10-25", "105", ("4", "3.5", "1")),
        row("2023-10-26", "120", ("7", "6", "2")),
        row("2023-10-27", "112", ("6", "5.5", "1")),
        row("2023-10-30", "130", ("9", "8", "2")),
        row("2023-10-31", "125", ("8", "8.5", "-1")),
    ]
    result = records(rows)
    assert turn_view(result, "CLOSE") == [
        ("MAX", "110", "2023-10-24", "2023-10-24", "2023-10-25T15:00:00+08:00"),
        ("MIN", "105", "2023-10-25", "2023-10-25", "2023-10-26T15:00:00+08:00"),
        ("MAX", "120", "2023-10-26", "2023-10-26", "2023-10-27T15:00:00+08:00"),
        ("MIN", "112", "2023-10-27", "2023-10-27", "2023-10-30T15:00:00+08:00"),
        ("MAX", "130", "2023-10-30", "2023-10-30", "2023-10-31T15:00:00+08:00"),
    ]
    assert turn_view(result, "DIF") == [
        ("MAX", "5", "2023-10-24", "2023-10-24", "2023-10-25T15:00:00+08:00"),
        ("MIN", "4", "2023-10-25", "2023-10-25", "2023-10-26T15:00:00+08:00"),
        ("MAX", "7", "2023-10-26", "2023-10-26", "2023-10-27T15:00:00+08:00"),
        ("MIN", "6", "2023-10-27", "2023-10-27", "2023-10-30T15:00:00+08:00"),
        ("MAX", "9", "2023-10-30", "2023-10-30", "2023-10-31T15:00:00+08:00"),
    ]
    red = result["colorSegments"][1]
    assert (red["color"], red["startDate"], red["endDate"], red["coloredCount"]) == (
        "RED", "2023-10-24", "2023-10-30", 5)
    assert red["isLeftComplete"] is True and red["isEnded"] is True
    assert red["endKnownAt"] == "2023-10-31T15:00:00+08:00"
    assert {t["id"] for t in result["turns"] if t["metric"] == "DIF"} <= set(red["turnIds"])


def test_close_peak_dif_peak_and_longest_histogram_are_not_forced_onto_one_date():
    result = records([
        row("2024-01-02", "100", ("1", "0", "2")),
        row("2024-01-03", "130", ("2", "0", "4")),
        row("2024-01-04", "120", ("3", "0", "6")),
        row("2024-01-05", "110", ("4", "3", "2")),
        row("2024-01-08", "105", ("3", "2.5", "1")),
    ])
    extrema = result["colorSegments"][0]["extrema"]
    assert extrema["maxClose"] == {"value": "130", "dates": ["2024-01-03"]}
    assert extrema["maxDif"] == {"value": "4", "dates": ["2024-01-05"]}
    assert extrema["longestRed"] == {
        "value": "6", "absoluteLength": "6", "dates": ["2024-01-04"]}
    assert extrema["longestGreen"] is None


def test_red_zero_red_is_one_segment_and_zero_price_and_dif_are_counted():
    result = records([
        row("2024-01-02", "100", ("-1", "-2", "2")),
        row("2024-01-03", "150", ("5", "5", "0")),
        row("2024-01-04", "110", ("-2", "-3", "2")),
    ])
    assert len(result["colorSegments"]) == 1
    segment = result["colorSegments"][0]
    assert (segment["color"], segment["coloredCount"], segment["zeroDates"]) == (
        "RED", 2, ["2024-01-03"])
    assert segment["isEnded"] is False and segment["endKnownAt"] is None
    assert segment["extrema"]["maxClose"] == {"value": "150", "dates": ["2024-01-03"]}
    assert segment["extrema"]["maxDif"] == {"value": "5", "dates": ["2024-01-03"]}


def test_red_zero_green_closes_on_first_green_without_including_it_in_red():
    result = records([
        row("2024-01-02", "100"),
        row("2024-01-03", "150", ("2", "2", "0")),
        row("2024-01-04", "200", ("1", "2", "-2")),
    ])
    red, green = result["colorSegments"]
    assert (red["startDate"], red["endDate"], red["lastColoredDate"], red["coloredCount"]) == (
        "2024-01-02", "2024-01-03", "2024-01-02", 1)
    assert red["endKnownAt"] == "2024-01-04T15:00:00+08:00"
    assert red["extrema"]["maxClose"]["value"] == "150"
    assert green["startDate"] == "2024-01-04"
    assert red["isLeftComplete"] is False and green["isLeftComplete"] is True


def test_initial_zero_remains_unassigned_and_first_color_is_left_incomplete():
    rows = [row("2024-01-02", "999", ("0", "0", "0")),
            row("2024-01-03", "100"),
            row("2024-01-04", "90", ("1", "2", "-2"))]
    result = records(rows)
    red, green = result["colorSegments"]
    assert len(result["sourcePoints"]) == 3
    assert red["startDate"] == "2024-01-03" and red["zeroDates"] == []
    assert red["extrema"]["maxClose"]["value"] == "100"
    assert red["isLeftComplete"] is False and red["isEnded"] is True
    assert green["isLeftComplete"] is True
    only_zeros = records(rows[:1])
    assert only_zeros["colorSegments"] == []
    assert only_zeros["pendingTurns"][0]["confirmedAt"] is None


def test_color_uses_histogram_sign_even_when_dif_sign_says_the_opposite():
    result = records([row("2024-01-02", indicators=("-2", "-3", "2")),
                      row("2024-01-03", indicators=("3", "4", "-2"))])
    assert [s["color"] for s in result["colorSegments"]] == ["RED", "GREEN"]


def test_cross_color_dif_platform_has_one_stable_id_and_original_dates():
    rows = [row("2024-01-02", indicators=("1", "0", "2")),
            row("2024-01-03", indicators=("3", "2", "2")),
            row("2024-01-04", indicators=("3", "4", "-2")),
            row("2024-01-05", indicators=("2", "3", "-2"))]
    pending = records(rows[:2])["pendingTurns"]
    pending_dif = next(t for t in pending if t["metric"] == "DIF")
    result = records(rows)
    dif = next(t for t in result["turns"] if t["metric"] == "DIF")
    assert dif == dict(id="000001.SH:day:DIF:2024-01-03", metric="DIF", kind="MAX",
                       value="3", firstDate="2024-01-03", lastDate="2024-01-04",
                       plateauDates=["2024-01-03", "2024-01-04"],
                       confirmedAt="2024-01-05T15:00:00+08:00")
    assert pending_dif["id"] == dif["id"]
    assert pending_dif["confirmedAt"] is None and pending_dif["kind"] is None
    assert pending_dif["possibleKind"] == "MAX"
    assert all(dif["id"] in s["turnIds"] for s in result["colorSegments"])
    assert sum(t["id"] == dif["id"] for t in result["turns"]) == 1


def test_raw_precision_is_preserved_and_no_two_digit_peak_filter_is_used():
    result = records([
        row("2024-01-02", indicators=("26", "25", "2")),
        row("2024-01-03", indicators=("26.912", "25.912", "2")),
        row("2024-01-04", indicators=("26.871", "25.871", "2")),
        row("2024-01-05", indicators=("27", "26", "2")),
    ])
    assert turn_view(result, "DIF") == [
        ("MAX", "26.912", "2024-01-03", "2024-01-03", "2024-01-04T15:00:00+08:00"),
        ("MIN", "26.871", "2024-01-04", "2024-01-04", "2024-01-05T15:00:00+08:00"),
    ]
    long_number = "100.0000000000000000000000000000000000000001"
    one = records([row("2024-01-02", long_number,
                       ("1.0000000000000000000000000000000000000001", "0",
                        "2.0000000000000000000000000000000000000002"))])
    assert one["sourcePoints"][0]["close"] == long_number
    assert one["sourcePoints"][0]["dif"] == "1.0000000000000000000000000000000000000001"


def test_extrema_preserve_all_ties_and_longest_green_keeps_sign():
    result = records([
        row("2024-01-02", "100", ("2", "3", "-2")),
        row("2024-01-03", "90", ("1", "3", "-4")),
        row("2024-01-04", "90", ("1", "3", "-4")),
        row("2024-01-05", "100", ("2", "3", "-2")),
    ])
    ex = result["colorSegments"][0]["extrema"]
    assert ex["maxClose"] == {"value": "100", "dates": ["2024-01-02", "2024-01-05"]}
    assert ex["minClose"] == {"value": "90", "dates": ["2024-01-03", "2024-01-04"]}
    assert ex["minDif"] == {"value": "1", "dates": ["2024-01-03", "2024-01-04"]}
    assert ex["longestGreen"] == {
        "value": "-4", "absoluteLength": "4", "dates": ["2024-01-03", "2024-01-04"]}
    assert ex["longestRed"] is None


def test_prefix_has_no_future_confirmation_and_old_result_is_not_mutated():
    rows = [row("2024-01-02", "100"), row("2024-01-03", "120", ("3", "2", "2"))]
    original_input = deepcopy(rows)
    old = build_basic_records(rows, as_of="2024-01-03")
    snapshot = old.to_dict()
    assert snapshot["turns"] == [] and snapshot["colorSegments"][0]["isEnded"] is False
    future = rows + [row("2024-01-04", "110", ("2", "3", "-2"))]
    later = records(future)
    assert old.to_dict() == snapshot and rows == original_input
    assert later["colorSegments"][0]["id"] == snapshot["colorSegments"][0]["id"]
    assert later["colorSegments"][0]["endKnownAt"] == "2024-01-04T15:00:00+08:00"
    assert all(t["confirmedAt"] == "2024-01-04T15:00:00+08:00" for t in later["turns"])
    with pytest.raises(FrozenInstanceError):
        old.asOf = "changed"
    with pytest.raises(FrozenInstanceError):
        old.sourcePoints[0].close = Decimal("1")
    snapshot["sourcePoints"][0]["close"] = "changed"
    snapshot["colorSegments"][0]["turnIds"].append("foreign")
    assert old.to_dict()["sourcePoints"][0]["close"] == "100"
    assert "foreign" not in old.to_dict()["colorSegments"][0]["turnIds"]


def test_every_turn_reference_resolves_and_source_context_is_not_cut_to_main_window():
    result = records([row("2023-10-20", "100"),
                      row("2023-10-23", "120", ("2", "1", "2")),
                      row("2023-10-24", "110", ("1", "2", "-2"))])
    ids = [t["id"] for t in result["turns"] + result["pendingTurns"]]
    assert len(ids) == len(set(ids))
    assert all(set(s["turnIds"]) <= set(ids) for s in result["colorSegments"])
    assert result["contextStart"] == "2023-10-20"
    assert result["contextEnd"] == "2023-10-24"
    assert result["asOf"] == "2023-10-24T15:00:00+08:00"
    assert len(result["sourcePoints"]) == 3


def test_color_helper_uses_the_same_result_and_does_not_mutate_input():
    rows = [row("2024-01-02"), row("2024-01-03", indicators=("0", "1", "-2"))]
    assert build_color_segments(rows, as_of="2024-01-31") == build_basic_records(
        rows, as_of="2024-01-31").colorSegments
    assert build_basic_records(tuple(rows), as_of="2024-01-31").to_dict() == records(rows)


@pytest.mark.parametrize("column,bad", [
    ("close", "0"), ("close", "-1"), ("close", None), ("dif", "NaN"),
    ("dif", "Infinity"), ("dea", "-Infinity"), ("macd", "bad"),
    ("close", True), ("dif", False), ("dea", 1.0), ("macd", 2.0),
    ("completed", False), ("completed", 1), ("completed", "true"),
    ("date", "20240102"), ("date", "2024-02-30"), ("date", date(2024, 1, 2)),
    ("date", "2021-09-30"), ("date", "2026-10-22"),
    ("tsCode", "399001.SZ"), ("tsCode", None),
])
def test_invalid_rows_are_rejected_and_next_clean_call_still_works(column, bad):
    changed = row("2024-01-02")
    changed[column] = bad
    with pytest.raises(DailyWaveInputError):
        records([changed])
    assert records([row("2024-01-02")])["sourcePoints"][0]["close"] == "100"


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "reverse", "not_mapping"])
def test_strict_fields_and_ascending_unique_dates(change):
    rows = [row("2024-01-02"), row("2024-01-03")]
    if change == "missing":
        del rows[0]["dea"]
    elif change == "extra":
        rows[0]["high"] = "101"
    elif change == "duplicate":
        rows[1]["date"] = "2024-01-02"
    elif change == "reverse":
        rows.reverse()
    else:
        rows[0] = "not a mapping"
    with pytest.raises(DailyWaveInputError):
        records(rows)


@pytest.mark.parametrize("rows", [None, {}, "rows", iter(())])
def test_input_container_must_be_list_or_tuple(rows):
    with pytest.raises(DailyWaveInputError):
        records(rows)


@pytest.mark.parametrize("cutoff", ["20240102", "2024-02-30", "2021-09-30", "2026-10-22", None])
def test_invalid_cutoff_is_rejected(cutoff):
    with pytest.raises(DailyWaveInputError):
        records([], as_of=cutoff)


def test_no_later_row_is_used_to_confirm_a_peak_before_cutoff():
    with pytest.raises(DailyWaveInputError):
        records([row("2024-01-02"), row("2024-01-03")], as_of="2024-01-02")


def test_canonical_number_text_changes_notation_without_rounding_or_replacing_h():
    result = records([row("2024-01-02", Decimal("1E+2"), (Decimal("-0.00"), 0, "-0.000"))])
    assert result["sourcePoints"] == [dict(date="2024-01-02", close="100", dif="0", dea="0", macd="0")]
    accepted = records([row("2024-01-02", indicators=("1", "0", "2.0021"))])
    assert accepted["sourcePoints"][0]["macd"] == "2.0021"
    with pytest.raises(DailyWaveInputError):
        records([row("2024-01-02", indicators=("1", "0", "2.00210001"))])


def test_extreme_invalid_indicator_relation_reports_an_input_error():
    # Fits the byte budget but exceeds Decimal's arithmetic exponent range.
    # This is intentionally invalid input, not a realistic Float53 source row.
    with pytest.raises(DailyWaveInputError):
        records([row("2024-01-02", indicators=("1e1000000", "0", "0"))])
    assert records([row("2024-01-02")])["sourcePoints"][0]["macd"] == "2"


def test_point_limits_are_checked_with_normal_boundary_inputs_also_allowed():
    rows = [row("2024-01-02"), row("2024-01-03"), row("2024-01-04")]
    assert len(records(rows[:2], spec=replace(DEFAULT_SPEC, max_total_points=2))["sourcePoints"]) == 2
    with pytest.raises(DailyWaveBudgetExceeded):
        records(rows, spec=replace(DEFAULT_SPEC, max_total_points=2))
    assert len(records(rows[:2], spec=replace(DEFAULT_SPEC, max_main_points=2))["sourcePoints"]) == 2
    with pytest.raises(DailyWaveBudgetExceeded):
        records(rows, spec=replace(DEFAULT_SPEC, max_main_points=2))
    context = [row("2023-10-19"), row("2023-10-20"), row("2023-10-23")]
    assert len(records(context[:2], spec=replace(DEFAULT_SPEC, max_context_points=2))["sourcePoints"]) == 2
    with pytest.raises(DailyWaveBudgetExceeded):
        records(context, spec=replace(DEFAULT_SPEC, max_context_points=2))


def test_default_total_limit_is_enforced_without_parsing_or_processing_oversized_rows():
    # The object count, not the placeholder's contents, should reject this call.
    with pytest.raises(DailyWaveBudgetExceeded):
        records([None] * 1301)


def test_input_bytes_large_exponents_and_result_memory_are_bounded():
    with pytest.raises(DailyWaveBudgetExceeded):
        records([row("2024-01-02")], spec=replace(DEFAULT_SPEC, max_input_bytes=10))
    with pytest.raises(DailyWaveBudgetExceeded):
        records([row("2024-01-02", "1E+1048577")])
    with pytest.raises(DailyWaveBudgetExceeded):
        records([row("2024-01-02")], spec=replace(DEFAULT_SPEC, max_memory_bytes=1))
    assert len(records([row("2024-01-02")])["sourcePoints"]) == 1


def test_deadline_and_cancellation_stop_without_reusing_partial_state():
    rows = [row("2024-01-02"), row("2024-01-03")]
    with pytest.raises(DailyWaveBudgetExceeded):
        records(rows, deadline=time.monotonic() - 1)
    with pytest.raises(DailyWaveCancelled):
        records(rows, check_cancelled=lambda: True)
    calls = []

    def later_cancel():
        calls.append(True)
        return len(calls) >= 4

    with pytest.raises(DailyWaveCancelled):
        records(rows, check_cancelled=later_cancel)
    assert len(calls) == 4
    assert records(rows, check_cancelled=lambda: False)["contextEnd"] == "2024-01-03"


def test_basic_calculation_performs_no_file_or_network_operations(monkeypatch):
    rows = [row("2024-01-02"), row("2024-01-03", "110", ("2", "1", "2"))]

    def forbidden(*args, **kwargs):
        raise AssertionError("Basic daily calculation must not perform I/O")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(Path, "write_text", forbidden)
        patch.setattr(Path, "write_bytes", forbidden)
        patch.setattr(socket, "socket", forbidden)
        output = records(rows)
    assert output["contextEnd"] == "2024-01-03"


def test_basic_module_has_only_stdlib_and_local_imports_and_no_dynamic_io_escape():
    package = Path(calculator.__file__).parent
    allowed_roots = sys.stdlib_module_names
    forbidden_calls = {"open", "__import__", "eval", "exec", "compile"}
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] in allowed_roots for alias in node.names), path
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module and node.module.split(".")[0] in allowed_roots, path
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, path


def test_migrated_scanner_is_the_single_byte_identical_implementation():
    import hashlib
    from src.biz.services.wealth.market.index_detail_daily_wave import local_extrema

    root = Path(__file__).resolve().parents[1]
    assert not (root / "scripts/research/index_market/xxm/local_extrema.py").exists()
    assert hashlib.sha256(Path(local_extrema.__file__).read_bytes()).hexdigest() == (
        "ed1d71519ed3bd8f0e4ca3d6abccdec7b3c6878ec97bdd1b5ffd7b9253602c7c")
