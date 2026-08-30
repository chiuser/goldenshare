from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.asset_guards.etf_basic_readiness import (
    EtfBasicReadinessError,
    select_latest_etf_basic_raw_snapshot_reference,
    select_latest_etf_basic_snapshot_reference,
)
from orchestrator.defs.assets.etf_basic import (
    build_etf_basic_silver_materialization_metadata,
    write_etf_basic_silver_snapshot,
)
from orchestrator.defs.paths import raw_etf_basic_snapshot_path
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_SOURCE_COLUMNS,
    RAW_ETF_BASIC_CHECKS,
    SILVER_ETF_BASIC_CHECKS,
    build_etf_basic_raw_snapshot_reference,
    compute_etf_basic_snapshot_hash,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata


class TestDuckDBResource:
    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with duckdb.connect(":memory:") as connection:
            yield connection


class FakeEventLogStorage:
    def __init__(self, records_by_key: dict[dg.AssetCheckKey, list[object]]) -> None:
        self.records_by_key = records_by_key
        self.calls: list[tuple[dg.AssetCheckKey, int]] = []

    def get_asset_check_execution_history(
        self,
        check_key: dg.AssetCheckKey,
        *,
        limit: int,
        status: object,
    ) -> list[object]:
        del status
        self.calls.append((check_key, limit))
        return self.records_by_key.get(check_key, [])[:limit]


class FakeInstance:
    def __init__(
        self,
        *,
        records_by_asset: dict[dg.AssetKey, list[object]],
        check_records: dict[dg.AssetCheckKey, list[object]],
    ) -> None:
        self.records_by_asset = records_by_asset
        self.event_log_storage = FakeEventLogStorage(check_records)
        self.fetch_calls: list[tuple[dg.AssetKey, int]] = []

    def fetch_materializations(self, records_filter, *, limit: int):  # type: ignore[no-untyped-def]
        asset_key = records_filter.asset_key
        self.fetch_calls.append((asset_key, limit))
        return SimpleNamespace(records=self.records_by_asset.get(asset_key, [])[:limit])


def _row(
    code: str,
    *,
    list_status: str = "L",
    exchange: str | None = None,
    list_date: str | None = "20120528",
) -> dict[str, object]:
    suffix = code.rsplit(".", maxsplit=1)[-1]
    return {
        "ts_code": code,
        "csname": f"ETF-{code}",
        "extname": None,
        "cname": None,
        "index_code": None,
        "index_name": None,
        "setup_date": "20120504",
        "list_date": list_date,
        "list_status": list_status,
        "exchange": exchange if exchange is not None else suffix,
        "mgr_name": None,
        "custod_name": None,
        "mgt_fee": 0.5,
        "etf_type": "境内",
    }


def _write_raw(root: Path, rows: list[dict[str, object]]) -> tuple[str, Path]:
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


def _materialization_record(
    *,
    storage_id: int,
    metadata: dict[str, object],
) -> object:
    return SimpleNamespace(
        storage_id=storage_id,
        asset_materialization=SimpleNamespace(metadata=metadata),
    )


def _check_record(
    storage_id: int,
    *,
    passed: bool = True,
    blocking: bool = True,
) -> object:
    return SimpleNamespace(
        status=(
            AssetCheckExecutionRecordStatus.SUCCEEDED
            if passed
            else AssetCheckExecutionRecordStatus.FAILED
        ),
        event=SimpleNamespace(
            dagster_event=SimpleNamespace(
                event_specific_data=SimpleNamespace(
                    target_materialization_data=SimpleNamespace(storage_id=storage_id),
                    blocking=blocking,
                    passed=passed,
                )
            )
        ),
    )


def _ready_fixture(
    tmp_path: Path,
    *,
    raw_observed_at: str = "2026-08-30T09:00:00+08:00",
    silver_observed_at: str = "2026-08-30T09:05:00+08:00",
) -> tuple[FakeInstance, Path, str]:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    rows = [
        _row("510300.SH"),
        _row("159915.SZ", list_status="D"),
        _row("588000.SH", list_date="20260901"),
        _row("159001.OF", exchange="OF"),
    ]
    raw_hash, raw_path = _write_raw(lake_root, rows)
    raw_reference = build_etf_basic_raw_snapshot_reference(
        raw_snapshot_hash=raw_hash,
        raw_uri=str(raw_path),
        raw_observed_at=raw_observed_at,
    )
    silver_result = write_etf_basic_silver_snapshot(
        raw_snapshot_reference=raw_reference,
        duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        run_id="silver-run",
        observed_at=silver_observed_at,
    )
    raw_metadata = build_materialization_metadata(
        uri=raw_path,
        row_count=len(rows),
        observed_columns=ETF_BASIC_SOURCE_COLUMNS,
        extra_metadata={
            "raw_snapshot_hash": raw_hash,
            "observed_at": raw_observed_at,
        },
    )
    silver_metadata = build_etf_basic_silver_materialization_metadata(silver_result)
    raw_record = _materialization_record(storage_id=101, metadata=raw_metadata)
    silver_record = _materialization_record(storage_id=202, metadata=silver_metadata)
    check_records = {
        **{
            dg.AssetCheckKey(dg.AssetKey("raw_tushare_etf_basic"), check_name): [
                _check_record(101)
            ]
            for check_name in RAW_ETF_BASIC_CHECKS
        },
        **{
            dg.AssetCheckKey(dg.AssetKey("silver_etf_basic"), check_name): [
                _check_record(202)
            ]
            for check_name in SILVER_ETF_BASIC_CHECKS
        },
    }
    return (
        FakeInstance(
            records_by_asset={
                dg.AssetKey("raw_tushare_etf_basic"): [raw_record],
                dg.AssetKey("silver_etf_basic"): [silver_record],
            },
            check_records=check_records,
        ),
        lake_root,
        raw_hash,
    )


def test_latest_only_selector_builds_small_same_day_reference(tmp_path: Path) -> None:
    instance, lake_root, raw_hash = _ready_fixture(tmp_path)

    reference = select_latest_etf_basic_snapshot_reference(
        instance=instance,  # type: ignore[arg-type]
        lake_root_path=lake_root,
        duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
        eligibility_as_of=date(2026, 8, 30),
        required_freshness_date=date(2026, 8, 30),
    )

    assert reference.raw_snapshot_hash == raw_hash
    assert reference.requestable_code_count == 1
    assert reference.eligibility_as_of == "2026-08-30"
    serialized = reference.model_dump()
    assert "storage_id" not in str(serialized)
    assert "ts_codes" not in serialized
    assert instance.fetch_calls == [
        (dg.AssetKey("raw_tushare_etf_basic"), 1),
        (dg.AssetKey("silver_etf_basic"), 1),
    ]
    assert len(instance.event_log_storage.calls) == 6
    assert all(limit == 1 for _, limit in instance.event_log_storage.calls)


def test_raw_selector_is_independently_available_for_silver_run_config(
    tmp_path: Path,
) -> None:
    instance, lake_root, raw_hash = _ready_fixture(tmp_path)

    reference = select_latest_etf_basic_raw_snapshot_reference(
        instance=instance,  # type: ignore[arg-type]
        lake_root_path=lake_root,
        duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
        required_freshness_date=date(2026, 8, 30),
    )

    assert reference.raw_snapshot_hash == raw_hash
    assert len(instance.event_log_storage.calls) == 3


def test_stale_latest_raw_does_not_gain_freshness_from_new_silver(
    tmp_path: Path,
) -> None:
    instance, lake_root, _ = _ready_fixture(
        tmp_path,
        raw_observed_at="2026-08-29T09:00:00+08:00",
    )

    with pytest.raises(EtfBasicReadinessError, match="raw_observed_at_stale"):
        select_latest_etf_basic_snapshot_reference(
            instance=instance,  # type: ignore[arg-type]
            lake_root_path=lake_root,
            duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
            eligibility_as_of=date(2026, 8, 30),
            required_freshness_date=date(2026, 8, 30),
        )


def test_stale_latest_silver_fails_even_when_raw_is_fresh(tmp_path: Path) -> None:
    instance, lake_root, _ = _ready_fixture(
        tmp_path,
        silver_observed_at="2026-08-29T09:05:00+08:00",
    )

    with pytest.raises(EtfBasicReadinessError, match="silver_observed_at_stale"):
        select_latest_etf_basic_snapshot_reference(
            instance=instance,  # type: ignore[arg-type]
            lake_root_path=lake_root,
            duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
            eligibility_as_of=date(2026, 8, 30),
            required_freshness_date=date(2026, 8, 30),
        )


def test_latest_failed_check_does_not_fall_back_to_older_success(
    tmp_path: Path,
) -> None:
    instance, lake_root, _ = _ready_fixture(tmp_path)
    failed_name = RAW_ETF_BASIC_CHECKS[0]
    key = dg.AssetCheckKey(dg.AssetKey("raw_tushare_etf_basic"), failed_name)
    instance.event_log_storage.records_by_key[key] = [
        _check_record(101, passed=False),
        _check_record(100),
    ]

    with pytest.raises(EtfBasicReadinessError, match="latest_check_failed"):
        select_latest_etf_basic_snapshot_reference(
            instance=instance,  # type: ignore[arg-type]
            lake_root_path=lake_root,
            duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
            eligibility_as_of=date(2026, 8, 30),
            required_freshness_date=date(2026, 8, 30),
        )


def test_latest_silver_failed_check_does_not_fall_back(tmp_path: Path) -> None:
    instance, lake_root, _ = _ready_fixture(tmp_path)
    failed_name = SILVER_ETF_BASIC_CHECKS[-1]
    key = dg.AssetCheckKey(dg.AssetKey("silver_etf_basic"), failed_name)
    instance.event_log_storage.records_by_key[key] = [
        _check_record(202, passed=False),
        _check_record(201),
    ]

    with pytest.raises(EtfBasicReadinessError, match="latest_check_failed"):
        select_latest_etf_basic_snapshot_reference(
            instance=instance,  # type: ignore[arg-type]
            lake_root_path=lake_root,
            duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
            eligibility_as_of=date(2026, 8, 30),
            required_freshness_date=date(2026, 8, 30),
        )


def test_latest_raw_change_without_matching_silver_fails_closed(
    tmp_path: Path,
) -> None:
    instance, lake_root, _ = _ready_fixture(tmp_path)
    changed_rows = [_row("510500.SH")]
    changed_hash, changed_path = _write_raw(lake_root, changed_rows)
    changed_metadata = build_materialization_metadata(
        uri=changed_path,
        row_count=1,
        observed_columns=ETF_BASIC_SOURCE_COLUMNS,
        extra_metadata={
            "raw_snapshot_hash": changed_hash,
            "observed_at": "2026-08-30T10:00:00+08:00",
        },
    )
    instance.records_by_asset[dg.AssetKey("raw_tushare_etf_basic")] = [
        _materialization_record(storage_id=303, metadata=changed_metadata)
    ]
    for check_name in RAW_ETF_BASIC_CHECKS:
        instance.event_log_storage.records_by_key[
            dg.AssetCheckKey(dg.AssetKey("raw_tushare_etf_basic"), check_name)
        ] = [_check_record(303)]

    with pytest.raises(EtfBasicReadinessError, match="latest_layers_not_aligned"):
        select_latest_etf_basic_snapshot_reference(
            instance=instance,  # type: ignore[arg-type]
            lake_root_path=lake_root,
            duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
            eligibility_as_of=date(2026, 8, 30),
            required_freshness_date=date(2026, 8, 30),
        )


def test_required_freshness_date_must_equal_eligibility_as_of(
    tmp_path: Path,
) -> None:
    instance, lake_root, _ = _ready_fixture(tmp_path)

    with pytest.raises(EtfBasicReadinessError, match="freshness_date_mismatch"):
        select_latest_etf_basic_snapshot_reference(
            instance=instance,  # type: ignore[arg-type]
            lake_root_path=lake_root,
            duckdb_resource=TestDuckDBResource(),  # type: ignore[arg-type]
            eligibility_as_of=date(2026, 8, 30),
            required_freshness_date=date(2026, 8, 29),
        )
