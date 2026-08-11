from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from src.foundation.clients.local_lake.major_index_mins_reader import (  # noqa: E402
    IndexMinuteReadRequest,
    IndexMinuteRequestError,
    IndexMinuteSourceContractError,
    MajorIndexMinsLakeReader,
)


def _write_silver(
    root: Path,
    *,
    trade_date: date = date(2026, 8, 11),
    freq: int = 5,
    code: str = "000001.SH",
    rows: list[tuple] | None = None,
) -> Path:
    target = (
        root
        / "silver/quote/major_index_mins"
        / f"freq={freq}min"
        / f"trade_date={trade_date.isoformat()}"
        / "part-000.parquet"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = rows or [
        (code, f"{freq}min", f"{trade_date} 09:30:00", 10.0, 10.2, 10.3, 9.9, 100.0, 1000.0, "SSE", 10.1),
        (code, f"{freq}min", f"{trade_date} 09:35:00", 10.2, 10.4, 10.5, 10.1, 110.0, 1100.0, "SSE", 10.3),
        (code, f"{freq}min", f"{trade_date} 09:40:00", 10.4, 10.6, 10.7, 10.3, 120.0, 1200.0, "SSE", 10.5),
    ]
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars (
              ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
              open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
              vol DOUBLE, amount DOUBLE, exchange VARCHAR, vwap DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, CAST(? AS TIMESTAMP), ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target


def _write_gold(root: Path, *, trade_date: date = date(2026, 8, 11), freq: int = 5) -> Path:
    target = (
        root
        / "gold/indicator/major_index_mins_technical"
        / f"freq={freq}"
        / f"trade_date={trade_date.isoformat()}"
        / "part-000.parquet"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE indicators (
              ts_code VARCHAR, freq SMALLINT, trade_date DATE, trade_time TIMESTAMP,
              ma_5 DOUBLE, ma_10 DOUBLE, ma_20 DOUBLE, ma_30 DOUBLE,
              ma_60 DOUBLE, ma_90 DOUBLE, ma_250 DOUBLE,
              boll_mid DOUBLE, boll_upper DOUBLE, boll_lower DOUBLE,
              macd_dif DOUBLE, macd_dea DOUBLE, macd DOUBLE,
              kdj_k DOUBLE, kdj_d DOUBLE, kdj_j DOUBLE,
              observation_count INTEGER, params_key VARCHAR, indicator_version INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO indicators VALUES (
              '000001.SH', 5, DATE '2026-08-11', TIMESTAMP '2026-08-11 09:35:00',
              1, 2, 3, 4, 5, 6, NULL, 3, 4, 2, .1, .2, -.2,
              50, 45, 60, 120,
              'ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3', 1
            )
            """
        )
        connection.execute("COPY indicators TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target


def test_reader_reads_silver_schema_and_derives_partition_date(tmp_path: Path) -> None:
    _write_silver(tmp_path)
    page = MajorIndexMinsLakeReader(tmp_path).read_bars(
        IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None)
    )

    assert page.count == 3
    assert page.scanned_file_count == 1
    assert page.rows[0]["trade_date"] == date(2026, 8, 11)
    assert page.rows[0]["freq"] == 5
    assert set(page.rows[0]) == {
        "ts_code", "freq", "trade_date", "trade_time", "open", "high", "low", "close", "vol", "amount", "exchange"
    }


@pytest.mark.parametrize("freq", [1, 5, 15, 30, 60, 90, 120])
def test_reader_supports_all_frozen_frequencies(tmp_path: Path, freq: int) -> None:
    _write_silver(tmp_path, freq=freq)
    page = MajorIndexMinsLakeReader(tmp_path).read_bars(
        IndexMinuteReadRequest("000001.SH", freq, None, date(2026, 8, 11), 10, None)
    )

    assert page.count == 3
    assert {row["freq"] for row in page.rows} == {freq}


def test_reader_cursor_is_dataset_and_request_bound(tmp_path: Path) -> None:
    _write_silver(tmp_path)
    _write_gold(tmp_path)
    reader = MajorIndexMinsLakeReader(tmp_path)
    request = IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 2, None)

    first = reader.read_bars(request)
    second = reader.read_bars(replace(request, cursor=first.next_cursor))

    assert first.has_more is True
    assert first.next_cursor
    assert {row["trade_time"] for row in first.rows}.isdisjoint(
        {row["trade_time"] for row in second.rows}
    )
    with pytest.raises(IndexMinuteRequestError):
        reader.read_indicators(replace(request, cursor=first.next_cursor))


def test_reader_reads_gold_indicators_and_preserves_nulls(tmp_path: Path) -> None:
    _write_gold(tmp_path)
    page = MajorIndexMinsLakeReader(tmp_path).read_indicators(
        IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None)
    )

    assert page.count == 1
    assert page.rows[0]["ma_250"] is None
    assert page.rows[0]["observation_count"] == 120


def test_reader_rejects_partition_date_mismatch_and_duplicate_time_key(tmp_path: Path) -> None:
    mismatch = [
        ("000001.SH", "5min", "2026-08-10 09:30:00", 1, 1, 1, 1, 1, 1, "SSE", 1),
    ]
    _write_silver(tmp_path, rows=mismatch)
    reader = MajorIndexMinsLakeReader(tmp_path)
    with pytest.raises(IndexMinuteSourceContractError):
        reader.read_bars(IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None))

    duplicate_root = tmp_path / "duplicate"
    duplicate = [
        ("000001.SH", "5min", "2026-08-11 09:30:00", 1, 1, 1, 1, 1, 1, "SSE", 1),
        ("000001.SH", "5min", "2026-08-11 09:30:00", 1, 1, 1, 1, 1, 1, "SSE", 1),
    ]
    _write_silver(duplicate_root, rows=duplicate)
    with pytest.raises(IndexMinuteSourceContractError):
        MajorIndexMinsLakeReader(duplicate_root).read_bars(
            IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None)
        )


@pytest.mark.parametrize("invalid_value", [None, float("nan"), float("inf")])
def test_reader_rejects_null_or_non_finite_required_bar_values(
    tmp_path: Path,
    invalid_value: float | None,
) -> None:
    rows = [
        (
            "000001.SH", "5min", "2026-08-11 09:30:00",
            invalid_value, 10.2, 10.3, 9.9, 100.0, 1000.0, "SSE", 10.1,
        ),
    ]
    _write_silver(tmp_path, rows=rows)

    with pytest.raises(IndexMinuteSourceContractError):
        MajorIndexMinsLakeReader(tmp_path).read_bars(
            IndexMinuteReadRequest("000001.SH", 5, None, date(2026, 8, 11), 10, None)
        )


def test_reader_ignores_staging_and_rejects_symlink_escape(tmp_path: Path) -> None:
    staging = tmp_path / "silver/quote/major_index_mins/_staging/run/part-000.parquet"
    staging.parent.mkdir(parents=True)
    staging.write_bytes(b"not parquet")
    page = MajorIndexMinsLakeReader(tmp_path).read_bars(
        IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None)
    )
    assert page.rows == ()

    external = tmp_path.parent / f"{tmp_path.name}-external.parquet"
    external.write_bytes(b"external")
    try:
        link = tmp_path / "silver/quote/major_index_mins/freq=5min/trade_date=2026-08-11/part-000.parquet"
        link.parent.mkdir(parents=True)
        link.symlink_to(external)
        with pytest.raises(IndexMinuteSourceContractError):
            MajorIndexMinsLakeReader(tmp_path).read_bars(
                IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None)
            )
    finally:
        external.unlink(missing_ok=True)


def test_reader_rejects_symlink_even_when_target_stays_inside_lake(tmp_path: Path) -> None:
    target = tmp_path / "silver/quote/major_index_mins/internal.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"internal")
    link = tmp_path / "silver/quote/major_index_mins/freq=5min/trade_date=2026-08-11/part-000.parquet"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)

    with pytest.raises(IndexMinuteSourceContractError, match="符号链接"):
        MajorIndexMinsLakeReader(tmp_path).read_bars(
            IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None)
        )


def test_reader_rejects_invalid_schema_and_request(tmp_path: Path) -> None:
    target = tmp_path / "silver/quote/major_index_mins/freq=5min/trade_date=2026-08-11/part-000.parquet"
    target.parent.mkdir(parents=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("CREATE TABLE invalid (ts_code VARCHAR, freq VARCHAR)")
        connection.execute("INSERT INTO invalid VALUES ('000001.SH', '5min')")
        connection.execute("COPY invalid TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()

    reader = MajorIndexMinsLakeReader(tmp_path)
    with pytest.raises(IndexMinuteSourceContractError):
        reader.read_bars(IndexMinuteReadRequest("000001.SH", 5, None, None, 10, None))
    with pytest.raises(IndexMinuteRequestError):
        reader.read_bars(IndexMinuteReadRequest("../../secret", 5, None, None, 10, None))
    with pytest.raises(IndexMinuteRequestError):
        reader.read_bars(IndexMinuteReadRequest("000001.SH", 7, None, None, 10, None))
    with pytest.raises(IndexMinuteRequestError):
        reader.read_bars(IndexMinuteReadRequest("000001.SH", 5, date(2026, 8, 12), date(2026, 8, 11), 10, None))


def test_reader_rejects_queries_that_require_more_than_5000_partitions(tmp_path: Path) -> None:
    _write_silver(tmp_path, freq=120)

    with pytest.raises(IndexMinuteRequestError, match="5000"):
        MajorIndexMinsLakeReader(tmp_path).read_bars(
            IndexMinuteReadRequest("000001.SH", 120, None, None, 10_000, None)
        )
