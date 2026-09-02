from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from src.foundation.clients.local_lake.major_index_mins_contract import (  # noqa: E402
    MAJOR_INDEX_MINS_GOLD_CODES,
)
from src.foundation.clients.local_lake.major_index_turnover_reader import (  # noqa: E402
    MajorIndexTurnoverCodeScopeError,
    MajorIndexTurnoverLakeReader,
    MajorIndexTurnoverReadRequest,
    MajorIndexTurnoverRequestError,
    MajorIndexTurnoverSourceContractError,
)


def _times(trade_date: date) -> tuple[datetime, ...]:
    morning = datetime.combine(trade_date, time(9, 30))
    afternoon = datetime.combine(trade_date, time(13, 1))
    return tuple(morning + timedelta(minutes=index) for index in range(121)) + tuple(
        afternoon + timedelta(minutes=index) for index in range(120)
    )


def _write_partition(
    root: Path,
    *,
    trade_date: date,
    codes: tuple[str, ...] | None = None,
) -> Path:
    target = (
        root
        / "gold/quote/major_index_mins/freq=1"
        / f"trade_date={trade_date.isoformat()}"
        / "part-000.parquet"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (
            code,
            1,
            trade_date,
            trade_time,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            100_000_000.0,
            "SSE" if code.endswith(".SH") else "SZSE",
            1.0,
        )
        for code in (codes or tuple(sorted(MAJOR_INDEX_MINS_GOLD_CODES)))
        for trade_time in _times(trade_date)
    ]
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars (
              ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP,
              open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
              vol DOUBLE, amount DOUBLE, exchange VARCHAR, vwap DOUBLE
            )
            """
        )
        connection.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target


def test_reader_batches_explicit_partitions_and_returns_decimal_rows(
    tmp_path: Path,
) -> None:
    dates = (date(2026, 9, 1), date(2026, 8, 31))
    for trade_date in dates:
        _write_partition(tmp_path, trade_date=trade_date)

    result = MajorIndexTurnoverLakeReader(tmp_path).read(
        MajorIndexTurnoverReadRequest(trade_dates=dates)
    )

    assert result.available_trade_dates == dates
    assert result.missing_trade_dates == ()
    assert result.scanned_file_count == 2
    assert result.scanned_row_count == 2 * 10 * 241
    assert len(result.rows) == 2 * 10 * 241
    assert result.issues == ()
    assert result.rows[0].amount_yuan == Decimal("100000000.0")


def test_reader_keeps_valid_codes_and_reports_missing_code(
    tmp_path: Path,
) -> None:
    trade_date = date(2026, 9, 1)
    codes = tuple(sorted(MAJOR_INDEX_MINS_GOLD_CODES - {"000001.SH"}))
    _write_partition(tmp_path, trade_date=trade_date, codes=codes)

    result = MajorIndexTurnoverLakeReader(tmp_path).read(
        MajorIndexTurnoverReadRequest(trade_dates=(trade_date,))
    )

    assert len(result.rows) == 9 * 241
    assert [(issue.code, issue.ts_code) for issue in result.issues] == [
        ("ITI_SOURCE_NOT_READY", "000001.SH")
    ]


def test_reader_fails_closed_on_extra_code(tmp_path: Path) -> None:
    trade_date = date(2026, 9, 1)
    _write_partition(
        tmp_path,
        trade_date=trade_date,
        codes=(*tuple(sorted(MAJOR_INDEX_MINS_GOLD_CODES)), "932000.CSI"),
    )

    with pytest.raises(MajorIndexTurnoverCodeScopeError):
        MajorIndexTurnoverLakeReader(tmp_path).read(
            MajorIndexTurnoverReadRequest(trade_dates=(trade_date,))
        )


def test_reader_does_not_scan_missing_or_unrequested_dates(tmp_path: Path) -> None:
    requested = date(2026, 9, 1)
    missing = date(2026, 8, 31)
    _write_partition(tmp_path, trade_date=requested)
    _write_partition(tmp_path, trade_date=date(2026, 8, 28))

    result = MajorIndexTurnoverLakeReader(tmp_path).read(
        MajorIndexTurnoverReadRequest(trade_dates=(requested, missing))
    )

    assert result.available_trade_dates == (requested,)
    assert result.missing_trade_dates == (missing,)
    assert result.scanned_file_count == 1


def test_reader_uses_one_connection_and_one_batch_data_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trade_date = date(2026, 9, 1)
    _write_partition(tmp_path, trade_date=trade_date)
    original_connect = duckdb.connect
    counts = {"connections": 0, "data_queries": 0}

    class ConnectionProxy:
        def __init__(self) -> None:
            self._connection = original_connect(database=":memory:")

        def execute(self, sql, parameters=None):
            if "WITH source AS MATERIALIZED" in str(sql):
                counts["data_queries"] += 1
            return self._connection.execute(sql, parameters)

        def close(self) -> None:
            self._connection.close()

    def counting_connect(*_args, **_kwargs):
        counts["connections"] += 1
        return ConnectionProxy()

    monkeypatch.setattr(duckdb, "connect", counting_connect)
    result = MajorIndexTurnoverLakeReader(tmp_path).read(
        MajorIndexTurnoverReadRequest(trade_dates=(trade_date,))
    )

    assert result.scanned_file_count == 1
    assert counts == {"connections": 1, "data_queries": 1}


def test_reader_rejects_symlink_escape_and_forbidden_lake_roots(
    tmp_path: Path,
) -> None:
    trade_date = date(2026, 9, 1)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    source = _write_partition(outside, trade_date=trade_date)
    target = (
        tmp_path
        / "gold/quote/major_index_mins/freq=1"
        / f"trade_date={trade_date.isoformat()}"
        / "part-000.parquet"
    )
    target.parent.mkdir(parents=True)
    target.symlink_to(source)

    with pytest.raises(MajorIndexTurnoverSourceContractError):
        MajorIndexTurnoverLakeReader(tmp_path).read(
            MajorIndexTurnoverReadRequest(trade_dates=(trade_date,))
        )
    with pytest.raises(MajorIndexTurnoverSourceContractError):
        MajorIndexTurnoverLakeReader(
            Path("/Volumes/datasource/data_lake_staging")
        )


@pytest.mark.parametrize(
    "trade_dates",
    [(), (date(2026, 8, 31), date(2026, 9, 1)), (date(2026, 9, 1),) * 2],
)
def test_reader_rejects_unbounded_unsorted_or_duplicate_dates(
    tmp_path: Path, trade_dates: tuple[date, ...]
) -> None:
    with pytest.raises(MajorIndexTurnoverRequestError):
        MajorIndexTurnoverLakeReader(tmp_path).read(
            MajorIndexTurnoverReadRequest(trade_dates=trade_dates)
        )


def test_reader_rejects_more_than_24_explicit_dates(tmp_path: Path) -> None:
    trade_dates = tuple(
        date(2026, 9, 1) - timedelta(days=index) for index in range(25)
    )
    with pytest.raises(MajorIndexTurnoverRequestError):
        MajorIndexTurnoverLakeReader(tmp_path).read(
            MajorIndexTurnoverReadRequest(trade_dates=trade_dates)
        )
