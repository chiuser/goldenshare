from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, timedelta

import pytest

from orchestrator.defs.bootstrap.etf_daily_raw_batch_audit import (
    audit_etf_daily_raw_batch,
    etf_daily_raw_batches,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    audit_etf_daily_basic_coverage,
    audit_etf_daily_domain,
)
from orchestrator.defs.resources import DuckDBResource
from tests.etf_daily_test_support import make_roots, write_raw_fixture
from tests.test_etf_daily_bootstrap import _adj_row, _daily_row


class _CountedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.queries: list[str] = []

    def execute(self, sql):
        self.queries.append(sql)
        return self.connection.execute(sql)


def _basic_table(connection):
    connection.execute("""
        CREATE TEMP TABLE basic (ts_code VARCHAR, exchange VARCHAR, list_status VARCHAR, list_date DATE);
        INSERT INTO basic VALUES
          ('510330.SH', 'SH', 'L', '2020-01-01'),
          ('510001.SH', 'SH', 'L', '2025-01-03'),
          ('510002.SH', 'SH', 'D', '2020-01-01'),
          ('510003.SH', 'SZ', 'L', '2020-01-01'),
          ('510004.SH', 'SH', 'L', NULL),
          ('158008.OF', 'OF', 'L', '2020-01-01')
    """)


@pytest.mark.parametrize(
    "spec,silver_spec,row_builder",
    [
        (FUND_DAILY_RAW_SPEC, FUND_DAILY_SILVER_SPEC, _daily_row),
        (FUND_ADJ_RAW_SPEC, FUND_ADJ_SILVER_SPEC, _adj_row),
    ],
)
def test_batch_matches_single_file_hash_domain_and_coverage(
    tmp_path, spec, silver_spec, row_builder
):
    lake, _ = make_roots(tmp_path)
    dates = ("2025-01-02", "2025-01-03")
    for value in dates:
        rows = [
            row_builder(code, value.replace("-", ""))
            for code in ("510330.SH", "158008.OF")
        ]
        if spec is FUND_DAILY_RAW_SPEC:
            rows[1]["vol"] = -1.0
        else:
            rows[1]["adj_factor"] = -1.0
            rows[1]["discount_rate"] = -100.0
        write_raw_fixture(lake_root=lake, spec=spec, partition_key=value, rows=rows)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in lake.rglob("*.parquet")
    }
    with DuckDBResource().connect() as connection:
        _basic_table(connection)
        batch = audit_etf_daily_raw_batch(
            connection,
            lake_root=lake,
            trade_dates=dates,
            spec=spec,
            basic_relation_sql="basic",
        )
        for index, value in enumerate(dates):
            relation = read_parquet(
                spec.target_path_builder(lake, value), hive_partitioning=False
            )
            single = audit_etf_daily_raw_relation(
                connection, relation_sql=relation, spec=spec, partition_key=value
            )
            observed = batch["files"][index]
            assert observed["row_count"] == single.row_count == 2
            assert observed["content_hash"] == single.content_hash
            assert observed["error_codes"] == list(single.error_codes) == []
            domain = asdict(
                audit_etf_daily_domain(
                    connection, silver_relation_sql=relation, spec=silver_spec
                )
            )
            domain["failure_samples"] = list(domain["failure_samples"])
            profile = next(
                item for item in batch["domain_profiles"] if item["trade_date"] == value
            )
            assert {key: profile[key] for key in domain} == domain
            assert (
                profile["failed_row_count"] == 1
            )  # Raw quality is observation, not rejection.
            matching = f"(SELECT ts_code FROM {relation} WHERE ts_code = '510330.SH')"
            reference = audit_etf_daily_basic_coverage(
                connection,
                raw_relation_sql=relation,
                silver_relation_sql=matching,
                basic_relation_sql="basic",
                partition_key=value,
            )
            coverage = next(
                item
                for item in batch["coverage_profiles"]
                if item["trade_date"] == value
            )
            assert (
                coverage["expected_code_count"]
                == reference.expected_code_count
                == index + 1
            )
            assert coverage["present_code_count"] == 2
            assert (
                coverage["missing_expected_code_count"]
                == reference.missing_expected_code_count
                == index
            )
            assert (
                coverage["raw_extra_code_count"] == reference.raw_extra_code_count == 1
            )
            assert coverage["samples"] == list(reference.failure_samples)
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in lake.rglob("*.parquet")
    }


@pytest.mark.parametrize("day_count", [2, 20])
@pytest.mark.parametrize("profile", [False, True])
def test_query_and_parquet_scan_counts_do_not_grow_with_same_year_dates(
    tmp_path, day_count, profile
):
    lake, _ = make_roots(tmp_path)
    dates = tuple(
        (date(2025, 1, 2) + timedelta(days=index)).isoformat()
        for index in range(day_count)
    )
    for value in dates:
        write_raw_fixture(
            lake_root=lake,
            spec=FUND_ADJ_RAW_SPEC,
            partition_key=value,
            rows=[_adj_row("510330.SH", value.replace("-", ""))],
        )
    with DuckDBResource().connect() as connection:
        _basic_table(connection)
        counted = _CountedConnection(connection)
        batch = audit_etf_daily_raw_batch(
            counted,
            lake_root=lake,
            trade_dates=dates,
            spec=FUND_ADJ_RAW_SPEC,
            basic_relation_sql="basic" if profile else None,
        )
        assert (
            batch["performance"]["sql_query_count"]
            == len(counted.queries)
            == (11 if profile else 5)
        )
        assert sum("read_parquet(" in sql for sql in counted.queries) == 1
        assert sum("parquet_schema(" in sql for sql in counted.queries) == 1
        assert batch["performance"]["row_count"] == day_count
        assert (
            connection.execute(
                "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'etf_daily_bootstrap_%'"
            ).fetchall()
            == []
        )
        if not profile:
            assert batch["domain_profiles"] == batch["coverage_profiles"] == []
            assert all("basic" not in sql for sql in counted.queries)


def test_batches_only_expand_by_asset_and_year():
    groups = list(etf_daily_raw_batches(("2025-12-31", "2026-01-05", "2026-01-06")))
    assert [(spec.api_name, dates) for spec, dates in groups] == [
        ("fund_daily", ("2025-12-31",)),
        ("fund_daily", ("2026-01-05", "2026-01-06")),
        ("fund_adj", ("2025-12-31",)),
        ("fund_adj", ("2026-01-05", "2026-01-06")),
    ]
    with pytest.raises(ValueError, match="unique and sorted"):
        list(etf_daily_raw_batches(("2025-01-02", "2025-01-02")))


@pytest.mark.parametrize(
    "fault,match",
    [
        ("missing", "missing"),
        ("unreadable", "Parquet"),
        ("schema_columns", "schema_columns"),
        ("schema_types", "schema_types"),
        ("schema_order", "schema_columns"),
        ("empty", "empty_partition"),
        ("null_key", "invalid_key"),
        ("duplicate", "duplicate_key"),
        ("wrong_date", "partition_date"),
        ("null_date", "invalid_key"),
    ],
)
def test_batch_rejects_bad_second_file_without_union_or_hive_masking(
    tmp_path, fault, match
):
    lake, _ = make_roots(tmp_path)
    spec = FUND_ADJ_RAW_SPEC
    dates = ("2025-01-02", "2025-01-03")
    write_raw_fixture(
        lake_root=lake,
        spec=spec,
        partition_key=dates[0],
        rows=[_adj_row("510330.SH", "20250102")],
    )
    path = spec.target_path_builder(lake, dates[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    if fault == "unreadable":
        path.write_bytes(b"not parquet")
    elif fault != "missing":
        if fault.startswith("schema") or fault == "empty":
            columns = [
                "'510330.SH'::VARCHAR AS ts_code",
                "'20250103'::VARCHAR AS trade_date",
                "1.0::DOUBLE AS adj_factor",
                "NULL::DOUBLE AS discount_rate",
            ]
            if fault == "schema_columns":
                columns.pop()
            elif fault == "schema_types":
                columns[2] = "1::INTEGER AS adj_factor"
            elif fault == "schema_order":
                columns[2], columns[3] = columns[3], columns[2]
            with DuckDBResource().connect() as connection:
                connection.execute(
                    f"COPY (SELECT {', '.join(columns)} {'WHERE false' if fault == 'empty' else ''}) TO {duckdb_string(path)} (FORMAT PARQUET)"
                )
        else:
            row = _adj_row("510330.SH", "20250103")
            if fault == "null_key":
                row["ts_code"] = None
            elif fault == "wrong_date":
                row["trade_date"] = "20250102"
            elif fault == "null_date":
                row["trade_date"] = None
            write_raw_fixture(
                lake_root=lake,
                spec=spec,
                partition_key=dates[1],
                rows=[row, row] if fault == "duplicate" else [row],
            )
    with DuckDBResource().connect() as connection:
        with pytest.raises(Exception, match=match):
            audit_etf_daily_raw_batch(
                connection, lake_root=lake, trade_dates=dates, spec=spec
            )
        assert (
            connection.execute(
                "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'etf_daily_bootstrap_%'"
            ).fetchall()
            == []
        )


def test_hash_keeps_preexisting_canonical_bytes(tmp_path):
    lake, _ = make_roots(tmp_path)
    row = _adj_row("510330.SH", "20250102")
    write_raw_fixture(
        lake_root=lake, spec=FUND_ADJ_RAW_SPEC, partition_key="2025-01-02", rows=[row]
    )
    canonical = '{"ts_code":"510330.SH","trade_date":"20250102","adj_factor":1.0,"discount_rate":null}'
    assert canonical == json.dumps(row, separators=(",", ":"))
    with DuckDBResource().connect() as connection:
        batch = audit_etf_daily_raw_batch(
            connection,
            lake_root=lake,
            trade_dates=("2025-01-02",),
            spec=FUND_ADJ_RAW_SPEC,
        )
    assert (
        batch["files"][0]["content_hash"]
        == hashlib.sha256(canonical.encode()).hexdigest()
    )


def test_profile_samples_are_limited_per_date_and_keep_missing_before_extras(tmp_path):
    lake, _ = make_roots(tmp_path)
    dates = ("2025-01-02", "2025-01-03")
    for value in dates:
        rows = [
            {**_adj_row(f"{index:06}.OF", value.replace("-", "")), "adj_factor": 0.0}
            for index in range(30)
        ]
        write_raw_fixture(
            lake_root=lake, spec=FUND_ADJ_RAW_SPEC, partition_key=value, rows=rows
        )
    with DuckDBResource().connect() as connection:
        _basic_table(connection)
        batch = audit_etf_daily_raw_batch(
            connection,
            lake_root=lake,
            trade_dates=dates,
            spec=FUND_ADJ_RAW_SPEC,
            basic_relation_sql="basic",
        )
    for profile in batch["domain_profiles"]:
        assert profile["failed_row_count"] == 30
        assert len(profile["failure_samples"]) == 20
    for profile in batch["coverage_profiles"]:
        assert len(profile["samples"]) == 20
        assert profile["raw_extra_code_count"] == 30
        assert profile["samples"][0]["reason_code"] == "MISSING_EXPECTED_CODE"
