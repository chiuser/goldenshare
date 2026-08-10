from __future__ import annotations

import pytest

from orchestrator.defs.run_contracts import major_index_mins
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_CODES,
    MAJOR_INDEX_MINS_DAILY_CODES,
    MAJOR_INDEX_MINS_RAW_SOURCE_CODES,
    MAJOR_INDEX_MINS_SILVER_EXCLUDED_CODES,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
    MAJOR_INDEX_MINS_SOURCE_SCOPES,
    MajorIndexMinsContractError,
    effective_raw_request_codes_for_date,
    effective_silver_codes_for_date,
    major_index_mins_silver_cleanup_fingerprint,
    major_index_mins_silver_ohlc_cleanup_scope_rows,
    major_index_mins_silver_opening_price_replacement_rows,
    raw_scope_hash_for_partition,
    silver_scope_hash_for_date,
)


def test_contract_freezes_codes_fields_and_frequencies() -> None:
    assert len(MAJOR_INDEX_MINS_CODES) == 11
    assert len(set(MAJOR_INDEX_MINS_CODES)) == 11
    assert len(MAJOR_INDEX_MINS_DAILY_CODES) == 10
    assert MAJOR_INDEX_MINS_RAW_SOURCE_CODES == MAJOR_INDEX_MINS_CODES
    assert MAJOR_INDEX_MINS_SILVER_EXCLUDED_CODES == ("899050.BJ",)
    assert "899050.BJ" not in MAJOR_INDEX_MINS_DAILY_CODES
    assert MAJOR_INDEX_MINS_SOURCE_FREQS == (
        "1min",
        "5min",
        "15min",
        "30min",
        "60min",
    )
    assert MAJOR_INDEX_MINS_SOURCE_COLUMNS == (
        "ts_code",
        "freq",
        "trade_time",
        "open",
        "close",
        "high",
        "low",
        "vol",
        "amount",
        "exchange",
        "vwap",
    )


def test_source_scopes_freeze_real_boundaries() -> None:
    scopes = {scope.ts_code: scope for scope in MAJOR_INDEX_MINS_SOURCE_SCOPES}
    assert scopes["000001.SH"].source_start_date == "2009-01-05"
    assert scopes["899050.BJ"].source_start_date == "2022-11-21"
    assert scopes["899050.BJ"].source_end_date == "2025-10-30"
    assert scopes["000680.SH"].source_start_date == "2025-01-20"


def test_raw_and_silver_scopes_follow_separate_contracts() -> None:
    assert effective_raw_request_codes_for_date("2009-01-05") == (
        "000001.SH",
        "000016.SH",
        "000300.SH",
        "000905.SH",
        "399001.SZ",
    )
    assert "899050.BJ" in effective_raw_request_codes_for_date("2025-10-30")
    assert "899050.BJ" not in effective_raw_request_codes_for_date("2025-10-31")
    assert "899050.BJ" not in effective_silver_codes_for_date("2025-10-30")
    assert len(effective_silver_codes_for_date("2025-10-30")) == 10
    assert len(effective_raw_request_codes_for_date("2026-08-04")) == 10


def test_effective_codes_reject_invalid_dates_and_duplicate_scopes() -> None:
    with pytest.raises(MajorIndexMinsContractError, match="ISO trade date"):
        effective_raw_request_codes_for_date("20260804")
    with pytest.raises(MajorIndexMinsContractError, match="duplicate source scope"):
        effective_silver_codes_for_date(
            "2026-08-04",
            scopes=MAJOR_INDEX_MINS_SOURCE_SCOPES
            + (MAJOR_INDEX_MINS_SOURCE_SCOPES[0],),
        )


def test_layer_scope_hashes_are_stable_and_semantically_distinct() -> None:
    raw_1m = raw_scope_hash_for_partition("2025-10-30", "1min")
    assert raw_1m == raw_scope_hash_for_partition("2025-10-30", "1min")
    assert raw_1m != raw_scope_hash_for_partition("2025-10-30", "5min")
    silver = silver_scope_hash_for_date("2025-10-30")
    assert silver == silver_scope_hash_for_date("2025-10-30")
    assert silver != raw_1m


def test_silver_cleanup_scope_is_explicit_and_fingerprinted() -> None:
    rows = major_index_mins_silver_ohlc_cleanup_scope_rows()
    assert len(rows) == 135
    assert len(set(rows)) == 135
    assert sum(row[-1] == "opening_sentinel" for row in rows) == 30
    assert sum(row[-1] == "ohlc_envelope" for row in rows) == 105
    assert all(row[2] != "2017-01-04" for row in rows if row[1] != "5min")
    replacements = major_index_mins_silver_opening_price_replacement_rows()
    assert len(replacements) == 21
    assert len(set(replacements)) == 21
    assert replacements[0] == (
        "000016.SH",
        "15min",
        "2016-10-10",
        "09:30:00",
        2187.652,
    )
    assert {
        row[0] for row in replacements if row[2] == "2017-11-29"
    } == {
        "000001.SH",
        "000016.SH",
        "000300.SH",
        "000852.SH",
        "000905.SH",
    }
    assert {
        row[1] for row in replacements if row[2] == "2017-11-29"
    } == {"5min", "15min", "30min", "60min"}
    assert len(major_index_mins_silver_cleanup_fingerprint()) == 64


def test_legacy_shared_scope_api_is_removed() -> None:
    assert not hasattr(major_index_mins, "effective_codes_for_date")
    assert not hasattr(major_index_mins, "source_scope_hash_for_date")
