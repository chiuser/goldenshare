from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from src.foundation.clients.local_lake.stock_daily_trend_channel_reader import (
    StockDailyTrendChannelLakeReader,
    StockDailyTrendChannelReadRequest,
    StockDailyTrendChannelSourceNotReadyError,
)
from src.foundation.clients.local_lake import stock_daily_trend_channel_reader


def _write_partition(
    root: Path,
    *,
    trade_date: str,
    formula_version: str = "stock-daily-trend-channel-v1",
    duplicate: bool = False,
) -> Path:
    target = (
        root
        / "gold/indicator/stock_daily_trend_channel"
        / f"trade_date={trade_date}"
        / "part-000.parquet"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (
            "000001.SZ",
            trade_date,
            10.0,
            11.0,
            9.0,
            10.5,
            12.0,
            9.5,
            "INSIDE",
            "UP",
            13.0,
            8.5,
            "INSIDE",
            "DOWN",
            "UP_DOWN",
            formula_version,
        ),
        (
            "600000.SH",
            trade_date,
            8.0,
            9.0,
            7.0,
            8.5,
            10.0,
            7.5,
            "INSIDE",
            "UP",
            11.0,
            6.5,
            "INSIDE",
            "UP",
            "UP_UP",
            formula_version,
        ),
    ]
    if duplicate:
        rows.append(rows[0])
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE result (
              ts_code VARCHAR, trade_date DATE,
              open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
              short_upper DOUBLE, short_lower DOUBLE,
              short_position VARCHAR, short_state VARCHAR,
              long_upper DOUBLE, long_lower DOUBLE,
              long_position VARCHAR, long_state VARCHAR,
              combined_state VARCHAR, formula_version VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO result VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute("COPY result TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target


def _reader(root: Path, monkeypatch: pytest.MonkeyPatch) -> StockDailyTrendChannelLakeReader:
    monkeypatch.setattr(
        "src.foundation.clients.local_lake.stock_daily_trend_channel_reader.FORMAL_LAKE_ROOT",
        root,
    )
    return StockDailyTrendChannelLakeReader(root)


def test_reader_selects_bounded_partitions_and_returns_strict_ascending_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for trade_date in ("2026-08-25", "2026-08-26", "2026-08-27"):
        _write_partition(tmp_path, trade_date=trade_date)
    result = _reader(tmp_path, monkeypatch).read(
        StockDailyTrendChannelReadRequest(
            ts_code="000001.sz",
            end_date=date(2026, 8, 26),
            limit=2,
        )
    )

    assert [row["trade_date"] for row in result.rows] == [
        date(2026, 8, 25),
        date(2026, 8, 26),
    ]
    assert {row["ts_code"] for row in result.rows} == {"000001.SZ"}
    assert result.scanned_file_count == 2


@pytest.mark.parametrize("failure", ["formula", "duplicate"])
def test_reader_fails_closed_on_contract_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    _write_partition(
        tmp_path,
        trade_date="2026-08-27",
        formula_version=("old-version" if failure == "formula" else "stock-daily-trend-channel-v1"),
        duplicate=failure == "duplicate",
    )
    reader = _reader(tmp_path, monkeypatch)

    with pytest.raises(StockDailyTrendChannelSourceNotReadyError):
        reader.read(
            StockDailyTrendChannelReadRequest(
                ts_code="000001.SZ",
                end_date=date(2026, 8, 27),
                limit=1,
            )
        )


def test_reader_maps_missing_source_file_to_source_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_partition(tmp_path, trade_date="2026-08-27")
    monkeypatch.setattr(
        stock_daily_trend_channel_reader,
        "_query_rows",
        lambda _connection, _paths, _request: [
            {
                "ts_code": "000001.SZ",
                "trade_date": date(2026, 8, 27),
            }
        ],
    )

    with pytest.raises(
        StockDailyTrendChannelSourceNotReadyError,
        match="缺少来源文件",
    ):
        _reader(tmp_path, monkeypatch).read(
            StockDailyTrendChannelReadRequest(
                ts_code="000001.SZ",
                end_date=date(2026, 8, 27),
                limit=1,
            )
        )
