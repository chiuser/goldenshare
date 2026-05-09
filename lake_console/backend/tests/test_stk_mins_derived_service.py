from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from lake_console.backend.app.services.indicators import IndicatorRecalcQueueService
from lake_console.backend.app.services.parquet_writer import write_rows_to_parquet
from lake_console.backend.app.services.stk_mins_derived_service import StkMinsDerivedService


def test_derive_day_records_indicator_recalc_queue_for_derived_partition(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    trade_date = date(2026, 4, 24)
    write_rows_to_parquet(
        [
            _bar("600000.SH", "2026-04-24 10:00:00", 10.0),
            _bar("600000.SH", "2026-04-24 10:30:00", 10.5),
            _bar("600000.SH", "2026-04-24 11:00:00", 10.8),
        ],
        tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=30" / "trade_date=2026-04-24" / "part-000.parquet",
    )

    summary = StkMinsDerivedService(lake_root=tmp_path, progress=lambda _: None).derive_day(
        trade_date=trade_date,
        targets=[90],
    )

    event_rows = [
        json.loads(line)
        for line in (tmp_path / "manifest" / "source_partition_events" / "stk_mins.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    queue_items = IndicatorRecalcQueueService(lake_root=tmp_path).list_items()
    assert summary["written_rows"] == 1
    assert event_rows[0]["layer"] == "derived"
    assert event_rows[0]["freq"] == 90
    assert queue_items[0]["freq_value"] == 90
    assert queue_items[0]["status"] == "pending"


def _bar(ts_code: str, trade_time: str, close: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": 30,
        "trade_time": datetime.fromisoformat(trade_time),
        "open": close,
        "close": close,
        "high": close,
        "low": close,
        "vol": 100.0,
        "amount": close * 100,
    }
