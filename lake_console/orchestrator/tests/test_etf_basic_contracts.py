from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal

import duckdb
import pytest

from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_ETF_BASIC_SCHEMA,
    SILVER_ETF_BASIC_SCHEMA,
)
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_CODE_SUFFIXES,
    ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_BASIC_LIST_STATUSES,
    ETF_BASIC_PAGE_LIMIT,
    ETF_BASIC_REQUESTABILITY_EXCHANGE_MISMATCH,
    ETF_BASIC_REQUESTABILITY_LIST_DATE_AFTER_AS_OF,
    ETF_BASIC_REQUESTABILITY_LIST_DATE_NULL,
    ETF_BASIC_REQUESTABILITY_NON_EXCHANGE_SUFFIX,
    ETF_BASIC_REQUESTABILITY_STATUS_NOT_LISTED,
    ETF_BASIC_SILVER_SUFFIXES,
    ETF_BASIC_SOURCE_API,
    ETF_BASIC_SOURCE_COLUMNS,
    classify_etf_basic_requestability,
    compute_etf_basic_silver_content_hash,
    compute_etf_basic_snapshot_hash,
    compute_etf_requestable_target_hash,
    normalize_etf_basic_snapshot_rows,
)


def _raw_rows() -> list[dict[str, object]]:
    return [
        {
            "ts_code": "510300.SH",
            "csname": "沪深300ETF",
            "extname": None,
            "cname": "华泰柏瑞沪深300交易型开放式指数证券投资基金",
            "index_code": "000300.SH",
            "index_name": "沪深300指数",
            "setup_date": "20120504",
            "list_date": "20120528",
            "list_status": "L",
            "exchange": "SH",
            "mgr_name": "华泰柏瑞基金",
            "custod_name": "中国工商银行",
            "mgt_fee": 0.5,
            "etf_type": "境内",
        },
        {
            "ts_code": "159001.OF",
            "csname": "源端场外样本",
            "extname": None,
            "cname": None,
            "index_code": None,
            "index_name": None,
            "setup_date": None,
            "list_date": None,
            "list_status": "D",
            "exchange": None,
            "mgr_name": None,
            "custod_name": None,
            "mgt_fee": None,
            "etf_type": "QDII",
        },
    ]


def _silver_rows() -> list[dict[str, object]]:
    row = deepcopy(_raw_rows()[0])
    row["setup_date"] = date(2012, 5, 4)
    row["list_date"] = date(2012, 5, 28)
    row["mgt_fee"] = Decimal("0.500000")
    return [row]


def test_source_and_schema_contracts_freeze_all_fourteen_fields() -> None:
    assert ETF_BASIC_SOURCE_API == "etf_basic"
    assert ETF_BASIC_PAGE_LIMIT == 5_000
    assert ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT == 20
    assert ETF_BASIC_LIST_STATUSES == ("D", "L", "P")
    assert ETF_BASIC_CODE_SUFFIXES == ("OF", "SH", "SZ")
    assert ETF_BASIC_SILVER_SUFFIXES == ("SH", "SZ")
    assert tuple(column.name for column in RAW_TUSHARE_ETF_BASIC_SCHEMA) == (
        ETF_BASIC_SOURCE_COLUMNS
    )
    assert tuple(column.name for column in SILVER_ETF_BASIC_SCHEMA) == (
        ETF_BASIC_SOURCE_COLUMNS
    )
    assert tuple(column.type for column in RAW_TUSHARE_ETF_BASIC_SCHEMA) == (
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "VARCHAR",
        "DOUBLE",
        "VARCHAR",
    )
    assert SILVER_ETF_BASIC_SCHEMA[6].type == "DATE"
    assert SILVER_ETF_BASIC_SCHEMA[7].type == "DATE"
    assert SILVER_ETF_BASIC_SCHEMA[12].type == "DECIMAL(12,6)"


def test_raw_snapshot_hash_has_a_fixed_post_parquet_fixture() -> None:
    rows = _raw_rows()

    expected_hash = "9ac465d85be0192e582dafd3320bd40dec55d1c4da8e8cea4131a0d1886ddfd8"
    assert compute_etf_basic_snapshot_hash(rows) == expected_hash
    assert compute_etf_basic_snapshot_hash(reversed(rows)) == expected_hash
    assert [row["ts_code"] for row in normalize_etf_basic_snapshot_rows(rows)] == [
        "159001.OF",
        "510300.SH",
    ]


def test_raw_snapshot_hash_is_stable_after_parquet_round_trip(tmp_path) -> None:
    rows = _raw_rows()
    target = tmp_path / "etf-basic.parquet"

    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE snapshot (
              ts_code VARCHAR,
              csname VARCHAR,
              extname VARCHAR,
              cname VARCHAR,
              index_code VARCHAR,
              index_name VARCHAR,
              setup_date VARCHAR,
              list_date VARCHAR,
              list_status VARCHAR,
              exchange VARCHAR,
              mgr_name VARCHAR,
              custod_name VARCHAR,
              mgt_fee DOUBLE,
              etf_type VARCHAR
            )
            """
        )
        connection.executemany(
            f"INSERT INTO snapshot VALUES ({', '.join('?' for _ in ETF_BASIC_SOURCE_COLUMNS)})",
            [tuple(row[column] for column in ETF_BASIC_SOURCE_COLUMNS) for row in rows],
        )
        connection.execute("COPY snapshot TO ? (FORMAT PARQUET)", [str(target)])
        cursor = connection.execute(
            "SELECT * FROM read_parquet(?, hive_partitioning=false)",
            [str(target)],
        )
        columns = tuple(item[0] for item in cursor.description)
        round_tripped = [dict(zip(columns, values, strict=True)) for values in cursor.fetchall()]

    assert compute_etf_basic_snapshot_hash(round_tripped) == (
        compute_etf_basic_snapshot_hash(rows)
    )


@pytest.mark.parametrize("column", ETF_BASIC_SOURCE_COLUMNS)
def test_raw_snapshot_hash_changes_when_any_business_field_changes(column: str) -> None:
    rows = _raw_rows()
    changed = deepcopy(rows)
    if column == "mgt_fee":
        changed[0][column] = 0.6
    else:
        changed[0][column] = f"changed-{column}"
        if column == "ts_code":
            changed[0][column] = "510301.SH"
        elif column == "list_status":
            changed[0][column] = "P"
        elif column == "exchange":
            changed[0]["ts_code"] = "159915.SZ"
            changed[0][column] = "SZ"

    assert compute_etf_basic_snapshot_hash(changed) != (
        compute_etf_basic_snapshot_hash(rows)
    )


def test_silver_content_hash_has_a_fixed_date_and_decimal_fixture() -> None:
    rows = _silver_rows()

    expected_hash = "6f30f2f0fe431d5fe8adcd8689fbfe233048fa8624322602efaf519c03ea9c5d"
    assert compute_etf_basic_silver_content_hash(rows) == expected_hash
    rows[0]["mgt_fee"] = Decimal("0.5")
    assert compute_etf_basic_silver_content_hash(rows) == expected_hash


def test_requestability_matches_prod_serving_rules() -> None:
    eligible = _silver_rows()[0]
    as_of = date(2026, 5, 3)

    assert (
        classify_etf_basic_requestability(eligible, eligibility_as_of=as_of) is None
    )

    cases = (
        ({**eligible, "ts_code": "159001.OF"}, ETF_BASIC_REQUESTABILITY_NON_EXCHANGE_SUFFIX),
        ({**eligible, "exchange": "SZ"}, ETF_BASIC_REQUESTABILITY_EXCHANGE_MISMATCH),
        ({**eligible, "list_status": "D"}, ETF_BASIC_REQUESTABILITY_STATUS_NOT_LISTED),
        ({**eligible, "list_date": None}, ETF_BASIC_REQUESTABILITY_LIST_DATE_NULL),
        (
            {**eligible, "list_date": date(2026, 5, 4)},
            ETF_BASIC_REQUESTABILITY_LIST_DATE_AFTER_AS_OF,
        ),
    )
    for row, expected_reason in cases:
        assert classify_etf_basic_requestability(
            row,
            eligibility_as_of=as_of,
        ) == expected_reason


def test_requestable_target_hash_matches_the_prod_payload_contract() -> None:
    targets = (
        {"ts_code": "510300.SH", "list_date": date(2012, 5, 28), "exchange": "SH"},
        {"ts_code": "159915.SZ", "list_date": date(2011, 12, 9), "exchange": "SZ"},
    )

    expected_hash = "4bf87c51d3679d43d74fd5e277602ff09b0c313b95390ce529b5c2721eecff35"
    assert compute_etf_requestable_target_hash(targets) == expected_hash
    assert compute_etf_requestable_target_hash(reversed(targets)) == (
        expected_hash
    )


def test_raw_normalization_rejects_contract_drift_and_identity_pollution() -> None:
    rows = _raw_rows()
    bad_rows = []

    missing_column = deepcopy(rows)
    del missing_column[0]["etf_type"]
    bad_rows.append(missing_column)

    duplicate_code = deepcopy(rows)
    duplicate_code[1]["ts_code"] = duplicate_code[0]["ts_code"]
    duplicate_code[1]["exchange"] = "SH"
    bad_rows.append(duplicate_code)

    unknown_status = deepcopy(rows)
    unknown_status[0]["list_status"] = "X"
    bad_rows.append(unknown_status)

    unknown_suffix = deepcopy(rows)
    unknown_suffix[0]["ts_code"] = "510300.BJ"
    bad_rows.append(unknown_suffix)

    exchange_mismatch = deepcopy(rows)
    exchange_mismatch[0]["exchange"] = "SZ"
    bad_rows.append(exchange_mismatch)

    for invalid_rows in bad_rows:
        with pytest.raises(ValueError):
            normalize_etf_basic_snapshot_rows(invalid_rows)
