from __future__ import annotations

from datetime import date, datetime

import pytest

from lake_console.backend.app.services.parquet_writer import read_parquet_rows, write_rows_to_parquet
from lake_console.backend.app.services.stk_mins_clean_next_refresh_service import CleanNextRefreshService
from lake_console.backend.app.services.stk_mins_gap_repair_service import StkMinsGapRepairService


def test_repair_from_1m_builds_5m_partition_for_known_source_gap(tmp_path, monkeypatch) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    refresh_calls = _mock_clean_next_refresh(monkeypatch)

    trade_date = date(2010, 9, 2)
    _write_source_rows(
        tmp_path,
        trade_date=trade_date,
        rows=[
            _minute_row("000001.SZ", "2010-09-02 09:30:00", 10.0, 10.0, 10.0, 10.0, 10.0, 100.0, "SSE", 10.0),
            _minute_row("000001.SZ", "2010-09-02 09:31:00", 10.1, 10.2, 10.3, 10.0, 10.0, 102.0, "SSE", 10.2),
            _minute_row("000001.SZ", "2010-09-02 09:32:00", 10.2, 10.3, 10.4, 10.1, 10.0, 103.0, "SSE", 10.3),
            _minute_row("000001.SZ", "2010-09-02 09:33:00", 10.3, 10.4, 10.5, 10.2, 10.0, 104.0, "SSE", 10.4),
            _minute_row("000001.SZ", "2010-09-02 09:34:00", 10.4, 10.5, 10.6, 10.3, 10.0, 105.0, "SSE", 10.5),
            _minute_row("000001.SZ", "2010-09-02 09:35:00", 10.5, 10.6, 10.7, 10.4, 10.0, 106.0, "SSE", 10.6),
            _minute_row("000001.SZ", "2010-09-02 13:01:00", 11.0, 11.0, 11.0, 11.0, 0.0, 0.0, "SSE", 11.0),
            _minute_row("000001.SZ", "2010-09-02 13:02:00", 11.0, 11.0, 11.0, 11.0, 0.0, 0.0, "SSE", 11.0),
            _minute_row("000001.SZ", "2010-09-02 13:03:00", 11.0, 11.0, 11.0, 11.0, 0.0, 0.0, "SSE", 11.0),
            _minute_row("000001.SZ", "2010-09-02 13:04:00", 11.0, 11.0, 11.0, 11.0, 0.0, 0.0, "SSE", 11.0),
            _minute_row("000001.SZ", "2010-09-02 13:05:00", 11.0, 11.0, 11.0, 11.0, 0.0, 0.0, "SSE", 11.0),
        ],
    )

    summary = StkMinsGapRepairService(lake_root=tmp_path, progress=lambda _: None).repair_day(
        trade_date=trade_date,
        freq=5,
    )

    repaired_rows = sorted(
        _read_partition_rows(tmp_path, freq=5, trade_date=trade_date),
        key=lambda item: item["trade_time"],
    )

    assert summary["operation"] == "repair_stk_mins_from_1m"
    assert summary["repair_reason"] == "source_gap"
    assert summary["target_freq"] == 5
    assert summary["written_rows"] == 3
    assert summary["clean_next_refresh"]["status"] == "passed"
    assert len(refresh_calls) == 1
    affected_partition = refresh_calls[0][0]
    assert affected_partition.layer == "raw_tushare"
    assert affected_partition.partition_values == {"freq": "5", "trade_date": "2010-09-02"}
    assert affected_partition.partition_path == "raw_tushare/stk_mins_by_date/freq=5/trade_date=2010-09-02"

    assert [row["trade_time"] for row in repaired_rows] == [
        datetime(2010, 9, 2, 9, 30),
        datetime(2010, 9, 2, 9, 35),
        datetime(2010, 9, 2, 13, 5),
    ]
    assert repaired_rows[0]["freq"] == 5
    assert repaired_rows[0]["exchange"] == "SSE"
    assert repaired_rows[0]["open"] == 10.0
    assert repaired_rows[0]["close"] == 10.0
    assert repaired_rows[1]["open"] == 10.1
    assert repaired_rows[1]["close"] == 10.6
    assert repaired_rows[1]["high"] == 10.7
    assert repaired_rows[1]["low"] == 10.0
    assert repaired_rows[1]["vol"] == 50.0
    assert repaired_rows[1]["amount"] == 520.0
    assert repaired_rows[1]["vwap"] == 10.4
    assert repaired_rows[2]["vol"] == 0.0
    assert repaired_rows[2]["amount"] == 0.0
    assert repaired_rows[2]["vwap"] == 11.0


def test_repair_from_1m_builds_15m_partition_for_known_source_gap(tmp_path, monkeypatch) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _mock_clean_next_refresh(monkeypatch)

    trade_date = date(2009, 5, 5)
    rows = [
        _minute_row("000001.SZ", "2009-05-05 09:30:00", 8.0, 8.0, 8.0, 8.0, 1.0, 8.0, "SZSE", 8.0),
    ]
    for minute in range(31, 46):
        rows.append(
            _minute_row(
                "000001.SZ",
                f"2009-05-05 09:{minute:02d}:00",
                8.0 + (minute - 30) / 100,
                8.1 + (minute - 30) / 100,
                8.2 + (minute - 30) / 100,
                7.9 + (minute - 30) / 100,
                2.0,
                16.0 + (minute - 30),
                "SZSE",
                8.1 + (minute - 30) / 100,
            )
        )
    _write_source_rows(tmp_path, trade_date=trade_date, rows=rows)

    summary = StkMinsGapRepairService(lake_root=tmp_path, progress=lambda _: None).repair_day(
        trade_date=trade_date,
        freq=15,
    )
    repaired_rows = sorted(
        _read_partition_rows(tmp_path, freq=15, trade_date=trade_date),
        key=lambda item: item["trade_time"],
    )

    assert summary["written_rows"] == 2
    assert [row["trade_time"] for row in repaired_rows] == [
        datetime(2009, 5, 5, 9, 30),
        datetime(2009, 5, 5, 9, 45),
    ]
    assert repaired_rows[1]["freq"] == 15
    assert repaired_rows[1]["exchange"] == "SZSE"
    assert repaired_rows[1]["open"] == 8.01
    assert repaired_rows[1]["close"] == 8.25
    assert repaired_rows[1]["vol"] == 30.0
    assert repaired_rows[1]["vwap"] == round(sum(16.0 + (minute - 30) for minute in range(31, 46)) / 30.0, 3)


def test_repair_from_1m_rejects_non_gap_date(tmp_path) -> None:
    with pytest.raises(ValueError, match="不在 freq=5 的已审计源端缺口白名单内"):
        StkMinsGapRepairService(lake_root=tmp_path, progress=lambda _: None).repair_day(
            trade_date=date(2010, 9, 1),
            freq=5,
        )


def test_repair_from_1m_rejects_existing_target_partition(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    trade_date = date(2010, 9, 2)
    _write_source_rows(
        tmp_path,
        trade_date=trade_date,
        rows=[_minute_row("000001.SZ", "2010-09-02 09:30:00", 10.0, 10.0, 10.0, 10.0, 1.0, 10.0, "SSE", 10.0)],
    )
    target_partition = tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=5" / "trade_date=2010-09-02"
    write_rows_to_parquet(
        [
            {
                "ts_code": "000001.SZ",
                "freq": 5,
                "trade_time": datetime(2010, 9, 2, 9, 30),
                "open": 10.0,
                "close": 10.0,
                "high": 10.0,
                "low": 10.0,
                "vol": 1.0,
                "amount": 10.0,
                "exchange": "SSE",
                "vwap": 10.0,
            }
        ],
        target_partition / "part-00000.parquet",
    )

    with pytest.raises(RuntimeError, match="目标分区已存在"):
        StkMinsGapRepairService(lake_root=tmp_path, progress=lambda _: None).repair_day(
            trade_date=trade_date,
            freq=5,
        )


def test_repair_from_1m_merges_single_symbol_into_existing_partition(tmp_path, monkeypatch) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    refresh_calls = _mock_clean_next_refresh(monkeypatch)

    trade_date = date(2010, 9, 2)
    _write_source_rows(
        tmp_path,
        trade_date=trade_date,
        rows=[
            _minute_row("300114.SZ", "2010-09-02 09:30:00", 10.0, 10.0, 10.0, 10.0, 10.0, 100.0, "SZSE", 10.0),
            _minute_row("300114.SZ", "2010-09-02 09:31:00", 10.1, 10.2, 10.3, 10.0, 10.0, 102.0, "SZSE", 10.2),
            _minute_row("300114.SZ", "2010-09-02 09:32:00", 10.2, 10.3, 10.4, 10.1, 10.0, 103.0, "SZSE", 10.3),
            _minute_row("300114.SZ", "2010-09-02 09:33:00", 10.3, 10.4, 10.5, 10.2, 10.0, 104.0, "SZSE", 10.4),
            _minute_row("300114.SZ", "2010-09-02 09:34:00", 10.4, 10.5, 10.6, 10.3, 10.0, 105.0, "SZSE", 10.5),
            _minute_row("300114.SZ", "2010-09-02 09:35:00", 10.5, 10.6, 10.7, 10.4, 10.0, 106.0, "SZSE", 10.6),
        ],
    )
    target_partition = tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=5" / "trade_date=2010-09-02"
    write_rows_to_parquet(
        [
            {
                "ts_code": "000001.SZ",
                "freq": 5,
                "trade_time": datetime(2010, 9, 2, 9, 30),
                "open": 8.0,
                "close": 8.0,
                "high": 8.0,
                "low": 8.0,
                "vol": 1.0,
                "amount": 8.0,
                "exchange": "SZSE",
                "vwap": 8.0,
            }
        ],
        target_partition / "part-00000.parquet",
    )

    summary = StkMinsGapRepairService(lake_root=tmp_path, progress=lambda _: None).repair_day(
        trade_date=trade_date,
        freq=5,
        ts_code="300114.SZ",
    )
    repaired_rows = sorted(
        _read_partition_rows(tmp_path, freq=5, trade_date=trade_date),
        key=lambda item: (item["ts_code"], item["trade_time"]),
    )

    assert summary["scope"] == "single_symbol_merge"
    assert summary["ts_code"] == "300114.SZ"
    assert summary["existing_target_rows"] == 1
    assert summary["existing_target_symbol_rows"] == 0
    assert summary["repaired_symbol_rows"] == 2
    assert summary["written_rows"] == 3
    assert summary["clean_next_refresh"]["status"] == "passed"
    assert len(refresh_calls) == 1
    assert refresh_calls[0][0].partition_values == {"freq": "5", "trade_date": "2010-09-02"}
    assert [row["ts_code"] for row in repaired_rows] == ["000001.SZ", "300114.SZ", "300114.SZ"]
    assert [row["trade_time"] for row in repaired_rows if row["ts_code"] == "300114.SZ"] == [
        datetime(2010, 9, 2, 9, 30),
        datetime(2010, 9, 2, 9, 35),
    ]


def _minute_row(
    ts_code: str,
    trade_time: str,
    open_: float,
    close: float,
    high: float,
    low: float,
    vol: float,
    amount: float,
    exchange: str,
    vwap: float,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": 1,
        "trade_time": datetime.fromisoformat(trade_time),
        "open": open_,
        "close": close,
        "high": high,
        "low": low,
        "vol": vol,
        "amount": amount,
        "exchange": exchange,
        "vwap": vwap,
    }


def _write_source_rows(root, *, trade_date: date, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(
        rows,
        root / "raw_tushare" / "stk_mins_by_date" / "freq=1" / f"trade_date={trade_date.isoformat()}" / "part-00000.parquet",
    )


def _read_partition_rows(root, *, freq: int, trade_date: date) -> list[dict[str, object]]:
    return read_parquet_rows(
        root / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}" / "part-00000.parquet"
    )


def _mock_clean_next_refresh(monkeypatch) -> list[list[object]]:
    calls: list[list[object]] = []

    def fake_refresh(self, *, affected_partitions, dry_run: bool, apply: bool) -> dict[str, object]:
        del self
        assert dry_run is False
        assert apply is True
        calls.append(list(affected_partitions))
        return {
            "status": "passed",
            "affected_partitions": len(affected_partitions),
            "passed_partitions": len(affected_partitions),
            "failed_partitions": 0,
            "ledger_path": None,
            "gate_path": "manifest/stk_mins_quality/clean_next_gate_status.parquet",
        }

    monkeypatch.setattr(CleanNextRefreshService, "refresh", fake_refresh)
    return calls
