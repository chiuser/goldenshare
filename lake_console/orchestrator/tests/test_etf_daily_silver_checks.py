from __future__ import annotations

import os
from pathlib import Path

import dagster as dg
import pytest

from orchestrator.defs.checks.etf_daily_checks import (
    evaluate_etf_daily_silver_check,
    silver_etf_adj_factor_basic_coverage_check,
    silver_etf_adj_factor_contract_check,
    silver_etf_adj_factor_domain_check,
    silver_etf_adj_factor_key_integrity_check,
    silver_etf_adj_factor_source_filter_check,
    silver_etf_adj_factor_source_parity_check,
    silver_etf_daily_bar_domain_check,
    silver_etf_daily_basic_coverage_check,
    silver_etf_daily_contract_check,
    silver_etf_daily_key_integrity_check,
    silver_etf_daily_source_filter_check,
    silver_etf_daily_source_parity_check,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    EtfDailySilverSpec,
    EtfDailySilverWriteResult,
    write_etf_adj_factor_silver_partition,
    write_etf_daily_silver_partition,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.etf_daily import (
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_SOURCE_COLUMNS,
    SILVER_ETF_DAILY_ASSET_KEY,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from tests.etf_daily_test_support import (
    basic_row,
    make_roots,
    write_basic_reference,
    write_raw_fixture,
)

PARTITION = "2026-09-01"
SOURCE_DATE = "20260901"


class _CheckContext:
    def __init__(self, instance: dg.DagsterInstance) -> None:
        self.instance = instance
        self.partition_keys = (PARTITION,)


def _daily_row(ts_code: str = "510330.SH") -> dict[str, object]:
    return {
        "ts_code": ts_code,
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


def _adj_row(
    ts_code: str = "510330.SH",
    *,
    adj_factor: float | None = 1.0,
    discount_rate: float | None = None,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": SOURCE_DATE,
        "adj_factor": adj_factor,
        "discount_rate": discount_rate,
    }


def _report_materialization(
    instance: dg.DagsterInstance,
    result: EtfDailySilverWriteResult,
) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=result.asset_key,
            partition=PARTITION,
            metadata=build_materialization_metadata(
                uri=result.target_path,
                row_count=result.written_row_count,
                observed_columns=(
                    FUND_DAILY_SOURCE_COLUMNS
                    if result.asset_key == SILVER_ETF_DAILY_ASSET_KEY
                    else FUND_ADJ_SOURCE_COLUMNS
                ),
                extra_metadata=result.to_details(),
            ),
        )
    )


def _evaluate(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    spec: EtfDailySilverSpec,
    check_kind: str,
) -> dg.AssetCheckResult:
    return evaluate_etf_daily_silver_check(
        context=_CheckContext(instance),  # type: ignore[arg-type]
        lake_root=LakeRootResource(root_path=str(lake_root)),
        duckdb_resource=DuckDBResource(),
        spec=spec,
        check_kind=check_kind,
    )


def _write_daily(
    tmp_path: Path,
    *,
    rows: tuple[dict[str, object], ...] | None = None,
    basic_rows: tuple[dict[str, object], ...] | None = None,
) -> tuple[Path, EtfDailySilverWriteResult]:
    lake_root, staging_root = make_roots(tmp_path)
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=basic_rows or (basic_row("510330.SH"),),
    )
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_DAILY_RAW_SPEC,
        partition_key=PARTITION,
        rows=rows or (_daily_row(),),
    )
    result = write_etf_daily_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="silver-check",
        basic_reference=reference,
    )
    return lake_root, result


def _write_adj(
    tmp_path: Path,
    *,
    rows: tuple[dict[str, object], ...] | None = None,
    basic_rows: tuple[dict[str, object], ...] | None = None,
) -> tuple[Path, EtfDailySilverWriteResult]:
    lake_root, staging_root = make_roots(tmp_path)
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=basic_rows or (basic_row("510330.SH"),),
    )
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_ADJ_RAW_SPEC,
        partition_key=PARTITION,
        rows=rows or (_adj_row(),),
    )
    result = write_etf_adj_factor_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="silver-check",
        basic_reference=reference,
    )
    return lake_root, result


def _replace_target(result: EtfDailySilverWriteResult, select_sql: str) -> None:
    replacement = result.target_path.with_name("replacement.parquet")
    relation = read_parquet(result.target_path, hive_partitioning=False)
    with DuckDBResource().connect() as connection:
        connection.execute(
            f"COPY ({select_sql.format(relation=relation)}) TO "
            f"{duckdb_string(replacement)} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    os.replace(replacement, result.target_path)


def test_silver_check_definitions_have_exact_blocking_policy() -> None:
    checks = (
        silver_etf_daily_contract_check,
        silver_etf_daily_source_filter_check,
        silver_etf_daily_source_parity_check,
        silver_etf_daily_key_integrity_check,
        silver_etf_daily_bar_domain_check,
        silver_etf_daily_basic_coverage_check,
        silver_etf_adj_factor_contract_check,
        silver_etf_adj_factor_source_filter_check,
        silver_etf_adj_factor_source_parity_check,
        silver_etf_adj_factor_key_integrity_check,
        silver_etf_adj_factor_domain_check,
        silver_etf_adj_factor_basic_coverage_check,
    )
    for index, check in enumerate(checks):
        spec = next(iter(check.check_specs))
        assert spec.partitions_def is not None
        assert spec.blocking is (index not in {5, 11})


@pytest.mark.parametrize(
    "check_kind",
    ("contract", "source_filter", "source_parity", "key_integrity", "domain", "coverage"),
)
def test_daily_checks_pass_on_one_fully_aligned_partition(
    tmp_path: Path,
    check_kind: str,
) -> None:
    lake_root, result = _write_daily(tmp_path)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance, result)

    check_result = _evaluate(
        instance=instance,
        lake_root=lake_root,
        spec=FUND_DAILY_SILVER_SPEC,
        check_kind=check_kind,
    )

    assert check_result.passed is True
    assert len(
        check_result.metadata["goldenshare/input_file_paths"].value
    ) == {
        "contract": 0,
        "source_filter": 1,
        "source_parity": 2,
        "key_integrity": 0,
        "domain": 0,
        "coverage": 2,
    }[check_kind]


@pytest.mark.parametrize(
    ("check_kind", "replacement_sql", "expected_rule"),
    [
        ("contract", "SELECT * EXCLUDE (amount) FROM {relation}", "schema_columns"),
        (
            "source_filter",
            "SELECT * REPLACE ('588000.SH' AS ts_code) FROM {relation}",
            "source_filter",
        ),
        (
            "source_parity",
            "SELECT * REPLACE (amount + 1 AS amount) FROM {relation}",
            "expected_rows_missing",
        ),
        (
            "key_integrity",
            "SELECT * FROM {relation} UNION ALL SELECT * FROM {relation}",
            "duplicate_key",
        ),
        (
            "domain",
            "SELECT * REPLACE (CAST(-1.0 AS DOUBLE) AS vol) FROM {relation}",
            "negative_volume_count",
        ),
    ],
)
def test_each_daily_blocking_check_detects_its_own_failure(
    tmp_path: Path,
    check_kind: str,
    replacement_sql: str,
    expected_rule: str,
) -> None:
    lake_root, result = _write_daily(tmp_path)
    _replace_target(result, replacement_sql)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance, result)

    check_result = _evaluate(
        instance=instance,
        lake_root=lake_root,
        spec=FUND_DAILY_SILVER_SPEC,
        check_kind=check_kind,
    )

    assert check_result.passed is False
    assert expected_rule in check_result.metadata[
        "goldenshare/failed_rule_names"
    ].value


def test_daily_coverage_difference_is_warn_and_does_not_become_blocking(
    tmp_path: Path,
) -> None:
    lake_root, result = _write_daily(
        tmp_path,
        basic_rows=(basic_row("510330.SH"), basic_row("159919.SZ")),
    )
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance, result)

    check_result = _evaluate(
        instance=instance,
        lake_root=lake_root,
        spec=FUND_DAILY_SILVER_SPEC,
        check_kind="coverage",
    )

    assert check_result.passed is False
    assert check_result.severity is dg.AssetCheckSeverity.WARN
    assert check_result.metadata["goldenshare/missing_expected_code_count"].value == 1
    assert check_result.metadata["goldenshare/failed_rule_names"].value == [
        "missing_expected_codes"
    ]


def test_source_filter_check_revalidates_the_materialized_basic_reference(
    tmp_path: Path,
) -> None:
    lake_root, result = _write_daily(tmp_path)
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance, result)
    Path(result.basic_reference.silver_uri).write_bytes(b"not parquet")

    check_result = _evaluate(
        instance=instance,
        lake_root=lake_root,
        spec=FUND_DAILY_SILVER_SPEC,
        check_kind="source_filter",
    )

    assert check_result.passed is False
    assert any(
        name.startswith("basic_reference_")
        for name in check_result.metadata["goldenshare/failed_rule_names"].value
    )


def test_adj_domain_counts_invalid_factor_and_nonfinite_discount_rate(
    tmp_path: Path,
) -> None:
    rows = (
        _adj_row("510330.SH", adj_factor=None),
        _adj_row("159919.SZ", adj_factor=0.0),
        _adj_row("512000.SH", adj_factor=float("inf")),
        _adj_row("513000.SH", discount_rate=float("-inf")),
    )
    lake_root, result = _write_adj(
        tmp_path,
        rows=rows,
        basic_rows=tuple(basic_row(str(row["ts_code"])) for row in rows),
    )
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance, result)

    check_result = _evaluate(
        instance=instance,
        lake_root=lake_root,
        spec=FUND_ADJ_SILVER_SPEC,
        check_kind="domain",
    )

    assert check_result.passed is False
    assert check_result.metadata["goldenshare/domain_failure_counts"].value == {
        "adj_factor_null_count": 1,
        "adj_factor_nonfinite_count": 1,
        "adj_factor_non_positive_count": 1,
        "discount_rate_nonfinite_count": 1,
    }
    assert check_result.metadata["goldenshare/failed_row_count"].value == 4


@pytest.mark.parametrize(
    "check_kind",
    ("contract", "source_filter", "source_parity", "key_integrity", "domain", "coverage"),
)
def test_adj_checks_pass_with_null_negative_and_extreme_finite_discount_rate(
    tmp_path: Path,
    check_kind: str,
) -> None:
    rows = (
        _adj_row("510330.SH", discount_rate=None),
        _adj_row("159919.SZ", discount_rate=-3.5),
        _adj_row("512000.SH", discount_rate=9_940.7),
    )
    lake_root, result = _write_adj(
        tmp_path,
        rows=rows,
        basic_rows=tuple(basic_row(str(row["ts_code"])) for row in rows),
    )
    instance = dg.DagsterInstance.ephemeral()
    _report_materialization(instance, result)

    assert _evaluate(
        instance=instance,
        lake_root=lake_root,
        spec=FUND_ADJ_SILVER_SPEC,
        check_kind=check_kind,
    ).passed is True
