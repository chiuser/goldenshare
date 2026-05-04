from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from lake_console.backend.app.catalog.tushare_reference_master import (
    ETF_BASIC_FIELDS,
    ETF_INDEX_FIELDS,
    THS_INDEX_FIELDS,
    THS_MEMBER_FIELDS,
)
from lake_console.backend.app.services.prod_raw_db import (
    PROD_RAW_DB_ALLOWED_TABLES,
    build_prod_raw_current_query,
)
from lake_console.backend.app.services.prod_raw_current_export_service import ProdRawCurrentExportService
from lake_console.backend.app.sync.planner import LakeSyncPlanner


@pytest.mark.parametrize(
    ("dataset_key", "expected_table", "expected_fields", "expected_order"),
    [
        ("etf_basic", "raw_tushare.etf_basic", ETF_BASIC_FIELDS, "order by ts_code"),
        ("etf_index", "raw_tushare.etf_index", ETF_INDEX_FIELDS, "order by ts_code"),
        ("ths_index", "raw_tushare.ths_index", THS_INDEX_FIELDS, "order by ts_code"),
        ("ths_member", "raw_tushare.ths_member", THS_MEMBER_FIELDS, "order by ts_code, con_code"),
    ],
)
def test_prod_raw_snapshot_query_uses_whitelist_projection(
    dataset_key: str,
    expected_table: str,
    expected_fields: tuple[str, ...],
    expected_order: str,
) -> None:
    query = build_prod_raw_current_query(dataset_key=dataset_key)

    assert query.table_name == PROD_RAW_DB_ALLOWED_TABLES[dataset_key]
    assert query.table_name == expected_table
    assert query.fields == expected_fields
    assert "select *" not in " ".join(query.sql.lower().split())
    assert expected_order in query.sql.lower()
    assert "api_name" not in query.fields
    assert "fetched_at" not in query.fields
    assert "raw_payload" not in query.fields
    assert query.params == ()


def test_prod_raw_snapshot_plan_marks_source_and_dual_write_paths(tmp_path) -> None:
    plan = LakeSyncPlanner(lake_root=tmp_path).plan(
        dataset_key="etf_basic",
        source="prod-raw-db",
    )

    assert plan.source == "prod-raw-db"
    assert plan.request_strategy_key == "etf_basic:prod-raw-db"
    assert plan.request_count == 1
    assert "raw_tushare/etf_basic/current/part-000.parquet" in plan.write_paths
    assert "manifest/etf_universe/tushare_etf_basic.parquet" in plan.write_paths


def test_prod_raw_snapshot_plan_rejects_subset_filters(tmp_path) -> None:
    with pytest.raises(ValueError, match="只支持全量 current 快照"):
        LakeSyncPlanner(lake_root=tmp_path).plan(
            dataset_key="ths_member",
            source="prod-raw-db",
            ts_code="885001.TI",
        )


def test_etf_basic_prod_raw_export_writes_raw_and_manifest(monkeypatch, tmp_path) -> None:
    pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    def fake_fetch_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.etf_basic"
        return [
            {
                "ts_code": "510300.SH",
                "csname": "沪深300ETF",
                "extname": "300ETF",
                "cname": "沪深300交易型开放式指数证券投资基金",
                "index_code": "000300.SH",
                "index_name": "沪深300",
                "setup_date": date(2012, 5, 28),
                "list_date": date(2012, 5, 28),
                "list_status": "L",
                "exchange": "SH",
                "mgr_name": "华泰柏瑞",
                "custod_name": "中国工商银行",
                "mgt_fee": Decimal("0.500000"),
                "etf_type": "境内",
            }
        ]

    monkeypatch.setattr(
        "lake_console.backend.app.services.prod_raw_current_export_service.fetch_prod_raw_rows",
        fake_fetch_prod_raw_rows,
    )

    summary = ProdRawCurrentExportService(
        lake_root=tmp_path,
        database_url="postgresql://readonly@example/db",
        progress=lambda _: None,
    ).export(dataset_key="etf_basic")

    raw_file = tmp_path / "raw_tushare" / "etf_basic" / "current" / "part-000.parquet"
    manifest_file = tmp_path / "manifest" / "etf_universe" / "tushare_etf_basic.parquet"
    raw_schema = pq.read_schema(raw_file)
    manifest_schema = pq.read_schema(manifest_file)

    assert summary["source"] == "prod-raw-db"
    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert summary["manifest_written_rows"] == 1
    assert raw_file.exists()
    assert manifest_file.exists()
    assert pa.types.is_date(raw_schema.field("setup_date").type)
    assert pa.types.is_date(raw_schema.field("list_date").type)
    assert pa.types.is_float64(raw_schema.field("mgt_fee").type)
    assert raw_schema.equals(manifest_schema)


def test_ths_member_prod_raw_export_streams_and_writes_raw_and_manifest(monkeypatch, tmp_path) -> None:
    pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    def fake_iter_prod_raw_rows(*, database_url, query, batch_size, cursor_name):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.ths_member"
        assert batch_size == 20000
        assert cursor_name == "lake_ths_member_prod_raw_cursor"
        yield [
            _ths_member_row("885001.TI", "600000.SH", Decimal("1.250000")),
            _ths_member_row("885001.TI", "600519.SH", Decimal("3.500000")),
        ]
        yield [
            _ths_member_row("885002.TI", "000001.SZ", Decimal("2.000000")),
        ]

    monkeypatch.setattr(
        "lake_console.backend.app.services.prod_raw_current_export_service.iter_prod_raw_rows",
        fake_iter_prod_raw_rows,
    )

    summary = ProdRawCurrentExportService(
        lake_root=tmp_path,
        database_url="postgresql://readonly@example/db",
        progress=lambda _: None,
    ).export(dataset_key="ths_member")

    raw_file = tmp_path / "raw_tushare" / "ths_member" / "current" / "part-000.parquet"
    manifest_file = tmp_path / "manifest" / "board_membership" / "tushare_ths_member.parquet"
    raw_schema = pq.read_schema(raw_file)
    manifest_schema = pq.read_schema(manifest_file)

    assert summary["fetched_rows"] == 3
    assert summary["written_rows"] == 3
    assert summary["manifest_written_rows"] == 3
    assert raw_file.exists()
    assert manifest_file.exists()
    assert pa.types.is_float64(raw_schema.field("weight").type)
    assert pa.types.is_date(raw_schema.field("in_date").type)
    assert pa.types.is_date(raw_schema.field("out_date").type)
    assert raw_schema.equals(manifest_schema)


def _ths_member_row(ts_code: str, con_code: str, weight: Decimal) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "con_code": con_code,
        "con_name": "示例股票",
        "weight": weight,
        "in_date": date(2026, 1, 1),
        "out_date": date(2026, 4, 30),
        "is_new": "Y",
    }
