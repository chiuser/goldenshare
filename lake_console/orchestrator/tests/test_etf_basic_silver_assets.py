from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.assets import etf_basic as etf_basic_assets
from orchestrator.defs.assets.etf_basic import (
    EtfBasicSnapshotValidationError,
    audit_etf_basic_silver_snapshot,
    build_etf_basic_silver_materialization_metadata,
    silver_etf_basic,
    write_etf_basic_silver_snapshot,
)
from orchestrator.defs.paths import (
    raw_etf_basic_snapshot_path,
    silver_etf_basic_snapshot_path,
)
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_SOURCE_COLUMNS,
    EtfBasicSilverConfig,
    build_etf_basic_raw_snapshot_reference,
    compute_etf_basic_snapshot_hash,
)
from orchestrator.defs.run_contracts.metadata import (
    DATA_CONTRACT_METADATA_KEY,
    SOURCE_API_METADATA_KEY,
    SOURCE_DOC_METADATA_KEY,
    SOURCE_SYSTEM_METADATA_KEY,
)


class TestDuckDBResource:
    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with duckdb.connect(":memory:") as connection:
            yield connection


def _row(
    code: str,
    *,
    list_status: str = "L",
    exchange: str | None = None,
    setup_date: str | None = "20120504",
    list_date: str | None = "20120528",
    mgt_fee: float | None = 0.5,
) -> dict[str, object]:
    suffix = code.rsplit(".", maxsplit=1)[-1]
    return {
        "ts_code": code,
        "csname": f"ETF-{code}",
        "extname": None,
        "cname": None,
        "index_code": None,
        "index_name": None,
        "setup_date": setup_date,
        "list_date": list_date,
        "list_status": list_status,
        "exchange": exchange if exchange is not None else suffix,
        "mgr_name": None,
        "custod_name": None,
        "mgt_fee": mgt_fee,
        "etf_type": "境内",
    }


def _write_raw_snapshot(root: Path, rows: list[dict[str, object]]) -> tuple[str, Path]:
    raw_hash = compute_etf_basic_snapshot_hash(rows)
    path = raw_etf_basic_snapshot_path(root, raw_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    types = ["VARCHAR"] * len(ETF_BASIC_SOURCE_COLUMNS)
    types[ETF_BASIC_SOURCE_COLUMNS.index("mgt_fee")] = "DOUBLE"
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE snapshot ("
            + ", ".join(
                f'"{column}" {column_type}'
                for column, column_type in zip(
                    ETF_BASIC_SOURCE_COLUMNS,
                    types,
                    strict=True,
                )
            )
            + ")"
        )
        connection.executemany(
            "INSERT INTO snapshot VALUES ("
            + ", ".join("?" for _ in ETF_BASIC_SOURCE_COLUMNS)
            + ")",
            [[row[column] for column in ETF_BASIC_SOURCE_COLUMNS] for row in rows],
        )
        connection.execute("COPY snapshot TO ? (FORMAT PARQUET)", [str(path)])
    return raw_hash, path


def _write_silver(
    tmp_path: Path,
    rows: list[dict[str, object]],
    *,
    run_id: str = "run-1",
):
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir(exist_ok=True)
    staging_root.mkdir(exist_ok=True)
    raw_hash, raw_path = _write_raw_snapshot(lake_root, rows)
    reference = build_etf_basic_raw_snapshot_reference(
        raw_snapshot_hash=raw_hash,
        raw_uri=str(raw_path),
        raw_observed_at="2026-08-30T09:00:00+08:00",
    )
    result = write_etf_basic_silver_snapshot(
        raw_snapshot_reference=reference,
        duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        run_id=run_id,
        observed_at="2026-08-30T09:05:00+08:00",
    )
    return result, reference


def test_silver_writer_filters_only_of_and_retains_d_and_p(tmp_path: Path) -> None:
    rows = [
        _row("510300.SH", list_status="D"),
        _row("159915.SZ", list_status="P"),
        _row("159001.OF", list_status="L", exchange="OF"),
    ]

    result, _ = _write_silver(tmp_path, rows)

    assert result.row_count == 2
    assert result.filtered_out_count == 1
    assert result.status_counts == {"D": 1, "P": 1}
    assert result.suffix_counts == {"SH": 1, "SZ": 1}
    assert result.target_path == silver_etf_basic_snapshot_path(
        tmp_path / "data_lake",
        result.raw_snapshot_hash,
    )
    with duckdb.connect(":memory:") as connection:
        selected = connection.execute(
            "SELECT ts_code, setup_date, list_date, mgt_fee FROM read_parquet(?) "
            "ORDER BY ts_code",
            [str(result.target_path)],
        ).fetchall()
    assert [row[0] for row in selected] == ["159915.SZ", "510300.SH"]
    assert all(type(row[1]).__name__ == "date" for row in selected)
    assert all(type(row[2]).__name__ == "date" for row in selected)
    assert all(type(row[3]).__name__ == "Decimal" for row in selected)


def test_bad_non_null_date_fails_the_entire_version(tmp_path: Path) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    rows = [_row("510300.SH", list_date="2026-02-30")]
    raw_hash, raw_path = _write_raw_snapshot(lake_root, rows)
    reference = build_etf_basic_raw_snapshot_reference(
        raw_snapshot_hash=raw_hash,
        raw_uri=str(raw_path),
        raw_observed_at="2026-08-30T09:00:00+08:00",
    )

    with pytest.raises(
        EtfBasicSnapshotValidationError,
        match="etf_basic_silver_date_normalization_failed",
    ):
        write_etf_basic_silver_snapshot(
            raw_snapshot_reference=reference,
            duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            run_id="run-bad-date",
            observed_at="2026-08-30T09:05:00+08:00",
        )

    assert not list((lake_root / "silver").rglob("*.parquet"))


def test_numeric_value_outside_decimal_contract_fails_the_entire_version(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    rows = [_row("510300.SH", mgt_fee=1e20)]
    raw_hash, raw_path = _write_raw_snapshot(lake_root, rows)
    reference = build_etf_basic_raw_snapshot_reference(
        raw_snapshot_hash=raw_hash,
        raw_uri=str(raw_path),
        raw_observed_at="2026-08-30T09:00:00+08:00",
    )

    with pytest.raises(
        EtfBasicSnapshotValidationError,
        match="etf_basic_silver_normalization_failed",
    ):
        write_etf_basic_silver_snapshot(
            raw_snapshot_reference=reference,
            duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            run_id="run-bad-decimal",
            observed_at="2026-08-30T09:05:00+08:00",
        )

    assert not list((lake_root / "silver").rglob("*.parquet"))


def test_same_version_reuses_and_existing_conflict_stops(tmp_path: Path) -> None:
    rows = [_row("510300.SH")]
    first, _ = _write_silver(tmp_path, rows, run_id="run-1")
    reused, _ = _write_silver(tmp_path, rows, run_id="run-2")
    assert reused.target_path == first.target_path
    assert reused.write_mode == "reuse_existing"

    first.target_path.write_text("not parquet", encoding="utf-8")
    with pytest.raises(
        EtfBasicSnapshotValidationError,
        match="etf_basic_silver_snapshot_conflict",
    ):
        _write_silver(tmp_path, rows, run_id="run-3")
    assert first.target_path.read_text(encoding="utf-8") == "not parquet"


def test_silver_readback_reconciles_both_directions_and_hash(tmp_path: Path) -> None:
    result, _ = _write_silver(
        tmp_path,
        [_row("510300.SH"), _row("159001.OF", exchange="OF")],
    )

    audit = audit_etf_basic_silver_snapshot(
        path=result.target_path,
        raw_path=result.raw_path,
        duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
        expected_raw_snapshot_hash=result.raw_snapshot_hash,
        expected_silver_content_hash=result.silver_content_hash,
    )

    assert audit.passed
    assert audit.filtered_out_count == 1
    assert audit.silver_content_hash == result.silver_content_hash


def test_silver_metadata_and_definition_match_the_lld(tmp_path: Path) -> None:
    result, reference = _write_silver(tmp_path, [_row("510300.SH")])
    metadata = build_etf_basic_silver_materialization_metadata(result)

    assert set(metadata) == {
        "dagster/uri",
        "dagster/row_count",
        "goldenshare/observed_columns",
        "goldenshare/raw_uri",
        "goldenshare/raw_snapshot_hash",
        "goldenshare/silver_content_hash",
        "goldenshare/raw_observed_at",
        "goldenshare/observed_at",
        "goldenshare/filtered_out_count",
        "goldenshare/status_counts",
        "goldenshare/suffix_counts",
        "goldenshare/write_mode",
    }
    assert "storage_id" not in " ".join(metadata)
    config = EtfBasicSilverConfig(raw_snapshot_reference=reference)
    assert set(config.model_dump()) == {"raw_snapshot_reference"}
    assert "eligibility_as_of" not in config.model_dump_json()

    spec = silver_etf_basic.get_asset_spec(silver_etf_basic.key)
    assert spec.description == (
        "把指定 Raw 快照标准化为 `.SH/.SZ` 全状态 ETF 基础信息，不按上市状态或日期再筛选；"
        "供 ETF 分钟任务冻结当次请求范围。"
    )
    assert spec.metadata[SOURCE_SYSTEM_METADATA_KEY] == "derived"
    assert spec.metadata[DATA_CONTRACT_METADATA_KEY] == "sh_sz_full_status_etf_basic"
    assert SOURCE_API_METADATA_KEY not in spec.metadata
    assert SOURCE_DOC_METADATA_KEY not in spec.metadata


def test_silver_asset_revalidates_only_the_frozen_raw_reference() -> None:
    source = inspect.getsource(etf_basic_assets).split(
        "def silver_etf_basic(",
        maxsplit=1,
    )[1]

    assert "write_etf_basic_silver_snapshot(" in source
    assert "eligibility_as_of" not in source
    assert "list_status" not in source
    assert "storage_id" not in source
