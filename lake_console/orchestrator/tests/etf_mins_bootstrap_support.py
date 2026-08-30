from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string
from orchestrator.defs.paths import (
    raw_etf_basic_snapshot_path,
    silver_etf_basic_snapshot_path,
)
from orchestrator.defs.prod_db.etf_mins import ProdEtfMinsFrequencyCoverage
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
)


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


def roots(tmp_path: Path) -> tuple[Path, Path]:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir(parents=True)
    staging_root.mkdir(parents=True)
    return lake_root, staging_root


def write_basic_pair(
    *,
    lake_root: Path,
    eligibility_as_of: str = "2026-09-30",
) -> tuple[object, tuple[EtfMinsRequestableTarget, ...]]:
    raw_rows = (
        {
            "ts_code": "510300.SH",
            "csname": "ETF-510300.SH",
            "extname": None,
            "cname": None,
            "index_code": None,
            "index_name": None,
            "setup_date": "20120101",
            "list_date": "20120528",
            "list_status": "L",
            "exchange": "SH",
            "mgr_name": None,
            "custod_name": None,
            "mgt_fee": 0.5,
            "etf_type": "境内",
        },
        {
            "ts_code": "510500.SH",
            "csname": "ETF-510500.SH",
            "extname": None,
            "cname": None,
            "index_code": None,
            "index_name": None,
            "setup_date": "20130201",
            "list_date": "20130218",
            "list_status": "D",
            "exchange": "SH",
            "mgr_name": None,
            "custod_name": None,
            "mgt_fee": 0.5,
            "etf_type": "境内",
        },
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
    placeholders = ", ".join("?" for _ in ETF_BASIC_SOURCE_COLUMNS)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE basic_raw (
              ts_code VARCHAR, csname VARCHAR, extname VARCHAR, cname VARCHAR,
              index_code VARCHAR, index_name VARCHAR, setup_date VARCHAR,
              list_date VARCHAR, list_status VARCHAR, exchange VARCHAR,
              mgr_name VARCHAR, custod_name VARCHAR, mgt_fee DOUBLE,
              etf_type VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE basic_silver (
              ts_code VARCHAR, csname VARCHAR, extname VARCHAR, cname VARCHAR,
              index_code VARCHAR, index_name VARCHAR, setup_date DATE,
              list_date DATE, list_status VARCHAR, exchange VARCHAR,
              mgr_name VARCHAR, custod_name VARCHAR,
              mgt_fee DECIMAL(12, 6), etf_type VARCHAR
            )
            """
        )
        connection.executemany(
            f"INSERT INTO basic_raw VALUES ({placeholders})",
            [
                tuple(row[column] for column in ETF_BASIC_SOURCE_COLUMNS)
                for row in raw_rows
            ],
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
    requestable_rows = tuple(row for row in silver_rows if row["list_status"] == "L")
    targets = tuple(
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
        raw_observed_at=f"{eligibility_as_of}T08:00:00+08:00",
        silver_observed_at=f"{eligibility_as_of}T08:05:00+08:00",
        eligibility_as_of=eligibility_as_of,
        requestable_code_count=len(requestable_rows),
        requestable_code_hash=compute_etf_requestable_target_hash(requestable_rows),
    )
    return reference, targets


def coverages(
    trade_dates: Sequence[str],
    *,
    incomplete: set[tuple[str, str]] | None = None,
) -> tuple[ProdEtfMinsFrequencyCoverage, ...]:
    incomplete_keys = incomplete or set()
    return tuple(
        ProdEtfMinsFrequencyCoverage(
            trade_date=trade_date,
            source_freq=source_freq,
            expected_code_count=1,
            present_code_count=(
                0 if (trade_date, source_freq) in incomplete_keys else 1
            ),
            missing_code_count=(
                1 if (trade_date, source_freq) in incomplete_keys else 0
            ),
            missing_code_samples=(
                ("510300.SH",) if (trade_date, source_freq) in incomplete_keys else ()
            ),
        )
        for trade_date in trade_dates
        for source_freq in ETF_MINS_SOURCE_FREQS
    )


def minute_row(
    *,
    source_freq: str,
    trade_date: str,
    ts_code: str = "510300.SH",
    close: float = 10.1,
) -> tuple[object, ...]:
    return (
        ts_code,
        source_freq,
        datetime.fromisoformat(f"{trade_date}T09:31:00"),
        10.0,
        close,
        10.2,
        9.9,
        100,
        1000.0,
        10.05,
        "XSHG",
    )


def write_minute_file(path: Path, rows: Sequence[tuple[object, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    placeholders = ", ".join("?" for _ in ETF_MINS_SOURCE_COLUMNS)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE minute_rows (
              ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
              open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
              vol BIGINT, amount DOUBLE, vwap DOUBLE, exchange VARCHAR
            )
            """
        )
        if rows:
            connection.executemany(
                f"INSERT INTO minute_rows VALUES ({placeholders})",
                rows,
            )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM minute_rows ORDER BY ts_code, trade_time",
                path,
            )
        )


def install_fake_prod_source(
    module,
    monkeypatch,
    *,
    rows: list[tuple[object, ...]],
) -> list[tuple[str, str, str]]:
    source_calls: list[tuple[str, str, str]] = []

    def attach(
        connection: duckdb.DuckDBPyConnection,
        *,
        postgres_connection_string: str,
    ) -> None:
        del postgres_connection_string
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
        source_calls.append((source_freq, start_datetime, end_datetime))
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

    monkeypatch.setattr(module, "_load_duckdb_postgres_extension", lambda _: None)
    monkeypatch.setattr(module, "_attach_prod_etf_mins_readonly", attach)
    monkeypatch.setattr(module, "build_prod_etf_mins_duckdb_source_sql", source_sql)
    return source_calls
