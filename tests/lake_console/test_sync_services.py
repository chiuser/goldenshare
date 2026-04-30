from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import lake_console.backend.app.services.tushare_stk_mins_sync_service as mins_module
import lake_console.backend.app.services.tushare_stock_basic_sync_service as stock_module
import lake_console.backend.app.services.tushare_trade_cal_sync_service as trade_cal_module
from lake_console.backend.app.services.tushare_stk_mins_sync_service import StkMinsProgressEvent, TushareStkMinsSyncService
from lake_console.backend.app.services.tushare_stock_basic_sync_service import TushareStockBasicSyncService
from lake_console.backend.app.services.tushare_trade_cal_sync_service import TushareTradeCalSyncService


class FakeClient:
    def stock_basic(self, *, list_status: str, fields: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        if list_status == "L":
            return [{"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}]
        return []

    def trade_cal(self, *, exchange: str, start_date: str, end_date: str, fields: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        return [
            {"exchange": exchange, "cal_date": "20260424", "is_open": "1", "pretrade_date": "20260423"},
            {"exchange": exchange, "cal_date": "20260425", "is_open": "0", "pretrade_date": "20260424"},
        ]

    def stk_mins(
        self,
        *,
        ts_code: str,
        freq: int,
        start_date: str,
        end_date: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        if offset:
            return []
        return [
            {
                "ts_code": ts_code,
                "trade_time": "2026-04-24 09:31:00",
                "open": 10.1,
                "close": 10.2,
                "high": 10.3,
                "low": 10.0,
                "vol": 1000,
                "amount": 10200.0,
            }
        ]


def test_stock_basic_sync_writes_local_universe(tmp_path, monkeypatch):
    written: dict[str, Any] = {}

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        written["rows"] = rows
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake parquet", encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(stock_module, "write_rows_to_parquet", fake_write)
    monkeypatch.setattr(stock_module, "read_parquet_row_count", lambda path: 1)

    summary = TushareStockBasicSyncService(lake_root=tmp_path, client=FakeClient(), progress=lambda message: None).sync()

    assert summary["written_rows"] == 1
    assert (tmp_path / "raw_tushare" / "stock_basic" / "current" / "part-000.parquet").exists()
    assert (tmp_path / "manifest" / "security_universe" / "tushare_stock_basic.parquet").exists()
    assert written["rows"][0]["ts_code"] == "000001.SZ"
    assert not any((tmp_path / "_tmp").iterdir())


def test_trade_cal_sync_writes_raw_and_local_calendar(tmp_path, monkeypatch):
    written: dict[str, Any] = {}

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        written[str(output_path)] = rows
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake parquet", encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(trade_cal_module, "write_rows_to_parquet", fake_write)
    monkeypatch.setattr(trade_cal_module, "read_parquet_row_count", lambda path: 2)

    summary = TushareTradeCalSyncService(lake_root=tmp_path, client=FakeClient(), progress=lambda message: None).sync(
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 25),
    )

    assert summary["written_rows"] == 2
    assert (tmp_path / "raw_tushare" / "trade_cal" / "current" / "part-000.parquet").exists()
    assert (tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet").exists()
    raw_rows = written[str(tmp_path / "_tmp" / summary["run_id"] / "raw_tushare" / "trade_cal" / "current" / "part-000.parquet")]
    assert raw_rows[0]["cal_date"] == "2026-04-24"
    assert raw_rows[0]["is_open"] is True


def test_stk_mins_sync_writes_single_symbol_day_partition(tmp_path, monkeypatch):
    written: dict[str, Any] = {}

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        written["rows"] = rows
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake parquet", encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(mins_module, "write_rows_to_parquet", fake_write)
    monkeypatch.setattr(mins_module, "read_parquet_row_count", lambda path: 1)
    monkeypatch.setattr(TushareStkMinsSyncService, "_ensure_stock_universe_exists", lambda self: None)

    summary = TushareStkMinsSyncService(lake_root=tmp_path, client=FakeClient(), progress=lambda message: None).sync_single_symbol_day(
        ts_code="000001.SZ",
        freq=30,
        trade_date=date(2026, 4, 24),
    )

    assert summary["written_rows"] == 1
    assert written["rows"][0]["freq"] == 30
    assert (tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=30" / "trade_date=2026-04-24" / "part-000.parquet").exists()


def test_stk_mins_market_sync_reads_local_universe_and_writes_parts(tmp_path, monkeypatch):
    written_parts: list[list[dict[str, Any]]] = []

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        written_parts.append(rows)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake parquet", encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(mins_module, "write_rows_to_parquet", fake_write)
    monkeypatch.setattr(mins_module, "read_parquet_row_count", lambda path: 1)
    monkeypatch.setattr(
        mins_module,
        "read_parquet_rows",
        lambda path: [
            {"ts_code": "000001.SZ", "list_status": "L"},
            {"ts_code": "000002.SZ", "list_status": "D"},
        ],
    )
    universe = tmp_path / "manifest" / "security_universe" / "tushare_stock_basic.parquet"
    universe.parent.mkdir(parents=True)
    universe.write_text("fake parquet", encoding="utf-8")

    summary = TushareStkMinsSyncService(lake_root=tmp_path, client=FakeClient(), progress=lambda message: None).sync_market_day(
        freqs=[30],
        trade_date=date(2026, 4, 24),
        part_rows=1,
    )

    assert summary["symbols_total"] == 1
    assert summary["written_rows"] == 1
    assert written_parts[0][0]["ts_code"] == "000001.SZ"


def test_stk_mins_range_uses_local_open_trade_calendar(tmp_path, monkeypatch):
    calls: list[date] = []

    monkeypatch.setattr(
        mins_module,
        "read_parquet_rows",
        lambda path: [
            {"cal_date": "2026-04-24", "is_open": True},
            {"cal_date": "2026-04-25", "is_open": False},
            {"cal_date": "2026-04-27", "is_open": True},
        ],
    )
    calendar = tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
    calendar.parent.mkdir(parents=True)
    calendar.write_text("fake parquet", encoding="utf-8")

    def fake_sync_single(self: TushareStkMinsSyncService, *, ts_code: str, freq: int, trade_date: date) -> dict[str, Any]:
        calls.append(trade_date)
        return {"fetched_rows": 1, "written_rows": 1, "trade_date": trade_date.isoformat()}

    monkeypatch.setattr(TushareStkMinsSyncService, "sync_single_symbol_day", fake_sync_single)

    summary = TushareStkMinsSyncService(lake_root=tmp_path, client=FakeClient(), progress=lambda message: None).sync_range(
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 27),
        freqs=[],
        all_market=False,
        ts_code="000001.SZ",
        freq=30,
    )

    assert calls == [date(2026, 4, 24), date(2026, 4, 27)]
    assert summary["trade_date_count"] == 2
    assert summary["written_rows"] == 2


def test_stk_mins_range_all_market_emits_structured_progress(tmp_path, monkeypatch):
    progress_events: list[StkMinsProgressEvent] = []
    text_messages: list[str] = []

    def fake_read(path: Path) -> list[dict[str, Any]]:
        if "trading_calendar" in str(path):
            return [{"cal_date": "2026-04-24", "is_open": True}]
        return [
            {"ts_code": "000001.SZ", "list_status": "L"},
            {"ts_code": "000002.SZ", "list_status": "L"},
        ]

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake parquet", encoding="utf-8")
        return len(rows)

    def collect_progress(payload: str | StkMinsProgressEvent) -> None:
        if isinstance(payload, StkMinsProgressEvent):
            progress_events.append(payload)
        else:
            text_messages.append(payload)

    monkeypatch.setattr(mins_module, "read_parquet_rows", fake_read)
    monkeypatch.setattr(mins_module, "write_rows_to_parquet", fake_write)
    monkeypatch.setattr(mins_module, "read_parquet_row_count", lambda path: 2)
    (tmp_path / "manifest" / "trading_calendar").mkdir(parents=True)
    (tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet").write_text("fake parquet", encoding="utf-8")
    (tmp_path / "manifest" / "security_universe").mkdir(parents=True)
    (tmp_path / "manifest" / "security_universe" / "tushare_stock_basic.parquet").write_text("fake parquet", encoding="utf-8")

    summary = TushareStkMinsSyncService(lake_root=tmp_path, client=FakeClient(), progress=collect_progress).sync_range(
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        freqs=[30, 60],
        all_market=True,
        part_rows=100,
    )

    assert summary["trade_date_count"] == 1
    assert summary["written_rows"] == 4
    assert [event.units_done for event in progress_events] == [1, 2, 3, 4]
    assert progress_events[-1].units_total == 4
    assert progress_events[-1].ts_code == "000002.SZ"
    assert not any("page=" in message for message in text_messages)
