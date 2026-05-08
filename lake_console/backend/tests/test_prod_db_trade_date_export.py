from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from lake_console.backend.app.catalog.datasets.board_hotspot import (
    DC_DAILY_FIELDS,
    DC_HOT_FIELDS,
    DC_INDEX_FIELDS,
    DC_MEMBER_FIELDS,
    KPL_CONCEPT_CONS_FIELDS,
    KPL_LIST_FIELDS,
    THS_DAILY_FIELDS,
    THS_HOT_FIELDS,
)
from lake_console.backend.app.catalog.datasets.leader_board import (
    LIMIT_CPT_LIST_FIELDS,
    LIMIT_LIST_D_FIELDS,
    LIMIT_LIST_THS_FIELDS,
    LIMIT_STEP_FIELDS,
    TOP_LIST_FIELDS,
)
from lake_console.backend.app.catalog.datasets.market_equity import (
    ADJ_FACTOR_FIELDS,
    DAILY_BASIC_FIELDS,
    MARGIN_FIELDS,
    STK_LIMIT_FIELDS,
    STOCK_ST_FIELDS,
    SUSPEND_D_FIELDS,
)
from lake_console.backend.app.catalog.datasets.market_fund import FUND_ADJ_FIELDS, FUND_DAILY_FIELDS
from lake_console.backend.app.catalog.datasets.moneyflow import (
    MONEYFLOW_CNT_THS_FIELDS,
    MONEYFLOW_DC_FIELDS,
    MONEYFLOW_FIELDS,
    MONEYFLOW_IND_DC_FIELDS,
    MONEYFLOW_IND_THS_FIELDS,
    MONEYFLOW_MKT_DC_FIELDS,
    MONEYFLOW_THS_FIELDS,
)
from lake_console.backend.app.catalog.datasets.technical_indicators import CYQ_PERF_FIELDS
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
        ("cyq_perf", "raw_tushare.cyq_perf", CYQ_PERF_FIELDS),
        ("daily_basic", "raw_tushare.daily_basic", DAILY_BASIC_FIELDS),
        ("dc_daily", "raw_tushare.dc_daily", DC_DAILY_FIELDS),
        ("dc_hot", "raw_tushare.dc_hot", DC_HOT_FIELDS),
        ("dc_index", "raw_tushare.dc_index", DC_INDEX_FIELDS),
        ("dc_member", "raw_tushare.dc_member", DC_MEMBER_FIELDS),
        ("fund_adj", "raw_tushare.fund_adj", FUND_ADJ_FIELDS),
        ("fund_daily", "raw_tushare.fund_daily", FUND_DAILY_FIELDS),
        ("index_daily_basic", "raw_tushare.index_daily_basic", INDEX_DAILY_BASIC_FIELDS),
        ("kpl_concept_cons", "raw_tushare.kpl_concept_cons", KPL_CONCEPT_CONS_FIELDS),
        ("kpl_list", "raw_tushare.kpl_list", KPL_LIST_FIELDS),
        ("limit_cpt_list", "raw_tushare.limit_cpt_list", LIMIT_CPT_LIST_FIELDS),
        ("limit_list_d", "raw_tushare.limit_list", LIMIT_LIST_D_FIELDS),
        ("limit_list_ths", "raw_tushare.limit_list_ths", LIMIT_LIST_THS_FIELDS),
        ("limit_step", "raw_tushare.limit_step", LIMIT_STEP_FIELDS),
        ("margin", "raw_tushare.margin", MARGIN_FIELDS),
        ("moneyflow", "raw_tushare.moneyflow", MONEYFLOW_FIELDS),
        ("moneyflow_ths", "raw_tushare.moneyflow_ths", MONEYFLOW_THS_FIELDS),
        ("moneyflow_dc", "raw_tushare.moneyflow_dc", MONEYFLOW_DC_FIELDS),
        ("moneyflow_cnt_ths", "raw_tushare.moneyflow_cnt_ths", MONEYFLOW_CNT_THS_FIELDS),
        ("moneyflow_ind_ths", "raw_tushare.moneyflow_ind_ths", MONEYFLOW_IND_THS_FIELDS),
        ("moneyflow_ind_dc", "raw_tushare.moneyflow_ind_dc", MONEYFLOW_IND_DC_FIELDS),
        ("moneyflow_mkt_dc", "raw_tushare.moneyflow_mkt_dc", MONEYFLOW_MKT_DC_FIELDS),
        ("stk_limit", "raw_tushare.stk_limit", STK_LIMIT_FIELDS),
        ("stock_st", "raw_tushare.stock_st", STOCK_ST_FIELDS),
        ("suspend_d", "raw_tushare.suspend_d", SUSPEND_D_FIELDS),
        ("ths_daily", "raw_tushare.ths_daily", THS_DAILY_FIELDS),
        ("ths_hot", "raw_tushare.ths_hot", THS_HOT_FIELDS),
        ("top_list", "raw_tushare.top_list", TOP_LIST_FIELDS),
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
    expected_order = {
        "adj_factor": "order by trade_date, ts_code",
        "cyq_perf": "order by trade_date, ts_code",
        "daily_basic": "order by trade_date, ts_code",
        "dc_daily": "order by trade_date, ts_code",
        "dc_hot": "order by trade_date, ts_code, rank_time, query_market, query_hot_type, query_is_new",
        "dc_index": "order by trade_date, ts_code",
        "dc_member": "order by trade_date, ts_code, con_code",
        "fund_adj": "order by trade_date, ts_code",
        "fund_daily": "order by trade_date, ts_code",
        "index_daily_basic": "order by trade_date, ts_code",
        "kpl_concept_cons": 'order by trade_date, ts_code, con_code',
        "kpl_list": "order by trade_date, ts_code",
        "limit_cpt_list": "order by trade_date, ts_code, rank",
        "limit_list_d": 'order by trade_date, ts_code, "limit"',
        "limit_list_ths": "order by trade_date, ts_code, limit_type",
        "limit_step": "order by trade_date, ts_code, nums",
        "margin": "order by trade_date, exchange_id",
        "moneyflow": "order by trade_date, ts_code",
        "moneyflow_ths": "order by trade_date, ts_code",
        "moneyflow_dc": "order by trade_date, ts_code",
        "moneyflow_cnt_ths": "order by trade_date, ts_code",
        "moneyflow_ind_ths": "order by trade_date, ts_code",
        "moneyflow_ind_dc": "order by trade_date, content_type, ts_code",
        "moneyflow_mkt_dc": "order by trade_date",
        "stk_limit": "order by trade_date, ts_code",
        "stock_st": "order by trade_date, ts_code, type",
        "suspend_d": "order by trade_date, ts_code, suspend_type, suspend_timing",
        "ths_daily": "order by trade_date, ts_code",
        "ths_hot": "order by trade_date, ts_code, rank_time, query_market, query_is_new",
        "top_list": "order by trade_date, ts_code, reason",
    }
    assert expected_order[dataset_key] in range_query.sql
    assert range_query.params == (date(2026, 4, 1), date(2026, 4, 30))


def test_limit_list_d_prod_raw_query_quotes_limit_column() -> None:
    point_query = build_prod_raw_trade_date_query(dataset_key="limit_list_d", trade_date=date(2026, 5, 7))
    assert '"limit"' in point_query.sql
    assert " limit," not in point_query.sql.lower()


def test_kpl_concept_cons_prod_raw_query_quotes_desc_column() -> None:
    point_query = build_prod_raw_trade_date_query(dataset_key="kpl_concept_cons", trade_date=date(2026, 5, 7))
    assert '"desc"' in point_query.sql
    assert "select desc" not in point_query.sql.lower()


def test_dc_index_prod_raw_query_quotes_leading_column() -> None:
    point_query = build_prod_raw_trade_date_query(dataset_key="dc_index", trade_date=date(2026, 5, 7))
    assert '"leading"' in point_query.sql
    assert "select ts_code, trade_date, name, leading," not in point_query.sql.lower()


def test_limit_list_ths_prod_raw_query_excludes_query_context_fields() -> None:
    point_query = build_prod_raw_trade_date_query(dataset_key="limit_list_ths", trade_date=date(2026, 4, 30))
    assert "query_limit_type" not in point_query.sql
    assert "query_market" not in point_query.sql


def test_dc_hot_prod_raw_query_maps_request_fact_dimensions() -> None:
    point_query = build_prod_raw_trade_date_query(dataset_key="dc_hot", trade_date=date(2026, 5, 7))
    assert point_query.fields == DC_HOT_FIELDS
    assert "query_market as market" in point_query.sql
    assert "query_hot_type as hot_type" in point_query.sql
    assert "query_is_new as is_new" in point_query.sql


def test_ths_hot_prod_raw_query_maps_request_fact_dimensions() -> None:
    point_query = build_prod_raw_trade_date_query(dataset_key="ths_hot", trade_date=date(2026, 5, 7))
    assert point_query.fields == THS_HOT_FIELDS
    assert "query_market as market" in point_query.sql
    assert "query_is_new as is_new" in point_query.sql


def test_top_list_prod_raw_query_excludes_hash_fields() -> None:
    point_query = build_prod_raw_trade_date_query(dataset_key="top_list", trade_date=date(2026, 5, 7))
    assert "payload_hash" not in point_query.sql
    assert "reason_hash" not in point_query.sql


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
        ("cyq_perf", "prod-raw-db", "cyq_perf:prod-raw-db"),
        ("daily_basic", "prod-raw-db", "daily_basic:prod-raw-db"),
        ("dc_daily", "prod-raw-db", "dc_daily:prod-raw-db"),
        ("dc_hot", "prod-raw-db", "dc_hot:prod-raw-db"),
        ("dc_index", "prod-raw-db", "dc_index:prod-raw-db"),
        ("dc_member", "prod-raw-db", "dc_member:prod-raw-db"),
        ("fund_adj", "prod-raw-db", "fund_adj:prod-raw-db"),
        ("fund_daily", "prod-raw-db", "fund_daily:prod-raw-db"),
        ("index_daily_basic", "prod-raw-db", "index_daily_basic:prod-raw-db"),
        ("index_daily", "prod-core-db", "index_daily:prod-core-db"),
        ("kpl_concept_cons", "prod-raw-db", "kpl_concept_cons:prod-raw-db"),
        ("kpl_list", "prod-raw-db", "kpl_list:prod-raw-db"),
        ("limit_cpt_list", "prod-raw-db", "limit_cpt_list:prod-raw-db"),
        ("limit_list_d", "prod-raw-db", "limit_list_d:prod-raw-db"),
        ("limit_list_ths", "prod-raw-db", "limit_list_ths:prod-raw-db"),
        ("limit_step", "prod-raw-db", "limit_step:prod-raw-db"),
        ("margin", "prod-raw-db", "margin:prod-raw-db"),
        ("moneyflow", "prod-raw-db", "moneyflow:prod-raw-db"),
        ("moneyflow_ths", "prod-raw-db", "moneyflow_ths:prod-raw-db"),
        ("moneyflow_dc", "prod-raw-db", "moneyflow_dc:prod-raw-db"),
        ("moneyflow_cnt_ths", "prod-raw-db", "moneyflow_cnt_ths:prod-raw-db"),
        ("moneyflow_ind_ths", "prod-raw-db", "moneyflow_ind_ths:prod-raw-db"),
        ("moneyflow_ind_dc", "prod-raw-db", "moneyflow_ind_dc:prod-raw-db"),
        ("moneyflow_mkt_dc", "prod-raw-db", "moneyflow_mkt_dc:prod-raw-db"),
        ("stk_limit", "prod-raw-db", "stk_limit:prod-raw-db"),
        ("stock_st", "prod-raw-db", "stock_st:prod-raw-db"),
        ("suspend_d", "prod-raw-db", "suspend_d:prod-raw-db"),
        ("ths_daily", "prod-raw-db", "ths_daily:prod-raw-db"),
        ("ths_hot", "prod-raw-db", "ths_hot:prod-raw-db"),
        ("top_list", "prod-raw-db", "top_list:prod-raw-db"),
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
    assert pq.ParquetFile(parquet_file).read().num_rows == 1
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


def test_margin_prod_raw_export_does_not_require_ts_code(tmp_path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    _write_trade_calendar(tmp_path, [date(2026, 4, 30)])

    def fake_fetch_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.margin"
        return [
            {
                "trade_date": date(2026, 4, 30),
                "exchange_id": "SSE",
                "rzye": Decimal("1.1"),
                "rzmre": Decimal("2.2"),
                "rzche": Decimal("3.3"),
                "rqye": Decimal("4.4"),
                "rqmcl": Decimal("5.5"),
                "rzrqye": Decimal("6.6"),
                "rqyl": Decimal("7.7"),
            }
        ]

    summary = DbTradeDateExportService(
        lake_root=tmp_path,
        dataset_key="margin",
        api_name="margin",
        source="prod-raw-db",
        database_url="postgresql://readonly@example/db",
        build_point_query=build_prod_raw_trade_date_query,
        build_range_query=build_prod_raw_trade_date_range_query,
        fetch_rows=fake_fetch_prod_raw_rows,
        iter_rows=lambda **_: iter(()),
        progress=lambda _: None,
    ).export(trade_date=date(2026, 4, 30))

    parquet_file = tmp_path / "raw_tushare" / "margin" / "trade_date=2026-04-30" / "part-000.parquet"
    schema = pq.read_schema(parquet_file)
    table = pq.ParquetFile(parquet_file).read()
    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert "exchange_id" in schema.names
    assert "ts_code" not in schema.names
    assert pa.types.is_date(schema.field("trade_date").type)
    assert table.to_pylist()[0]["exchange_id"] == "SSE"


def test_moneyflow_dc_known_source_gap_marks_skip_reason(tmp_path) -> None:
    pytest.importorskip("pyarrow")

    _write_trade_calendar(tmp_path, [date(2023, 11, 22)])

    summary = DbTradeDateExportService(
        lake_root=tmp_path,
        dataset_key="moneyflow_dc",
        api_name="moneyflow_dc",
        source="prod-raw-db",
        database_url="postgresql://readonly@example/db",
        build_point_query=build_prod_raw_trade_date_query,
        build_range_query=build_prod_raw_trade_date_range_query,
        fetch_rows=lambda **_: [],
        iter_rows=lambda **_: iter(()),
        known_source_gap_dates=(date(2023, 11, 22),),
        progress=lambda _: None,
    ).export(trade_date=date(2023, 11, 22))

    assert summary["fetched_rows"] == 0
    assert summary["written_rows"] == 0
    assert summary["skipped_partitions"] == 1
    assert summary["source_gap_partitions"] == 1
    assert summary["no_data_partitions"] == 0
    assert summary["partitions"][0]["skip_reason"] == "source_gap"
    assert not (tmp_path / "raw_tushare" / "moneyflow_dc" / "trade_date=2023-11-22").exists()


def test_moneyflow_ths_missing_rows_without_known_gap_marks_no_data(tmp_path) -> None:
    pytest.importorskip("pyarrow")

    _write_trade_calendar(tmp_path, [date(2026, 4, 30)])

    summary = DbTradeDateExportService(
        lake_root=tmp_path,
        dataset_key="moneyflow_ths",
        api_name="moneyflow_ths",
        source="prod-raw-db",
        database_url="postgresql://readonly@example/db",
        build_point_query=build_prod_raw_trade_date_query,
        build_range_query=build_prod_raw_trade_date_range_query,
        fetch_rows=lambda **_: [],
        iter_rows=lambda **_: iter(()),
        progress=lambda _: None,
    ).export(trade_date=date(2026, 4, 30))

    assert summary["skipped_partitions"] == 1
    assert summary["source_gap_partitions"] == 0
    assert summary["no_data_partitions"] == 1
    assert summary["partitions"][0]["skip_reason"] == "no_data"


def test_dc_hot_prod_raw_export_writes_promoted_fact_dimensions(tmp_path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    _write_trade_calendar(tmp_path, [date(2026, 5, 7)])

    def fake_fetch_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.dc_hot"
        return [
            {
                "trade_date": date(2026, 5, 7),
                "data_type": "股票",
                "ts_code": "600000.SH",
                "ts_name": "浦发银行",
                "rank": 1,
                "pct_change": Decimal("1.23"),
                "current_price": Decimal("10.56"),
                "rank_time": "2026-05-07 14:30:00",
                "hot": Decimal("88.8"),
                "market": "A股市场",
                "hot_type": "人气榜",
                "is_new": "Y",
            }
        ]

    summary = DbTradeDateExportService(
        lake_root=tmp_path,
        dataset_key="dc_hot",
        api_name="dc_hot",
        source="prod-raw-db",
        database_url="postgresql://readonly@example/db",
        build_point_query=build_prod_raw_trade_date_query,
        build_range_query=build_prod_raw_trade_date_range_query,
        fetch_rows=fake_fetch_prod_raw_rows,
        iter_rows=lambda **_: iter(()),
        progress=lambda _: None,
    ).export(trade_date=date(2026, 5, 7))

    parquet_file = tmp_path / "raw_tushare" / "dc_hot" / "trade_date=2026-05-07" / "part-000.parquet"
    schema = pq.read_schema(parquet_file)
    table = pq.ParquetFile(parquet_file).read()
    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert "market" in schema.names
    assert "hot_type" in schema.names
    assert "is_new" in schema.names
    assert "query_market" not in schema.names
    assert "query_hot_type" not in schema.names
    assert "query_is_new" not in schema.names
    assert pa.types.is_date(schema.field("trade_date").type)
    assert table.to_pylist()[0]["market"] == "A股市场"


def test_ths_daily_prod_raw_export_ignores_non_open_day_rows(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    _write_trade_calendar(tmp_path, [date(2026, 4, 10)])

    def fake_iter_prod_raw_rows(*, database_url, query, batch_size, cursor_name):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.ths_daily"
        assert batch_size == 20000
        assert cursor_name == "lake_ths_daily_prod_raw_db_cursor"
        yield [
            {
                "ts_code": "885001.TI",
                "trade_date": date(2026, 4, 10),
                "close": Decimal("101.1"),
                "open": Decimal("100.0"),
                "high": Decimal("102.2"),
                "low": Decimal("99.9"),
                "pre_close": Decimal("99.8"),
                "avg_price": Decimal("100.5"),
                "change": Decimal("1.3"),
                "pct_change": Decimal("1.31"),
                "vol": Decimal("1234"),
                "turnover_rate": Decimal("5.6"),
                "total_mv": Decimal("700.1"),
                "float_mv": Decimal("500.2"),
            },
            {
                "ts_code": "885001.TI",
                "trade_date": date(2026, 4, 11),
                "close": Decimal("101.2"),
                "open": Decimal("100.1"),
                "high": Decimal("102.3"),
                "low": Decimal("100.0"),
                "pre_close": Decimal("101.1"),
                "avg_price": Decimal("100.6"),
                "change": Decimal("0.1"),
                "pct_change": Decimal("0.09"),
                "vol": Decimal("1200"),
                "turnover_rate": Decimal("5.5"),
                "total_mv": Decimal("700.2"),
                "float_mv": Decimal("500.3"),
            },
        ]

    summary = DbTradeDateExportService(
        lake_root=tmp_path,
        dataset_key="ths_daily",
        api_name="ths_daily",
        source="prod-raw-db",
        database_url="postgresql://readonly@example/db",
        build_point_query=build_prod_raw_trade_date_query,
        build_range_query=build_prod_raw_trade_date_range_query,
        fetch_rows=lambda **_: [],
        iter_rows=fake_iter_prod_raw_rows,
        progress=lambda _: None,
    ).export(start_date=date(2026, 4, 10), end_date=date(2026, 4, 10))

    parquet_file = tmp_path / "raw_tushare" / "ths_daily" / "trade_date=2026-04-10" / "part-000.parquet"
    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert pq.ParquetFile(parquet_file).read().num_rows == 1
    assert not (tmp_path / "raw_tushare" / "ths_daily" / "trade_date=2026-04-11").exists()


def _write_trade_calendar(root, trade_dates: list[date]) -> None:
    pytest.importorskip("pyarrow")
    calendar_file = root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
    calendar_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"cal_date": item, "is_open": True} for item in trade_dates]).to_parquet(
        calendar_file,
        index=False,
        engine="pyarrow",
    )
