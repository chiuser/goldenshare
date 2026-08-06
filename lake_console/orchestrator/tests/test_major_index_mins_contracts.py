from __future__ import annotations

import pytest

from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_CODES,
    MAJOR_INDEX_MINS_DAILY_CODES,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
    MAJOR_INDEX_MINS_SOURCE_SCOPES,
    MajorIndexMinsContractError,
    effective_codes_for_date,
    source_scope_hash_for_date,
)


def test_contract_freezes_codes_fields_and_frequencies() -> None:
    assert len(MAJOR_INDEX_MINS_CODES) == 11
    assert len(set(MAJOR_INDEX_MINS_CODES)) == 11
    assert len(MAJOR_INDEX_MINS_DAILY_CODES) == 10
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


def test_effective_codes_follow_per_code_lifecycle() -> None:
    assert effective_codes_for_date("2009-01-05") == (
        "000001.SH",
        "000016.SH",
        "000300.SH",
        "000905.SH",
        "399001.SZ",
    )
    assert "899050.BJ" in effective_codes_for_date("2025-10-30")
    assert "899050.BJ" not in effective_codes_for_date("2025-10-31")
    assert len(effective_codes_for_date("2026-08-04")) == 10


def test_effective_codes_reject_invalid_dates_and_duplicate_scopes() -> None:
    with pytest.raises(MajorIndexMinsContractError, match="ISO trade date"):
        effective_codes_for_date("20260804")
    with pytest.raises(MajorIndexMinsContractError, match="duplicate source scope"):
        effective_codes_for_date(
            "2026-08-04",
            scopes=MAJOR_INDEX_MINS_SOURCE_SCOPES
            + (MAJOR_INDEX_MINS_SOURCE_SCOPES[0],),
        )


def test_scope_hash_is_stable_and_changes_with_expected_codes() -> None:
    same_day = source_scope_hash_for_date("2026-08-04")
    assert same_day == source_scope_hash_for_date("2026-08-04")
    assert same_day != source_scope_hash_for_date("2025-10-30")
