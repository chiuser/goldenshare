"""Isolated reads from the DG Silver index and calendar contracts."""

from datetime import date
from pathlib import Path

import pytest

from src.foundation.clients.local_lake.index_daily_reader import (
    IndexDailyLakeReader,
    IndexDailyLakeSourceError,
)

duckdb = pytest.importorskip("duckdb")


def _write_parquet(root: Path, relative: str, query: str, params: list | None = None) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(f"CREATE TABLE fixture AS {query}", params or [])
        connection.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(target)])


def test_factors_use_published_window_and_project_one_index(tmp_path):
    # DG idx_factor_pro Silver uses a DATE key and DOUBLE technical values.
    factors = "silver/index/index_factor_pro"
    start, missing, end = (date(2010, 1, day) for day in (4, 5, 6))
    for day, close in ((start, 100.0), (end, 101.0)):
        _write_parquet(
            tmp_path, f"{factors}/trade_date={day}/part-000.parquet",
            """
            SELECT ts_code, ?::DATE AS trade_date, close::DOUBLE AS close,
                   dif::DOUBLE AS macd_dif_bfq
            FROM (VALUES ('000001.SH', ?, -1.0), ('399001.SZ', 900.0, 10.0)) t(ts_code, close, dif)
            """,
            [day, close],
        )
    (tmp_path / factors / f"trade_date={missing}").mkdir()
    (tmp_path / factors / "trade_date=2009-12-31").mkdir()
    (tmp_path / factors / "trade_date=2009-12-31/part-000.parquet").write_bytes(b"outside requested window")

    reader = IndexDailyLakeReader(tmp_path)
    dates = reader.factor_dates(start=start, end=end)
    assert dates == (start, end)
    assert reader.factor_rows(
        ts_code="000001.SH", dates=dates, columns=("trade_date", "close", "macd_dif_bfq"), limit=3,
    ) == [
        {"trade_date": start, "close": 100.0, "macd_dif_bfq": -1.0},
        {"trade_date": end, "close": 101.0, "macd_dif_bfq": -1.0},
    ]
    assert reader.factor_rows(
        ts_code="399001.SZ", dates=dates, columns=("trade_date", "close"), limit=1, descending=True,
    ) == [{"trade_date": end, "close": 900.0}]


def test_sse_calendar_selects_recent_open_days_with_intervening_closed_days(tmp_path):
    # DG trade calendar Silver contains one DATE per natural day and exchange.
    _write_parquet(
        tmp_path, "silver/calendar/trade_calendar/full/part-000.parquet",
        """
        SELECT * FROM (VALUES
            ('SSE', DATE '2026-11-05', true, DATE '2026-11-04'),
            ('SSE', DATE '2026-11-06', true, DATE '2026-11-05'),
            ('SSE', DATE '2026-11-07', false, DATE '2026-11-06'),
            ('SSE', DATE '2026-11-08', false, DATE '2026-11-06'),
            ('SSE', DATE '2026-11-09', true, DATE '2026-11-06'),
            ('SZSE', DATE '2026-11-09', true, DATE '2026-11-06')
        ) t(exchange, trade_date, is_open, pretrade_date)
        """,
    )
    reader = IndexDailyLakeReader(tmp_path)
    friday, saturday, sunday, monday = (date(2026, 11, day) for day in (6, 7, 8, 9))
    expected = (
        (friday, True, date(2026, 11, 5)), (saturday, False, friday),
        (sunday, False, friday), (monday, True, friday),
    )
    assert reader.calendar_rows(end=monday, recent_open_days=2) == expected
    assert reader.calendar_rows(start=saturday, end=monday) == expected[1:]
    assert reader.calendar_rows(end=sunday, recent_open_days=1) == expected[:3]


def test_chart_reads_identity_and_checks_for_newer_daily_prices_of_that_index(tmp_path):
    # Identity and freshness only consume the specified fields of DG index_basic/index_daily Silver.
    _write_parquet(
        tmp_path, "silver/index_basic/full/part-000.parquet",
        "SELECT '000001.SH' AS ts_code, '上证指数' AS name, 'SSE' AS market, "
        "'上交所' AS publisher, '综合指数' AS category",
    )
    _write_parquet(
        tmp_path, "silver/index_daily/trade_date=2026-11-06/part-000.parquet",
        "SELECT '000001.SH' AS ts_code, DATE '2026-11-06' AS trade_date",
    )
    reader = IndexDailyLakeReader(tmp_path)
    assert reader.index_identity("000001.SH") == {
        "ts_code": "000001.SH", "name": "上证指数", "market": "SSE",
        "publisher": "上交所", "category": "综合指数",
    }
    assert reader.index_identity("399001.SZ") is None
    observed, newer = date(2026, 11, 5), date(2026, 11, 6)
    assert reader.has_daily_after(ts_code="000001.SH", after=observed, end=newer)
    assert not reader.has_daily_after(ts_code="399001.SZ", after=observed, end=newer)
    assert not reader.has_daily_after(ts_code="000001.SH", after=newer, end=date(2026, 11, 9))


def test_missing_reader_configuration_and_unreadable_source_are_errors(tmp_path):
    with pytest.raises(IndexDailyLakeSourceError, match="未配置"):
        IndexDailyLakeReader(None).calendar_rows(end=date(2026, 11, 6))
    with pytest.raises(IndexDailyLakeSourceError, match="无法读取"):
        IndexDailyLakeReader(tmp_path).index_identity("000001.SH")
