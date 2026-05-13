from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from lake_console.backend.app.cli.main import main
from lake_console.backend.app.services.index_mins_research_service import IndexMinsResearchService
from lake_console.backend.app.services.parquet_writer import read_parquet_rows, write_rows_to_parquet


@pytest.mark.parametrize("cli_mode", ("service", "cli"))
def test_index_mins_research_rebuild_month_uses_lifecycle_complete_gate(tmp_path, cli_mode: str) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    _write_trade_cal(tmp_path, trade_dates=[date(2025, 7, 10), date(2025, 7, 11)])
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
            _index_basic("000002.SH", "20250711", None),
        ],
    )
    _write_source_rows(tmp_path, freq="15min", trade_date=date(2025, 7, 10), rows=_build_day_rows("000001.SH", "15min", date(2025, 7, 10)))
    _write_source_rows(
        tmp_path,
        freq="15min",
        trade_date=date(2025, 7, 11),
        rows=_build_day_rows("000001.SH", "15min", date(2025, 7, 11)) + _build_day_rows("000002.SH", "15min", date(2025, 7, 11)),
    )

    if cli_mode == "service":
        summary = IndexMinsResearchService(lake_root=tmp_path, progress=lambda _: None).rebuild_month(
            freq="15min",
            trade_month="2025-07",
        )
    else:
        exit_code = main(
            [
                "rebuild-index-mins-research",
                "--lake-root",
                str(tmp_path),
                "--freq",
                "15min",
                "--trade-month",
                "2025-07",
            ]
        )
        assert exit_code == 0
        summary = _latest_summary(tmp_path, operation="research_index_mins")

    bucket_files = sorted(
        (
            tmp_path
            / "research"
            / "index_mins_by_symbol_month"
            / "freq=15min"
            / "trade_month=2025-07"
        ).glob("bucket=*/*.parquet")
    )
    rows = []
    for path in bucket_files:
        rows.extend(read_parquet_rows(path))

    assert summary["operation"] == "research_index_mins"
    assert summary["source_node_key"] == "raw_tushare_by_date"
    assert summary["freq"] == "15min"
    assert summary["trade_month"] == "2025-07"
    assert summary["bucket_count"] == 16
    assert summary["input_trade_dates"] == ["2025-07-10", "2025-07-11"]
    assert summary["source_rows"] == 51
    assert summary["written_rows"] == 51
    assert len(bucket_files) == 2
    assert sorted(row["ts_code"] for row in rows).count("000001.SH") == 34
    assert sorted(row["ts_code"] for row in rows).count("000002.SH") == 17


def test_index_mins_research_rebuild_month_rejects_missing_raw_partition(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    _write_trade_cal(tmp_path, trade_dates=[date(2025, 7, 10), date(2025, 7, 11)])
    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(tmp_path, [_index_basic("000001.SH", "20000101", None)])
    _write_source_rows(tmp_path, freq="30min", trade_date=date(2025, 7, 10), rows=_build_day_rows("000001.SH", "30min", date(2025, 7, 10)))

    with pytest.raises(RuntimeError, match="缺少正式 raw 分区"):
        IndexMinsResearchService(lake_root=tmp_path, progress=lambda _: None).rebuild_month(
            freq="30min",
            trade_month="2025-07",
        )


def test_index_mins_research_rebuild_month_rejects_row_count_mismatch(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    _write_trade_cal(tmp_path, trade_dates=[date(2025, 8, 1)])
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
        trade_date=date(2025, 8, 1),
        rows=_build_day_rows("000001.SH", "60min", date(2025, 8, 1)),
    )

    with pytest.raises(RuntimeError, match="行数不满足 completeness gate"):
        IndexMinsResearchService(lake_root=tmp_path, progress=lambda _: None).rebuild_month(
            freq="60min",
            trade_month="2025-08",
        )


def test_rebuild_index_mins_research_range_cli(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    _write_trade_cal(tmp_path, trade_dates=[date(2025, 7, 10)])
    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(tmp_path, [_index_basic("000001.SH", "20000101", None)])
    _write_source_rows(tmp_path, freq="5min", trade_date=date(2025, 7, 10), rows=_build_day_rows("000001.SH", "5min", date(2025, 7, 10)))

    exit_code = main(
        [
            "rebuild-index-mins-research-range",
            "--lake-root",
            str(tmp_path),
            "--start-month",
            "2025-07",
            "--end-month",
            "2025-07",
            "--freqs",
            "5min",
        ]
    )

    assert exit_code == 0
    assert (
        tmp_path
        / "research"
        / "index_mins_by_symbol_month"
        / "freq=5min"
        / "trade_month=2025-07"
    ).exists()


def _write_trade_cal(root, *, trade_dates: list[date]) -> None:
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
    if freq == "1min":
        times: list[datetime] = []
        current = datetime.combine(trade_date, time(9, 30))
        while current <= datetime.combine(trade_date, time(11, 30)):
            times.append(current)
            current += timedelta(minutes=1)
        current = datetime.combine(trade_date, time(13, 1))
        while current <= datetime.combine(trade_date, time(15, 0)):
            times.append(current)
            current += timedelta(minutes=1)
        return times
    if freq == "5min":
        labels = ["09:30", "09:35", "09:40", "09:45", "09:50", "09:55", "10:00", "10:05", "10:10", "10:15", "10:20", "10:25", "10:30", "10:35", "10:40", "10:45", "10:50", "10:55", "11:00", "11:05", "11:10", "11:15", "11:20", "11:25", "11:30", "13:05", "13:10", "13:15", "13:20", "13:25", "13:30", "13:35", "13:40", "13:45", "13:50", "13:55", "14:00", "14:05", "14:10", "14:15", "14:20", "14:25", "14:30", "14:35", "14:40", "14:45", "14:50", "14:55", "15:00"]
        return [datetime.combine(trade_date, time.fromisoformat(item)) for item in labels]
    if freq == "15min":
        labels = ["09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30", "13:15", "13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00"]
        return [datetime.combine(trade_date, time.fromisoformat(item)) for item in labels]
    if freq == "30min":
        labels = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"]
        return [datetime.combine(trade_date, time.fromisoformat(item)) for item in labels]
    if freq == "60min":
        labels = ["09:30", "10:30", "11:30", "14:00", "15:00"]
        return [datetime.combine(trade_date, time.fromisoformat(item)) for item in labels]
    raise ValueError(f"unsupported freq={freq}")


def _latest_summary(root, *, operation: str) -> dict[str, object]:
    manifest = root / "manifest" / "sync_runs.jsonl"
    lines = manifest.read_text(encoding="utf-8").strip().splitlines()
    for line in reversed(lines):
        import json

        payload = json.loads(line)
        if payload.get("operation") == operation:
            return payload
    raise AssertionError(f"missing operation={operation} summary")
