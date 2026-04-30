from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import lake_console.backend.app.services.tushare_stk_mins_sync_service as mins_module
import lake_console.backend.app.services.tushare_stock_basic_sync_service as stock_module
from lake_console.backend.app.services.tushare_stk_mins_sync_service import TushareStkMinsSyncService
from lake_console.backend.app.services.tushare_stock_basic_sync_service import TushareStockBasicSyncService


class FakeClient:
    def stock_basic(self, *, list_status: str, fields: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        if list_status == "L":
            return [{"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}]
        return []

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
