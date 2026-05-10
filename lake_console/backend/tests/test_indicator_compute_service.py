from __future__ import annotations

from datetime import datetime

import pytest

from lake_console.backend.app.cli.main import main
from lake_console.backend.app.services.indicators import MacdStateStore, StkMinsIndicatorComputeService
from lake_console.backend.app.services.parquet_writer import read_parquet_rows, write_rows_to_parquet


def test_compute_macd_full_writes_indicator_and_state(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-24",
        rows=[
            _source_row("600000.SH", "2026-04-24 10:00:00", 10.0),
            _source_row("600000.SH", "2026-04-24 10:30:00", 10.5),
            _source_row("000001.SZ", "2026-04-24 10:00:00", 8.0),
        ],
    )
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-27",
        rows=[_source_row("600000.SH", "2026-04-27 10:00:00", 10.8)],
    )

    summary = StkMinsIndicatorComputeService(lake_root=tmp_path, progress=lambda _: None).compute_macd(
        mode="full",
        ts_code="600000.SH",
        freq=30,
        start_date=datetime(2026, 4, 24).date(),
        end_date=datetime(2026, 4, 27).date(),
    )

    state = MacdStateStore(lake_root=tmp_path).get_state(ts_code="600000.SH", freq=30)
    first_partition_rows = read_parquet_rows(_indicator_partition(tmp_path, "2026-04-24") / "part-000.parquet")
    second_partition_rows = read_parquet_rows(_indicator_partition(tmp_path, "2026-04-27") / "part-000.parquet")
    assert summary["status"] == "success"
    assert summary["source_rows"] == 3
    assert summary["written_rows"] == 3
    assert summary["state_updates"] == 1
    assert [row["ts_code"] for row in first_partition_rows] == ["600000.SH", "600000.SH"]
    assert [row["ts_code"] for row in second_partition_rows] == ["600000.SH"]
    assert state is not None
    assert state.last_trade_time == datetime(2026, 4, 27, 10, 0)


def test_compute_macd_incremental_uses_existing_state(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-24",
        rows=[
            _source_row("600000.SH", "2026-04-24 10:00:00", 10.0),
            _source_row("600000.SH", "2026-04-24 10:30:00", 10.5),
        ],
    )
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-27",
        rows=[
            _source_row("600000.SH", "2026-04-27 10:00:00", 10.8),
            _source_row("600000.SH", "2026-04-27 10:30:00", 11.0),
        ],
    )
    service = StkMinsIndicatorComputeService(lake_root=tmp_path, progress=lambda _: None)
    service.compute_macd(
        mode="full",
        ts_code="600000.SH",
        freq=30,
        start_date=datetime(2026, 4, 24).date(),
        end_date=datetime(2026, 4, 24).date(),
    )

    summary = service.compute_macd(
        mode="incremental",
        ts_code="600000.SH",
        freq=30,
        start_date=datetime(2026, 4, 27).date(),
        end_date=datetime(2026, 4, 27).date(),
    )

    state = MacdStateStore(lake_root=tmp_path).get_state(ts_code="600000.SH", freq=30)
    second_partition_rows = read_parquet_rows(_indicator_partition(tmp_path, "2026-04-27") / "part-000.parquet")
    assert summary["source_rows"] == 2
    assert summary["indicator_rows"] == 2
    assert summary["written_rows"] == 2
    assert second_partition_rows[0]["macd_bar"] != 0.0
    assert state is not None
    assert state.last_trade_time == datetime(2026, 4, 27, 10, 30)


def test_compute_macd_incremental_requires_bootstrap(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-24",
        rows=[_source_row("600000.SH", "2026-04-24 10:00:00", 10.0)],
    )

    with pytest.raises(RuntimeError, match="needs_bootstrap"):
        StkMinsIndicatorComputeService(lake_root=tmp_path, progress=lambda _: None).compute_macd(
            mode="incremental",
            ts_code="600000.SH",
            freq=30,
            start_date=datetime(2026, 4, 24).date(),
            end_date=datetime(2026, 4, 24).date(),
        )


def test_compute_macd_full_rejects_state_regression(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-24",
        rows=[_source_row("600000.SH", "2026-04-24 10:00:00", 10.0)],
    )
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-27",
        rows=[_source_row("600000.SH", "2026-04-27 10:00:00", 10.5)],
    )
    service = StkMinsIndicatorComputeService(lake_root=tmp_path, progress=lambda _: None)
    service.compute_macd(
        mode="full",
        ts_code="600000.SH",
        freq=30,
        start_date=datetime(2026, 4, 24).date(),
        end_date=datetime(2026, 4, 27).date(),
    )

    with pytest.raises(RuntimeError, match="state_regression"):
        service.compute_macd(
            mode="full",
            ts_code="600000.SH",
            freq=30,
            start_date=datetime(2026, 4, 24).date(),
            end_date=datetime(2026, 4, 24).date(),
        )


def test_compute_stk_mins_indicator_cli_single_symbol(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-24",
        rows=[_source_row("600000.SH", "2026-04-24 10:00:00", 10.0)],
    )

    exit_code = main(
        [
            "compute-stk-mins-indicator",
            "--lake-root",
            str(tmp_path),
            "--indicator",
            "macd",
            "--mode",
            "full",
            "--ts-code",
            "600000.SH",
            "--freq",
            "30",
            "--start-date",
            "2026-04-24",
            "--end-date",
            "2026-04-24",
        ]
    )

    assert exit_code == 0
    assert MacdStateStore(lake_root=tmp_path).get_state(ts_code="600000.SH", freq=30) is not None
    assert (_indicator_partition(tmp_path, "2026-04-24") / "part-000.parquet").exists()


def test_compute_macd_all_market_full_reads_source_research(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_research_rows(
        tmp_path,
        trade_month="2026-04",
        bucket="00",
        rows=[
            _source_row("600000.SH", "2026-04-24 10:00:00", 10.0),
            _source_row("600000.SH", "2026-04-24 10:30:00", 10.5),
            _source_row("000001.SZ", "2026-04-24 10:00:00", 8.0),
            _source_row("000001.SZ", "2026-04-27 10:00:00", 8.3),
        ],
    )

    summary = StkMinsIndicatorComputeService(lake_root=tmp_path, progress=lambda _: None).compute_macd(
        mode="full",
        all_market=True,
        freq=30,
        start_date=datetime(2026, 4, 24).date(),
        end_date=datetime(2026, 4, 27).date(),
    )

    states = MacdStateStore(lake_root=tmp_path).load_states()
    first_partition_rows = read_parquet_rows(_indicator_partition(tmp_path, "2026-04-24") / "part-bucket-00.parquet")
    second_partition_rows = read_parquet_rows(_indicator_partition(tmp_path, "2026-04-27") / "part-bucket-00.parquet")
    assert summary["scope"] == "all_market"
    assert summary["source_rows"] == 4
    assert summary["written_rows"] == 4
    assert summary["processed_symbols"] == 2
    assert summary["state_updates"] == 2
    assert set(states) == {("600000.SH", 30), ("000001.SZ", 30)}
    assert sorted(row["ts_code"] for row in first_partition_rows) == ["000001.SZ", "600000.SH", "600000.SH"]
    assert [row["ts_code"] for row in second_partition_rows] == ["000001.SZ"]


def test_compute_macd_all_market_full_streams_by_month_and_keeps_state(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    progress_messages: list[str] = []
    _write_research_rows(
        tmp_path,
        trade_month="2026-04",
        bucket="00",
        rows=[
            _source_row("600000.SH", "2026-04-24 10:00:00", 10.0),
            _source_row("600000.SH", "2026-04-24 10:30:00", 10.5),
        ],
    )
    _write_research_rows(
        tmp_path,
        trade_month="2026-05",
        bucket="00",
        rows=[
            _source_row("600000.SH", "2026-05-06 10:00:00", 10.8),
            _source_row("600000.SH", "2026-05-06 10:30:00", 11.0),
        ],
    )

    summary = StkMinsIndicatorComputeService(lake_root=tmp_path, progress=progress_messages.append).compute_macd(
        mode="full",
        all_market=True,
        freq=30,
        start_date=datetime(2026, 4, 24).date(),
        end_date=datetime(2026, 5, 6).date(),
    )

    may_rows = read_parquet_rows(_indicator_partition(tmp_path, "2026-05-06") / "part-bucket-00.parquet")
    state = MacdStateStore(lake_root=tmp_path).get_state(ts_code="600000.SH", freq=30)
    assert summary["committed_months"] == ["2026-04", "2026-05"]
    assert summary["source_rows"] == 4
    assert summary["written_rows"] == 4
    assert may_rows[0]["macd_bar"] != 0.0
    assert state is not None
    assert state.last_trade_time == datetime(2026, 5, 6, 10, 30)
    assert any("month_start freq=30 month=2026-04" in message for message in progress_messages)
    assert any("batch=1/2 freq=30 month=2026-04 bucket=00" in message for message in progress_messages)
    assert any("checkpoint freq=30 month=2026-05" in message for message in progress_messages)


def test_compute_macd_all_market_full_rejects_state_regression(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_research_rows(
        tmp_path,
        trade_month="2026-04",
        bucket="00",
        rows=[_source_row("600000.SH", "2026-04-24 10:00:00", 10.0)],
    )
    _write_research_rows(
        tmp_path,
        trade_month="2026-05",
        bucket="00",
        rows=[_source_row("600000.SH", "2026-05-06 10:00:00", 10.8)],
    )
    service = StkMinsIndicatorComputeService(lake_root=tmp_path, progress=lambda _: None)
    service.compute_macd(
        mode="full",
        all_market=True,
        freq=30,
        start_date=datetime(2026, 4, 24).date(),
        end_date=datetime(2026, 5, 6).date(),
    )

    with pytest.raises(RuntimeError, match="state_regression"):
        service.compute_macd(
            mode="full",
            all_market=True,
            freq=30,
            start_date=datetime(2026, 4, 24).date(),
            end_date=datetime(2026, 4, 24).date(),
        )


def test_compute_macd_all_market_full_requires_source_research(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    with pytest.raises(RuntimeError, match="rebuild-stk-mins-research-range"):
        StkMinsIndicatorComputeService(lake_root=tmp_path, progress=lambda _: None).compute_macd(
            mode="full",
            all_market=True,
            freq=30,
            start_date=datetime(2026, 4, 24).date(),
            end_date=datetime(2026, 4, 27).date(),
        )


def test_compute_macd_all_market_incremental_requires_existing_states(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_universe(tmp_path, [_stock("600000.SH", "L", "19991110", None)])
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-24",
        rows=[_source_row("600000.SH", "2026-04-24 10:00:00", 10.0)],
    )

    with pytest.raises(RuntimeError, match="needs_bootstrap"):
        StkMinsIndicatorComputeService(lake_root=tmp_path, progress=lambda _: None).compute_macd(
            mode="incremental",
            all_market=True,
            freq=30,
            start_date=datetime(2026, 4, 24).date(),
            end_date=datetime(2026, 4, 24).date(),
        )


def test_compute_macd_all_market_incremental_streams_by_trade_date(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    progress_messages: list[str] = []
    service = StkMinsIndicatorComputeService(lake_root=tmp_path, progress=progress_messages.append)
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-24",
        rows=[
            _source_row("600000.SH", "2026-04-24 10:00:00", 10.0),
            _source_row("600000.SH", "2026-04-24 10:30:00", 10.5),
            _source_row("000001.SZ", "2026-04-24 10:00:00", 8.0),
            _source_row("000001.SZ", "2026-04-24 10:30:00", 8.2),
        ],
    )
    for ts_code in ("600000.SH", "000001.SZ"):
        service.compute_macd(
            mode="full",
            ts_code=ts_code,
            freq=30,
            start_date=datetime(2026, 4, 24).date(),
            end_date=datetime(2026, 4, 24).date(),
        )
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-27",
        rows=[
            _source_row("600000.SH", "2026-04-27 10:00:00", 10.8),
            _source_row("000001.SZ", "2026-04-27 10:00:00", 8.4),
        ],
    )
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-28",
        rows=[
            _source_row("600000.SH", "2026-04-28 10:00:00", 11.0),
            _source_row("000001.SZ", "2026-04-28 10:00:00", 8.6),
        ],
    )

    summary = service.compute_macd(
        mode="incremental",
        all_market=True,
        freq=30,
        start_date=datetime(2026, 4, 27).date(),
        end_date=datetime(2026, 4, 28).date(),
    )

    states = MacdStateStore(lake_root=tmp_path).load_states()
    first_day_rows = read_parquet_rows(_indicator_partition(tmp_path, "2026-04-27") / "part-000.parquet")
    second_day_rows = read_parquet_rows(_indicator_partition(tmp_path, "2026-04-28") / "part-000.parquet")
    assert summary["status"] == "success"
    assert summary["scope"] == "all_market"
    assert summary["mode"] == "incremental"
    assert summary["committed_trade_dates"] == ["2026-04-27", "2026-04-28"]
    assert summary["source_rows"] == 4
    assert summary["written_rows"] == 4
    assert summary["state_updates"] == 2
    assert sorted(row["ts_code"] for row in first_day_rows) == ["000001.SZ", "600000.SH"]
    assert sorted(row["ts_code"] for row in second_day_rows) == ["000001.SZ", "600000.SH"]
    assert states[("600000.SH", 30)].last_trade_time == datetime(2026, 4, 28, 10, 0)
    assert states[("000001.SZ", 30)].last_trade_time == datetime(2026, 4, 28, 10, 0)
    assert any("source_plan mode=incremental freq=30 trade_dates=2" in message for message in progress_messages)
    assert any("trade_date=1/2 freq=30 date=2026-04-27" in message for message in progress_messages)
    assert any("trade_date_done freq=30 date=2026-04-28 written=2" in message for message in progress_messages)


def test_compute_macd_all_market_incremental_bootstraps_new_security(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    progress_messages: list[str] = []
    service = StkMinsIndicatorComputeService(lake_root=tmp_path, progress=progress_messages.append)
    _write_universe(
        tmp_path,
        [
            _stock("600000.SH", "L", "19991110", None),
            _stock("301999.SZ", "L", "20260427", None),
        ],
    )
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-24",
        rows=[
            _source_row("600000.SH", "2026-04-24 10:00:00", 10.0),
            _source_row("600000.SH", "2026-04-24 10:30:00", 10.5),
        ],
    )
    service.compute_macd(
        mode="full",
        ts_code="600000.SH",
        freq=30,
        start_date=datetime(2026, 4, 24).date(),
        end_date=datetime(2026, 4, 24).date(),
    )
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-27",
        rows=[
            _source_row("600000.SH", "2026-04-27 10:00:00", 10.8),
            _source_row("301999.SZ", "2026-04-27 10:00:00", 20.0),
            _source_row("301999.SZ", "2026-04-27 10:30:00", 20.4),
        ],
    )

    summary = service.compute_macd(
        mode="incremental",
        all_market=True,
        freq=30,
        start_date=datetime(2026, 4, 27).date(),
        end_date=datetime(2026, 4, 27).date(),
    )

    states = MacdStateStore(lake_root=tmp_path).load_states()
    rows = read_parquet_rows(_indicator_partition(tmp_path, "2026-04-27") / "part-000.parquet")
    assert summary["status"] == "success"
    assert summary["bootstrap_symbols"] == 1
    assert states[("301999.SZ", 30)].last_trade_time == datetime(2026, 4, 27, 10, 30)
    assert sorted(row["ts_code"] for row in rows) == ["301999.SZ", "301999.SZ", "600000.SH"]
    assert any(
        "new_security_bootstrap freq=30 date=2026-04-27 count=1 preview=301999.SZ" in message
        for message in progress_messages
    )


def test_compute_macd_all_market_incremental_rejects_old_security_without_state(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_universe(
        tmp_path,
        [
            _stock("600000.SH", "L", "19991110", None),
            _stock("000001.SZ", "L", "19910403", None),
        ],
    )
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-24",
        rows=[_source_row("600000.SH", "2026-04-24 10:00:00", 10.0)],
    )
    service = StkMinsIndicatorComputeService(lake_root=tmp_path, progress=lambda _: None)
    service.compute_macd(
        mode="full",
        ts_code="600000.SH",
        freq=30,
        start_date=datetime(2026, 4, 24).date(),
        end_date=datetime(2026, 4, 24).date(),
    )
    _write_source_rows(
        tmp_path,
        trade_date="2026-04-27",
        rows=[
            _source_row("600000.SH", "2026-04-27 10:00:00", 10.8),
            _source_row("000001.SZ", "2026-04-27 10:00:00", 8.0),
        ],
    )

    with pytest.raises(RuntimeError, match="老股票缺少 MACD state"):
        service.compute_macd(
            mode="incremental",
            all_market=True,
            freq=30,
            start_date=datetime(2026, 4, 27).date(),
            end_date=datetime(2026, 4, 27).date(),
        )


def test_compute_stk_mins_indicator_cli_all_market(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_research_rows(
        tmp_path,
        trade_month="2026-04",
        bucket="00",
        rows=[_source_row("600000.SH", "2026-04-24 10:00:00", 10.0)],
    )

    exit_code = main(
        [
            "compute-stk-mins-indicator",
            "--lake-root",
            str(tmp_path),
            "--indicator",
            "macd",
            "--mode",
            "full",
            "--all-market",
            "--freq",
            "30",
            "--start-date",
            "2026-04-24",
            "--end-date",
            "2026-04-24",
        ]
    )

    assert exit_code == 0
    assert MacdStateStore(lake_root=tmp_path).get_state(ts_code="600000.SH", freq=30) is not None
    assert (_indicator_partition(tmp_path, "2026-04-24") / "part-bucket-00.parquet").exists()


def test_compute_stk_mins_indicator_range_cli_orchestrates_compute_and_research(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_research_rows(
        tmp_path,
        trade_month="2026-04",
        bucket="00",
        rows=[
            _source_row("600000.SH", "2026-04-24 10:00:00", 10.0),
            _source_row("600000.SH", "2026-04-27 10:00:00", 10.5),
        ],
    )

    exit_code = main(
        [
            "compute-stk-mins-indicator-range",
            "--lake-root",
            str(tmp_path),
            "--indicator",
            "macd",
            "--mode",
            "full",
            "--all-market",
            "--freqs",
            "30",
            "--start-date",
            "2026-04-24",
            "--end-date",
            "2026-04-27",
            "--bucket-count",
            "4",
        ]
    )

    assert exit_code == 0
    assert MacdStateStore(lake_root=tmp_path).get_state(ts_code="600000.SH", freq=30) is not None
    assert (_indicator_partition(tmp_path, "2026-04-24") / "part-bucket-00.parquet").exists()
    assert (
        tmp_path
        / "research"
        / "stk_mins_indicators_by_symbol_month"
        / "indicator=macd"
        / "params_key=12_26_9"
        / "freq=30"
        / "trade_month=2026-04"
    ).exists()


def _source_row(ts_code: str, trade_time: str, close: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": 30,
        "trade_time": datetime.fromisoformat(trade_time),
        "open": close,
        "close": close,
        "high": close,
        "low": close,
        "vol": 100,
        "amount": close * 100,
        "exchange": None,
        "vwap": close,
    }


def _write_source_rows(tmp_path, *, trade_date: str, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(
        rows,
        tmp_path / "raw_tushare" / "stk_mins_by_date" / "freq=30" / f"trade_date={trade_date}" / "part-000.parquet",
    )


def _write_research_rows(tmp_path, *, trade_month: str, bucket: str, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(
        rows,
        tmp_path
        / "research"
        / "stk_mins_by_symbol_month"
        / "freq=30"
        / f"trade_month={trade_month}"
        / f"bucket={bucket}"
        / "part-000.parquet",
    )


def _stock(ts_code: str, list_status: str, list_date: str, delist_date: str | None) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "list_status": list_status,
        "list_date": list_date,
        "delist_date": delist_date,
    }


def _write_universe(root, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(rows, root / "manifest" / "security_universe" / "tushare_stock_basic.parquet")


def _indicator_partition(tmp_path, trade_date: str):
    return (
        tmp_path
        / "derived"
        / "stk_mins_indicators_by_date"
        / "indicator=macd"
        / "params_key=12_26_9"
        / "freq=30"
        / f"trade_date={trade_date}"
    )
