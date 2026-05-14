from __future__ import annotations

from datetime import date, datetime

import pytest

from lake_console.backend.app.services.parquet_writer import read_parquet_rows, write_rows_to_parquet
from lake_console.backend.app.services.stk_mins_clean_next_gate_backfill_service import StkMinsCleanNextGateBackfillService


def test_backfill_clean_next_gate_writes_passed_status(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    _write_identity_map(tmp_path)
    trade_date = date(2026, 4, 24)
    _write_clean_next_partition(tmp_path, trade_date=trade_date)

    summary = StkMinsCleanNextGateBackfillService(lake_root=tmp_path, progress=lambda _: None).backfill(
        freqs=[30],
        start_date=trade_date,
        end_date=trade_date,
        dry_run=False,
        apply=True,
    )

    assert summary["operation"] == "backfill_stk_mins_clean_next_gate"
    assert summary["audited_partitions"] == 1
    assert summary["passed_partitions"] == 1
    assert summary["blocked_partitions"] == 0
    assert summary["issue_count"] == 0

    gate_rows = read_parquet_rows(tmp_path / "manifest" / "stk_mins_quality" / "clean_next_partition_gate.parquet")
    assert len(gate_rows) == 1
    assert gate_rows[0]["partition_key"] == "freq=30/trade_date=2026-04-24"
    assert gate_rows[0]["status"] == "passed"
    assert gate_rows[0]["clean_rows"] == 9


def _write_identity_map(root) -> None:
    write_rows_to_parquet(
        [
            {
                "latest_ts_code": "000001.SZ",
                "source_ts_code": "000001.SZ",
                "valid_from": date(2000, 1, 1),
                "valid_to": None,
                "effective_list_date": date(2000, 1, 1),
                "effective_delist_date": None,
                "identity_source": "test",
                "confidence": "confirmed",
                "reason": "test identity",
                "created_at": datetime(2026, 1, 1),
            }
        ],
        root / "manifest" / "security_identity" / "security_identity_map.parquet",
    )


def _write_clean_next_partition(root, *, trade_date: date) -> None:
    rows = []
    for hour, minute in [
        (9, 30),
        (10, 0),
        (10, 30),
        (11, 0),
        (11, 30),
        (13, 30),
        (14, 0),
        (14, 30),
        (15, 0),
    ]:
        rows.append(
            {
                "ts_code": "000001.SZ",
                "freq": 30,
                "trade_time": datetime(trade_date.year, trade_date.month, trade_date.day, hour, minute),
                "open": 10.0,
                "close": 10.1,
                "high": 10.2,
                "low": 9.9,
                "vol": 100,
                "amount": 1000.0,
                "exchange": "SZSE",
                "vwap": 10.0,
            }
        )
    write_rows_to_parquet(
        rows,
        root
        / "research"
        / "stk_mins_by_date_clean_next"
        / "freq=30"
        / f"trade_date={trade_date.isoformat()}"
        / "part-000.parquet",
    )
