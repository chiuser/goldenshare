from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from lake_console.backend.app.catalog.datasets.market_equity import ADJ_FACTOR_FIELDS, DAILY_BASIC_FIELDS
from lake_console.backend.app.catalog.tushare_index_series import INDEX_DAILY_BASIC_FIELDS, INDEX_DAILY_FIELDS
from lake_console.backend.app.services.db_trade_date_export_service import DbTradeDateExportService
from lake_console.backend.app.services.prod_core_db import (
    PROD_CORE_DB_ALLOWED_TABLES,
    PROD_CORE_DB_SOURCE,
    build_prod_core_trade_date_query,
    build_prod_core_trade_date_range_query,
)
from lake_console.backend.app.services.prod_raw_db import (
    PROD_RAW_DB_ALLOWED_TABLES,
    build_prod_raw_trade_date_query,
    build_prod_raw_trade_date_range_query,
)
from lake_console.backend.app.sync.planner import LakeSyncPlanner


@pytest.mark.parametrize(
    ("dataset_key", "expected_table", "expected_fields"),
    [
        ("adj_factor", "raw_tushare.adj_factor", ADJ_FACTOR_FIELDS),
        ("daily_basic", "raw_tushare.daily_basic", DAILY_BASIC_FIELDS),
        ("index_daily_basic", "raw_tushare.index_daily_basic", INDEX_DAILY_BASIC_FIELDS),
    ],
)
def test_prod_raw_trade_date_query_uses_whitelist_projection(
    dataset_key: str,
    expected_table: str,
    expected_fields: tuple[str, ...],
) -> None:
    point_query = build_prod_raw_trade_date_query(dataset_key=dataset_key, trade_date=date(2026, 4, 30))
    range_query = build_prod_raw_trade_date_range_query(
        dataset_key=dataset_key,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
    )

    assert point_query.table_name == PROD_RAW_DB_ALLOWED_TABLES[dataset_key]
    assert point_query.table_name == expected_table
    assert point_query.fields == expected_fields
    assert "select *" not in " ".join(point_query.sql.lower().split())
    assert point_query.params == (date(2026, 4, 30),)

    assert range_query.table_name == expected_table
    assert range_query.fields == expected_fields
    assert "trade_date >= %s and trade_date <= %s" in range_query.sql
    assert "order by trade_date, ts_code" in range_query.sql
    assert range_query.params == (date(2026, 4, 1), date(2026, 4, 30))


def test_prod_core_trade_date_query_maps_change_field() -> None:
    point_query = build_prod_core_trade_date_query(dataset_key="index_daily", trade_date=date(2026, 4, 30))
    range_query = build_prod_core_trade_date_range_query(
        dataset_key="index_daily",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
    )

    assert point_query.table_name == PROD_CORE_DB_ALLOWED_TABLES["index_daily"]
    assert point_query.fields == INDEX_DAILY_FIELDS
    assert "change_amount as change" in point_query.sql.lower()
    assert "source" not in point_query.sql.lower()
    assert "created_at" not in point_query.sql.lower()
    assert "updated_at" not in point_query.sql.lower()
    assert range_query.params == (date(2026, 4, 1), date(2026, 4, 30))


@pytest.mark.parametrize(
    ("dataset_key", "source", "expected_strategy_key"),
    [
        ("adj_factor", "prod-raw-db", "adj_factor:prod-raw-db"),
        ("daily_basic", "prod-raw-db", "daily_basic:prod-raw-db"),
        ("index_daily_basic", "prod-raw-db", "index_daily_basic:prod-raw-db"),
        ("index_daily", "prod-core-db", "index_daily:prod-core-db"),
    ],
)
def test_trade_date_plans_use_expected_source_and_strategy(
    tmp_path,
    dataset_key: str,
    source: str,
    expected_strategy_key: str,
) -> None:
    pytest.importorskip("pyarrow")
    _write_trade_calendar(tmp_path, [date(2026, 4, 30)])
    plan = LakeSyncPlanner(lake_root=tmp_path).plan(
        dataset_key=dataset_key,
        source=source,
        trade_date=date(2026, 4, 30),
    )

    assert plan.source == source
    assert plan.request_strategy_key == expected_strategy_key
    assert plan.partition_count == 1
    assert plan.parameters["trade_date"] == "2026-04-30"


def test_adj_factor_prod_raw_export_ignores_non_open_day_rows(monkeypatch, tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    _write_trade_calendar(tmp_path, [date(2026, 4, 30)])

    def fake_iter_prod_raw_rows(*, database_url, query, batch_size, cursor_name):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.adj_factor"
        assert batch_size == 20000
        assert cursor_name == "lake_adj_factor_prod_raw_db_cursor"
        yield [
            {"ts_code": "600000.SH", "trade_date": date(2026, 4, 30), "adj_factor": Decimal("1.010000")},
            {"ts_code": "600001.SH", "trade_date": date(2026, 5, 1), "adj_factor": Decimal("1.020000")},
        ]

    summary = DbTradeDateExportService(
        lake_root=tmp_path,
        dataset_key="adj_factor",
        api_name="adj_factor",
        source="prod-raw-db",
        database_url="postgresql://readonly@example/db",
        build_point_query=build_prod_raw_trade_date_query,
        build_range_query=build_prod_raw_trade_date_range_query,
        fetch_rows=lambda **_: [],
        iter_rows=fake_iter_prod_raw_rows,
        progress=lambda _: None,
    ).export(start_date=date(2026, 4, 30), end_date=date(2026, 4, 30))

    parquet_file = tmp_path / "raw_tushare" / "adj_factor" / "trade_date=2026-04-30" / "part-000.parquet"
    schema = pq.read_schema(parquet_file)
    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert pq.read_table(parquet_file).num_rows == 1
    assert "trade_date=2026-05-01" not in str(list((tmp_path / "raw_tushare" / "adj_factor").glob("*")))
    assert "adj_factor" in schema.names


def test_index_daily_prod_core_export_maps_change_amount_to_change(monkeypatch, tmp_path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    _write_trade_calendar(tmp_path, [date(2026, 4, 30)])

    def fake_fetch_prod_core_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "core_serving.index_daily_serving"
        return [
            {
                "ts_code": "000300.SH",
                "trade_date": date(2026, 4, 30),
                "open": Decimal("100.1"),
                "high": Decimal("101.2"),
                "low": Decimal("99.8"),
                "close": Decimal("100.8"),
                "pre_close": Decimal("100.0"),
                "change": Decimal("0.8"),
                "pct_chg": Decimal("0.8"),
                "vol": Decimal("12345"),
                "amount": Decimal("56789"),
            }
        ]

    summary = DbTradeDateExportService(
        lake_root=tmp_path,
        dataset_key="index_daily",
        api_name="index_daily",
        source=PROD_CORE_DB_SOURCE,
        database_url="postgresql://readonly@example/db",
        build_point_query=build_prod_core_trade_date_query,
        build_range_query=build_prod_core_trade_date_range_query,
        fetch_rows=fake_fetch_prod_core_rows,
        iter_rows=lambda **_: iter(()),
        progress=lambda _: None,
    ).export(trade_date=date(2026, 4, 30))

    parquet_file = tmp_path / "raw_tushare" / "index_daily" / "trade_date=2026-04-30" / "part-000.parquet"
    schema = pq.read_schema(parquet_file)
    assert summary["source"] == "prod-core-db"
    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert "change" in schema.names
    assert "change_amount" not in schema.names
    assert pa.types.is_date(schema.field("trade_date").type)


def _write_trade_calendar(root, trade_dates: list[date]) -> None:
    pytest.importorskip("pyarrow")
    calendar_file = root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
    calendar_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"cal_date": item, "is_open": True} for item in trade_dates]).to_parquet(
        calendar_file,
        index=False,
        engine="pyarrow",
    )
