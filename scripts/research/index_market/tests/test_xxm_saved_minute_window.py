"""Literal CSV contract from the saved M0 source_headers.json, not a product fixture.

The hand-written DIF/DEA/H values satisfy 2*(-8.0860+9.0000)=1.8280.
All files are synthetic temporary inputs; no real market input is opened.
"""
from datetime import date, timedelta
import hashlib

import pytest

from scripts.research.index_market.xxm.saved_minute_window import read_window


HEADER = ("ts_code,freq,trade_date,trade_time,close,macd_dif,macd_dea,macd,"
          "params_key,indicator_version,observation_count")
KEY = "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3"


def literal_rows(days=5):
    result = []
    day = date(2025, 11, 3)
    for i in range(days):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        for slot in ("11:00:00", "14:00:00", "15:00:00"):
            result.append(["000001.SH", "90", day.isoformat(), f"{day} {slot}",
                           f"{4000+i}.0100", "-8.0860", "-9.0000", "1.8280", KEY, "1", "90"])
        day += timedelta(days=1)
    return result


def save_csv(tmp_path, rows, *, header=HEADER, newline="\n", final_newline=True):
    text = newline.join([header, *[",".join(row) for row in rows]])
    if final_newline:
        text += newline
    raw = text.encode()
    path = tmp_path / "synthetic.csv"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), raw


def read_all(path, sha, rows, **options):
    return read_window(path, start=rows[0][3], end=rows[-1][3], expected_sha=sha, **options)


def test_bounded_middle_window_retains_original_strings_and_counts_all_reads(tmp_path):
    rows = literal_rows(200)
    path, sha, raw = save_csv(tmp_path, rows)
    selected = rows[300:306]
    result = read_window(path, start=selected[0][3], end=selected[-1][3], expected_sha=sha)
    assert result["rows"] == [dict(zip(HEADER.split(","), row)) for row in selected]
    assert result["rows"][0]["close"] == "4100.0100"
    assert result["source_sha256"] == sha
    metrics = result["metrics"]
    assert metrics["window_rows"] == 6
    assert metrics["window_bytes"] == sum(len((",".join(row)+"\n").encode()) for row in selected)
    assert metrics["sha_bytes"] == len(raw)
    assert 0 < metrics["seek_rows"] < 50 < len(rows)
    assert 0 < metrics["seek_bytes"] < 65536
    assert metrics["preceding_time"] == rows[299][3]
    assert metrics["following_time"] == rows[306][3]
    assert metrics["seconds"] >= metrics["sha_seconds"] >= 0
    assert metrics["global_order_verified"] is False
    assert metrics["trading_calendar_rechecked"] is False


def test_binary_line_alignment_matches_every_small_complete_date_interval(tmp_path):
    rows = literal_rows(6)
    path, sha, _ = save_csv(tmp_path, rows)
    for left in range(6):
        for right in range(left, 6):
            expected = rows[left*3:(right+1)*3]
            actual = read_window(path, start=expected[0][3], end=expected[-1][3], expected_sha=sha)
            assert [row["trade_time"] for row in actual["rows"]] == [row[3] for row in expected]


@pytest.mark.parametrize("newline,final", [("\n", True), ("\r\n", True), ("\n", False), ("\r\n", False)])
def test_file_edges_line_endings_and_missing_final_newline(tmp_path, newline, final):
    rows = literal_rows(2)
    path, sha, _ = save_csv(tmp_path, rows, newline=newline, final_newline=final)
    result = read_all(path, sha, rows)
    assert len(result["rows"]) == 6
    assert result["metrics"]["preceding_time"] is None
    assert result["metrics"]["following_time"] is None


@pytest.mark.parametrize("header", [HEADER.replace("close", "closing"), HEADER+",extra", ",".join(HEADER.split(",")[:-1])])
def test_changed_header_rejected(tmp_path, header):
    rows = literal_rows(1)
    path, sha, _ = save_csv(tmp_path, rows, header=header)
    with pytest.raises(ValueError, match="header"):
        read_all(path, sha, rows)


def test_sha_rejected_before_parsing_invalid_content(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_bytes(b"not a CSV\n")
    with pytest.raises(ValueError, match="SHA256"):
        read_window(path, start="2025-11-03 11:00:00", end="2025-11-03 15:00:00", expected_sha="0"*64)


@pytest.mark.parametrize("column,value", [
    (0,"399001.SZ"), (1,"60"), (2,"2025-11-04"), (3,"2025-11-03 12:00:00"),
    (3,"2025-02-30 11:00:00"), (4,"0"), (4,"-1"), (4,"NaN"), (4,""),
    (5,"Infinity"), (5,"not-a-number"), (6,"-Infinity"), (7,"999"),
    (8,"other"), (9,"2"), (10,"0"), (10,"1.5"),
])
def test_read_record_contract_errors_rejected(tmp_path, column, value):
    rows = literal_rows(1)
    rows[1][column] = value
    path, sha, _ = save_csv(tmp_path, rows)
    with pytest.raises(ValueError):
        read_window(path, start="2025-11-03 11:00:00", end="2025-11-03 15:00:00", expected_sha=sha)


@pytest.mark.parametrize("mutation", ["missing_midday", "duplicate", "unordered"])
def test_missing_duplicate_or_unordered_window_records_rejected(tmp_path, mutation):
    rows = literal_rows(3)
    if mutation == "missing_midday":
        del rows[4]
    elif mutation == "duplicate":
        rows.insert(5, rows[4].copy())
    else:
        rows[4], rows[5] = rows[5], rows[4]
    path, sha, _ = save_csv(tmp_path, rows)
    with pytest.raises(ValueError):
        read_window(path, start="2025-11-03 11:00:00", end="2025-11-05 15:00:00", expected_sha=sha)


@pytest.mark.parametrize("start,end", [
    ("2025-10-31 11:00:00", "2025-11-03 15:00:00"),
    ("2025-11-03 11:00:00", "2025-11-10 15:00:00"),
    ("2025-11-10 11:00:00", "2025-11-10 15:00:00"),
])
def test_absent_requested_boundary_rejected(tmp_path, start, end):
    path, sha, _ = save_csv(tmp_path, literal_rows(1))
    with pytest.raises(ValueError, match="not found"):
        read_window(path, start=start, end=end, expected_sha=sha)


@pytest.mark.parametrize("options", [{"max_rows": 2}, {"max_bytes": 10}])
def test_approved_window_budgets_enforced(tmp_path, options):
    rows = literal_rows(1)
    path, sha, _ = save_csv(tmp_path, rows)
    with pytest.raises(ValueError, match="budget"):
        read_all(path, sha, rows, **options)


@pytest.mark.parametrize("options", [{"max_rows": True}, {"max_rows": 151}, {"max_bytes": 65537}])
def test_budget_cannot_be_silently_expanded(tmp_path, options):
    with pytest.raises(ValueError, match="budget"):
        read_window(tmp_path/"not-read.csv", start="2025-11-03 11:00:00", end="2025-11-03 15:00:00", expected_sha="0"*64, **options)


def test_oversized_record_refused_during_positioning_or_window_read(tmp_path):
    rows = literal_rows(1)
    rows[1][4] = "4"*1050
    path, sha, _ = save_csv(tmp_path, rows)
    with pytest.raises(ValueError):
        read_all(path, sha, rows)


def test_normal_close_change_does_not_create_false_contract_failure(tmp_path):
    rows = literal_rows(1)
    rows[1][4] = "123.456789"
    path, sha, _ = save_csv(tmp_path, rows)
    assert read_all(path, sha, rows)["rows"][1]["close"] == "123.456789"


def test_empty_data_and_missing_frozen_identity_refused(tmp_path):
    path, sha, _ = save_csv(tmp_path, [])
    with pytest.raises(ValueError, match="no minute"):
        read_window(path, start="2025-11-03 11:00:00", end="2025-11-03 15:00:00", expected_sha=sha)
    with pytest.raises(ValueError, match="SHA256"):
        read_window(path, start="2025-11-03 11:00:00", end="2025-11-03 15:00:00", expected_sha="")
