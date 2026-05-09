from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from lake_console.backend.app.services.index_mins_gap_repair_service import IndexMinsGapRepairService
from lake_console.backend.app.services.parquet_writer import read_parquet_rows, write_rows_to_parquet


@pytest.mark.parametrize(
    ("target_freq", "expected_times"),
    [
        (
            "15min",
            [
                "09:30",
                "09:45",
                "10:00",
                "10:15",
                "10:30",
                "10:45",
                "11:00",
                "11:15",
                "11:30",
                "13:15",
                "13:30",
                "13:45",
                "14:00",
                "14:15",
                "14:30",
                "14:45",
                "15:00",
            ],
        ),
        (
            "30min",
            [
                "09:30",
                "10:00",
                "10:30",
                "11:00",
                "11:30",
                "13:30",
                "14:00",
                "14:30",
                "15:00",
            ],
        ),
        (
            "60min",
            [
                "09:30",
                "10:30",
                "11:30",
                "14:00",
                "15:00",
            ],
        ),
    ],
)
def test_repair_index_mins_from_1m_builds_expected_partition(tmp_path, target_freq: str, expected_times: list[str]) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    trade_date = date(2025, 7, 11)
    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(tmp_path, [_index_basic("000001.SH", "20000101", None)])
    _write_source_rows(
        tmp_path,
        trade_date=trade_date,
        rows=_build_full_day_rows("000001.SH", trade_date, exchange="SSE"),
    )

    summary = IndexMinsGapRepairService(lake_root=tmp_path, progress=lambda _: None).repair_day(
        trade_date=trade_date,
        freq=target_freq,
    )
    repaired_rows = sorted(
        _read_partition_rows(tmp_path, freq=target_freq, trade_date=trade_date),
        key=lambda item: item["trade_time"],
    )

    assert summary["operation"] == "repair_index_mins_from_1m"
    assert summary["repair_reason"] == "source_gap"
    assert summary["target_freq"] == target_freq
    assert summary["effective_code_count"] == 1
    assert summary["written_rows"] == len(expected_times)
    assert [row["trade_time"].strftime("%H:%M") for row in repaired_rows] == expected_times

    first_row = repaired_rows[0]
    assert first_row["freq"] == target_freq
    assert first_row["exchange"] == "SSE"
    assert first_row["trade_time"] == datetime.combine(trade_date, time(9, 30))

    second_row = repaired_rows[1]
    source_rows = _build_full_day_rows("000001.SH", trade_date, exchange="SSE")
    expected_chunk = source_rows[1 : 1 + int(target_freq.replace("min", ""))]
    assert second_row["open"] == expected_chunk[0]["open"]
    assert second_row["close"] == expected_chunk[-1]["close"]
    assert second_row["high"] == max(row["high"] for row in expected_chunk)
    assert second_row["low"] == min(row["low"] for row in expected_chunk)
    assert second_row["vol"] == sum(row["vol"] for row in expected_chunk)
    assert second_row["amount"] == sum(row["amount"] for row in expected_chunk)
    assert second_row["vwap"] == round(second_row["amount"] / second_row["vol"], 3)


def test_repair_index_mins_from_1m_rejects_missing_effective_code_source_rows(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    trade_date = date(2025, 7, 11)
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
        trade_date=trade_date,
        rows=_build_full_day_rows("000001.SH", trade_date, exchange="SSE"),
    )

    with pytest.raises(RuntimeError, match="缺少有效指数的 1 分钟源行"):
        IndexMinsGapRepairService(lake_root=tmp_path, progress=lambda _: None).repair_day(
            trade_date=trade_date,
            freq="15min",
        )


def test_repair_index_mins_from_1m_rejects_existing_target_partition(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    trade_date = date(2025, 7, 25)
    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(tmp_path, [_index_basic("000001.SH", "20000101", None)])
    _write_source_rows(
        tmp_path,
        trade_date=trade_date,
        rows=_build_full_day_rows("000001.SH", trade_date, exchange="SSE"),
    )
    target_partition = tmp_path / "raw_tushare" / "index_mins_by_date" / "freq=60min" / f"trade_date={trade_date.isoformat()}"
    write_rows_to_parquet(
        [
            {
                "ts_code": "000001.SH",
                "freq": "60min",
                "trade_time": datetime.combine(trade_date, time(9, 30)),
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
        target_partition / "part-000.parquet",
    )

    with pytest.raises(RuntimeError, match="目标分区已存在"):
        IndexMinsGapRepairService(lake_root=tmp_path, progress=lambda _: None).repair_day(
            trade_date=trade_date,
            freq="60min",
        )


def _build_full_day_rows(ts_code: str, trade_date: date, *, exchange: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    price_seed = 100.0
    for index, trade_time in enumerate(_expected_schedule(trade_date)):
        open_ = round(price_seed + index * 0.01, 4)
        close = round(open_ + 0.005, 4)
        high = round(close + 0.003, 4)
        low = round(open_ - 0.003, 4)
        vol = float(1000 + index)
        amount = round(vol * (open_ + close) / 2, 3)
        vwap = round(amount / vol, 4)
        rows.append(
            {
                "ts_code": ts_code,
                "freq": "1min",
                "trade_time": trade_time,
                "open": open_,
                "close": close,
                "high": high,
                "low": low,
                "vol": vol,
                "amount": amount,
                "exchange": exchange,
                "vwap": vwap,
            }
        )
    return rows


def _expected_schedule(trade_date: date) -> list[datetime]:
    result: list[datetime] = []
    current = datetime.combine(trade_date, time(9, 30))
    while current <= datetime.combine(trade_date, time(11, 30)):
        result.append(current)
        current += timedelta(minutes=1)

    current = datetime.combine(trade_date, time(13, 1))
    while current <= datetime.combine(trade_date, time(15, 0)):
        result.append(current)
        current += timedelta(minutes=1)
    return result


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


def _write_active_pool(root, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(rows, root / "manifest" / "index_universe" / "index_mins_active_pool.parquet")


def _write_index_basic(root, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(rows, root / "manifest" / "index_universe" / "tushare_index_basic.parquet")


def _write_source_rows(root, *, trade_date: date, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(
        rows,
        root / "raw_tushare" / "index_mins_by_date" / "freq=1min" / f"trade_date={trade_date.isoformat()}" / "part-000.parquet",
    )


def _read_partition_rows(root, *, freq: str, trade_date: date) -> list[dict[str, object]]:
    return read_parquet_rows(
        root / "raw_tushare" / "index_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}" / "part-000.parquet"
    )
