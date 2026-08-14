from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from src.foundation.clients.local_lake import index_nine_turn_reader as reader_module
from src.foundation.clients.local_lake.index_nine_turn_reader import (
    IndexNineTurnLakeReader,
    IndexNineTurnReadRequest,
    IndexNineTurnRequestError,
    IndexNineTurnSourceContractError,
)


def _reader(monkeypatch: pytest.MonkeyPatch, root: Path) -> IndexNineTurnLakeReader:
    monkeypatch.setattr(reader_module, "FORMAL_LAKE_ROOT", root)
    return IndexNineTurnLakeReader(root)


def _request(**overrides) -> IndexNineTurnReadRequest:
    values = {
        "ts_code": "000001.SH",
        "freq": 5,
        "start_date": date(2026, 8, 11),
        "end_date": date(2026, 8, 12),
        "limit": 3,
        "cursor": None,
    }
    values.update(overrides)
    return IndexNineTurnReadRequest(**values)


def test_reader_aligns_gold_bar_window_and_uses_stable_cursor(
    tmp_path,
    monkeypatch,
) -> None:
    _write_bars(tmp_path, "2026-08-11")
    _write_bars(tmp_path, "2026-08-12")
    _write_nine_turn(
        tmp_path,
        "2026-08-11",
        [("10:00:00", 1, 0), ("10:05:00", 9, 0)],
    )
    _write_nine_turn(
        tmp_path,
        "2026-08-12",
        [("10:00:00", 10, 0), ("10:05:00", 0, 4)],
    )
    reader = _reader(monkeypatch, tmp_path)

    first = reader.read(_request())
    second = reader.read(_request(cursor=first.next_cursor))

    assert first.source_row_count == 3
    assert first.matched_row_count == 3
    assert first.has_more is True
    assert [row["up_count"] for row in first.rows] == [9, 10, 0]
    assert second.source_row_count == 1
    assert second.rows[0]["up_count"] == 1


def test_reader_returns_empty_for_bj_index_missing_from_gold_bars(
    tmp_path,
    monkeypatch,
) -> None:
    _write_bars(tmp_path, "2026-08-12")
    reader = _reader(monkeypatch, tmp_path)

    page = reader.read(_request(ts_code="899050.BJ", limit=500))

    assert page.source_row_count == 0
    assert page.matched_row_count == 0
    assert page.rows == ()
    assert page.scanned_file_count == 1


def test_reader_expands_older_partitions_when_supported_index_is_missing_recently(
    tmp_path,
    monkeypatch,
) -> None:
    _write_bars(tmp_path, "2026-08-10")
    _write_bars(tmp_path, "2026-08-11", ts_code="399001.SZ")
    _write_bars(tmp_path, "2026-08-12", ts_code="399001.SZ")
    _write_nine_turn(
        tmp_path,
        "2026-08-10",
        [("10:00:00", 2, 0), ("10:05:00", 3, 0)],
    )
    reader = _reader(monkeypatch, tmp_path)

    page = reader.read(_request(start_date=None, limit=1))

    assert page.source_row_count == 1
    assert page.matched_row_count == 1
    assert page.has_more is True
    assert page.observed_end_date == date(2026, 8, 10)


@pytest.mark.parametrize("freq", [1, 7])
def test_reader_rejects_unsupported_index_nine_turn_frequency(
    tmp_path,
    monkeypatch,
    freq,
) -> None:
    reader = _reader(monkeypatch, tmp_path)

    with pytest.raises(IndexNineTurnRequestError, match="5/15/30/60/90/120"):
        reader.read(_request(freq=freq))


def test_reader_rejects_partition_date_mismatch(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path, "2026-08-12")
    _write_nine_turn(
        tmp_path,
        "2026-08-12",
        [("10:00:00", 2, 0)],
        row_trade_date="2026-08-11",
    )
    reader = _reader(monkeypatch, tmp_path)

    with pytest.raises(IndexNineTurnSourceContractError, match="分区"):
        reader.read(_request())


def test_reader_reports_partial_alignment_without_dropping_bar_window(
    tmp_path,
    monkeypatch,
) -> None:
    _write_bars(tmp_path, "2026-08-11")
    _write_bars(tmp_path, "2026-08-12")
    _write_nine_turn(
        tmp_path,
        "2026-08-11",
        [("10:00:00", 2, 0), ("10:05:00", 3, 0)],
    )
    reader = _reader(monkeypatch, tmp_path)

    page = reader.read(_request())

    assert page.source_row_count == 3
    assert page.matched_row_count == 1
    assert page.missing_row_count == 2


def test_reader_rejects_cursor_bound_to_another_window(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path, "2026-08-11")
    _write_bars(tmp_path, "2026-08-12")
    _write_nine_turn(
        tmp_path,
        "2026-08-11",
        [("10:00:00", 2, 0), ("10:05:00", 3, 0)],
    )
    _write_nine_turn(
        tmp_path,
        "2026-08-12",
        [("10:00:00", 4, 0), ("10:05:00", 5, 0)],
    )
    reader = _reader(monkeypatch, tmp_path)
    first = reader.read(_request(limit=1))

    with pytest.raises(IndexNineTurnRequestError, match="endDate"):
        reader.read(
            _request(
                limit=1,
                end_date=date(2026, 8, 11),
                cursor=first.next_cursor,
            )
        )


def test_reader_rejects_duplicate_bar_time_key(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path, "2026-08-12", duplicate_time=True)
    reader = _reader(monkeypatch, tmp_path)

    with pytest.raises(IndexNineTurnSourceContractError, match="重复时间键"):
        reader.read(_request())


def test_reader_rejects_symlink_partition_file(tmp_path, monkeypatch) -> None:
    external_root = tmp_path / "external"
    _write_bars(external_root, "2026-08-12")
    source = (
        external_root
        / "gold/quote/major_index_mins/freq=5"
        / "trade_date=2026-08-12/part-000.parquet"
    )
    candidate = (
        tmp_path
        / "gold/quote/major_index_mins/freq=5"
        / "trade_date=2026-08-12/part-000.parquet"
    )
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.symlink_to(source)
    reader = _reader(monkeypatch, tmp_path)

    with pytest.raises(IndexNineTurnSourceContractError, match="符号链接"):
        reader.read(_request())


def test_reader_enforces_combined_partition_file_limit(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path, "2026-08-12")
    _write_nine_turn(
        tmp_path,
        "2026-08-12",
        [("10:00:00", 2, 0), ("10:05:00", 3, 0)],
    )
    monkeypatch.setattr(reader_module, "MAX_INDEX_NINE_TURN_PARTITION_FILES", 1)
    reader = _reader(monkeypatch, tmp_path)

    with pytest.raises(IndexNineTurnRequestError, match="5000"):
        reader.read(_request())


def test_reader_reuses_one_bounded_duckdb_connection(tmp_path, monkeypatch) -> None:
    _write_bars(tmp_path, "2026-08-12")
    _write_nine_turn(
        tmp_path,
        "2026-08-12",
        [("10:00:00", 2, 0), ("10:05:00", 3, 0)],
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
        reader.read(_request(limit=1))
        assert len(connections) == 1
    finally:
        reader.close()


def _write_bars(
    root: Path,
    partition_key: str,
    *,
    ts_code: str = "000001.SH",
    duplicate_time: bool = False,
) -> None:
    path = (
        root
        / "gold/quote/major_index_mins/freq=5"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    second_trade_time = "10:00:00" if duplicate_time else "10:05:00"
    try:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES
                ('{ts_code}', 5::INTEGER, DATE '{partition_key}',
                 TIMESTAMP '{partition_key} 10:00:00', 10.0::DOUBLE,
                 11.0::DOUBLE, 9.0::DOUBLE, 10.5::DOUBLE,
                 100.0::DOUBLE, 1050.0::DOUBLE, 'SSE'::VARCHAR, 10.5::DOUBLE),
                ('{ts_code}', 5::INTEGER, DATE '{partition_key}',
                 TIMESTAMP '{partition_key} {second_trade_time}', 10.5::DOUBLE,
                 12.0::DOUBLE, 10.0::DOUBLE, 11.0::DOUBLE,
                 120.0::DOUBLE, 1320.0::DOUBLE, 'SSE'::VARCHAR, 11.0::DOUBLE)
              ) AS source(
                ts_code, freq, trade_date, trade_time, open, high, low, close,
                vol, amount, exchange, vwap
              )
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
) -> None:
    path = (
        root
        / "gold/indicator/major_index_mins_nineturn/freq=5"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    effective_date = row_trade_date or partition_key
    values = ",".join(
        (
            f"('000001.SH', 5::INTEGER, DATE '{effective_date}', "
            f"TIMESTAMP '{effective_date} {trade_time}', 10.5::DOUBLE, "
            f"{up_count}::INTEGER, {down_count}::INTEGER, "
            f"{_signal(up_count, '+9')}::VARCHAR, "
            f"{_signal(down_count, '-9')}::VARCHAR)"
        )
        for trade_time, up_count, down_count in rows
    )
    connection = duckdb.connect()
    try:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES {values}) AS source(
                ts_code, freq, trade_date, trade_time, close,
                up_count, down_count, nine_up_turn, nine_down_turn
              )
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )
    finally:
        connection.close()


def _signal(count: int, value: str) -> str:
    return f"'{value}'" if count >= 9 else "NULL"
