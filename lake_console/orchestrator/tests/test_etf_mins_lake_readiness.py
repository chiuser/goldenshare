from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.asset_guards.etf_mins_lake_readiness import (
    EtfMinsRawMaterializationBatchEvidence,
    batch_etf_mins_raw_lake_readiness,
    batch_etf_mins_silver_lake_readiness,
    load_etf_mins_raw_materialization_evidence_batch,
)
from orchestrator.defs.assets.etf_mins import RAW_ETF_MINS_ASSETS
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import raw_etf_mins_path, silver_etf_mins_path
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_RAW_APPROVED_POLICY_VERSION,
    ETF_MINS_SOURCE_COLUMNS,
    ETF_MINS_SOURCE_FREQS,
    get_etf_mins_raw_decision_policy,
)
from tests.test_etf_mins_raw_writer import _write_basic_pair

TRADE_DATE = "2026-08-28"


class FakeInstance:
    def __init__(self, records_by_asset: dict[dg.AssetKey, list[object]]) -> None:
        self.records_by_asset = records_by_asset
        self.fetch_calls: list[tuple[dg.AssetKey, tuple[str, ...], int]] = []

    def fetch_materializations(self, records_filter, *, limit: int):  # type: ignore[no-untyped-def]
        partitions = tuple(records_filter.asset_partitions or ())
        self.fetch_calls.append((records_filter.asset_key, partitions, limit))
        records = [
            record
            for record in self.records_by_asset.get(records_filter.asset_key, [])
            if record.asset_materialization.partition in set(partitions)
        ]
        return SimpleNamespace(records=records[:limit])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_minute_file(path: Path, source_freq: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    clock_times = get_etf_mins_raw_decision_policy(
        ETF_MINS_RAW_APPROVED_POLICY_VERSION
    ).expected_clock_times(source_freq)
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
        connection.executemany(
            "INSERT INTO minute_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "510300.SH",
                    source_freq,
                    f"{TRADE_DATE} {clock_time}",
                    10.0,
                    10.1,
                    10.2,
                    9.9,
                    100,
                    1000.0,
                    10.05,
                    "XSHG",
                )
                for clock_time in clock_times
            ],
        )
        connection.execute(
            "COPY (SELECT * FROM minute_rows ORDER BY ts_code, trade_time) "
            "TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(path)],
        )
    return len(clock_times)


def _metadata(reference, path: Path, source_freq: str, row_count: int) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "dagster/uri": str(path),
        "dagster/row_count": row_count,
        "goldenshare/partition_key": TRADE_DATE,
        "goldenshare/source_freq": source_freq,
        "goldenshare/observed_columns": list(ETF_MINS_SOURCE_COLUMNS),
        "goldenshare/source_method": "prod_db_readonly",
        "goldenshare/query_count": 1,
        "goldenshare/policy_state": "unclassified",
        "goldenshare/silver_eligible": False,
        "goldenshare/file_sha256": _sha256(path),
        "goldenshare/code_count": 1,
        "goldenshare/expected_count": 1,
        "goldenshare/present_count": 1,
        "goldenshare/missing_count": 0,
        "goldenshare/known_non_required_present_count": 0,
        "goldenshare/retained_legacy_count": 0,
        "goldenshare/unexplained_new_count": 0,
        "goldenshare/basic_raw_snapshot_hash": reference.raw_snapshot_hash,
        "goldenshare/basic_silver_content_hash": reference.silver_content_hash,
        "goldenshare/basic_raw_observed_at": reference.raw_observed_at,
        "goldenshare/basic_silver_observed_at": reference.silver_observed_at,
        "goldenshare/basic_reference_fingerprint": reference.reference_fingerprint,
        "goldenshare/eligibility_as_of": reference.eligibility_as_of,
        "goldenshare/requestable_code_count": reference.requestable_code_count,
        "goldenshare/requestable_code_hash": reference.requestable_code_hash,
    }


def _fixture(tmp_path: Path):  # type: ignore[no-untyped-def]
    lake_root = tmp_path / "data_lake"
    lake_root.mkdir()
    reference, _ = _write_basic_pair(lake_root=lake_root)
    records_by_asset: dict[dg.AssetKey, list[object]] = {}
    for storage_id, (asset, source_freq) in enumerate(
        zip(RAW_ETF_MINS_ASSETS, ETF_MINS_SOURCE_FREQS, strict=True),
        start=1,
    ):
        path = raw_etf_mins_path(lake_root, source_freq, TRADE_DATE)
        row_count = _write_minute_file(path, source_freq)
        records_by_asset[asset.key] = [
            SimpleNamespace(
                storage_id=storage_id,
                asset_materialization=SimpleNamespace(
                    partition=TRADE_DATE,
                    metadata=_metadata(reference, path, source_freq, row_count),
                ),
            )
        ]
    instance = FakeInstance(records_by_asset)
    asset_keys = {
        source_freq: asset.key
        for source_freq, asset in zip(
            ETF_MINS_SOURCE_FREQS,
            RAW_ETF_MINS_ASSETS,
            strict=True,
        )
    }
    lineage = load_etf_mins_raw_materialization_evidence_batch(
        instance=instance,  # type: ignore[arg-type]
        lake_root=lake_root,
        asset_keys_by_source_freq=asset_keys,
        partition_keys=(TRADE_DATE,),
    )
    return lake_root, reference, instance, lineage


def test_lineage_loader_uses_five_bounded_queries_and_restores_original_basic(
    tmp_path: Path,
) -> None:
    _, reference, instance, lineage = _fixture(tmp_path)

    assert lineage.materialization_query_count == 5
    assert len(instance.fetch_calls) == 5
    assert {call[0] for call in instance.fetch_calls} == {
        asset.key for asset in RAW_ETF_MINS_ASSETS
    }
    assert all(call[1] == (TRADE_DATE,) for call in instance.fetch_calls)
    assert not lineage.missing_partition_and_freqs
    assert {
        evidence.basic_reference.reference_fingerprint
        for evidence in lineage.evidences_by_partition_and_freq.values()
    } == {reference.reference_fingerprint}


def test_lineage_loader_rejects_more_than_ten_dates_without_querying() -> None:
    instance = FakeInstance({})
    asset_keys = {
        source_freq: asset.key
        for source_freq, asset in zip(
            ETF_MINS_SOURCE_FREQS,
            RAW_ETF_MINS_ASSETS,
            strict=True,
        )
    }
    with pytest.raises(ValueError, match="exceeds_ten"):
        load_etf_mins_raw_materialization_evidence_batch(
            instance=instance,  # type: ignore[arg-type]
            lake_root=Path("/isolated/lake"),
            asset_keys_by_source_freq=asset_keys,
            partition_keys=tuple(f"2026-08-{day:02d}" for day in range(1, 12)),
        )
    assert instance.fetch_calls == []


def test_raw_and_silver_batch_readiness_recompute_physical_contracts(
    tmp_path: Path,
) -> None:
    lake_root, _, _, lineage = _fixture(tmp_path)
    with duckdb.connect(":memory:") as connection:
        raw = batch_etf_mins_raw_lake_readiness(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=(TRADE_DATE,),
            registered_trade_days=(TRADE_DATE,),
            lineage=lineage,
        )
    assert raw.status_for_trade_date(TRADE_DATE).ready
    assert raw.scanned_file_count == 5

    for source_freq in ETF_MINS_SOURCE_FREQS:
        raw_path = raw_etf_mins_path(lake_root, source_freq, TRADE_DATE)
        silver_path = silver_etf_mins_path(lake_root, source_freq, TRADE_DATE)
        silver_path.parent.mkdir(parents=True, exist_ok=True)
        silver_path.write_bytes(raw_path.read_bytes())
    with duckdb.connect(":memory:") as connection:
        silver = batch_etf_mins_silver_lake_readiness(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=(TRADE_DATE,),
            registered_trade_days=(TRADE_DATE,),
            raw_lineage=lineage,
        )
    assert silver.status_for_trade_date(TRADE_DATE).ready
    assert silver.scanned_file_count == 10

    mismatched_path = silver_etf_mins_path(lake_root, "5min", TRADE_DATE)
    candidate_path = mismatched_path.with_suffix(".tmp.parquet")
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT ts_code, freq, trade_time, open, close + 1 AS close, "
            "high, low, vol, amount, vwap, exchange FROM read_parquet("
            f"{duckdb_string(str(mismatched_path))}) ORDER BY ts_code, trade_time) "
            f"TO {duckdb_string(str(candidate_path))} (FORMAT PARQUET)"
        )
    candidate_path.replace(mismatched_path)
    with duckdb.connect(":memory:") as connection:
        silver = batch_etf_mins_silver_lake_readiness(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=(TRADE_DATE,),
            registered_trade_days=(TRADE_DATE,),
            raw_lineage=lineage,
        )
    status = silver.status_for_trade_date(TRADE_DATE)
    assert status.materialized
    assert not status.ready
    assert "silver_etf_mins_5m_raw_equivalence_check" in status.failed_check_names


def test_raw_batch_missing_lineage_is_not_materialized(tmp_path: Path) -> None:
    lake_root, _, _, lineage = _fixture(tmp_path)
    missing_key = (TRADE_DATE, "60min")
    reduced = EtfMinsRawMaterializationBatchEvidence(
        expected_partition_keys=lineage.expected_partition_keys,
        evidences_by_partition_and_freq={
            key: evidence
            for key, evidence in lineage.evidences_by_partition_and_freq.items()
            if key != missing_key
        },
        missing_partition_and_freqs=(missing_key,),
        materialization_query_count=5,
    )
    with duckdb.connect(":memory:") as connection:
        readiness = batch_etf_mins_raw_lake_readiness(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=(TRADE_DATE,),
            registered_trade_days=(TRADE_DATE,),
            lineage=reduced,
        )
    status = readiness.status_for_trade_date(TRADE_DATE)
    assert not status.materialized
    assert not status.ready
    assert status.reason == "etf_mins_raw_materialization_missing"
