from __future__ import annotations

import ast
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.assets import etf_mins as etf_mins_assets
from orchestrator.defs.assets.etf_mins import (
    EtfMinsRawWriteError,
    build_etf_mins_raw_materialization_metadata,
    write_raw_etf_mins_partition_from_prod_db,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string
from orchestrator.defs.paths import (
    etf_mins_staging_path,
    raw_etf_basic_snapshot_path,
    raw_etf_mins_path,
    silver_etf_basic_snapshot_path,
)
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_SOURCE_COLUMNS,
    build_etf_basic_silver_snapshot_reference,
    compute_etf_basic_silver_content_hash,
    compute_etf_basic_snapshot_hash,
    compute_etf_requestable_target_hash,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_SOURCE_COLUMNS,
    ETF_MINS_SOURCE_FREQS,
    EtfMinsRequestableTarget,
    build_etf_mins_prod_coverage_reference,
    compute_etf_mins_expected_code_hash,
)

TRADE_DATE = "2026-08-28"


class TestDuckDBResource:
    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with duckdb.connect(":memory:") as connection:
            yield connection


class FakeProdPostgres:
    def __init__(self) -> None:
        self.conninfo_calls = 0

    def duckdb_connection_string(self) -> str:
        self.conninfo_calls += 1
        return "host=fake dbname=fake"


def _basic_raw_row(
    ts_code: str,
    *,
    list_date: str,
    list_status: str,
    exchange: str,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "csname": f"ETF-{ts_code}",
        "extname": None,
        "cname": None,
        "index_code": None,
        "index_name": None,
        "setup_date": "20120101",
        "list_date": list_date,
        "list_status": list_status,
        "exchange": exchange,
        "mgr_name": None,
        "custod_name": None,
        "mgt_fee": 0.5,
        "etf_type": "境内",
    }


def _write_basic_pair(
    *,
    lake_root: Path,
) -> tuple[object, tuple[EtfMinsRequestableTarget, ...]]:
    raw_rows = (
        _basic_raw_row(
            "510300.SH",
            list_date="20120528",
            list_status="L",
            exchange="SH",
        ),
        _basic_raw_row(
            "159915.SZ",
            list_date="20260901",
            list_status="L",
            exchange="SZ",
        ),
        _basic_raw_row(
            "510500.SH",
            list_date="20130218",
            list_status="D",
            exchange="SH",
        ),
    )
    silver_rows = tuple(
        {
            **row,
            "setup_date": date.fromisoformat(
                f"{str(row['setup_date'])[:4]}-{str(row['setup_date'])[4:6]}-"
                f"{str(row['setup_date'])[6:]}"
            ),
            "list_date": date.fromisoformat(
                f"{str(row['list_date'])[:4]}-{str(row['list_date'])[4:6]}-"
                f"{str(row['list_date'])[6:]}"
            ),
        }
        for row in raw_rows
    )
    raw_hash = compute_etf_basic_snapshot_hash(raw_rows)
    silver_hash = compute_etf_basic_silver_content_hash(silver_rows)
    raw_path = raw_etf_basic_snapshot_path(lake_root, raw_hash)
    silver_path = silver_etf_basic_snapshot_path(lake_root, raw_hash)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    silver_path.parent.mkdir(parents=True, exist_ok=True)

    raw_schema = """
      ts_code VARCHAR, csname VARCHAR, extname VARCHAR, cname VARCHAR,
      index_code VARCHAR, index_name VARCHAR, setup_date VARCHAR,
      list_date VARCHAR, list_status VARCHAR, exchange VARCHAR,
      mgr_name VARCHAR, custod_name VARCHAR, mgt_fee DOUBLE, etf_type VARCHAR
    """
    silver_schema = """
      ts_code VARCHAR, csname VARCHAR, extname VARCHAR, cname VARCHAR,
      index_code VARCHAR, index_name VARCHAR, setup_date DATE,
      list_date DATE, list_status VARCHAR, exchange VARCHAR,
      mgr_name VARCHAR, custod_name VARCHAR, mgt_fee DECIMAL(12, 6),
      etf_type VARCHAR
    """
    placeholders = ", ".join("?" for _ in ETF_BASIC_SOURCE_COLUMNS)
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"CREATE TABLE basic_raw ({raw_schema})")
        connection.execute(f"CREATE TABLE basic_silver ({silver_schema})")
        connection.executemany(
            f"INSERT INTO basic_raw VALUES ({placeholders})",
            [tuple(row[column] for column in ETF_BASIC_SOURCE_COLUMNS) for row in raw_rows],
        )
        connection.executemany(
            f"INSERT INTO basic_silver VALUES ({placeholders})",
            [
                tuple(row[column] for column in ETF_BASIC_SOURCE_COLUMNS)
                for row in silver_rows
            ],
        )
        connection.execute(
            copy_query_to_parquet("SELECT * FROM basic_raw ORDER BY ts_code", raw_path)
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM basic_silver ORDER BY ts_code",
                silver_path,
            )
        )

    requestable_rows = tuple(
        row for row in silver_rows if row["list_status"] == "L"
    )
    requestable_targets = tuple(
        EtfMinsRequestableTarget(
            ts_code=str(row["ts_code"]),
            list_date=row["list_date"],  # type: ignore[arg-type]
            exchange=str(row["exchange"]),
        )
        for row in requestable_rows
    )
    reference = build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash=raw_hash,
        silver_content_hash=silver_hash,
        raw_uri=str(raw_path),
        silver_uri=str(silver_path),
        raw_observed_at="2026-09-30T08:00:00+08:00",
        silver_observed_at="2026-09-30T08:05:00+08:00",
        eligibility_as_of="2026-09-30",
        requestable_code_count=len(requestable_rows),
        requestable_code_hash=compute_etf_requestable_target_hash(
            requestable_rows
        ),
    )
    return reference, requestable_targets


def _coverage_reference(reference, targets: Sequence[EtfMinsRequestableTarget]):  # type: ignore[no-untyped-def]
    return build_etf_mins_prod_coverage_reference(
        trade_date=TRADE_DATE,
        basic_reference_fingerprint=reference.reference_fingerprint,
        expected_code_count=1,
        expected_code_hash=compute_etf_mins_expected_code_hash(
            targets,
            trade_date=TRADE_DATE,
        ),
        frequency_coverages=(
            (source_freq, 1, 1, 0) for source_freq in ETF_MINS_SOURCE_FREQS
        ),
        coverage_observed_at="2026-09-30T18:00:00+08:00",
    )


def _minute_row(
    *,
    ts_code: str,
    source_freq: str,
    trade_time: str = "2026-08-28T09:31:00",
    close: float = 10.1,
) -> tuple[object, ...]:
    exchange = "XSHG" if ts_code.endswith(".SH") else "XSHE"
    return (
        ts_code,
        source_freq,
        datetime.fromisoformat(trade_time),
        10.0,
        close,
        10.2,
        9.9,
        100,
        1000.0,
        10.05,
        exchange,
    )


def _patch_fake_prod_source(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[tuple[object, ...]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    source_sql_calls: list[tuple[str, str, str]] = []
    attach_calls: list[str] = []

    def attach(
        connection: duckdb.DuckDBPyConnection,
        *,
        postgres_connection_string: str,
    ) -> None:
        attach_calls.append(postgres_connection_string)
        connection.execute(
            """
            CREATE TABLE fake_prod_etf_mins (
              ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
              open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
              vol BIGINT, amount DOUBLE, vwap DOUBLE, exchange VARCHAR
            )
            """
        )
        if rows:
            placeholders = ", ".join("?" for _ in ETF_MINS_SOURCE_COLUMNS)
            connection.executemany(
                f"INSERT INTO fake_prod_etf_mins VALUES ({placeholders})",
                rows,
            )

    def source_sql(
        *,
        source_freq: str,
        start_datetime: str,
        end_datetime: str,
    ) -> str:
        source_sql_calls.append((source_freq, start_datetime, end_datetime))
        return (
            "SELECT "
            + ", ".join(ETF_MINS_SOURCE_COLUMNS)
            + " FROM fake_prod_etf_mins WHERE freq = "
            + duckdb_string(source_freq)
            + " AND trade_time >= TIMESTAMP "
            + duckdb_string(start_datetime)
            + " AND trade_time < TIMESTAMP "
            + duckdb_string(end_datetime)
        )

    monkeypatch.setattr(etf_mins_assets, "_load_duckdb_postgres_extension", lambda _: None)
    monkeypatch.setattr(etf_mins_assets, "_attach_prod_etf_mins_readonly", attach)
    monkeypatch.setattr(
        etf_mins_assets,
        "build_prod_etf_mins_duckdb_source_sql",
        source_sql,
    )
    return source_sql_calls, attach_calls


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir(parents=True)
    staging_root.mkdir(parents=True)
    return lake_root, staging_root


def test_five_writers_issue_exactly_five_detail_queries_and_build_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    reference, targets = _write_basic_pair(lake_root=lake_root)
    coverage = _coverage_reference(reference, targets)
    rows = [
        _minute_row(ts_code=ts_code, source_freq=source_freq)
        for source_freq in ETF_MINS_SOURCE_FREQS
        for ts_code in ("510300.SH", "159915.SZ", "510500.SH")
    ]
    source_sql_calls, attach_calls = _patch_fake_prod_source(
        monkeypatch,
        rows=rows,
    )
    prod_postgres = FakeProdPostgres()

    results = tuple(
        write_raw_etf_mins_partition_from_prod_db(
            lake_root=lake_root,
            staging_root=staging_root,
            operation_id=f"daily-{source_freq}",
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=prod_postgres,  # type: ignore[arg-type]
            source_freq=source_freq,
            partition_key=TRADE_DATE,
            basic_reference=reference,  # type: ignore[arg-type]
            prod_coverage_reference=coverage,
        )
        for source_freq in ETF_MINS_SOURCE_FREQS
    )

    assert len(source_sql_calls) == 5
    assert len(attach_calls) == 5
    assert prod_postgres.conninfo_calls == 5
    assert sum(result.query_count for result in results) == 5
    assert all(result.write_disposition == "added" for result in results)
    assert all(result.validation.missing_count == 0 for result in results)
    assert all(
        result.validation.known_non_required_present_count == 2
        for result in results
    )
    for result in results:
        metadata = build_etf_mins_raw_materialization_metadata(result)
        assert metadata["dagster/row_count"] == 3
        assert metadata["goldenshare/query_count"] == 1
        assert metadata["goldenshare/source_method"] == "prod_db_readonly"
        assert metadata["goldenshare/policy_state"] == "unclassified"
        assert metadata["goldenshare/silver_eligible"] is False
        assert metadata["goldenshare/prod_coverage_reference_fingerprint"] == (
            coverage.coverage_fingerprint
        )
    assert not list(staging_root.rglob("*.parquet"))


def test_equivalent_target_is_reused_but_conflicting_target_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    reference, targets = _write_basic_pair(lake_root=lake_root)
    coverage = _coverage_reference(reference, targets)
    source_rows = [_minute_row(ts_code="510300.SH", source_freq="1min")]
    _patch_fake_prod_source(monkeypatch, rows=source_rows)
    prod_postgres = FakeProdPostgres()
    arguments = {
        "lake_root": lake_root,
        "staging_root": staging_root,
        "duckdb": TestDuckDBResource(),
        "prod_postgres": prod_postgres,
        "source_freq": "1min",
        "partition_key": TRADE_DATE,
        "basic_reference": reference,
        "prod_coverage_reference": coverage,
    }

    first = write_raw_etf_mins_partition_from_prod_db(
        operation_id="first",
        **arguments,  # type: ignore[arg-type]
    )
    original_hash = first.file_sha256
    second = write_raw_etf_mins_partition_from_prod_db(
        operation_id="second",
        **arguments,  # type: ignore[arg-type]
    )
    assert second.write_disposition == "reused"
    assert second.file_sha256 == original_hash

    source_rows[0] = _minute_row(
        ts_code="510300.SH",
        source_freq="1min",
        close=11.1,
    )
    with pytest.raises(EtfMinsRawWriteError, match="etf_mins_target_conflict"):
        write_raw_etf_mins_partition_from_prod_db(
            operation_id="conflict",
            **arguments,  # type: ignore[arg-type]
        )
    assert first.target_path.is_file()
    assert etf_mins_assets._sha256_file(first.target_path) == original_hash
    assert etf_mins_staging_path(
        staging_root,
        "conflict",
        "raw",
        "1min",
        TRADE_DATE,
    ).is_file()


def test_historical_candidate_keeps_missing_grid_and_explicit_zero_row_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    reference, _ = _write_basic_pair(lake_root=lake_root)
    historical_rows = [
        _minute_row(
            ts_code="510500.SH",
            source_freq="1min",
            trade_time="2026-08-28T09:31:00",
        ),
        _minute_row(
            ts_code="510500.SH",
            source_freq="1min",
            trade_time="2026-08-28T10:01:00",
        ),
    ]
    _patch_fake_prod_source(monkeypatch, rows=historical_rows)

    result = write_raw_etf_mins_partition_from_prod_db(
        lake_root=lake_root,
        staging_root=staging_root,
        operation_id="historical-missing",
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
        source_freq="1min",
        partition_key=TRADE_DATE,
        basic_reference=reference,  # type: ignore[arg-type]
        prod_coverage_reference=None,
    )
    assert result.validation.promotion_allowed is True
    assert result.validation.missing_count == 1
    assert result.validation.grid_gap_candidate_count == 1
    assert result.validation.silver_eligible is False

    empty_lake_root, empty_staging_root = _roots(tmp_path / "empty")
    empty_reference, _ = _write_basic_pair(lake_root=empty_lake_root)
    _patch_fake_prod_source(monkeypatch, rows=[])
    empty_result = write_raw_etf_mins_partition_from_prod_db(
        lake_root=empty_lake_root,
        staging_root=empty_staging_root,
        operation_id="historical-zero",
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
        source_freq="5min",
        partition_key=TRADE_DATE,
        basic_reference=empty_reference,  # type: ignore[arg-type]
        prod_coverage_reference=None,
    )
    assert empty_result.source_row_count == 0
    assert empty_result.validation.missing_count == 1
    with duckdb.connect(":memory:") as connection:
        assert connection.execute(
            "SELECT count(*) FROM read_parquet(?, hive_partitioning=false)",
            [str(empty_result.target_path)],
        ).fetchone() == (0,)
        columns = tuple(
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
                [str(empty_result.target_path)],
            ).fetchall()
        )
    assert columns == ETF_MINS_SOURCE_COLUMNS


def test_daily_coverage_contradiction_and_unexplained_code_keep_candidate_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    reference, targets = _write_basic_pair(lake_root=lake_root)
    coverage = _coverage_reference(reference, targets)
    _patch_fake_prod_source(monkeypatch, rows=[])

    with pytest.raises(
        EtfMinsRawWriteError,
        match="etf_mins_daily_coverage_candidate_mismatch",
    ):
        write_raw_etf_mins_partition_from_prod_db(
            lake_root=lake_root,
            staging_root=staging_root,
            operation_id="daily-empty",
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            source_freq="1min",
            partition_key=TRADE_DATE,
            basic_reference=reference,  # type: ignore[arg-type]
            prod_coverage_reference=coverage,
        )
    assert not raw_etf_mins_path(lake_root, "1min", TRADE_DATE).exists()
    assert etf_mins_staging_path(
        staging_root,
        "daily-empty",
        "raw",
        "1min",
        TRADE_DATE,
    ).is_file()

    unexplained_rows = [
        _minute_row(ts_code="999999.SH", source_freq="5min"),
    ]
    _patch_fake_prod_source(monkeypatch, rows=unexplained_rows)
    with pytest.raises(EtfMinsRawWriteError, match="etf_mins_unexplained_new_code"):
        write_raw_etf_mins_partition_from_prod_db(
            lake_root=lake_root,
            staging_root=staging_root,
            operation_id="unexplained",
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            source_freq="5min",
            partition_key=TRADE_DATE,
            basic_reference=reference,  # type: ignore[arg-type]
            prod_coverage_reference=None,
        )
    assert not raw_etf_mins_path(lake_root, "5min", TRADE_DATE).exists()


def test_changed_basic_file_fails_before_the_detail_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    reference, targets = _write_basic_pair(lake_root=lake_root)
    coverage = _coverage_reference(reference, targets)
    Path(reference.silver_uri).write_bytes(b"not-a-parquet-file")
    source_sql_calls, attach_calls = _patch_fake_prod_source(
        monkeypatch,
        rows=[_minute_row(ts_code="510300.SH", source_freq="1min")],
    )
    prod_postgres = FakeProdPostgres()

    with pytest.raises(EtfMinsRawWriteError, match="etf_mins_basic_reference_invalid"):
        write_raw_etf_mins_partition_from_prod_db(
            lake_root=lake_root,
            staging_root=staging_root,
            operation_id="changed-basic",
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=prod_postgres,  # type: ignore[arg-type]
            source_freq="1min",
            partition_key=TRADE_DATE,
            basic_reference=reference,  # type: ignore[arg-type]
            prod_coverage_reference=coverage,
        )
    assert source_sql_calls == []
    assert attach_calls == []
    assert prod_postgres.conninfo_calls == 0
    assert not list(staging_root.rglob("*.parquet"))


def test_unreadable_staging_candidate_never_touches_the_formal_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = _roots(tmp_path)
    reference, targets = _write_basic_pair(lake_root=lake_root)
    coverage = _coverage_reference(reference, targets)
    source_rows = [_minute_row(ts_code="510300.SH", source_freq="1min")]
    _patch_fake_prod_source(monkeypatch, rows=source_rows)
    common_arguments = {
        "lake_root": lake_root,
        "staging_root": staging_root,
        "duckdb": TestDuckDBResource(),
        "prod_postgres": FakeProdPostgres(),
        "source_freq": "1min",
        "partition_key": TRADE_DATE,
        "basic_reference": reference,
        "prod_coverage_reference": coverage,
    }
    first = write_raw_etf_mins_partition_from_prod_db(
        operation_id="valid-target",
        **common_arguments,  # type: ignore[arg-type]
    )
    formal_hash = first.file_sha256

    def copy_as_csv(query: str, target_path: Path) -> str:
        return (
            f"COPY ({query}) TO {duckdb_string(target_path)} "
            "(FORMAT CSV, HEADER true)"
        )

    monkeypatch.setattr(etf_mins_assets, "copy_query_to_parquet", copy_as_csv)
    with pytest.raises(EtfMinsRawWriteError, match="etf_mins_staging_readback_failed"):
        write_raw_etf_mins_partition_from_prod_db(
            operation_id="bad-readback",
            **common_arguments,  # type: ignore[arg-type]
        )
    assert etf_mins_assets._sha256_file(first.target_path) == formal_hash
    assert etf_mins_staging_path(
        staging_root,
        "bad-readback",
        "raw",
        "1min",
        TRADE_DATE,
    ).is_file()


def test_writer_source_has_no_second_prod_probe_or_active_definition() -> None:
    source = Path(etf_mins_assets.__file__).read_text()
    for forbidden in (
        "probe_prod_etf_mins_code_coverage",
        "load_prod_etf_mins_code_coverage",
        "connect_readonly_transaction",
        "ops.",
        "@dg.sensor",
        "define_asset_job",
    ):
        assert forbidden not in source
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "duckdb_module"
        and node.func.attr == "connect"
        for node in ast.walk(tree)
    )
    assert source.count("build_prod_etf_mins_duckdb_source_sql(") == 1
    assert "os.replace(candidate_path, target_path)" in source
