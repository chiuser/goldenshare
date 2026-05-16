from __future__ import annotations

from datetime import date

import pytest

from lake_console.backend.app.services.prod_raw_event_date_db import (
    PROD_RAW_EVENT_DATE_DATASET_SPECS,
    PROD_RAW_EVENT_DATE_SYSTEM_FIELDS,
    build_event_date_null_count_query,
    build_event_date_detail_query,
    build_event_date_partition_counts_query,
    get_event_date_dataset_spec,
    list_event_date_dataset_keys,
)


def test_event_date_dataset_specs_are_safe() -> None:
    assert list_event_date_dataset_keys() == ("anns_d", "irm_qa_sh", "irm_qa_sz", "research_report")
    for dataset_key, spec in PROD_RAW_EVENT_DATE_DATASET_SPECS.items():
        assert spec.table_name.startswith("raw_tushare.")
        assert not (set(spec.fields) & PROD_RAW_EVENT_DATE_SYSTEM_FIELDS), dataset_key
        assert "*" not in spec.fields


def test_event_date_partition_counts_query_uses_source_date_field() -> None:
    query = build_event_date_partition_counts_query(
        dataset_key="anns_d",
        start_date=date(2026, 5, 13),
        end_date=date(2026, 5, 15),
    )

    normalized_sql = " ".join(query.sql.lower().split())
    assert "select ann_date as event_date, count(*) as source_row_count" in normalized_sql
    assert "from raw_tushare.anns_d" in normalized_sql
    assert "where ann_date >= %s and ann_date <= %s" in normalized_sql
    assert "select *" not in normalized_sql
    assert query.params == (date(2026, 5, 13), date(2026, 5, 15))


def test_event_date_detail_query_uses_field_whitelist() -> None:
    query = build_event_date_detail_query(dataset_key="irm_qa_sz", event_date=date(2026, 5, 15))

    normalized_sql = " ".join(query.sql.lower().split())
    assert normalized_sql == (
        "select ts_code, name, trade_date, q, a, pub_time, industry "
        "from raw_tushare.irm_qa_sz "
        "where trade_date = %s "
        "order by trade_date, ts_code, pub_time, q"
    )
    assert query.params == (date(2026, 5, 15),)
    assert set(query.fields) == {"ts_code", "name", "trade_date", "q", "a", "pub_time", "industry"}
    assert not (set(query.fields) & PROD_RAW_EVENT_DATE_SYSTEM_FIELDS)


def test_event_date_query_rejects_unknown_dataset() -> None:
    with pytest.raises(ValueError, match="prod-db-event-date 只允许数据集"):
        get_event_date_dataset_spec("broker_recommend")


def test_research_report_null_count_query_is_explicit() -> None:
    query = build_event_date_null_count_query(dataset_key="research_report")

    normalized_sql = " ".join(query.sql.lower().split())
    assert normalized_sql == (
        "select count(*) as null_date_count "
        "from raw_tushare.research_report "
        "where trade_date is null"
    )
