from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import lake_console.backend.app.services.stk_mins_derived_service as derived_module
from lake_console.backend.app.services.stk_mins_derived_service import StkMinsDerivedService, derive_rows


def test_derive_rows_aggregates_complete_chunks_only():
    rows = [
        _row("000001.SZ", "2026-04-24 09:30:00", 10, 11, 12, 9, 100, 1000),
        _row("000001.SZ", "2026-04-24 10:00:00", 11, 12, 13, 10, 200, 2000),
        _row("000001.SZ", "2026-04-24 10:30:00", 12, 13, 14, 11, 300, 3000),
        _row("000001.SZ", "2026-04-24 11:00:00", 13, 14, 15, 12, 400, 4000),
    ]

    result = derive_rows(rows, target_freq=90, group_size=3)

    assert len(result) == 1
    assert result[0]["trade_time"] == "2026-04-24 10:30:00"
    assert result[0]["open"] == 10
    assert result[0]["close"] == 13
    assert result[0]["high"] == 14
    assert result[0]["low"] == 9
    assert result[0]["vol"] == 600
    assert result[0]["amount"] == 6000


def test_derive_rows_does_not_cross_lunch_break():
    rows = [
        _row("000001.SZ", "2026-04-24 10:30:00", 10, 11, 12, 9, 100, 1000),
        _row("000001.SZ", "2026-04-24 11:00:00", 11, 12, 13, 10, 200, 2000),
        _row("000001.SZ", "2026-04-24 13:30:00", 20, 21, 22, 19, 300, 3000),
        _row("000001.SZ", "2026-04-24 14:00:00", 21, 22, 23, 20, 400, 4000),
        _row("000001.SZ", "2026-04-24 14:30:00", 22, 23, 24, 21, 500, 5000),
    ]

    result = derive_rows(rows, target_freq=90, group_size=3)

    assert len(result) == 1
    assert result[0]["trade_time"] == "2026-04-24 14:30:00"
    assert result[0]["open"] == 20
    assert result[0]["close"] == 23


def test_derive_day_writes_derived_partition(tmp_path, monkeypatch):
    source = tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=30" / "trade_date=2026-04-24"
    source.mkdir(parents=True)
    (source / "part-000.parquet").write_text("fake", encoding="utf-8")

    monkeypatch.setattr(
        derived_module,
        "read_parquet_files",
        lambda paths: [
            _row("000001.SZ", "2026-04-24 09:30:00", 10, 11, 12, 9, 100, 1000),
            _row("000001.SZ", "2026-04-24 10:00:00", 11, 12, 13, 10, 200, 2000),
            _row("000001.SZ", "2026-04-24 10:30:00", 12, 13, 14, 11, 300, 3000),
        ],
    )
    monkeypatch.setattr(derived_module, "read_parquet_row_count", lambda path: 1)

    def fake_write(rows: list[dict[str, Any]], output_path: Path) -> int:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake", encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(derived_module, "write_rows_to_parquet", fake_write)

    summary = StkMinsDerivedService(lake_root=tmp_path, progress=lambda message: None).derive_day(
        trade_date=date(2026, 4, 24),
        targets=[90],
    )

    assert summary["written_rows"] == 1
    assert (tmp_path / "derived" / "stk_mins_by_date" / "freq=90" / "trade_date=2026-04-24" / "part-000.parquet").exists()


def _row(ts_code: str, trade_time: str, open_: float, close: float, high: float, low: float, vol: int, amount: float) -> dict[str, Any]:
    return {
        "ts_code": ts_code,
        "trade_time": trade_time,
        "open": open_,
        "close": close,
        "high": high,
        "low": low,
        "vol": vol,
        "amount": amount,
    }
