from __future__ import annotations

from datetime import datetime

import pytest

from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner
from lake_console.backend.app.services.parquet_writer import write_rows_to_parquet


def test_index_mins_scan_accepts_minute_suffix_freq_partition(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    write_rows_to_parquet(
        [
            {
                "ts_code": "000001.SH",
                "freq": "30min",
                "trade_time": datetime(2026, 1, 5, 9, 30),
                "open": 10.0,
                "close": 10.2,
                "high": 10.3,
                "low": 9.9,
                "vol": 1000.0,
                "amount": 10000.0,
                "exchange": "SSE",
                "vwap": 10.1,
            }
        ],
        tmp_path
        / "raw_tushare"
        / "index_mins_by_date"
        / "freq=30min"
        / "trade_date=2026-01-05"
        / "part-000.parquet",
    )

    summary = FilesystemScanner(tmp_path).list_datasets(dataset_key="index_mins")[0]
    partitions = FilesystemScanner(tmp_path).list_partitions(dataset_key="index_mins", node_key="raw_tushare_by_date", freq=30)

    assert summary.health_status == "ok"
    assert summary.file_count == 1
    assert summary.partition_count == 1
    assert summary.freqs == [30]
    assert summary.earliest_trade_date == "2026-01-05"
    assert summary.latest_trade_date == "2026-01-05"
    assert partitions[0].partition_values["freq"] == 30
    assert partitions[0].partition_values["trade_date"] == "2026-01-05"
