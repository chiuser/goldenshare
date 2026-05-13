from __future__ import annotations

from datetime import date, datetime, time

import pytest

from lake_console.backend.app.cli.main import main
from lake_console.backend.app.services.index_mins_derived_service import IndexMinsDerivedService
from lake_console.backend.app.services.parquet_writer import read_parquet_rows, write_rows_to_parquet


def test_derive_index_mins_day_builds_90_and_120_from_formal_raw(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    trade_date = date(2025, 8, 1)
    _write_active_pool(
        tmp_path,
        [
            {"resource": "index_mins", "ts_code": "000001.SH"},
            {"resource": "index_mins", "ts_code": "000002.SH"},
        ],
    )
    _write_index_basic(
        tmp_path,
        [
            _index_basic("000001.SH", "20000101", None),
            _index_basic("000002.SH", "20250802", None),
        ],
    )
    _write_source_rows(
        tmp_path,
        freq="30min",
        trade_date=trade_date,
        rows=_build_day_rows("000001.SH", "30min", trade_date),
    )
    _write_source_rows(
        tmp_path,
        freq="60min",
        trade_date=trade_date,
        rows=_build_day_rows("000001.SH", "60min", trade_date),
    )

    summary = IndexMinsDerivedService(lake_root=tmp_path, progress=lambda _: None).derive_day(
        trade_date=trade_date,
        targets=["90min", "120min"],
    )

    rows_90 = _read_partition_rows(tmp_path, freq="90min", trade_date=trade_date)
    rows_120 = _read_partition_rows(tmp_path, freq="120min", trade_date=trade_date)

    assert summary["operation"] == "derive_index_mins"
    assert summary["source_node_key"] == "raw_tushare_by_date"
    assert summary["trade_date"] == "2025-08-01"
    assert summary["targets"] == ["90min", "120min"]
    assert summary["source_rows"] == 14
    assert summary["written_rows"] == 5

    assert [row["trade_time"] for row in rows_90] == [
        datetime(2025, 8, 1, 11, 0),
        datetime(2025, 8, 1, 14, 0),
        datetime(2025, 8, 1, 15, 0),
    ]
    assert [row["trade_time"] for row in rows_120] == [
        datetime(2025, 8, 1, 10, 30),
        datetime(2025, 8, 1, 14, 0),
    ]
    assert all(row["freq"] == "90min" for row in rows_90)
    assert all(row["freq"] == "120min" for row in rows_120)
    assert all(row["exchange"] == "SSE" for row in rows_90 + rows_120)


def test_derive_index_mins_day_overwrites_existing_partition(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    trade_date = date(2025, 8, 1)
    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(tmp_path, [_index_basic("000001.SH", "20000101", None)])
    _write_source_rows(
        tmp_path,
        freq="30min",
        trade_date=trade_date,
        rows=_build_day_rows("000001.SH", "30min", trade_date),
    )
    target_file = (
        tmp_path
        / "derived"
        / "index_mins_by_date"
        / "freq=90min"
        / "trade_date=2025-08-01"
        / "part-000.parquet"
    )
    write_rows_to_parquet(
        [
            {
                "ts_code": "000001.SH",
                "freq": "90min",
                "trade_time": datetime(2025, 8, 1, 11, 0),
                "open": 1.0,
                "close": 1.0,
                "high": 1.0,
                "low": 1.0,
                "vol": 1.0,
                "amount": 1.0,
                "exchange": "SSE",
                "vwap": 1.0,
            }
        ],
        target_file,
    )

    summary = IndexMinsDerivedService(lake_root=tmp_path, progress=lambda _: None).derive_day(
        trade_date=trade_date,
        targets=["90min"],
    )
    rows_90 = _read_partition_rows(tmp_path, freq="90min", trade_date=trade_date)

    assert summary["written_rows"] == 3
    assert len(rows_90) == 3
    assert rows_90[-1]["trade_time"] == datetime(2025, 8, 1, 15, 0)


def test_derive_index_mins_range_cli_prechecks_all_sources_before_write(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    _write_trade_cal(tmp_path, [date(2025, 8, 1), date(2025, 8, 4)])
    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(tmp_path, [_index_basic("000001.SH", "20000101", None)])
    _write_source_rows(
        tmp_path,
        freq="30min",
        trade_date=date(2025, 8, 1),
        rows=_build_day_rows("000001.SH", "30min", date(2025, 8, 1)),
    )

    with pytest.raises(RuntimeError, match="缺少正式 raw 源分区"):
        main(
            [
                "derive-index-mins-range",
                "--lake-root",
                str(tmp_path),
                "--start-date",
                "2025-08-01",
                "--end-date",
                "2025-08-04",
                "--targets",
                "90min",
            ]
        )

    assert not (
        tmp_path
        / "derived"
        / "index_mins_by_date"
        / "freq=90min"
        / "trade_date=2025-08-01"
    ).exists()


def test_derive_index_mins_day_rejects_source_row_count_mismatch(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    trade_date = date(2025, 8, 1)
    _write_active_pool(
        tmp_path,
        [
            {"resource": "index_mins", "ts_code": "000001.SH"},
            {"resource": "index_mins", "ts_code": "000002.SH"},
        ],
    )
    _write_index_basic(
        tmp_path,
        [
            _index_basic("000001.SH", "20000101", None),
            _index_basic("000002.SH", "20000101", None),
        ],
    )
    _write_source_rows(
        tmp_path,
        freq="60min",
        trade_date=trade_date,
        rows=_build_day_rows("000001.SH", "60min", trade_date),
    )

    with pytest.raises(RuntimeError, match="源分区行数不满足 completeness gate"):
        IndexMinsDerivedService(lake_root=tmp_path, progress=lambda _: None).derive_day(
            trade_date=trade_date,
            targets=["120min"],
        )


def _write_trade_cal(root, trade_dates: list[date]) -> None:
    rows = [{"cal_date": item.isoformat(), "is_open": True} for item in trade_dates]
    write_rows_to_parquet(rows, root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet")


def _write_active_pool(root, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(rows, root / "manifest" / "index_universe" / "index_mins_active_pool.parquet")


def _write_index_basic(root, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(rows, root / "manifest" / "index_universe" / "tushare_index_basic.parquet")


def _write_source_rows(root, *, freq: str, trade_date: date, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(
        rows,
        root / "raw_tushare" / "index_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}" / "part-000.parquet",
    )


def _read_partition_rows(root, *, freq: str, trade_date: date) -> list[dict[str, object]]:
    rows = read_parquet_rows(
        root / "derived" / "index_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}" / "part-000.parquet",
    )
    return sorted(rows, key=lambda item: item["trade_time"])


def _index_basic(ts_code: str, list_date: str, exp_date: str | None) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "name": ts_code,
        "market": "SSE",
        "publisher": "CSI",
        "category": "规模指数",
        "list_date": list_date,
        "exp_date": exp_date,
    }


def _build_day_rows(ts_code: str, freq: str, trade_date: date) -> list[dict[str, object]]:
    trade_times = _trade_times_for_freq(freq, trade_date)
    rows: list[dict[str, object]] = []
    for index, trade_time in enumerate(trade_times):
        open_ = round(100 + index * 0.1, 4)
        close = round(open_ + 0.02, 4)
        high = round(close + 0.01, 4)
        low = round(open_ - 0.01, 4)
        vol = float(1000 + index)
        amount = round(vol * (open_ + close) / 2, 3)
        rows.append(
            {
                "ts_code": ts_code,
                "freq": freq,
                "trade_time": trade_time,
                "open": open_,
                "close": close,
                "high": high,
                "low": low,
                "vol": vol,
                "amount": amount,
                "exchange": "SSE",
                "vwap": round(amount / vol, 3),
            }
        )
    return rows


def _trade_times_for_freq(freq: str, trade_date: date) -> list[datetime]:
    if freq == "30min":
        labels = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"]
        return [datetime.combine(trade_date, time.fromisoformat(item)) for item in labels]
    if freq == "60min":
        labels = ["09:30", "10:30", "11:30", "14:00", "15:00"]
        return [datetime.combine(trade_date, time.fromisoformat(item)) for item in labels]
    raise ValueError(f"unsupported freq={freq}")
