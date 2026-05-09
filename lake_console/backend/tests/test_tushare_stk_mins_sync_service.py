from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from lake_console.backend.app.services.indicators import IndicatorRecalcQueueService
from lake_console.backend.app.services.parquet_writer import write_rows_to_parquet
from lake_console.backend.app.services.tushare_stk_mins_sync_service import TushareStkMinsSyncService


def test_stk_mins_range_uses_lifecycle_filtered_security_universe(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_universe(
        tmp_path,
        [
            _stock("000001.SZ", "L", "20090105", None),
            _stock("000002.SZ", "D", "20060101", "20120601"),
            _stock("000003.SZ", "L", "20210315", None),
            _stock("000004.SZ", "D", "20050101", "20071231"),
        ],
    )
    _write_calendar(tmp_path, [date(2019, 12, 31)])
    client = _FakeStkMinsClient()

    summary = TushareStkMinsSyncService(
        lake_root=tmp_path,
        client=client,
        progress=lambda _: None,
    ).sync_range(
        start_date=date(2009, 1, 1),
        end_date=date(2019, 12, 31),
        freqs=[30],
        all_market=True,
    )

    assert [call["ts_code"] for call in client.calls] == ["000001.SZ", "000002.SZ"]
    assert summary["security_universe"] == {
        "total_symbols": 4,
        "selected_symbols": 2,
        "skipped_listed_after_range": 1,
        "skipped_delisted_before_range": 1,
        "selected_listed_symbols": 1,
        "selected_delisted_or_paused_symbols": 1,
    }


def test_stk_mins_single_symbol_day_records_indicator_recalc_queue(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_universe(tmp_path, [_stock("600000.SH", "L", "19991110", None)])
    client = _FakeSingleSymbolClient(
        [
            {
                "ts_code": "600000.SH",
                "trade_time": "2026-04-24 10:00:00",
                "open": 10.0,
                "close": 10.1,
                "high": 10.2,
                "low": 9.9,
                "vol": 100.0,
                "amount": 1010.0,
            }
        ]
    )

    summary = TushareStkMinsSyncService(
        lake_root=tmp_path,
        client=client,
        progress=lambda _: None,
    ).sync_single_symbol_day(ts_code="600000.SH", freq=30, trade_date=date(2026, 4, 24))

    queue_items = IndicatorRecalcQueueService(lake_root=tmp_path).list_items()
    assert summary["written_rows"] == 1
    assert queue_items[0]["reason"] == "source_partition_replaced"
    assert queue_items[0]["freq_value"] == 30
    assert queue_items[0]["security_scope"] == "all"


class _FakeStkMinsClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def stk_mins(self, **kwargs) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return []


class _FakeSingleSymbolClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def stk_mins(self, **kwargs) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return self.rows


def _stock(ts_code: str, list_status: str, list_date: str, delist_date: str | None) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "list_status": list_status,
        "list_date": list_date,
        "delist_date": delist_date,
    }


def _write_universe(root, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(rows, root / "manifest" / "security_universe" / "tushare_stock_basic.parquet")


def _write_calendar(root, dates: list[date]) -> None:
    write_rows_to_parquet(
        [{"cal_date": item, "is_open": True, "exchange": "SSE", "pretrade_date": None} for item in dates],
        root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet",
    )
