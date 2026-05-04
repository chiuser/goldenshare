from __future__ import annotations

from datetime import date

import pytest

from lake_console.backend.app.catalog.datasets.market_equity import DAILY_FIELDS
from lake_console.backend.app.services.prod_raw_db import (
    PROD_RAW_DB_ALLOWED_TABLES,
    ProdRawDbConfigError,
    build_daily_prod_raw_query,
    build_daily_prod_raw_range_query,
    fetch_prod_raw_rows,
)
from lake_console.backend.app.services.prod_raw_daily_export_service import ProdRawDailyExportService
from lake_console.backend.app.services.tushare_daily_sync_service import _normalize_daily_row
from lake_console.backend.app.sync.planner import LakeSyncPlanner


def test_daily_prod_raw_query_uses_whitelist_projection() -> None:
    query = build_daily_prod_raw_query(trade_date=date(2026, 4, 24))

    assert query.table_name == PROD_RAW_DB_ALLOWED_TABLES["daily"]
    assert query.fields == DAILY_FIELDS
    assert "select *" not in " ".join(query.sql.lower().split())
    assert "from raw_tushare.daily" in query.sql
    assert query.params == (date(2026, 4, 24),)
    assert "api_name" not in query.fields
    assert "fetched_at" not in query.fields
    assert "raw_payload" not in query.fields


def test_daily_prod_raw_range_query_uses_one_whitelisted_range_projection() -> None:
    query = build_daily_prod_raw_range_query(start_date=date(2026, 4, 1), end_date=date(2026, 4, 30))

    assert query.table_name == PROD_RAW_DB_ALLOWED_TABLES["daily"]
    assert query.fields == DAILY_FIELDS
    assert "select *" not in " ".join(query.sql.lower().split())
    assert "from raw_tushare.daily" in query.sql
    assert "trade_date >= %s and trade_date <= %s" in query.sql
    assert "order by trade_date, ts_code" in query.sql
    assert query.params == (date(2026, 4, 1), date(2026, 4, 30))


def test_daily_prod_raw_requires_explicit_database_url() -> None:
    query = build_daily_prod_raw_query(trade_date=date(2026, 4, 24))

    with pytest.raises(ProdRawDbConfigError, match="GOLDENSHARE_PROD_RAW_DB_URL"):
        fetch_prod_raw_rows(database_url=None, query=query)


def test_daily_prod_raw_plan_marks_source_and_strategy(tmp_path) -> None:
    plan = LakeSyncPlanner(lake_root=tmp_path).plan(
        dataset_key="daily",
        source="prod-raw-db",
        trade_date=date(2026, 4, 24),
    )

    assert plan.source == "prod-raw-db"
    assert plan.request_strategy_key == "daily:prod-raw-db"
    assert plan.request_count == 1
    assert "raw_tushare.daily" in " ".join(plan.notes)


def test_tushare_daily_normalizer_writes_trade_date_as_date() -> None:
    normalized = _normalize_daily_row(
        {
            "ts_code": "600000.SH",
            "trade_date": "20260424",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10.5,
            "pre_close": 10,
            "change": 0.5,
            "pct_chg": 5,
            "vol": 1000,
            "amount": 12000,
        },
        expected_trade_date=date(2026, 4, 24),
    )

    assert normalized is not None
    assert normalized["trade_date"] == date(2026, 4, 24)


def test_daily_prod_raw_export_writes_date_column(monkeypatch, tmp_path) -> None:
    pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    def fake_fetch_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.params == (date(2026, 4, 24),)
        return [
            {
                "ts_code": "600000.SH",
                "trade_date": "20260424",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "pre_close": 10,
                "change": 0.5,
                "pct_chg": 5,
                "vol": 1000,
                "amount": 12000,
            }
        ]

    monkeypatch.setattr(
        "lake_console.backend.app.services.prod_raw_daily_export_service.fetch_prod_raw_rows",
        fake_fetch_prod_raw_rows,
    )

    summary = ProdRawDailyExportService(
        lake_root=tmp_path,
        database_url="postgresql://readonly@example/db",
        progress=lambda _: None,
    ).export(trade_date=date(2026, 4, 24))

    parquet_file = tmp_path / "raw_tushare" / "daily" / "trade_date=2026-04-24" / "part-000.parquet"
    schema = pq.read_schema(parquet_file)
    assert summary["source"] == "prod-raw-db"
    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert pa.types.is_date(schema.field("trade_date").type)


def test_daily_prod_raw_range_export_streams_once_and_writes_daily_partitions(monkeypatch, tmp_path) -> None:
    pd = pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    calendar_file = tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
    calendar_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"cal_date": date(2026, 4, 24), "is_open": True},
            {"cal_date": date(2026, 4, 25), "is_open": True},
        ]
    ).to_parquet(calendar_file, index=False, engine="pyarrow")

    def fake_iter_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.params == (date(2026, 4, 24), date(2026, 4, 25))
        yield [
            _daily_row("600000.SH", "20260424"),
            _daily_row("000001.SZ", "20260424"),
        ]
        yield [
            _daily_row("600000.SH", "20260425"),
        ]

    monkeypatch.setattr(
        "lake_console.backend.app.services.prod_raw_daily_export_service.iter_prod_raw_rows",
        fake_iter_prod_raw_rows,
    )

    summary = ProdRawDailyExportService(
        lake_root=tmp_path,
        database_url="postgresql://readonly@example/db",
        progress=lambda _: None,
    ).export(start_date=date(2026, 4, 24), end_date=date(2026, 4, 25))

    first_file = tmp_path / "raw_tushare" / "daily" / "trade_date=2026-04-24" / "part-000.parquet"
    second_file = tmp_path / "raw_tushare" / "daily" / "trade_date=2026-04-25" / "part-000.parquet"
    assert summary["fetched_rows"] == 3
    assert summary["written_rows"] == 3
    assert first_file.exists()
    assert second_file.exists()
    assert pa.types.is_date(pq.read_schema(first_file).field("trade_date").type)
    assert pa.types.is_date(pq.read_schema(second_file).field("trade_date").type)


def _daily_row(ts_code: str, trade_date: str) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10.5,
        "pre_close": 10,
        "change": 0.5,
        "pct_chg": 5,
        "vol": 1000,
        "amount": 12000,
    }
