from __future__ import annotations

import os
from pathlib import Path

import dagster as dg

from orchestrator.defs.checks.etf_daily_checks import (
    evaluate_etf_daily_raw_check,
    raw_tushare_fund_adj_key_integrity_check,
    raw_tushare_fund_adj_partition_scope_check,
    raw_tushare_fund_adj_source_contract_check,
    raw_tushare_fund_daily_key_integrity_check,
    raw_tushare_fund_daily_partition_scope_check,
    raw_tushare_fund_daily_source_contract_check,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawWriteResult,
    write_fund_daily_raw_partition,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResult,
)
from orchestrator.defs.run_contracts.etf_daily import FUND_DAILY_SOURCE_COLUMNS
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata

PARTITION = "2026-09-01"
SOURCE_DATE = "20260901"


class _FakeTushare:
    def call(self, api_name, params, fields):  # type: ignore[no-untyped-def]
        return TushareResult(
            rows=[
                {
                    "ts_code": "510330.SH",
                    "trade_date": SOURCE_DATE,
                    "pre_close": 4.0,
                    "open": 4.0,
                    "high": 4.02,
                    "low": 3.99,
                    "close": 4.01,
                    "change": 0.01,
                    "pct_chg": 0.25,
                    "vol": 100.0,
                    "amount": 400.0,
                }
            ],
            columns=FUND_DAILY_SOURCE_COLUMNS,
            metadata={},
        )


class _CheckContext:
    def __init__(self, instance: dg.DagsterInstance) -> None:
        self.instance = instance
        self.partition_keys = (PARTITION,)


def _write_raw(tmp_path: Path) -> tuple[Path, EtfDailyRawWriteResult]:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    result = write_fund_daily_raw_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        tushare=_FakeTushare(),  # type: ignore[arg-type]
        partition_key=PARTITION,
        operation_id="p2-check-test",
    )
    return lake_root, result


def _report_materialization(
    instance: dg.DagsterInstance,
    result: EtfDailyRawWriteResult,
    *,
    source_row_count: int | None = None,
) -> None:
    details = dict(result.to_details())
    if source_row_count is not None:
        details["source_row_count"] = source_row_count
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=result.asset_key,
            partition=PARTITION,
            metadata=build_materialization_metadata(
                uri=result.target_path,
                row_count=result.written_row_count,
                observed_columns=result.source_fields,
                extra_metadata=details,
            ),
        )
    )


def _evaluate(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    check_kind: str,
) -> dg.AssetCheckResult:
    return evaluate_etf_daily_raw_check(
        context=_CheckContext(instance),  # type: ignore[arg-type]
        lake_root=LakeRootResource(root_path=str(lake_root)),
        duckdb_resource=DuckDBResource(),
        spec=FUND_DAILY_RAW_SPEC,
        check_kind=check_kind,
    )


def test_all_raw_check_definitions_are_partitioned_and_blocking() -> None:
    checks = (
        raw_tushare_fund_daily_source_contract_check,
        raw_tushare_fund_daily_partition_scope_check,
        raw_tushare_fund_daily_key_integrity_check,
        raw_tushare_fund_adj_source_contract_check,
        raw_tushare_fund_adj_partition_scope_check,
        raw_tushare_fund_adj_key_integrity_check,
    )
    for check in checks:
        spec = next(iter(check.check_specs))
        assert spec.blocking is True
        assert spec.partitions_def is not None


def test_raw_checks_pass_for_matching_file_and_materialization(
    tmp_path: Path,
) -> None:
    lake_root, result = _write_raw(tmp_path)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance, result)

    for check_kind in ("source_contract", "partition_scope", "key_integrity"):
        check_result = _evaluate(
            instance=instance,
            lake_root=lake_root,
            check_kind=check_kind,
        )
        assert check_result.passed is True
        assert (
            check_result.metadata["goldenshare/failed_rule_names"].value == []
        )


def test_source_contract_check_requires_matching_materialization_counts(
    tmp_path: Path,
) -> None:
    lake_root, result = _write_raw(tmp_path)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance, result, source_row_count=2)

    check_result = _evaluate(
        instance=instance,
        lake_root=lake_root,
        check_kind="source_contract",
    )

    assert check_result.passed is False
    assert "row_count_mismatch" in check_result.metadata[
        "goldenshare/failed_rule_names"
    ].value
    assert "materialization_row_counts_mismatch" in check_result.metadata[
        "goldenshare/failed_rule_names"
    ].value


def test_partition_and_key_checks_detect_existing_bad_raw_file(
    tmp_path: Path,
) -> None:
    lake_root, result = _write_raw(tmp_path)
    replacement = result.target_path.with_name("replacement.parquet")
    relation = read_parquet(result.target_path, hive_partitioning=False)
    with DuckDBResource().connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM {relation}
              UNION ALL BY NAME
              SELECT * FROM {relation}
              UNION ALL BY NAME
              SELECT * REPLACE ('20260829' AS trade_date) FROM {relation}
            ) TO {duckdb_string(replacement)} (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    os.replace(replacement, result.target_path)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance, result)

    partition_result = _evaluate(
        instance=instance,
        lake_root=lake_root,
        check_kind="partition_scope",
    )
    key_result = _evaluate(
        instance=instance,
        lake_root=lake_root,
        check_kind="key_integrity",
    )

    assert partition_result.passed is False
    assert "partition_date" in partition_result.metadata[
        "goldenshare/failed_rule_names"
    ].value
    assert key_result.passed is False
    assert "duplicate_key" in key_result.metadata[
        "goldenshare/failed_rule_names"
    ].value
