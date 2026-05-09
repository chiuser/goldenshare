from __future__ import annotations

from datetime import date, datetime

import pytest

from lake_console.backend.app.catalog.datasets import get_dataset_definition
from lake_console.backend.app.services.parquet_writer import read_parquet_rows, write_rows_to_parquet
from lake_console.backend.app.services.prod_raw_db import build_prod_raw_index_mins_range_query
from lake_console.backend.app.services.prod_raw_index_mins_export_service import ProdRawIndexMinsExportService
from lake_console.backend.app.services.tushare_index_mins_sync_service import TushareIndexMinsSyncService
from lake_console.backend.app.sync.planners.index_mins import build_index_mins_plan


def test_build_index_mins_plan_uses_dual_source_request_model(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_calendar(tmp_path, [date(2026, 1, 5), date(2026, 1, 6)])
    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(tmp_path, [_index_basic("000001.SH", "20000101", None)])
    definition = get_dataset_definition("index_mins")

    tushare_plan = build_index_mins_plan(
        definition,
        lake_root=tmp_path,
        source="tushare",
        trade_date=None,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        ts_code=None,
        freqs=["1min", "30min"],
    )
    prod_raw_plan = build_index_mins_plan(
        definition,
        lake_root=tmp_path,
        source="prod-raw-db",
        trade_date=None,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        ts_code=None,
        freqs=["1min", "30min"],
    )

    assert tushare_plan.request_count == 2
    assert prod_raw_plan.request_count == 2
    assert tushare_plan.required_manifests == (
        "manifest/index_universe/index_mins_active_pool.parquet",
        "manifest/index_universe/tushare_index_basic.parquet",
        "manifest/trading_calendar/tushare_trade_cal.parquet",
    )


def test_tushare_index_mins_sync_filters_by_lifecycle_and_writes_partition(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_calendar(tmp_path, [date(2026, 1, 5)])
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
            _index_basic("000002.SH", "20260110", None),
        ],
    )
    client = _FakeIndexMinsClient()

    summary = TushareIndexMinsSyncService(
        lake_root=tmp_path,
        client=client,
        progress=lambda _: None,
    ).sync(
        trade_date=date(2026, 1, 5),
        freqs=["30min"],
    )

    rows = read_parquet_rows(
        tmp_path / "raw_tushare" / "index_mins_by_date" / "freq=30min" / "trade_date=2026-01-05" / "part-000.parquet"
    )
    assert [call["ts_code"] for call in client.calls] == ["000001.SH"]
    assert summary["request_count"] == 1
    assert summary["written_rows"] == 1
    assert rows[0]["ts_code"] == "000001.SH"
    assert rows[0]["freq"] == "30min"


def test_prod_raw_index_mins_export_uses_whitelist_query_and_writes_partition(tmp_path, monkeypatch) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_calendar(tmp_path, [date(2026, 1, 5)])
    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(tmp_path, [_index_basic("000001.SH", "20000101", None)])

    def _fake_iter_rows(**kwargs):
        yield [
            {
                "ts_code": "000001.SH",
                "freq": "30min",
                "trade_time": datetime(2026, 1, 5, 9, 30),
                "close": 10.2,
                "open": 10.0,
                "high": 10.3,
                "low": 9.9,
                "vol": 1000.0,
                "amount": 10000.0,
                "exchange": "SSE",
                "vwap": 10.1,
            }
        ]

    monkeypatch.setattr(
        "lake_console.backend.app.services.prod_raw_index_mins_export_service.iter_prod_raw_rows",
        _fake_iter_rows,
    )

    summary = ProdRawIndexMinsExportService(
        lake_root=tmp_path,
        database_url="postgresql://unused",
        progress=lambda _: None,
    ).export(
        trade_date=date(2026, 1, 5),
        freqs=["30min"],
    )

    rows = read_parquet_rows(
        tmp_path / "raw_tushare" / "index_mins_by_date" / "freq=30min" / "trade_date=2026-01-05" / "part-000.parquet"
    )
    query = build_prod_raw_index_mins_range_query(
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
        freq="30min",
        ts_codes=["000001.SH"],
    )

    assert "raw_tushare.index_mins" == query.table_name
    assert "trade_time >= %s" in query.sql
    assert "trade_time < %s" in query.sql
    assert "ts_code = any(%s)" in query.sql
    assert query.params == ("30min", date(2026, 1, 5), date(2026, 1, 6), ["000001.SH"])
    assert summary["request_count"] == 1
    assert summary["written_rows"] == 1
    assert rows[0]["ts_code"] == "000001.SH"
    assert rows[0]["freq"] == "30min"


class _FakeIndexMinsClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def index_mins(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {
                "ts_code": kwargs["ts_code"],
                "freq": kwargs["freq"],
                "trade_time": "2026-01-05 09:30:00",
                "close": 10.2,
                "open": 10.0,
                "high": 10.3,
                "low": 9.9,
                "vol": 1000.0,
                "amount": 10000.0,
                "exchange": "SSE",
                "vwap": 10.1,
            }
        ]


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


def _write_calendar(root, dates: list[date]) -> None:
    write_rows_to_parquet(
        [{"cal_date": item, "is_open": True, "exchange": "SSE", "pretrade_date": None} for item in dates],
        root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet",
    )
