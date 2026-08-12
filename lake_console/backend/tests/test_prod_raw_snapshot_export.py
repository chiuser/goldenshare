from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from lake_console.backend.app.catalog.tushare_reference_master import (
    BSE_MAPPING_FIELDS,
    ETF_BASIC_FIELDS,
    ETF_INDEX_FIELDS,
    HK_BASIC_FIELDS,
    NAMECHANGE_FIELDS,
    STOCK_COMPANY_FIELDS,
    ST_FIELDS,
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
        ("bse_mapping", "raw_tushare.bse_mapping", BSE_MAPPING_FIELDS, "order by o_code, n_code"),
        ("hk_basic", "raw_tushare.hk_basic", HK_BASIC_FIELDS, "order by ts_code"),
        ("namechange", "raw_tushare.namechange", NAMECHANGE_FIELDS, "order by ts_code, start_date, ann_date"),
        ("stock_company", "raw_tushare.stock_company", STOCK_COMPANY_FIELDS, "order by ts_code"),
        ("st", "raw_tushare.st", ST_FIELDS, "order by ts_code, imp_date, pub_date"),
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


def test_st_prod_raw_snapshot_query_projects_current_source_field() -> None:
    query = build_prod_raw_current_query(dataset_key="st")

    assert query.fields == (
        "ts_code",
        "name",
        "pub_date",
        "imp_date",
        "st_type",
        "st_reason",
        "st_explain",
    )
    assert "st_tpye" not in query.fields
    assert "st_type" in query.sql


def test_prod_raw_snapshot_plan_marks_source_and_dual_write_paths(tmp_path) -> None:
    plan = LakeSyncPlanner(lake_root=tmp_path).plan(
        dataset_key="bse_mapping",
        source="prod-raw-db",
    )

    assert plan.source == "prod-raw-db"
    assert plan.request_strategy_key == "bse_mapping:prod-raw-db"
    assert plan.request_count == 1
    assert "raw_tushare/bse_mapping/current/part-000.parquet" in plan.write_paths
    assert "manifest/security_reference/tushare_bse_mapping.parquet" in plan.write_paths


@pytest.mark.parametrize(
    ("dataset_key", "manifest_path"),
    [
        ("hk_basic", "manifest/security_universe/tushare_hk_basic.parquet"),
        ("namechange", "manifest/security_reference/tushare_namechange.parquet"),
        ("stock_company", "manifest/security_reference/tushare_stock_company.parquet"),
        ("st", "manifest/security_reference/tushare_st.parquet"),
    ],
)
def test_prod_raw_snapshot_plan_marks_new_snapshot_dual_write_paths(
    tmp_path,
    dataset_key: str,
    manifest_path: str,
) -> None:
    plan = LakeSyncPlanner(lake_root=tmp_path).plan(
        dataset_key=dataset_key,
        source="prod-raw-db",
    )

    assert plan.source == "prod-raw-db"
    assert plan.request_strategy_key == f"{dataset_key}:prod-raw-db"
    assert plan.request_count == 1
    assert f"raw_tushare/{dataset_key}/current/part-000.parquet" in plan.write_paths
    assert manifest_path in plan.write_paths


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


def test_bse_mapping_prod_raw_export_writes_raw_and_manifest(monkeypatch, tmp_path) -> None:
    pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    def fake_fetch_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.bse_mapping"
        return [
            {
                "name": "示例北交所公司",
                "o_code": "430198.BJ",
                "n_code": "830198.BJ",
                "list_date": date(2020, 7, 27),
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
    ).export(dataset_key="bse_mapping")

    raw_file = tmp_path / "raw_tushare" / "bse_mapping" / "current" / "part-000.parquet"
    manifest_file = tmp_path / "manifest" / "security_reference" / "tushare_bse_mapping.parquet"
    raw_schema = pq.read_schema(raw_file)
    manifest_schema = pq.read_schema(manifest_file)

    assert summary["source"] == "prod-raw-db"
    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert summary["manifest_written_rows"] == 1
    assert raw_file.exists()
    assert manifest_file.exists()
    assert pa.types.is_date(raw_schema.field("list_date").type)
    assert raw_schema.equals(manifest_schema)


def test_hk_basic_prod_raw_export_writes_raw_and_manifest(monkeypatch, tmp_path) -> None:
    pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    def fake_fetch_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.hk_basic"
        return [
            {
                "ts_code": "00001.HK",
                "name": "长和",
                "fullname": "长江和记实业有限公司",
                "enname": "CK Hutchison Holdings Limited",
                "cn_spell": "changhe",
                "market": "港股主板",
                "list_status": "L",
                "list_date": date(1921, 1, 1),
                "delist_date": date(2026, 4, 17),
                "trade_unit": 500,
                "isin": "KYG217651051",
                "curr_type": "HKD",
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
    ).export(dataset_key="hk_basic")

    raw_file = tmp_path / "raw_tushare" / "hk_basic" / "current" / "part-000.parquet"
    manifest_file = tmp_path / "manifest" / "security_universe" / "tushare_hk_basic.parquet"
    raw_schema = pq.read_schema(raw_file)
    manifest_schema = pq.read_schema(manifest_file)

    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert summary["manifest_written_rows"] == 1
    assert pa.types.is_date(raw_schema.field("list_date").type)
    assert pa.types.is_date(raw_schema.field("delist_date").type)
    assert pa.types.is_int64(raw_schema.field("trade_unit").type)
    assert raw_schema.equals(manifest_schema)


def test_namechange_prod_raw_export_writes_raw_and_manifest(monkeypatch, tmp_path) -> None:
    pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    def fake_fetch_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.namechange"
        return [
            {
                "ts_code": "600848.SH",
                "name": "上海临港",
                "start_date": date(2015, 11, 18),
                "end_date": date(2016, 11, 17),
                "ann_date": date(2015, 11, 18),
                "change_reason": "改名",
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
    ).export(dataset_key="namechange")

    raw_file = tmp_path / "raw_tushare" / "namechange" / "current" / "part-000.parquet"
    manifest_file = tmp_path / "manifest" / "security_reference" / "tushare_namechange.parquet"
    raw_schema = pq.read_schema(raw_file)
    manifest_schema = pq.read_schema(manifest_file)

    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert summary["manifest_written_rows"] == 1
    assert pa.types.is_date(raw_schema.field("start_date").type)
    assert pa.types.is_date(raw_schema.field("end_date").type)
    assert pa.types.is_date(raw_schema.field("ann_date").type)
    assert raw_schema.equals(manifest_schema)


def test_stock_company_prod_raw_export_writes_raw_and_manifest(monkeypatch, tmp_path) -> None:
    pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    def fake_fetch_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.stock_company"
        return [
            {
                "ts_code": "000001.SZ",
                "com_name": "平安银行股份有限公司",
                "com_id": "9144030019219991XW",
                "exchange": "SZSE",
                "chairman": "谢永林",
                "manager": "胡跃飞",
                "secretary": "周强",
                "reg_capital": Decimal("1717041.1366"),
                "setup_date": date(1987, 12, 22),
                "province": "广东",
                "city": "深圳",
                "introduction": "示例介绍",
                "website": "https://example.com",
                "email": "ir@example.com",
                "office": "深圳",
                "employees": 1000,
                "main_business": "银行业务",
                "business_scope": "经营范围示例",
                "ann_date": date(2026, 4, 10),
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
    ).export(dataset_key="stock_company")

    raw_file = tmp_path / "raw_tushare" / "stock_company" / "current" / "part-000.parquet"
    manifest_file = tmp_path / "manifest" / "security_reference" / "tushare_stock_company.parquet"
    raw_schema = pq.read_schema(raw_file)
    manifest_schema = pq.read_schema(manifest_file)

    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert summary["manifest_written_rows"] == 1
    assert pa.types.is_date(raw_schema.field("setup_date").type)
    assert pa.types.is_date(raw_schema.field("ann_date").type)
    assert pa.types.is_float64(raw_schema.field("reg_capital").type)
    assert pa.types.is_int64(raw_schema.field("employees").type)
    assert raw_schema.equals(manifest_schema)


def test_st_prod_raw_export_writes_raw_and_manifest(monkeypatch, tmp_path) -> None:
    pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    def fake_fetch_prod_raw_rows(*, database_url, query):
        assert database_url == "postgresql://readonly@example/db"
        assert query.table_name == "raw_tushare.st"
        return [
            {
                "ts_code": "300125.SZ",
                "name": "*ST聆达",
                "pub_date": date(2026, 1, 27),
                "imp_date": date(2026, 1, 28),
                "st_type": "撤销叠加*ST",
                "st_reason": "重整完成或和解协议执行完成或案件结束",
                "st_explain": "示例说明",
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
    ).export(dataset_key="st")

    raw_file = tmp_path / "raw_tushare" / "st" / "current" / "part-000.parquet"
    manifest_file = tmp_path / "manifest" / "security_reference" / "tushare_st.parquet"
    raw_schema = pq.read_schema(raw_file)
    manifest_schema = pq.read_schema(manifest_file)

    assert summary["fetched_rows"] == 1
    assert summary["written_rows"] == 1
    assert summary["manifest_written_rows"] == 1
    assert pa.types.is_date(raw_schema.field("pub_date").type)
    assert pa.types.is_date(raw_schema.field("imp_date").type)
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
