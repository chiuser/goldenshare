from __future__ import annotations

from datetime import datetime

import pytest

from lake_console.backend.app.services.indicators import calculate_macd
from lake_console.backend.app.services.indicators.indicator_by_date_writer import IndicatorByDateWriter
from lake_console.backend.app.services.parquet_writer import read_parquet_rows, write_rows_to_parquet


def test_indicator_by_date_writer_replaces_partitions(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    old_partition = _partition(tmp_path, "2026-04-24")
    write_rows_to_parquet(
        [
            {
                "ts_code": "OLD.SH",
                "freq": 30,
                "trade_time": datetime(2026, 4, 24, 10, 0),
                "dif": 999.0,
                "dea": 999.0,
                "macd_bar": 999.0,
                "params_key": "12_26_9",
                "indicator_version": 1,
            }
        ],
        old_partition / "part-000.parquet",
    )
    rows = calculate_macd(
        [
            _bar("2026-04-24 10:00:00", 10.0),
            _bar("2026-04-24 10:30:00", 10.5),
            _bar("2026-04-27 10:00:00", 10.8),
        ]
    ).rows

    summary = IndicatorByDateWriter(lake_root=tmp_path).write_rows(
        rows,
        indicator="macd",
        params_key="12_26_9",
        freq=30,
        run_id="test-indicator-by-date",
    )

    assert summary["operation"] == "write_indicator_by_date"
    assert summary["input_rows"] == 3
    assert summary["written_rows"] == 3
    assert summary["partition_count"] == 2
    assert [partition["trade_date"] for partition in summary["partitions"]] == ["2026-04-24", "2026-04-27"]

    first_partition_rows = read_parquet_rows(_partition(tmp_path, "2026-04-24") / "part-000.parquet")
    second_partition_rows = read_parquet_rows(_partition(tmp_path, "2026-04-27") / "part-000.parquet")
    assert [row["ts_code"] for row in first_partition_rows] == ["600000.SH", "600000.SH"]
    assert first_partition_rows[0]["params_key"] == "12_26_9"
    assert first_partition_rows[0]["indicator_version"] == 1
    assert second_partition_rows[0]["trade_time"] == datetime(2026, 4, 27, 10, 0)
    assert not (tmp_path / "_tmp" / "test-indicator-by-date" / "derived").exists()


def test_indicator_by_date_writer_rejects_mismatched_freq(tmp_path) -> None:
    rows = calculate_macd([_bar("2026-04-24 10:00:00", 10.0, freq=60)]).rows

    with pytest.raises(ValueError, match="freq=60"):
        IndicatorByDateWriter(lake_root=tmp_path).write_rows(
            rows,
            indicator="macd",
            params_key="12_26_9",
            freq=30,
            run_id="test-invalid",
        )


def _bar(trade_time: str, close: float, *, freq: int = 30) -> dict[str, object]:
    return {
        "ts_code": "600000.SH",
        "freq": freq,
        "trade_time": datetime.fromisoformat(trade_time),
        "close": close,
    }


def _partition(root, trade_date: str):
    return (
        root
        / "derived"
        / "stk_mins_indicators_by_date"
        / "indicator=macd"
        / "params_key=12_26_9"
        / "freq=30"
        / f"trade_date={trade_date}"
    )
