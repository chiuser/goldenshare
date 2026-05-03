from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import lake_console.backend.app.services.tushare_stk_mins_sync_service as mins_module
import lake_console.backend.app.services.tushare_stock_basic_sync_service as stock_module
import lake_console.backend.app.services.tushare_trade_cal_sync_service as trade_cal_module
from lake_console.backend.app.services.tushare_stk_mins_sync_service import StkMinsProgressEvent, TushareStkMinsSyncService
from lake_console.backend.app.services.tushare_stock_basic_sync_service import TushareStockBasicSyncService
from lake_console.backend.app.services.tushare_trade_cal_sync_service import TushareTradeCalSyncService
from lake_console.backend.app.services.tushare_client import TushareQuotaExceededError


class FakeClient:
    def stock_basic(self, *, list_status: str, fields: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        if list_status == "L":
            return [{"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}]
        return []

    def trade_cal(
        self,
        *,
        exchange: str,
        start_date: str | None,
        end_date: str | None,
        fields: list[str] | tuple[str, ...],
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        del limit
        del offset
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
    assert summary["mode"] == "date_range"


def test_trade_cal_sync_without_dates_fetches_full_snapshot_with_pagination(tmp_path, monkeypatch):
    written: dict[str, Any] = {}
    calls: list[dict[str, Any]] = []

    class PagedTradeCalClient(FakeClient):
        def trade_cal(
            self,
            *,
            exchange: str,
            start_date: str | None,
            end_date: str | None,
            fields: list[str] | tuple[str, ...],
            limit: int | None = None,
            offset: int | None = None,
        ) -> list[dict[str, Any]]:
            calls.append(
                {
                    "exchange": exchange,
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": limit,
                    "offset": offset,
                }
            )
            if offset == 0:
                return [
                    {"exchange": exchange, "cal_date": "20260424", "is_open": "1", "pretrade_date": "20260423"},
                    {"exchange": exchange, "cal_date": "20260425", "is_open": "0", "pretrade_date": "20260424"},
                ]
            return []

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        written[str(output_path)] = rows
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake parquet", encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(trade_cal_module, "write_rows_to_parquet", fake_write)
    monkeypatch.setattr(trade_cal_module, "read_parquet_row_count", lambda path: 2)
    monkeypatch.setattr(trade_cal_module, "TRADE_CAL_PAGE_LIMIT", 2)

    summary = TushareTradeCalSyncService(lake_root=tmp_path, client=PagedTradeCalClient(), progress=lambda message: None).sync()

    assert summary["mode"] == "full_snapshot"
    assert summary["start_date"] is None
    assert summary["end_date"] is None
    assert summary["written_rows"] == 2
    assert calls == [
        {
            "exchange": "SSE",
            "start_date": None,
            "end_date": None,
            "limit": 2,
            "offset": 0,
        },
        {
            "exchange": "SSE",
            "start_date": None,
            "end_date": None,
            "limit": 2,
            "offset": 2,
        },
    ]
    raw_rows = written[str(tmp_path / "_tmp" / summary["run_id"] / "raw_tushare" / "trade_cal" / "current" / "part-000.parquet")]
    assert [row["cal_date"] for row in raw_rows] == ["2026-04-24", "2026-04-25"]


def test_trade_cal_sync_treats_nan_pretrade_date_as_null(tmp_path, monkeypatch):
    written: dict[str, Any] = {}

    class NaNTradeCalClient(FakeClient):
        def trade_cal(
            self,
            *,
            exchange: str,
            start_date: str | None,
            end_date: str | None,
            fields: list[str] | tuple[str, ...],
            limit: int | None = None,
            offset: int | None = None,
        ) -> list[dict[str, Any]]:
            del start_date, end_date, fields, limit, offset
            return [
                {"exchange": exchange, "cal_date": "20260424", "is_open": "1", "pretrade_date": "nan"},
            ]

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        written[str(output_path)] = rows
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake parquet", encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(trade_cal_module, "write_rows_to_parquet", fake_write)
    monkeypatch.setattr(trade_cal_module, "read_parquet_row_count", lambda path: 1)

    summary = TushareTradeCalSyncService(
        lake_root=tmp_path,
        client=NaNTradeCalClient(),
        progress=lambda message: None,
    ).sync()

    assert summary["written_rows"] == 1
    raw_rows = written[str(tmp_path / "_tmp" / summary["run_id"] / "raw_tushare" / "trade_cal" / "current" / "part-000.parquet")]
    assert raw_rows[0]["pretrade_date"] is None


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
    completed_events = [event for event in progress_events if event.page is None]
    page_events = [event for event in progress_events if event.page is not None]

    assert [event.units_done for event in completed_events] == [1, 2, 3, 4]
    assert completed_events[-1].units_total == 4
    assert completed_events[-1].ts_code == "000002.SZ"
    assert completed_events[-1].window_start == date(2026, 4, 24)
    assert completed_events[-1].window_end == date(2026, 4, 24)
    assert page_events
    assert not any("page=" in message for message in text_messages)


def test_stk_mins_range_all_market_requests_window_and_splits_daily_partitions(tmp_path, monkeypatch):
    calls: list[dict[str, Any]] = []
    written_paths: list[str] = []

    class WindowClient(FakeClient):
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
            calls.append(
                {
                    "ts_code": ts_code,
                    "freq": freq,
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": limit,
                    "offset": offset,
                }
            )
            if offset:
                return []
            return [
                {
                    "ts_code": ts_code,
                    "trade_time": "2026-04-24 10:00:00",
                    "open": 10.1,
                    "close": 10.2,
                    "high": 10.3,
                    "low": 10.0,
                    "vol": 1000,
                    "amount": 10200.0,
                },
                {
                    "ts_code": ts_code,
                    "trade_time": "2026-04-27 10:00:00",
                    "open": 10.2,
                    "close": 10.3,
                    "high": 10.4,
                    "low": 10.1,
                    "vol": 2000,
                    "amount": 20400.0,
                },
            ]

    def fake_read(path: Path) -> list[dict[str, Any]]:
        if "trading_calendar" in str(path):
            return [
                {"cal_date": "2026-04-24", "is_open": True},
                {"cal_date": "2026-04-27", "is_open": True},
            ]
        return [{"ts_code": "000001.SZ", "list_status": "L"}]

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        written_paths.append(str(output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake parquet", encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(mins_module, "read_parquet_rows", fake_read)
    monkeypatch.setattr(mins_module, "write_rows_to_parquet", fake_write)
    monkeypatch.setattr(mins_module, "read_parquet_row_count", lambda path: 1)
    (tmp_path / "manifest" / "trading_calendar").mkdir(parents=True)
    (tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet").write_text("fake parquet", encoding="utf-8")
    (tmp_path / "manifest" / "security_universe").mkdir(parents=True)
    (tmp_path / "manifest" / "security_universe" / "tushare_stock_basic.parquet").write_text("fake parquet", encoding="utf-8")

    summary = TushareStkMinsSyncService(lake_root=tmp_path, client=WindowClient(), progress=lambda payload: None).sync_range(
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 27),
        freqs=[30],
        all_market=True,
        part_rows=100,
    )

    assert calls[0]["start_date"] == "2026-04-24 09:00:00"
    assert calls[0]["end_date"] == "2026-04-27 19:00:00"
    assert summary["written_rows"] == 2
    assert any("trade_date=2026-04-24" in path for path in written_paths)
    assert any("trade_date=2026-04-27" in path for path in written_paths)


def test_stk_mins_range_all_market_uses_per_freq_trade_day_windows(tmp_path, monkeypatch):
    calls: list[dict[str, Any]] = []

    month_open_days = [21, 20, 21, 21, 20, 20, 21, 21, 20, 20, 20, 20]

    def fake_read(path: Path) -> list[dict[str, Any]]:
        if "trading_calendar" in str(path):
            rows: list[dict[str, Any]] = []
            for month, open_days in enumerate(month_open_days, start=1):
                for day in range(1, open_days + 1):
                    rows.append({"cal_date": f"2025{month:02d}{day:02d}", "is_open": True})
            return rows
        return [{"ts_code": "000001.SZ", "list_status": "L"}]

    def fake_fetch(
        self: TushareStkMinsSyncService,
        *,
        ts_code: str,
        freq: int,
        window_start: date,
        window_end: date,
        units_done: int,
        units_total: int,
    ) -> list[dict[str, Any]]:
        calls.append(
            {
                "ts_code": ts_code,
                "freq": freq,
                "window_start": window_start,
                "window_end": window_end,
                "units_done": units_done,
                "units_total": units_total,
            }
        )
        return []

    monkeypatch.setattr(mins_module, "read_parquet_rows", fake_read)
    monkeypatch.setattr(TushareStkMinsSyncService, "_fetch_symbol_window", fake_fetch)
    (tmp_path / "manifest" / "trading_calendar").mkdir(parents=True)
    (tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet").write_text("fake parquet", encoding="utf-8")
    (tmp_path / "manifest" / "security_universe").mkdir(parents=True)
    (tmp_path / "manifest" / "security_universe" / "tushare_stock_basic.parquet").write_text("fake parquet", encoding="utf-8")

    summary = TushareStkMinsSyncService(lake_root=tmp_path, client=FakeClient(), progress=lambda payload: None).sync_range(
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        freqs=[1, 5, 15, 30, 60],
        all_market=True,
        part_rows=100,
    )

    assert len(calls) == 13
    assert summary["written_rows"] == 0
    per_freq_counts = {freq: sum(1 for item in calls if item["freq"] == freq) for freq in [1, 5, 15, 30, 60]}
    assert per_freq_counts == {1: 8, 5: 2, 15: 1, 30: 1, 60: 1}
    assert all(item["units_total"] == 13 for item in calls)


def test_stk_mins_range_all_market_returns_quota_exhausted_summary_and_checkpoint(tmp_path, monkeypatch):
    def fake_read(path: Path) -> list[dict[str, Any]]:
        if "trading_calendar" in str(path):
            return [{"cal_date": "2026-04-24", "is_open": True}]
        return [
            {"ts_code": "000001.SZ", "list_status": "L"},
            {"ts_code": "000002.SZ", "list_status": "L"},
        ]

    def quota_fetch(
        self: TushareStkMinsSyncService,
        *,
        ts_code: str,
        freq: int,
        window_start: date,
        window_end: date,
        units_done: int,
        units_total: int,
    ) -> list[dict[str, Any]]:
        raise TushareQuotaExceededError(
            api_name="stk_mins",
            message="抱歉，您访问接口(stk_mins)频率超限(250000次/天)",
        )

    monkeypatch.setattr(mins_module, "read_parquet_rows", fake_read)
    monkeypatch.setattr(TushareStkMinsSyncService, "_fetch_symbol_window", quota_fetch)
    (tmp_path / "manifest" / "trading_calendar").mkdir(parents=True)
    (tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet").write_text("fake parquet", encoding="utf-8")
    (tmp_path / "manifest" / "security_universe").mkdir(parents=True)
    (tmp_path / "manifest" / "security_universe" / "tushare_stock_basic.parquet").write_text("fake parquet", encoding="utf-8")

    summary = TushareStkMinsSyncService(lake_root=tmp_path, client=FakeClient(), progress=lambda payload: None).sync_range(
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 24),
        freqs=[30],
        all_market=True,
        part_rows=100,
    )

    assert summary["status"] == "quota_exhausted"
    assert summary["completed_units"] == 0
    assert summary["units_total"] == 2
    assert summary["remaining_units"] == 2
    assert summary["stopped_at"] == {
        "ts_code": "000001.SZ",
        "freq": 30,
        "window_start": "2026-04-24",
        "window_end": "2026-04-24",
    }
    assert summary["error"]["api_name"] == "stk_mins"
    assert "250000次/天" in summary["error"]["message"]
    checkpoint_file = Path(summary["checkpoint_file"])
    assert checkpoint_file.exists()
    checkpoint_rows = [
        json.loads(line)
        for line in checkpoint_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert checkpoint_rows == [
        {
            "completed_units": 0,
            "dataset_key": "stk_mins",
            "error_message": "抱歉，您访问接口(stk_mins)频率超限(250000次/天)",
            "finished_at": checkpoint_rows[0]["finished_at"],
            "freq": 30,
            "status": "quota_exhausted",
            "ts_code": "000001.SZ",
            "units_total": 2,
            "window_end": "2026-04-24",
            "window_start": "2026-04-24",
        }
    ]
