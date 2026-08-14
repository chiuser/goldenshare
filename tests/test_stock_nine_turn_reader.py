from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from src.foundation.clients.local_lake import stock_nine_turn_reader as reader_module
from src.foundation.clients.local_lake.stock_nine_turn_reader import (
    StockNineTurnLakeReader,
    StockNineTurnReadRequest,
    StockNineTurnRequestError,
    StockNineTurnSourceContractError,
)


def _reader(monkeypatch: pytest.MonkeyPatch, root: Path) -> StockNineTurnLakeReader:
    monkeypatch.setattr(reader_module, "FORMAL_LAKE_ROOT", root)
    return StockNineTurnLakeReader(root)


def _request(**overrides) -> StockNineTurnReadRequest:
    values = {
        "ts_code": "000001.SZ",
        "freq": 30,
        "start_date": date(2026, 8, 11),
        "end_date": date(2026, 8, 12),
        "limit": 3,
        "cursor": None,
    }
    values.update(overrides)
    return StockNineTurnReadRequest(**values)


def test_reader_aligns_bar_window_and_uses_stable_cursor(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path)
    _write_nine_turn(tmp_path, "2026-08-11", [("10:00:00", 1, 0), ("10:30:00", 9, 0)])
    _write_nine_turn(tmp_path, "2026-08-12", [("10:00:00", 10, 0), ("10:30:00", 0, 4)])
    reader = _reader(monkeypatch, tmp_path)

    first = reader.read(_request())

    assert first.source_row_count == 3
    assert first.matched_row_count == 3
    assert first.missing_row_count == 0
    assert first.has_more is True
    assert first.next_cursor is not None
    assert [row["trade_time"].strftime("%Y-%m-%d %H:%M") for row in first.rows] == [
        "2026-08-11 10:30",
        "2026-08-12 10:00",
        "2026-08-12 10:30",
    ]
    assert [row["up_count"] for row in first.rows] == [9, 10, 0]

    second = reader.read(_request(cursor=first.next_cursor))

    assert second.source_row_count == 1
    assert second.has_more is False
    assert second.rows[0]["up_count"] == 1


def test_reader_reports_partial_when_one_bar_partition_has_no_nine_turn(
    tmp_path,
    monkeypatch,
) -> None:
    _write_bars(tmp_path)
    _write_nine_turn(tmp_path, "2026-08-12", [("10:00:00", 10, 0), ("10:30:00", 0, 4)])
    reader = _reader(monkeypatch, tmp_path)

    page = reader.read(_request(limit=4))

    assert page.source_row_count == 4
    assert page.matched_row_count == 2
    assert page.missing_row_count == 2
    assert page.scanned_file_count == 2


@pytest.mark.parametrize("freq", [1, 5, 15, 7])
def test_reader_rejects_unsupported_stock_nine_turn_frequencies(
    tmp_path,
    monkeypatch,
    freq,
) -> None:
    reader = _reader(monkeypatch, tmp_path)

    with pytest.raises(StockNineTurnRequestError, match="30/60/90/120"):
        reader.read(_request(freq=freq))


def test_reader_rejects_cursor_bound_to_another_frequency(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path)
    _write_nine_turn(tmp_path, "2026-08-11", [("10:00:00", 1, 0), ("10:30:00", 9, 0)])
    _write_nine_turn(tmp_path, "2026-08-12", [("10:00:00", 10, 0), ("10:30:00", 0, 4)])
    reader = _reader(monkeypatch, tmp_path)
    first = reader.read(_request(limit=1))

    with pytest.raises(StockNineTurnRequestError, match="freq"):
        reader.read(_request(freq=60, limit=1, cursor=first.next_cursor))


def test_reader_rejects_nine_turn_partition_date_mismatch(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path)
    _write_nine_turn(
        tmp_path,
        "2026-08-12",
        [("10:00:00", 10, 0)],
        row_trade_date="2026-08-11",
    )
    reader = _reader(monkeypatch, tmp_path)

    with pytest.raises(StockNineTurnSourceContractError, match="分区"):
        reader.read(_request())


def test_reader_rejects_duplicate_nine_turn_time_key(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path)
    _write_nine_turn(
        tmp_path,
        "2026-08-12",
        [("10:00:00", 2, 0), ("10:00:00", 3, 0)],
    )
    reader = _reader(monkeypatch, tmp_path)

    with pytest.raises(StockNineTurnSourceContractError, match="重复时间键"):
        reader.read(_request())


def test_reader_validates_only_the_requested_stock_rows(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path)
    _write_nine_turn(
        tmp_path,
        "2026-08-12",
        [("10:00:00", 2, 0), ("10:30:00", 3, 0)],
        extra_rows=[("000002.SZ", "10:00:00", 1, 1)],
    )
    reader = _reader(monkeypatch, tmp_path)

    page = reader.read(_request())

    assert page.matched_row_count == 2
    assert [row["up_count"] for row in page.rows[-2:]] == [2, 3]


def test_reader_reuses_one_bounded_duckdb_connection(
    tmp_path,
    monkeypatch,
) -> None:
    _write_bars(tmp_path)
    _write_nine_turn(
        tmp_path,
        "2026-08-11",
        [("10:00:00", 1, 0), ("10:30:00", 9, 0)],
    )
    _write_nine_turn(
        tmp_path,
        "2026-08-12",
        [("10:00:00", 10, 0), ("10:30:00", 0, 4)],
    )
    original_connect = duckdb.connect
    connections = []

    def counting_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(duckdb, "connect", counting_connect)
    reader = _reader(monkeypatch, tmp_path)
    try:
        reader.read(_request())
        reader.read(_request(limit=2))
        assert len(connections) == 1

        reader.close()
        reader.read(_request(limit=1))
        assert len(connections) == 2
    finally:
        reader.close()


def test_reader_rejects_symlinked_bar_file(tmp_path, monkeypatch) -> None:
    external = tmp_path / "external.parquet"
    _write_bar_file(external)
    target = (
        tmp_path
        / "gold/quote/stk_mins_qfq/freq=30/ts_code=000001.SZ/year=2026/part-000.parquet"
    )
    target.parent.mkdir(parents=True)
    target.symlink_to(external)
    reader = _reader(monkeypatch, tmp_path)

    with pytest.raises(StockNineTurnSourceContractError, match="符号链接"):
        reader.read(_request())


def test_reader_refuses_non_formal_root(tmp_path) -> None:
    with pytest.raises(StockNineTurnRequestError, match="只允许正式"):
        StockNineTurnLakeReader(tmp_path)


def _write_bars(root: Path) -> None:
    path = (
        root
        / "gold/quote/stk_mins_qfq/freq=30/ts_code=000001.SZ/year=2026/part-000.parquet"
    )
    _write_bar_file(path)


def _write_bar_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    try:
        connection.execute(
            """
            COPY (
              SELECT * FROM (VALUES
                ('000001.SZ', 30::INTEGER, DATE '2026-08-11', TIMESTAMP '2026-08-11 10:00:00'),
                ('000001.SZ', 30::INTEGER, DATE '2026-08-11', TIMESTAMP '2026-08-11 10:30:00'),
                ('000001.SZ', 30::INTEGER, DATE '2026-08-12', TIMESTAMP '2026-08-12 10:00:00'),
                ('000001.SZ', 30::INTEGER, DATE '2026-08-12', TIMESTAMP '2026-08-12 10:30:00')
              ) AS source(ts_code, freq, trade_date, trade_time)
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )
    finally:
        connection.close()


def _write_nine_turn(
    root: Path,
    partition_key: str,
    rows: list[tuple[str, int, int]],
    *,
    row_trade_date: str | None = None,
    extra_rows: list[tuple[str, str, int, int]] | None = None,
) -> None:
    path = (
        root
        / "gold/indicator/stk_mins_qfq_nineturn"
        / "freq=30"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    effective_date = row_trade_date or partition_key
    values = [
        (
            f"('000001.SZ', 30::INTEGER, DATE '{effective_date}', "
            f"TIMESTAMP '{effective_date} {trade_time}', 10.0::DOUBLE, "
            f"{up_count}::INTEGER, {down_count}::INTEGER, "
            f"{_signal(up_count, '+9')}::VARCHAR, {_signal(down_count, '-9')}::VARCHAR)"
        )
        for trade_time, up_count, down_count in rows
    ]
    values.extend(
        (
            f"('{ts_code}', 30::INTEGER, DATE '{effective_date}', "
            f"TIMESTAMP '{effective_date} {trade_time}', 10.0::DOUBLE, "
            f"{up_count}::INTEGER, {down_count}::INTEGER, "
            f"{_signal(up_count, '+9')}::VARCHAR, "
            f"{_signal(down_count, '-9')}::VARCHAR)"
        )
        for ts_code, trade_time, up_count, down_count in (extra_rows or [])
    )
    connection = duckdb.connect()
    try:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES {','.join(values)}) AS source(
                ts_code, freq, trade_date, trade_time, close_qfq,
                up_count, down_count, nine_up_turn, nine_down_turn
              )
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )
    finally:
        connection.close()


def _signal(count: int, signal: str) -> str:
    return f"'{signal}'" if count >= 9 else "NULL"
