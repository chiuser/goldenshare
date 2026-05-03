from __future__ import annotations

from datetime import date

from lake_console.backend.app.catalog.tushare_stk_mins import STK_MINS_FIELDS, STK_MINS_SOURCE_FIELDS
from lake_console.backend.app.services.tushare_stk_mins_sync_service import _normalize_stk_mins_row


def test_stk_mins_explicit_source_fields_include_optional_doc_outputs() -> None:
    assert STK_MINS_SOURCE_FIELDS == (
        "ts_code",
        "trade_time",
        "open",
        "close",
        "high",
        "low",
        "vol",
        "amount",
        "freq",
        "exchange",
        "vwap",
    )


def test_stk_mins_storage_fields_keep_integer_freq_and_optional_outputs() -> None:
    assert STK_MINS_FIELDS == (
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


def test_normalize_stk_mins_row_uses_storage_freq_not_source_freq() -> None:
    row = {
        "ts_code": "600000.SH",
        "trade_time": "2026-04-24 10:00:00",
        "open": 10.0,
        "close": 10.2,
        "high": 10.3,
        "low": 9.9,
        "vol": 1000,
        "amount": 10100.0,
        "freq": "30min",
        "exchange": "SSE",
        "vwap": 10.1,
    }

    normalized = _normalize_stk_mins_row(row, freq=30, trade_date=date(2026, 4, 24))

    assert normalized["freq"] == 30
    assert normalized["exchange"] == "SSE"
    assert normalized["vwap"] == 10.1
