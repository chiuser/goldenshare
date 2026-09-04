from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap.etf_daily_physical_batch_audit import (
    audit_etf_daily_physical_batch,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import audit_etf_daily_raw_relation
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    audit_etf_daily_basic_coverage,
    audit_etf_daily_domain,
    audit_etf_daily_silver_relation,
    audit_etf_daily_source_filter,
    audit_etf_daily_source_parity,
)
from orchestrator.defs.resources import DuckDBResource
from tests.etf_daily_test_support import (
    basic_row,
    make_roots,
    write_basic_reference,
    write_raw_fixture,
)
from tests.test_etf_daily_bootstrap import _adj_row, _daily_row
from tests.test_etf_daily_raw_batch_audit import _CountedConnection


def _fixture(tmp_path, spec, dates, fault="none"):
    lake, staging = make_roots(tmp_path)
    reference = write_basic_reference(
        lake_root=lake,
        staging_root=staging,
        rows=(basic_row("510330.SH"), basic_row("159919.SZ", list_date="20250103")),
    )
    row_builder = _daily_row if spec is FUND_DAILY_SILVER_SPEC else _adj_row
    for index, value in enumerate(dates):
        rows = [
            row_builder(code, value.replace("-", ""))
            for code in ("510330.SH", "159919.SZ", "158008.OF", "599999.SH")
        ]
        if index == 1 and fault == "domain":
            rows[0]["vol" if spec is FUND_DAILY_SILVER_SPEC else "adj_factor"] = -1.0
        raw = write_raw_fixture(
            lake_root=lake, spec=spec.raw_spec, partition_key=value, rows=rows
        )
        silver = spec.target_path_builder(lake, value)
        silver.parent.mkdir(parents=True, exist_ok=True)
        columns = ", ".join(
            "strptime(trade_date, '%Y%m%d')::DATE AS trade_date"
            if name == "trade_date"
            else f'"{name}"'
            for name in spec.source_columns
        )
        sql = f"""SELECT {columns} FROM {read_parquet(raw, hive_partitioning=False)}
                  WHERE ts_code = '510330.SH' OR (ts_code = '159919.SZ' AND trade_date >= '20250103')"""
        if index == 1:
            if fault == "changed_value":
                field = "amount" if spec is FUND_DAILY_SILVER_SPEC else "discount_rate"
                sql = f'SELECT * REPLACE (123.0::DOUBLE AS "{field}") FROM ({sql})'
            elif fault == "duplicate":
                sql = f"({sql}) UNION ALL ({sql})"
            elif fault == "wrong_date":
                sql = f"SELECT * REPLACE ((trade_date + 1)::DATE AS trade_date) FROM ({sql})"
            elif fault == "null_key":
                sql = f"SELECT * REPLACE (NULL::VARCHAR AS ts_code) FROM ({sql})"
            elif fault == "null_date":
                sql = f"SELECT * REPLACE (NULL::DATE AS trade_date) FROM ({sql})"
            elif fault == "empty":
                sql = f"SELECT * FROM ({sql}) WHERE false"
            elif fault == "source_filter":
                sql = f"SELECT {columns} FROM {read_parquet(raw, hive_partitioning=False)}"
        with DuckDBResource().connect() as connection:
            connection.execute(
                f"COPY ({sql}) TO {duckdb_string(silver)} (FORMAT PARQUET)"
            )
    return lake, reference


def _single_evidence(connection, lake, value, spec, reference):
    raw_path = spec.raw_spec.target_path_builder(lake, value)
    path = spec.target_path_builder(lake, value)
    raw_sql = read_parquet(raw_path, hive_partitioning=False)
    silver_sql = read_parquet(path, hive_partitioning=False)
    basic_sql = read_parquet(Path(reference.silver_uri), hive_partitioning=False)
    raw = audit_etf_daily_raw_relation(
        connection, relation_sql=raw_sql, spec=spec.raw_spec, partition_key=value
    )
    silver = audit_etf_daily_silver_relation(
        connection, relation_sql=silver_sql, spec=spec, partition_key=value
    )
    filtering = audit_etf_daily_source_filter(
        connection, silver_relation_sql=silver_sql, basic_relation_sql=basic_sql
    )
    parity = audit_etf_daily_source_parity(
        connection,
        raw_relation_sql=raw_sql,
        silver_relation_sql=silver_sql,
        basic_relation_sql=basic_sql,
        spec=spec,
    )
    domain = audit_etf_daily_domain(
        connection, silver_relation_sql=silver_sql, spec=spec
    )
    coverage = audit_etf_daily_basic_coverage(
        connection,
        raw_relation_sql=raw_sql,
        silver_relation_sql=silver_sql,
        basic_relation_sql=basic_sql,
        partition_key=value,
    )
    errors = list(
        silver.error_codes
        + filtering.error_codes
        + parity.error_codes
        + domain.error_codes
    )
    if spec is FUND_ADJ_SILVER_SPEC:
        errors.extend(coverage.error_codes)
    return [
        {
            "asset_key": spec.raw_spec.asset_key,
            "trade_date": value,
            "target_path": str(raw_path),
            "row_count": raw.row_count,
            "content_hash": raw.content_hash,
            "source_row_count": raw.row_count,
            "normalized_row_count": raw.row_count,
            "written_row_count": raw.row_count,
            "source_fields": list(spec.source_columns),
            "errors": list(raw.error_codes),
            "passed": not raw.error_codes,
        },
        {
            "asset_key": spec.asset_key,
            "trade_date": value,
            "target_path": str(path),
            "row_count": silver.row_count,
            "content_hash": silver.content_hash,
            "raw_row_count": parity.raw_row_count,
            "selected_row_count": parity.selected_row_count,
            "rejected_row_count": parity.rejected_row_count,
            "written_row_count": silver.row_count,
            "reject_reason_counts": dict(parity.reason_counts),
            "basic_reference": reference.model_dump(mode="json"),
            "basic_reference_fingerprint": reference.reference_fingerprint,
            "basic_raw_snapshot_hash": reference.raw_snapshot_hash,
            "basic_silver_content_hash": reference.silver_content_hash,
            "basic_raw_uri": reference.raw_uri,
            "basic_silver_uri": reference.silver_uri,
            "source_fields": list(spec.source_columns),
            "coverage_warning": spec is FUND_DAILY_SILVER_SPEC and coverage.has_warning,
            "coverage_error_codes": list(coverage.error_codes),
            "missing_expected_code_count": coverage.missing_expected_code_count,
            "silver_extra_code_count": coverage.silver_extra_code_count,
            "errors": errors,
            "passed": not errors,
        },
    ]


@pytest.mark.parametrize("spec", [FUND_DAILY_SILVER_SPEC, FUND_ADJ_SILVER_SPEC])
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "changed_value",
        "duplicate",
        "wrong_date",
        "null_key",
        "null_date",
        "empty",
        "source_filter",
        "domain",
    ],
)
def test_every_file_evidence_matches_single_file_checks(tmp_path, spec, fault):
    dates = ("2025-01-02", "2025-01-03")
    lake, reference = _fixture(tmp_path, spec, dates, fault)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in lake.rglob("*.parquet")
    }
    with DuckDBResource().connect() as connection:
        batch = audit_etf_daily_physical_batch(
            connection,
            lake_root=lake,
            trade_dates=dates,
            spec=spec,
            basic_sql=read_parquet(Path(reference.silver_uri), hive_partitioning=False),
            basic_reference=reference,
        )
        expected = [
            item
            for value in dates
            for item in _single_evidence(connection, lake, value, spec, reference)
        ]
        assert batch["files"] == expected
        assert batch["files"][1]["passed"] is True
        assert batch["files"][3]["passed"] is (fault == "none")
        if fault == "empty":
            assert batch["files"][3]["missing_expected_code_count"] == 2
        if fault == "changed_value":
            assert "expected_rows_missing" in batch["files"][3]["errors"]
            assert "unexpected_silver_rows" in batch["files"][3]["errors"]
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in lake.rglob("*.parquet")
    }


@pytest.mark.parametrize("days", [2, 20])
def test_physical_query_budget_is_per_year_not_per_date(tmp_path, days):
    dates = tuple(
        (date(2025, 1, 2) + timedelta(days=index)).isoformat() for index in range(days)
    )
    spec = FUND_ADJ_SILVER_SPEC
    lake, reference = _fixture(tmp_path, spec, dates)
    with DuckDBResource().connect() as connection:
        # Materialize Basic only for counting the three *dataset* loads, not its small snapshot reads.
        connection.execute(
            f"CREATE TEMP TABLE basic AS SELECT * FROM {read_parquet(Path(reference.silver_uri), hive_partitioning=False)}"
        )
        counted = _CountedConnection(connection)
        batch = audit_etf_daily_physical_batch(
            counted,
            lake_root=lake,
            trade_dates=dates,
            spec=spec,
            basic_sql="basic",
            basic_reference=reference,
        )
        assert batch["performance"]["sql_query_count"] == len(counted.queries) == 15
        assert sum("read_parquet(" in sql for sql in counted.queries) == 3
        assert sum("parquet_schema(" in sql for sql in counted.queries) == 2
        assert len(batch["files"]) == days * 2
        assert batch["performance"]["raw_data_load_count"] == 2
        assert batch["performance"]["silver_data_load_count"] == 1
        assert (
            connection.execute(
                "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'etf_daily_%'"
            ).fetchall()
            == []
        )


@pytest.mark.parametrize(
    "fault", ["schema_columns", "schema_types", "schema_order", "missing", "unreadable"]
)
def test_bad_second_silver_file_cannot_be_hidden_by_batch_schema(tmp_path, fault):
    dates = ("2025-01-02", "2025-01-03")
    spec = FUND_ADJ_SILVER_SPEC
    lake, reference = _fixture(tmp_path, spec, dates)
    path = spec.target_path_builder(lake, dates[1])
    if fault == "missing":
        path.unlink()
    elif fault == "unreadable":
        path.write_bytes(b"not parquet")
    else:
        with DuckDBResource().connect() as connection:
            connection.execute(
                f"CREATE TEMP TABLE original AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
            )
            projection = {
                "schema_columns": "* EXCLUDE (discount_rate)",
                "schema_types": "* REPLACE (trade_date::VARCHAR AS trade_date)",
                "schema_order": "trade_date, ts_code, adj_factor, discount_rate",
            }[fault]
            connection.execute(
                f"COPY (SELECT {projection} FROM original) TO {duckdb_string(path)} (FORMAT PARQUET)"
            )
    with DuckDBResource().connect() as connection, pytest.raises(
        Exception, match="schema_columns/schema_types|No files found|Parquet"
    ):
        audit_etf_daily_physical_batch(
            connection,
            lake_root=lake,
            trade_dates=dates,
            spec=spec,
            basic_sql=read_parquet(
                Path(reference.silver_uri), hive_partitioning=False
            ),
            basic_reference=reference,
        )
