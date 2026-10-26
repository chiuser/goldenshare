"""Limited acceptance: literal files/ledgers only, never a two-calculator replay.

Input contracts: next-stage LLD 0.6.4/0.6.8, six-column daily-source producer
and exact SSE calendar projection. Values and expected dates below are manual.
No real market file, software observation or valid comparison CLI is executed.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import date
import hashlib
import json
from pathlib import Path

import pytest

from scripts.research.index_market.xxm import confirmation_comparison as comparison
from scripts.research.index_market.xxm.confirmation_only_trial import TRIAL_SPEC


CSV_HEADER = "ts_code,trade_date,close,macd_dif_bfq,macd_dea_bfq,macd_bfq\n"
CSV_ROWS = (
    "000001.SH,2024-01-05,100.123400,41.0100,40.0100,2.0000\n"
    "000001.SH,2024-01-08,99.5000,-8.0860,-7.0860,-2.0000\n"
)
CALENDAR = [
    {"exchange": "SSE", "trade_date": "2024-01-05", "is_open": True},
    {"exchange": "SSE", "trade_date": "2024-01-06", "is_open": False},
    {"exchange": "SSE", "trade_date": "2024-01-07", "is_open": False},
    {"exchange": "SSE", "trade_date": "2024-01-08", "is_open": True},
]


@pytest.fixture(autouse=True)
def isolated_budget_memory(monkeypatch):
    # Isolate process-wide pytest RSS; individual memory-limit tests override it.
    monkeypatch.setattr(comparison, "_memory_bytes", lambda: 0)
    def forbidden_replay(*args, **kwargs):
        pytest.fail("This acceptance file must never start either calculator or a replay")
    monkeypatch.setattr(comparison, "XxmCalculator", forbidden_replay)
    monkeypatch.setattr(comparison, "TwoDigitTurnCalculator", forbidden_replay)
    monkeypatch.setattr(comparison, "_replay_one", forbidden_replay)


def manual_input(tmp_path, *, csv_text=None, calendar=None, calendar_text=None, **changes):
    csv_bytes = (CSV_HEADER + CSV_ROWS if csv_text is None else csv_text).encode()
    if calendar_text is None:
        calendar_text = json.dumps(CALENDAR if calendar is None else calendar, separators=(",", ":"))
    calendar_bytes = calendar_text.encode()
    source = tmp_path / "manual/daily.csv"
    source.parent.mkdir(exist_ok=True)
    calendar_path = tmp_path / "manual/calendar.json"
    source.write_bytes(csv_bytes)
    calendar_path.write_bytes(calendar_bytes)
    spec = replace(TRIAL_SPEC, source_path="manual/daily.csv", calendar_path="manual/calendar.json",
                   source_sha256=hashlib.sha256(csv_bytes).hexdigest(),
                   calendar_sha256=hashlib.sha256(calendar_bytes).hexdigest(),
                   source_start_date="2024-01-05", source_end_date="2024-01-08",
                   default_start_date="2024-01-05", default_end_date="2024-01-08")
    return replace(spec, **changes)


@pytest.mark.parametrize("start,end,expected", [
    (None, None, ("2023-10-24", "2026-10-13")),
    ("2025-01-01", None, ("2025-01-01", "2026-10-13")),
    (None, "2025-01-01", ("2023-10-24", "2025-01-01")),
    ("2023-01-03", "2026-10-13", ("2023-01-03", "2026-10-13")),
    ("2025-01-04", "2025-01-04", ("2025-01-04", "2025-01-04")),
])
def test_range_defaults_are_independent_and_keep_natural_dates(start, end, expected):
    before = (TRIAL_SPEC.default_start_date, TRIAL_SPEC.default_end_date)
    result = comparison.resolve_comparison_range(start, end)
    assert (result.requested_start, result.requested_end) == expected
    assert (TRIAL_SPEC.default_start_date, TRIAL_SPEC.default_end_date) == before
    with pytest.raises(FrozenInstanceError):
        result.requested_start = "2024-01-01"


@pytest.mark.parametrize("value", ["", "20250104", "2025-1-04", "2025-01-04T15:00:00+08:00",
                                    "2025-02-30", " 2025-01-04", True, 20250104, date(2025, 1, 4)])
@pytest.mark.parametrize("side", ["start", "end"])
def test_range_rejects_noncanonical_dates_instead_of_normalizing_them(value, side):
    args = (value, "2025-01-05") if side == "start" else ("2025-01-01", value)
    with pytest.raises(ValueError):
        comparison.resolve_comparison_range(*args)


def test_range_rejects_earlier_end_without_silently_moving_the_default_start():
    with pytest.raises(ValueError, match="2023-10-24.*2023-06-01"):
        comparison.resolve_comparison_range(end_date="2023-06-01")


@pytest.mark.parametrize("start,end,offender", [
    ("2023-01-02", "2025-01-01", "2023-01-02"),
    ("2025-01-01", "2026-10-14", "2026-10-14"),
])
def test_range_errors_identify_the_request_and_available_bounds(start, end, offender):
    with pytest.raises(ValueError) as error:
        comparison.resolve_comparison_range(start, end)
    assert all(value in str(error.value) for value in (offender, "2023-01-03", "2026-10-13"))


def test_invalid_spec_defaults_follow_the_same_range_validation():
    spec = replace(TRIAL_SPEC, default_end_date="2026-10-14")
    with pytest.raises(ValueError, match="2026-10-14"):
        comparison.resolve_comparison_range(spec=spec)


def test_manual_source_retains_text_and_builds_immutable_completed_bars(tmp_path):
    spec = manual_input(tmp_path)
    result = comparison.read_confirmation_input(spec=spec, root=tmp_path)
    assert result.source_rows == (
        ("000001.SH", "2024-01-05", "100.123400", "41.0100", "40.0100", "2.0000"),
        ("000001.SH", "2024-01-08", "99.5000", "-8.0860", "-7.0860", "-2.0000"),
    )
    assert tuple((bar.time, bar.close, bar.dif, bar.dea, bar.hist, bar.completed) for bar in result.bars) == (
        ("2024-01-05", 100.1234, 41.01, 40.01, 2.0, True),
        ("2024-01-08", 99.5, -8.086, -7.086, -2.0, True),
    )
    assert result.open_dates == ("2024-01-05", "2024-01-08")
    assert isinstance(result.bars, tuple) and isinstance(result.source_rows, tuple)
    assert len(result.source_identity) == 64 and set(result.source_identity) <= set("0123456789abcdef")
    with pytest.raises(FrozenInstanceError):
        result.source_identity = "changed"
    with pytest.raises(FrozenInstanceError):
        result.bars[0].close = 7


def test_reader_only_opens_declared_files_with_bounded_reads(tmp_path, monkeypatch):
    spec = manual_input(tmp_path)
    real_open = Path.open
    opened, reads = [], []

    class BoundedStream:
        def __init__(self, stream, path):
            self.stream, self.path = stream, path
        def __enter__(self):
            return self
        def read(self, size):
            reads.append((self.path, size))
            return self.stream.read(size)
        def __exit__(self, *args):
            self.stream.close()

    allowed = {tmp_path / spec.source_path, tmp_path / spec.calendar_path}
    def record_open(path, *args, **kwargs):
        assert path in allowed, "Reader attempted an undeclared input"
        opened.append(path)
        return BoundedStream(real_open(path, *args, **kwargs), path)
    monkeypatch.setattr(Path, "open", record_open)
    result = comparison.read_confirmation_input(spec=spec, root=tmp_path)
    assert len(result.bars) == 2
    assert opened == [tmp_path / spec.source_path, tmp_path / spec.calendar_path]
    assert reads == [(tmp_path / spec.source_path, spec.max_csv_bytes + 1),
                     (tmp_path / spec.calendar_path, spec.max_calendar_bytes + 1)]


@pytest.mark.parametrize("which", ["source", "calendar"])
def test_reader_rejects_changed_bytes_before_reinterpreting_their_identity(tmp_path, which):
    spec = manual_input(tmp_path)
    path = tmp_path / (spec.source_path if which == "source" else spec.calendar_path)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA"):
        comparison.read_confirmation_input(spec=spec, root=tmp_path)


@pytest.mark.parametrize("text", [
    CSV_HEADER.replace("close,macd_dif_bfq", "macd_dif_bfq,close") + CSV_ROWS,
    CSV_HEADER.replace(",macd_bfq", "") + CSV_ROWS,
    CSV_HEADER.rstrip() + ",extra\n" + CSV_ROWS,
    CSV_HEADER,
    CSV_HEADER + CSV_ROWS.replace("000001.SH", "399001.SZ", 1),
    CSV_HEADER + CSV_ROWS.replace("2024-01-08", "2024-01-05"),
    CSV_HEADER + "\n".join(CSV_ROWS.strip().splitlines()[::-1]) + "\n",
    CSV_HEADER + CSV_ROWS.replace("2024-01-05", "20240105"),
    CSV_HEADER + CSV_ROWS.replace("2024-01-08", "2024-01-09"),
    CSV_HEADER + CSV_ROWS.replace("100.123400", ""),
    CSV_HEADER + CSV_ROWS.replace("100.123400", "NULL"),
    CSV_HEADER + CSV_ROWS.replace("100.123400", "0"),
    CSV_HEADER + CSV_ROWS.replace("100.123400", "-1"),
    CSV_HEADER + CSV_ROWS.replace("41.0100", "NaN"),
    CSV_HEADER + CSV_ROWS.replace("41.0100", "Infinity"),
    CSV_HEADER + CSV_ROWS.replace("41.0100", " 41.0100"),
    CSV_HEADER + CSV_ROWS.replace("41.0100", "1e9999"),
    CSV_HEADER + CSV_ROWS.replace("40.0100,2.0000", "40.0100,2.0022"),
])
def test_reader_rejects_bad_source_without_dropping_or_repairing_rows(tmp_path, text):
    spec = manual_input(tmp_path, csv_text=text)
    with pytest.raises(ValueError):
        comparison.read_confirmation_input(spec=spec, root=tmp_path)


def test_legal_source_rounding_error_is_retained_instead_of_recomputed(tmp_path):
    spec = manual_input(tmp_path, csv_text=CSV_HEADER + CSV_ROWS.replace("40.0100,2.0000", "40.0100,2.0020"))
    result = comparison.read_confirmation_input(spec=spec, root=tmp_path)
    assert result.bars[0].hist == 2.002
    assert result.source_rows[0][-1] == "2.0020"


@pytest.mark.parametrize("kind", ["missing_day", "duplicate_day", "reverse", "missing_end",
                                   "wrong_exchange", "int_flag", "string_flag", "extra_field", "bad_date"])
def test_calendar_contract_and_complete_daily_coverage_are_required(tmp_path, kind):
    calendar = deepcopy(CALENDAR)
    if kind == "missing_day": calendar.pop(1)
    elif kind == "duplicate_day": calendar[1] = deepcopy(calendar[0])
    elif kind == "reverse": calendar.reverse()
    elif kind == "missing_end": calendar.pop()
    elif kind == "wrong_exchange": calendar[0]["exchange"] = "SZSE"
    elif kind == "int_flag": calendar[0]["is_open"] = 1
    elif kind == "string_flag": calendar[0]["is_open"] = "true"
    elif kind == "extra_field": calendar[0]["extra"] = None
    elif kind == "bad_date": calendar[0]["trade_date"] = "20240105"
    spec = manual_input(tmp_path, calendar=calendar)
    with pytest.raises(ValueError):
        comparison.read_confirmation_input(spec=spec, root=tmp_path)


def test_missing_open_day_and_closed_day_market_rows_are_not_empty_windows(tmp_path):
    missing = manual_input(tmp_path, csv_text=CSV_HEADER + CSV_ROWS.splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="交易日|覆盖"):
        comparison.read_confirmation_input(spec=missing, root=tmp_path)
    closed = manual_input(tmp_path, csv_text=CSV_HEADER + CSV_ROWS.replace("2024-01-08", "2024-01-06"))
    with pytest.raises(ValueError, match="交易日|休市"):
        comparison.read_confirmation_input(spec=closed, root=tmp_path)


@pytest.mark.parametrize("text", ["{}", "[]", '[{"exchange":"SSE","exchange":"SSE","trade_date":"2024-01-05","is_open":true}]'])
def test_calendar_container_and_duplicate_json_fields_are_rejected(tmp_path, text):
    spec = manual_input(tmp_path, calendar_text=text)
    with pytest.raises(ValueError):
        comparison.read_confirmation_input(spec=spec, root=tmp_path)


@pytest.mark.parametrize("change", [{"max_bars": 1}, {"max_calendar_rows": 3},
                                    {"max_csv_bytes": 10}, {"max_calendar_bytes": 10}])
def test_reader_rejects_count_and_size_overruns(tmp_path, change):
    spec = manual_input(tmp_path, **change)
    with pytest.raises(ValueError):
        comparison.read_confirmation_input(spec=spec, root=tmp_path)


def test_oversized_source_is_rejected_before_its_contents_are_read(tmp_path, monkeypatch):
    spec = manual_input(tmp_path, max_csv_bytes=10)
    def forbidden_open(*args, **kwargs):
        pytest.fail("Oversized source must be refused before open/read")
    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(ValueError, match="字节"):
        comparison.read_confirmation_input(spec=spec, root=tmp_path)


@pytest.mark.parametrize("change", [{"source_path": "../outside.csv"}, {"calendar_path": "/private/tmp/outside.json"}])
def test_reader_rejects_undeclared_root_escapes(tmp_path, change):
    spec = manual_input(tmp_path, **change)
    with pytest.raises(ValueError, match="路径|根目录"):
        comparison.read_confirmation_input(spec=spec, root=tmp_path)


def test_reader_obeys_original_deadline_cancellation_and_memory_cap(tmp_path, monkeypatch):
    spec = manual_input(tmp_path)
    monkeypatch.setattr(comparison.time, "monotonic", lambda: 10.0)
    with pytest.raises(TimeoutError):
        comparison.read_confirmation_input(spec=spec, root=tmp_path, deadline=10.0)
    with pytest.raises(InterruptedError):
        comparison.read_confirmation_input(spec=spec, root=tmp_path, deadline=20.0, cancelled=lambda: True)
    monkeypatch.setattr(comparison, "_memory_bytes", lambda: spec.max_memory_bytes + 1)
    with pytest.raises(MemoryError):
        comparison.read_confirmation_input(spec=spec, root=tmp_path, deadline=20.0)


DATES = ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08")
REFERENCE = {"startTime": "2024-01-02", "endTime": "2024-01-02", "price": 100.0, "dif": 50.0}


def literal_point(day, *, state="NONE", reference=None, pending_top=None):
    # All 11 fields are the actual XxmCalculator.step point contract, not an
    # abbreviated consumer-shaped replacement. Numbers are manual literals.
    return {"time": day, "close": 103.0, "dif": 40.99, "dea": 39.99, "hist": 2.0,
            "ordinaryState": state, "ordinaryDirection": "TOP" if state != "NONE" else None,
            "activeReference": deepcopy(reference), "pendingTopHistoryId": pending_top,
            "pendingBottomHistoryId": None, "pendingRearmId": None}


def literal_event(identity, day, *, route="activation", kind="DULL", reference=None):
    # Exact ten fields from calculator.py event creation; independent IDs are
    # deliberate so tests cannot pass merely because both groups share IDs.
    return {"id": identity, "time": day, "direction": "TOP", "type": kind, "route": route,
            "fromState": "DULL" if kind == "STRUCTURE" else "NONE",
            "eventReference": deepcopy(REFERENCE if reference is None else reference),
            "relatedTopHistoryId": None, "relatedBottomHistoryId": None, "relatedRearmId": None}


def literal_ledger(events=(), *, dates=DATES, origins=None):
    """Hand-authored record assembly only; no bar/step/replay is executed."""
    state, reference = "NONE", None
    records = []
    for day in dates:
        before = {key: value for key, value in literal_point(day, state=state, reference=reference).items()
                  if key not in {"time", "close", "dif", "dea", "hist"}}
        current = [deepcopy(event) for event in events if event["time"] == day]
        if current:
            state = current[-1]["type"]
            reference = current[-1]["eventReference"]
        records.append({"before": before, "point": literal_point(day, state=state, reference=reference),
                        "events": current, "histories": [], "bottomHistories": [], "rearmRecords": [],
                        "eventSegmentStarts": {event["id"]: (origins or {}).get(event["id"], DATES[0]) for event in current}})
    return records


def literal_compare(left, right, *, start="2024-01-02", end="2024-01-08", dates=DATES, **kwargs):
    spec = kwargs.pop("spec", replace(TRIAL_SPEC, source_start_date="2024-01-02",
                                    source_end_date="2024-01-08", default_start_date=start, default_end_date=end))
    requested = comparison.resolve_comparison_range(start, end, spec=spec)
    return comparison.compare_ledgers(left, right, comparison_range=requested,
                                      trading_dates=dates, spec=spec, **kwargs)


def test_literal_ledger_comparison_has_no_calculator_or_input_read_dependency(monkeypatch):
    def no_input(*args, **kwargs):
        pytest.fail("Literal ledger comparison must not read an input file")
    monkeypatch.setattr(comparison, "read_confirmation_input", no_input)
    result = literal_compare(literal_ledger(), literal_ledger())
    assert result["status"] == "ready"
    assert result["observationBarCount"] == 5
    assert result["eventComparisons"] == result["pointDifferences"] == result["historyDifferences"] == []
    assert result["firstDivergenceInPrefix"] is None
    assert result["firstDivergenceInObservation"] is None


def test_different_event_ids_with_equal_business_facts_are_not_false_differences():
    left = literal_ledger([literal_event("r2-event", DATES[2])])
    right = literal_ledger([literal_event("two-event", DATES[2])])
    old_left, old_right = deepcopy(left), deepcopy(right)
    result = literal_compare(left, right)
    assert len(result["eventComparisons"]) == 1
    pair = result["eventComparisons"][0]
    assert pair["classification"] == "相同"
    assert pair["r2"]["id"] == "r2-event" and pair["twoDigit"]["id"] == "two-event"
    assert pair["tradingBarShift"] == 0 and pair["changedFields"] == []
    assert result["summary"]["r2EventCounts"] == result["summary"]["twoDigitEventCounts"] == {"DULL": 1}
    assert result["pointDifferences"] == [] and result["firstDivergenceInPrefix"] is None
    assert left == old_left and right == old_right


@pytest.mark.parametrize("left_day,right_day,label,shift", [
    ("2024-01-05", "2024-01-08", "推后", 1),
    ("2024-01-08", "2024-01-05", "提前", -1),
])
def test_unique_cross_date_matches_count_trading_bars_not_weekend_days(left_day, right_day, label, shift):
    result = literal_compare(literal_ledger([literal_event("r", left_day)]),
                             literal_ledger([literal_event("t", right_day)]))
    assert len(result["eventComparisons"]) == 1
    pair = result["eventComparisons"][0]
    assert (pair["classification"], pair["tradingBarShift"], pair["r2"]["time"], pair["twoDigit"]["time"]) == (
        label, shift, left_day, right_day)


def test_same_day_reference_value_change_is_not_erased_by_pairing_on_reference_start():
    left = literal_ledger([literal_event("r", DATES[2])])
    right = literal_ledger([literal_event("t", DATES[2], reference={**REFERENCE, "price": 99.0})])
    pair = literal_compare(left, right)["eventComparisons"][0]
    assert pair["classification"] == "参照/历史等事件内容变化"
    assert pair["changedFields"] == ["eventReference"]
    assert pair["r2"]["eventReference"]["price"] == 100.0
    assert pair["twoDigit"]["eventReference"]["price"] == 99.0


def test_multiple_cross_date_candidates_are_not_paired_by_nearest_date_or_index():
    left = literal_ledger([literal_event("r-first", DATES[2]), literal_event("r-second", DATES[3])])
    right = literal_ledger([literal_event("t-only", DATES[4])])
    result = literal_compare(left, right)
    assert result["summary"]["eventComparisons"] == {"相对r2减少": 2, "相对r2新增": 1}
    assert all(item["tradingBarShift"] is None for item in result["eventComparisons"])
    assert all("截至本次结束日期未见可唯一对应事件" == item["unpairedNote"] for item in result["eventComparisons"])


def test_different_routes_do_not_become_an_early_or_late_pair():
    left = literal_ledger([literal_event("r", DATES[2], route="activation")])
    right = literal_ledger([literal_event("t", DATES[3], route="reactivation")])
    result = literal_compare(left, right)
    assert result["summary"]["eventComparisons"] == {"相对r2减少": 1, "相对r2新增": 1}
    assert all(item["tradingBarShift"] is None for item in result["eventComparisons"])


@pytest.mark.parametrize("difference", ["full_reference", "source_segment"])
def test_cross_date_pairing_requires_full_reference_and_same_origin(difference):
    left = literal_ledger([literal_event("r", DATES[2])])
    changed_ref = {**REFERENCE, "dif": 49.0} if difference == "full_reference" else REFERENCE
    right = literal_ledger([literal_event("t", DATES[3], reference=changed_ref)],
                           origins={"t": DATES[1] if difference == "source_segment" else DATES[0]})
    result = literal_compare(left, right)
    assert result["summary"]["eventComparisons"] == {"相对r2减少": 1, "相对r2新增": 1}


def test_cross_start_pairing_keeps_context_event_without_counting_it_as_an_observation_event():
    left = literal_ledger([literal_event("r-context", DATES[1])])
    right = literal_ledger([literal_event("t-observation", DATES[2])])
    left[1]["turn"] = {"p": 41.01, "c": 40.99, "Qp": "41", "Qc": "40", "r2Formation": False,
                       "twoDigitFormation": True, "r2Return": False, "twoDigitReturn": False}
    right[2]["turn"] = {"p": 41.9, "c": 41.4, "Qp": "41", "Qc": "41", "r2Formation": True,
                        "twoDigitFormation": False, "r2Return": False, "twoDigitReturn": False}
    result = literal_compare(left, right, start="2024-01-04")
    assert result["observationBarCount"] == 3
    assert result["summary"]["r2EventCounts"] == {}
    assert result["summary"]["twoDigitEventCounts"] == {"DULL": 1}
    assert len(result["eventComparisons"]) == 1
    pair = result["eventComparisons"][0]
    assert pair["classification"] == "推后" and pair["tradingBarShift"] == 1
    assert pair["r2OutsideRange"] is True and pair["twoDigitOutsideRange"] is False
    assert pair["r2"]["time"] == "2024-01-03" and pair["twoDigit"]["time"] == "2024-01-04"
    assert pair["r2Context"]["time"] == "2024-01-03"
    assert pair["twoDigitContext"]["time"] == "2024-01-04"
    assert pair["r2Context"]["turn"] == {"p": 41.01, "c": 40.99, "Qp": "41", "Qc": "40", "r2Formation": False,
                                          "twoDigitFormation": True, "r2Return": False, "twoDigitReturn": False}
    assert pair["twoDigitContext"]["turn"] == {"p": 41.9, "c": 41.4, "Qp": "41", "Qc": "41", "r2Formation": True,
                                                "twoDigitFormation": False, "r2Return": False, "twoDigitReturn": False}
    assert result["firstDivergenceInPrefix"] == "2024-01-03"
    assert result["firstDivergenceInObservation"] == "2024-01-04"


def test_pre_window_difference_is_kept_as_prefix_cause_not_observation_activity():
    result = literal_compare(literal_ledger([literal_event("r", DATES[0])]),
                             literal_ledger([literal_event("t", DATES[1])]), start="2024-01-04")
    assert result["eventComparisons"] == []
    assert result["summary"]["r2EventCounts"] == result["summary"]["twoDigitEventCounts"] == {}
    assert result["firstDivergenceInPrefix"] == "2024-01-02"
    assert result["firstDivergenceInObservation"] is None


def top_history(identity, *, through, status="PENDING", ended_at=None, end_reason=None):
    return {"id": identity, "confirmedAt": "2024-01-03", "confirmationRoute": "dif_turn",
            "pricePeak": 103.0, "pricePeakAt": "2024-01-03", "originalReference": deepcopy(REFERENCE),
            "status": status, "endedAt": ended_at, "endReason": end_reason, "observedThrough": through,
            "ageBars": 0 if through == "2024-01-03" else 1, "negativeBars": 0, "zeroBars": 0, "colorChanges": 0}


def historical_ledger(event_id, history_id):
    event = literal_event(event_id, DATES[1], kind="STRUCTURE", route="dif_turn")
    event["relatedTopHistoryId"] = history_id
    records = literal_ledger([event])
    for record in records[1:]:
        stamp = record["point"]["time"]
        record["histories"] = [top_history(history_id, through=stamp)]
        record["point"]["pendingTopHistoryId"] = history_id
    return records


def test_linked_history_ids_are_normalized_without_deleting_their_meaning():
    result = literal_compare(historical_ledger("r-event", "r-history"), historical_ledger("t-event", "t-history"))
    assert result["historyDifferences"] == [] and result["pointDifferences"] == []
    assert result["eventComparisons"][0]["classification"] == "相同"


def test_context_formation_and_in_window_history_end_use_update_day_for_filtering():
    left, right = historical_ledger("r-event", "r-history"), historical_ledger("t-event", "t-history")
    left[2]["histories"] = [top_history("r-history", through="2024-01-04", status="ENDED",
                                      ended_at="2024-01-04", end_reason="historical_price_break")]
    left[2]["point"]["pendingTopHistoryId"] = None
    # Compare only the explicitly handwritten prefix; this is not calculator execution.
    result = literal_compare(left[:3], right[:3], start="2024-01-04", end="2024-01-04", dates=DATES[:3])
    assert result["eventComparisons"] == []
    assert result["summary"]["r2EventCounts"] == result["summary"]["twoDigitEventCounts"] == {}
    assert len(result["historyDifferences"]) == 1
    update = result["historyDifferences"][0]
    assert update["time"] == "2024-01-04" and update["kind"] == "histories"
    assert update["r2"][0]["confirmedAt"] == "2024-01-03"
    assert update["r2"][0]["endedAt"] == "2024-01-04"
    assert update["r2"][0]["endReason"] == "historical_price_break"


def test_matched_withdrawals_cannot_make_different_original_structures_equivalent():
    left = historical_ledger("r-created", "r-history")
    right = historical_ledger("t-created", "t-history")
    # Producer permits independent confirmation routes. The creator events below
    # must stay unpaired; a later withdrawal cannot manufacture equivalence.
    right[1]["events"][0]["route"] = "color_flip"
    for record in right[1:]:
        record["histories"][0]["confirmationRoute"] = "color_flip"
    for records, event_id, history_id in ((left, "r-withdraw", "r-history"), (right, "t-withdraw", "t-history")):
        event = literal_event(event_id, DATES[3], kind="RESEARCH_HISTORICAL_WITHDRAWAL", route="historical_price_break")
        event["fromState"] = "STRUCTURE"
        event["relatedTopHistoryId"] = history_id
        records[3]["events"] = [event]
        records[3]["eventSegmentStarts"] = {event_id: DATES[0]}
        records[3]["histories"][0].update(status="ENDED", endedAt=DATES[3], endReason="historical_price_break")
        records[3]["point"]["pendingTopHistoryId"] = None
    result = literal_compare(left, right)
    withdrawal = next(item for item in result["eventComparisons"]
                      if item["r2"] is not None and item["r2"]["id"] == "r-withdraw")
    assert withdrawal["twoDigit"]["id"] == "t-withdraw"
    assert withdrawal["classification"] == "参照/历史等事件内容变化"
    assert "relatedTopHistoryId" in withdrawal["changedFields"]
    assert withdrawal["r2"]["relatedTopHistoryId"] == "r-history"
    assert withdrawal["twoDigit"]["relatedTopHistoryId"] == "t-history"


def test_cancel_priority_is_not_misreported_as_a_direct_numeric_return_difference():
    left, right = historical_ledger("r-created", "r-history"), historical_ledger("t-created", "t-history")
    # Move the trial creator one day later; its independent history is therefore
    # genuinely different even after cross-date creator IDs are paired.
    created = right[1]["events"].pop()
    right[1].update(histories=[], eventSegmentStarts={})
    right[1]["point"] = literal_point(DATES[1])
    created["time"] = DATES[2]
    right[2]["events"] = [created]
    right[2]["eventSegmentStarts"] = {"t-created": DATES[0]}
    right[2]["before"] = {key: value for key, value in literal_point(DATES[2]).items()
                           if key not in {"time", "close", "dif", "dea", "hist"}}
    for record in right[2:]:
        record["histories"][0].update(confirmedAt=DATES[2], pricePeakAt=DATES[2])
    for records, event_id, history_id in ((left, "r-cancel", "r-history"), (right, "t-cancel", "t-history")):
        for record in records:
            for reference in [record["point"]["activeReference"], record["before"]["activeReference"],
                              *[event["eventReference"] for event in record["events"]],
                              *[history["originalReference"] for history in record["histories"]]]:
                if reference is not None:
                    reference["dif"] = 42.0
        cancelled = literal_event(event_id, DATES[3], kind="CANCEL", route="dif_break", reference={**REFERENCE, "dif": 42.0})
        cancelled["fromState"] = "STRUCTURE"
        records[3]["events"] = [cancelled]
        records[3]["eventSegmentStarts"] = {event_id: DATES[0]}
        records[3]["turn"] = {"p": 41.9, "c": 42.01, "Qp": "41", "Qc": "42", "r2Return": False,
                              "twoDigitReturn": True, "r2Formation": False, "twoDigitFormation": False}
        records[3]["point"].update(dif=42.01, dea=41.01, ordinaryState="NONE", ordinaryDirection=None,
                                    activeReference=None, pendingTopHistoryId=None)
        records[3]["histories"][0].update(status="ENDED", endedAt=DATES[3], endReason="original_reference_break")
        # End at the cancellation day; no fabricated future updates are needed.
    result = literal_compare(left[:4], right[:4], start=DATES[3], end=DATES[3], dates=DATES[:4])
    update = result["historyDifferences"][0]
    assert update["time"] == DATES[3]
    assert update["cause"] == "历史记录不同；需沿创建记录核对前段原因"
    assert "直接" not in update["cause"]
    cancel_pair = result["eventComparisons"][0]
    assert cancel_pair["r2"]["route"] == cancel_pair["twoDigit"]["route"] == "dif_break"
    assert cancel_pair["r2Context"]["turn"]["twoDigitReturn"] is True
    assert cancel_pair["twoDigitContext"]["turn"]["r2Return"] is False


@pytest.mark.parametrize("field", ["relatedTopHistoryId", "relatedBottomHistoryId", "relatedRearmId"])
def test_existing_event_id_cannot_satisfy_a_different_record_type_link(field):
    event = literal_event("r-event", DATES[2])
    event[field] = "r-event"
    with pytest.raises(ValueError, match="悬挂|引用"):
        literal_compare(literal_ledger([event]), literal_ledger())


def test_a_history_created_later_cannot_be_referenced_from_an_earlier_point():
    left = historical_ledger("r-event", "r-history")
    left[0]["point"]["pendingTopHistoryId"] = "r-history"
    with pytest.raises(ValueError, match="悬挂|提前|引用"):
        literal_compare(left, historical_ledger("t-event", "t-history"))


@pytest.mark.parametrize("origin", ["2024-01-01", "2024-01-06", "2024-01-08"])
def test_origin_must_be_an_already_known_input_trading_date(origin):
    left = literal_ledger([literal_event("r", DATES[2])], origins={"r": origin})
    with pytest.raises(ValueError, match="来源|区间"):
        literal_compare(left, literal_ledger())


@pytest.mark.parametrize("field", ["close", "dif", "dea", "hist"])
def test_different_market_inputs_are_not_explained_as_confirmation_threshold_differences(field):
    left, right = literal_ledger(), literal_ledger()
    right[2]["point"][field] += 0.01
    with pytest.raises(ValueError, match="行情不同"):
        literal_compare(left, right)


@pytest.mark.parametrize("defect", ["missing_point", "event_extra", "missing_origin", "duplicate_id", "wrong_event_date", "wrong_point_date"])
def test_ledger_contract_errors_are_not_converted_to_missing_signals(defect):
    left = literal_ledger([literal_event("r", DATES[2])])
    if defect == "missing_point": del left[0]["point"]["dea"]
    elif defect == "event_extra": left[2]["events"][0]["extra"] = None
    elif defect == "missing_origin": left[2]["eventSegmentStarts"] = {}
    elif defect == "duplicate_id": left[3]["events"] = [literal_event("r", DATES[3])]; left[3]["eventSegmentStarts"] = {"r": DATES[0]}
    elif defect == "wrong_event_date": left[2]["events"][0]["time"] = DATES[3]
    elif defect == "wrong_point_date": left[2]["point"]["time"] = DATES[3]
    with pytest.raises(ValueError):
        literal_compare(left, literal_ledger())


def test_empty_weekend_window_is_not_a_claim_of_algorithm_agreement():
    result = literal_compare(literal_ledger(dates=DATES[:4]), literal_ledger(dates=DATES[:4]),
                             start="2024-01-06", end="2024-01-07", dates=DATES[:4])
    assert result["status"] == "empty" and result["observationBarCount"] == 0
    assert result["observationStart"] is None and result["observationEnd"] is None
    assert result["eventComparisons"] == result["pointDifferences"] == result["historyDifferences"] == []


def test_comparison_refuses_future_rows_and_obeys_common_budget(monkeypatch):
    with pytest.raises(ValueError, match="结束日之后|越界"):
        literal_compare(literal_ledger(), literal_ledger(), end="2024-01-05")
    monkeypatch.setattr(comparison.time, "monotonic", lambda: 10.0)
    with pytest.raises(TimeoutError):
        literal_compare(literal_ledger(), literal_ledger(), deadline=10.0)
    with pytest.raises(InterruptedError):
        literal_compare(literal_ledger(), literal_ledger(), deadline=20.0, cancelled=lambda: True)
    tiny = replace(TRIAL_SPEC, source_start_date=DATES[0], source_end_date=DATES[-1], max_result_bytes=1)
    with pytest.raises(ValueError, match="大小|上限"):
        literal_compare(literal_ledger(), literal_ledger(), spec=tiny, deadline=20.0)


def confirmation_literal_pair():
    """Manual LLD0.6.2 records plus one unchanged-reading continuation day.

    This builds literal dictionaries only. It never invokes either step method.
    41.01 -> 40.99 crosses Q(41)->Q(40), but is less than the r2 1% gate.
    """
    dates = (*DATES, "2024-01-09")
    activation_r = literal_event("r-dull", "2024-01-05")
    activation_t = literal_event("t-dull", "2024-01-05")
    formed_t = literal_event("t-structure", "2024-01-08", kind="STRUCTURE", route="dif_turn")
    formed_t["relatedTopHistoryId"] = "t-history"
    left = literal_ledger([activation_r], dates=dates, origins={"r-dull": "2024-01-04"})
    right = literal_ledger([activation_t, formed_t], dates=dates,
                           origins={"t-dull": "2024-01-04", "t-structure": "2024-01-04"})
    # Independent source literals from the approved hand-worked example.
    values = ((100.0, 50.0, 49.0, 2.0), (99.0, 30.0, 31.0, -2.0),
              (101.0, 41.01, 40.01, 2.0), (102.0, 41.01, 40.01, 2.0),
              (103.0, 40.99, 39.99, 2.0), (102.0, 40.98, 39.98, 2.0))
    for records in (left, right):
        for record, (close, dif, dea, hist) in zip(records, values):
            record["point"].update(close=close, dif=dif, dea=dea, hist=hist)
        records[4]["turn"] = {"p": 41.01, "c": 40.99, "Qp": "41", "Qc": "40",
                              "r2Formation": False, "twoDigitFormation": True,
                              "r2Return": False, "twoDigitReturn": False, "numericOnly": True}
        records[5]["turn"] = {"p": 40.99, "c": 40.98, "Qp": "40", "Qc": "40",
                              "r2Formation": False, "twoDigitFormation": False,
                              "r2Return": False, "twoDigitReturn": False, "numericOnly": True}
    for index in (4, 5):
        right[index]["histories"] = [{
            "id": "t-history", "confirmedAt": "2024-01-08", "confirmationRoute": "dif_turn",
            "pricePeak": 103.0, "pricePeakAt": "2024-01-08", "originalReference": deepcopy(REFERENCE),
            "status": "PENDING", "endedAt": None, "endReason": None, "observedThrough": dates[index],
            "ageBars": index - 4, "negativeBars": 0, "zeroBars": 0, "colorChanges": 0,
        }]
        right[index]["point"]["pendingTopHistoryId"] = "t-history"
    right[5]["before"]["pendingTopHistoryId"] = "t-history"
    return left, right, dates


def test_direct_turn_difference_is_distinct_from_later_state_consequences():
    left, right, dates = confirmation_literal_pair()
    spec = replace(TRIAL_SPEC, source_start_date="2024-01-02", source_end_date="2024-01-09")
    direct = literal_compare(left[:5], right[:5], start="2024-01-08", end="2024-01-08", dates=dates[:5], spec=spec)
    assert direct["pointDifferences"][0]["time"] == "2024-01-08"
    assert direct["pointDifferences"][0]["cause"] == "相邻DIF转折门槛直接不同"
    assert direct["eventComparisons"][0]["classification"] == "相对r2新增"
    assert direct["eventComparisons"][0]["cause"] == "相邻DIF转折门槛直接不同"
    later = literal_compare(left, right, start="2024-01-09", end="2024-01-09", dates=dates, spec=spec)
    assert later["firstDivergenceInPrefix"] == "2024-01-08"
    assert later["firstDivergenceInObservation"] == "2024-01-09"
    assert later["eventComparisons"] == []
    assert later["pointDifferences"][0]["cause"] == "此前状态或参照变化的后续影响"


def test_literal_report_filter_changes_do_not_mutate_previous_results_or_event_ids():
    left, right, dates = confirmation_literal_pair()
    spec = replace(TRIAL_SPEC, source_start_date="2024-01-02", source_end_date="2024-01-09")
    first = literal_compare(left, right, start="2024-01-08", end="2024-01-09", dates=dates, spec=spec)
    saved = deepcopy(first)
    second = literal_compare(left, right, start="2024-01-09", end="2024-01-09", dates=dates, spec=spec)
    assert first == saved
    assert first["pointDifferences"][-1] == second["pointDifferences"][0]
    assert first["eventComparisons"][0]["twoDigit"]["id"] == "t-structure"
    assert second["summary"]["r2EventCounts"] == second["summary"]["twoDigitEventCounts"] == {}


def test_direct_bar_validation_requires_the_declared_complete_physical_source(tmp_path):
    spec = manual_input(tmp_path)
    bars = comparison.read_confirmation_input(spec=spec, root=tmp_path).bars
    deadline = comparison.time.monotonic() + spec.timeout_seconds
    comparison._validate_bars(bars, spec, deadline, None)
    for partial in (bars[1:], bars[:-1]):
        with pytest.raises(ValueError, match="物理|源|首|末|完整|范围"):
            comparison._validate_bars(partial, spec, deadline, None)
    with pytest.raises(ValueError):
        comparison._validate_bars((replace(bars[0], completed=False), bars[1]), spec, deadline, None)


def cli_exit(argv):
    try:
        return comparison.main(argv)
    except SystemExit as error:
        return error.code


def test_cli_help_does_not_read_or_compare(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Help must not reach input reading or a comparison")
    monkeypatch.setattr(comparison, "read_confirmation_input", forbidden)
    monkeypatch.setattr(comparison, "compare_confirmation", forbidden)
    assert cli_exit(["--help"]) == 0
    output = capsys.readouterr().out
    assert "--start-date" in output and "--end-date" in output
    assert "--output" not in output and "--mode" not in output


@pytest.mark.parametrize("argv", [["--start-date"], ["--output", "ignored.json"], ["--mode", "two_digit"],
                                  ["--start-date", "20250104"], ["--end-date", "2023-06-01"],
                                  ["--start-date", "2025-12-31", "--end-date", "2025-09-01"],
                                  ["--end-date", "2026-10-14"]])
def test_invalid_cli_fails_before_any_source_or_dual_comparison(monkeypatch, capsys, argv):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid CLI must be rejected before file I/O or either calculator")
    monkeypatch.setattr(comparison, "read_confirmation_input", forbidden)
    monkeypatch.setattr(comparison, "compare_confirmation", forbidden)
    assert cli_exit(argv) == 2
    assert capsys.readouterr().err


def test_terminal_formatter_keeps_range_counts_and_each_difference_without_replay():
    # Deliberately independent output literal, not compare_confirmation output.
    result = {"status": "ready", "requestedStart": "2024-01-04", "requestedEnd": "2024-01-08",
              "observationStart": "2024-01-04", "observationEnd": "2024-01-08", "observationBarCount": 3,
              "availableStart": "2024-01-02", "availableEnd": "2024-01-08", "sourceBarCount": 5,
              "calculationStart": "2024-01-02", "calculationEnd": "2024-01-08", "calculationBarCount": 5,
              "contextBarCount": 2, "baseSpecHash": "literal-r2-rules", "researchSpecHash": "literal-trial-rules",
              "firstDivergenceInPrefix": "2024-01-03", "firstDivergenceInObservation": "2024-01-04",
              "contextWarnings": ["以源首日空状态为试验前提"],
              "summary": {"eventComparisons": {"推后": 1}, "pointDifferenceCount": 1, "historyDifferenceCount": 1},
              "eventComparisons": [{"classification": "推后", "r2": {"time": "2024-01-03"},
                                    "twoDigit": {"time": "2024-01-04"}, "tradingBarShift": 1}],
              "pointDifferences": [{"time": "2024-01-04", "cause": "相邻DIF转折门槛直接不同"}],
              "historyDifferences": [{"time": "2024-01-05", "kind": "histories"}]}
    text = comparison.format_report(result)
    assert "实际观察：2024-01-04 至 2024-01-08，3根" in text
    assert "来源范围：2024-01-02 至 2024-01-08，5根" in text
    assert "实际计算：2024-01-02 至 2024-01-08，5根；前段2根" in text
    assert all(label in text for label in ("事件差异", "逐根状态差异", "历史更新差异", "literal-r2-rules", "literal-trial-rules"))
    assert "相邻DIF转折门槛直接不同" in text and "2024-01-05" in text
    assert "软件准确率" not in text and "改善" not in text and "退化" not in text
    result.update(status="empty", observationStart=None, observationEnd=None, observationBarCount=0,
                  eventComparisons=[], pointDifferences=[], historyDifferences=[])
    assert "所选区间无交易日，未作该区间标签比较" in comparison.format_report(result)
