"""Small deterministic fixtures for ETF daily Silver tests."""

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from orchestrator.defs.assets.etf_basic import (
    audit_etf_basic_silver_snapshot,
    write_etf_basic_silver_snapshot,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.io.etf_daily_raw_writer import EtfDailyRawSpec
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_ETF_BASIC_SCHEMA,
)
from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
    build_etf_basic_raw_snapshot_reference,
    build_etf_basic_silver_snapshot_reference,
    classify_etf_basic_requestability,
    compute_etf_basic_snapshot_hash,
    compute_etf_requestable_target_hash,
)


def make_roots(tmp_path: Path) -> tuple[Path, Path]:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    return lake_root, staging_root


def basic_row(
    ts_code: str,
    *,
    exchange: str | None = None,
    list_status: str = "L",
    list_date: str | None = "20200101",
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "csname": ts_code,
        "extname": None,
        "cname": ts_code,
        "index_code": None,
        "index_name": None,
        "setup_date": "20191201",
        "list_date": list_date,
        "list_status": list_status,
        "exchange": exchange or ts_code.rsplit(".", maxsplit=1)[-1],
        "mgr_name": None,
        "custod_name": None,
        "mgt_fee": 0.5,
        "etf_type": None,
    }


def write_basic_reference(
    *,
    lake_root: Path,
    staging_root: Path,
    rows: Sequence[Mapping[str, object]],
    eligibility_as_of: date = date(2026, 9, 2),
) -> EtfBasicSilverSnapshotReference:
    raw_rows = tuple(dict(row) for row in rows)
    raw_hash = compute_etf_basic_snapshot_hash(raw_rows)
    raw_path = (
        lake_root
        / "raw"
        / "tushare"
        / "etf_basic"
        / f"snapshot_id={raw_hash}"
        / "part-000.parquet"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column.name for column in RAW_TUSHARE_ETF_BASIC_SCHEMA)
    column_types = {column.name: column.type for column in RAW_TUSHARE_ETF_BASIC_SCHEMA}
    with DuckDBResource().connect() as connection:
        connection.execute(
            "CREATE TEMP TABLE basic_fixture ("
            + ", ".join(f'"{column}" {column_types[column]}' for column in columns)
            + ")"
        )
        connection.executemany(
            "INSERT INTO basic_fixture VALUES ("
            + ", ".join("?" for _ in columns)
            + ")",
            [tuple(row[column] for column in columns) for row in raw_rows],
        )
        connection.execute(
            f"COPY (SELECT * FROM basic_fixture ORDER BY ts_code) TO "
            f"{duckdb_string(raw_path)} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    observed_at = "2026-09-02T20:55:00+08:00"
    raw_reference = build_etf_basic_raw_snapshot_reference(
        raw_snapshot_hash=raw_hash,
        raw_uri=str(raw_path),
        raw_observed_at=observed_at,
    )
    silver_result = write_etf_basic_silver_snapshot(
        raw_snapshot_reference=raw_reference,
        duckdb_resource=DuckDBResource(),
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        run_id="basic-fixture",
        observed_at=observed_at,
    )
    audit = audit_etf_basic_silver_snapshot(
        path=silver_result.target_path,
        duckdb_resource=DuckDBResource(),
        raw_path=raw_path,
        expected_raw_snapshot_hash=raw_hash,
        expected_silver_content_hash=silver_result.silver_content_hash,
    )
    requestable_rows = tuple(
        row
        for row in audit.rows
        if classify_etf_basic_requestability(
            row,
            eligibility_as_of=eligibility_as_of,
        )
        is None
    )
    return build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash=raw_hash,
        silver_content_hash=silver_result.silver_content_hash,
        raw_uri=str(raw_path),
        silver_uri=str(silver_result.target_path),
        raw_observed_at=observed_at,
        silver_observed_at=observed_at,
        eligibility_as_of=eligibility_as_of,
        requestable_code_count=len(requestable_rows),
        requestable_code_hash=compute_etf_requestable_target_hash(requestable_rows),
    )


def write_raw_fixture(
    *,
    lake_root: Path,
    spec: EtfDailyRawSpec,
    partition_key: str,
    rows: Sequence[Mapping[str, object]],
) -> Path:
    path = spec.target_path_builder(lake_root, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = spec.source_columns
    with DuckDBResource().connect() as connection:
        connection.execute(
            "CREATE TEMP TABLE raw_fixture ("
            + ", ".join(
                f'"{column}" {spec.raw_column_types[column]}' for column in columns
            )
            + ")"
        )
        connection.executemany(
            "INSERT INTO raw_fixture VALUES ("
            + ", ".join("?" for _ in columns)
            + ")",
            [tuple(row[column] for column in columns) for row in rows],
        )
        connection.execute(
            f"COPY (SELECT * FROM raw_fixture ORDER BY ts_code, trade_date) TO "
            f"{duckdb_string(path)} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    return path
