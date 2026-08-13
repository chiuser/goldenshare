from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from src.foundation.clients.local_lake.stock_mins_reader import (  # noqa: E402
    MinuteReadRequest,
    MinuteRequestError,
    MinuteSourceContractError,
    StockMinsLakeReader,
    build_stock_mins_qfq_paths,
)


BAR_COLUMNS = [
    "ts_code",
    "freq",
    "trade_date",
    "trade_time",
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
    "exchange",
]


def _write_bars(root: Path, *, code: str = "000638.SZ", freq: int = 5, year: int = 2026, rows: list[tuple] | None = None) -> Path:
    target = root / "gold" / "quote" / "stk_mins_qfq" / f"freq={freq}" / f"ts_code={code}" / f"year={year}" / "part-000.parquet"
    target.parent.mkdir(parents=True)
    rows = rows or [
        (code, freq, date(2026, 7, 31), "2026-07-31 09:35:00", 1.1, 1.3, 1.0, 1.2, 11.0, 110.0, "SZSE"),
        (code, freq, date(2026, 7, 31), "2026-07-31 09:40:00", 1.2, 1.4, 1.1, 1.3, 12.0, 120.0, "SZSE"),
        (code, freq, date(2026, 7, 31), "2026-07-31 09:45:00", 1.3, 1.5, 1.2, 1.4, 13.0, 130.0, "SZSE"),
        (code, freq, date(2026, 7, 31), "2026-07-31 09:50:00", 1.4, 1.6, 1.3, 1.5, 14.0, 140.0, "SZSE"),
    ]
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars (
                ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                vol DOUBLE, amount DOUBLE, exchange VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, CAST(? AS TIMESTAMP), ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target


def _write_invalid_bars(root: Path) -> Path:
    target = root / "gold" / "quote" / "stk_mins_qfq" / "freq=5" / "ts_code=000638.SZ" / "year=2026" / "part-000.parquet"
    target.parent.mkdir(parents=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("CREATE TABLE invalid (ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP)")
        connection.execute(
            "INSERT INTO invalid VALUES ('000638.SZ', 5, DATE '2026-07-31', TIMESTAMP '2026-07-31 09:30:00')"
        )
        connection.execute("COPY invalid TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target


def test_reader_uses_integer_frequency_path_and_explicit_projection(tmp_path: Path) -> None:
    target = _write_bars(tmp_path)
    reader = StockMinsLakeReader(tmp_path)

    page = reader.read_bars(MinuteReadRequest("000638.SZ", 5, date(2026, 7, 31), date(2026, 7, 31), 10, None))

    assert target.exists()
    assert page.count == 4
    assert page.scanned_file_count == 1
    assert set(page.rows[0]) == set(BAR_COLUMNS)
    assert all(row["freq"] == 5 for row in page.rows)
    assert page.observed_start_date == date(2026, 7, 31)
    assert page.observed_end_date == date(2026, 7, 31)
    assert not (tmp_path / "gold/quote/stk_mins_qfq/freq=5m").exists()


def test_reader_cursor_paginates_without_duplicates(tmp_path: Path) -> None:
    _write_bars(tmp_path)
    reader = StockMinsLakeReader(tmp_path)
    request = MinuteReadRequest("000638.SZ", 5, date(2026, 7, 31), date(2026, 7, 31), 2, None)

    first = reader.read_bars(request)
    second = reader.read_bars(replace(request, cursor=first.next_cursor))

    first_keys = {(row["trade_date"], row["trade_time"]) for row in first.rows}
    second_keys = {(row["trade_date"], row["trade_time"]) for row in second.rows}
    assert first.has_more is True
    assert first.next_cursor
    assert first_keys.isdisjoint(second_keys)
    assert max(second_keys) < min(first_keys)


def test_reader_rejects_cursor_bound_to_another_frequency(tmp_path: Path) -> None:
    _write_bars(tmp_path)
    reader = StockMinsLakeReader(tmp_path)
    request = MinuteReadRequest("000638.SZ", 5, date(2026, 7, 31), date(2026, 7, 31), 2, None)
    first = reader.read_bars(request)

    with pytest.raises(MinuteRequestError):
        reader.read_bars(replace(request, freq=15, cursor=first.next_cursor))


@pytest.mark.parametrize("invalid_time", ["2026-07-31 09:30:00", "2026-07-31 15:01:00"])
def test_reader_rejects_noncanonical_gold_times(
    tmp_path: Path,
    invalid_time: str,
) -> None:
    _write_bars(
        tmp_path,
        rows=[
            (
                "000638.SZ",
                5,
                date(2026, 7, 31),
                invalid_time,
                1.0,
                1.2,
                0.9,
                1.1,
                10.0,
                100.0,
                "SZSE",
            )
        ],
    )
    reader = StockMinsLakeReader(tmp_path)

    with pytest.raises(MinuteSourceContractError):
        reader.read_bars(
            MinuteReadRequest(
                "000638.SZ",
                5,
                date(2026, 7, 31),
                date(2026, 7, 31),
                10,
                None,
            )
        )


def test_reader_rejects_invalid_code_frequency_and_four_year_range(tmp_path: Path) -> None:
    _write_bars(tmp_path)
    reader = StockMinsLakeReader(tmp_path)

    with pytest.raises(MinuteRequestError):
        reader.read_bars(MinuteReadRequest("../../secret", 5, None, None, 10, None))
    with pytest.raises(MinuteRequestError):
        reader.read_bars(MinuteReadRequest("000638.SZ", 7, None, None, 10, None))
    with pytest.raises(MinuteRequestError):
        reader.read_bars(MinuteReadRequest("000638.SZ", 5, date(2023, 1, 1), date(2026, 1, 1), 10, None))


def test_reader_missing_file_returns_empty_without_scanning_other_data(tmp_path: Path) -> None:
    reader = StockMinsLakeReader(tmp_path)

    page = reader.read_bars(MinuteReadRequest("000638.SZ", 5, date(2026, 7, 31), date(2026, 7, 31), 10, None))

    assert page.rows == ()
    assert page.count == 0
    assert page.scanned_file_count == 0
    assert page.has_more is False


def test_reader_rejects_source_contract_before_business_query(tmp_path: Path) -> None:
    _write_invalid_bars(tmp_path)
    reader = StockMinsLakeReader(tmp_path)

    with pytest.raises(MinuteSourceContractError):
        reader.read_bars(MinuteReadRequest("000638.SZ", 5, date(2026, 7, 31), date(2026, 7, 31), 10, None))


def test_path_builder_rejects_unknown_dataset_and_does_not_create_paths(tmp_path: Path) -> None:
    with pytest.raises(MinuteRequestError):
        build_stock_mins_qfq_paths(tmp_path, "unknown", "000638.SZ", 5, [2026])  # type: ignore[arg-type]
    assert list(tmp_path.rglob("*.parquet")) == []
