from __future__ import annotations

from datetime import date
from pathlib import Path

import dagster as dg
import pytest

from orchestrator.defs.checks.etf_daily_checks import audit_etf_daily_silver_partition
from orchestrator.defs.corrections.etf_adj_factor_terminal_exceptions import (
    EtfAdjFactorTerminalExceptionError,
    load_etf_adj_factor_terminal_exception_registry,
    resolve_etf_adj_factor_terminal_exceptions,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import FUND_ADJ_RAW_SPEC
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    write_etf_adj_factor_silver_partition,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from tests.etf_daily_test_support import (
    basic_row,
    make_roots,
    write_basic_reference,
    write_raw_fixture,
)

PARTITION = "2026-09-15"


def _adj_row(
    ts_code: str,
    *,
    adj_factor: float = 1.0,
    discount_rate: float | None = None,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": PARTITION.replace("-", ""),
        "adj_factor": adj_factor,
        "discount_rate": discount_rate,
    }


def _reference(lake_root: Path, staging_root: Path, *rows: dict[str, object]):
    return write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=rows,
        eligibility_as_of=date(2026, 9, 15),
    )


def test_registry_rejects_unknown_fields_and_duplicate_codes(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown.yaml"
    unknown.write_text(
        "schema_version: 1\nentries:\n"
        "  - ts_code: 512390.SH\n"
        "    effective_from: '2026-09-15'\n"
        "    effective_to: null\n"
        "    frozen_adj_factor: '1.3094'\n"
        "    frozen_discount_rate: null\n"
        "    status: active\n"
        "    reason_code: terminal_trading_suspension\n"
        "    approval_ref: test\n"
        "    unexpected: value\n",
        encoding="utf-8",
    )
    with pytest.raises(EtfAdjFactorTerminalExceptionError, match="fields"):
        load_etf_adj_factor_terminal_exception_registry(unknown)

    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(
        "schema_version: 1\nentries:\n"
        "  - ts_code: 512390.SH\n"
        "    effective_from: '2026-09-15'\n"
        "    effective_to: null\n"
        "    frozen_adj_factor: '1.3094'\n"
        "    frozen_discount_rate: null\n"
        "    status: active\n"
        "    reason_code: terminal_trading_suspension\n"
        "    approval_ref: test\n"
        "  - ts_code: 512390.SH\n"
        "    effective_from: '2026-09-15'\n"
        "    effective_to: null\n"
        "    frozen_adj_factor: '1.3094'\n"
        "    frozen_discount_rate: null\n"
        "    status: active\n"
        "    reason_code: terminal_trading_suspension\n"
        "    approval_ref: test\n",
        encoding="utf-8",
    )
    with pytest.raises(EtfAdjFactorTerminalExceptionError, match="duplicate"):
        load_etf_adj_factor_terminal_exception_registry(duplicate)


def test_registry_hash_is_stable_for_canonical_entry_order(tmp_path: Path) -> None:
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "schema_version: 1\nentries:\n"
        "  - ts_code: 512390.SH\n"
        "    effective_from: '2026-09-15'\n"
        "    effective_to: null\n"
        "    frozen_adj_factor: '1.3094'\n"
        "    frozen_discount_rate: null\n"
        "    status: active\n"
        "    reason_code: terminal_trading_suspension\n"
        "    approval_ref: test\n",
        encoding="utf-8",
    )
    assert (
        load_etf_adj_factor_terminal_exception_registry(registry).content_hash
        == load_etf_adj_factor_terminal_exception_registry(registry).content_hash
    )


def test_writer_injects_only_the_approved_missing_terminal_factor(tmp_path: Path) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    reference = _reference(
        lake_root,
        staging_root,
        basic_row("510330.SH"),
        basic_row("512390.SH"),
    )
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_ADJ_RAW_SPEC,
        partition_key=PARTITION,
        rows=(_adj_row("510330.SH"),),
    )

    result = write_etf_adj_factor_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="terminal-injection",
        basic_reference=reference,
    )

    with DuckDBResource().connect() as connection:
        rows = connection.execute(
            f"SELECT ts_code, adj_factor, discount_rate FROM {read_parquet(result.target_path, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall()
    assert rows == [("510330.SH", 1.0, None), ("512390.SH", 1.3094, None)]
    assert result.raw_row_count == result.selected_row_count == 1
    assert result.written_row_count == 2
    assert result.approved_exception_row_count == 1
    assert result.exception_source_resumption_count == 0
    assert result.exception_registry_hash is not None
    assert result.exception_sample_codes == ("512390.SH",)

    instance = dg.DagsterInstance.ephemeral()
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=result.asset_key,
            partition=PARTITION,
            metadata=build_materialization_metadata(
                uri=result.target_path,
                row_count=result.written_row_count,
                observed_columns=FUND_ADJ_RAW_SPEC.source_columns,
                extra_metadata=result.to_details(),
            ),
        )
    )
    audit = audit_etf_daily_silver_partition(
        instance=instance,
        lake_root_path=lake_root,
        duckdb_resource=DuckDBResource(),
        spec=FUND_ADJ_SILVER_SPEC,
        partition_key=PARTITION,
        check_kind="source_parity",
    )
    assert audit.source_parity is not None
    assert audit.source_parity.error_codes == ()
    assert audit.source_parity.approved_exception_row_count == 1


def test_writer_prefers_matching_source_resumption_without_duplicate(tmp_path: Path) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    reference = _reference(lake_root, staging_root, basic_row("512390.SH"))
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_ADJ_RAW_SPEC,
        partition_key=PARTITION,
        rows=(_adj_row("512390.SH", adj_factor=1.3094),),
    )

    result = write_etf_adj_factor_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="source-resumption",
        basic_reference=reference,
    )

    assert result.written_row_count == 1
    assert result.approved_exception_row_count == 0
    assert result.exception_source_resumption_count == 1


def test_writer_rejects_changed_source_value_without_promoting(tmp_path: Path) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    reference = _reference(lake_root, staging_root, basic_row("512390.SH"))
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_ADJ_RAW_SPEC,
        partition_key=PARTITION,
        rows=(_adj_row("512390.SH", adj_factor=1.4),),
    )
    target = FUND_ADJ_RAW_SPEC.target_path_builder(lake_root, PARTITION)

    with pytest.raises(
        EtfAdjFactorTerminalExceptionError,
        match="terminal_exception_source_value_changed",
    ):
        write_etf_adj_factor_silver_partition(
            lake_root_path=lake_root,
            staging_root_path=staging_root,
            duckdb_resource=DuckDBResource(),
            partition_key=PARTITION,
            operation_id="source-changed",
            basic_reference=reference,
        )
    assert not (lake_root / "silver" / "etf_adj_factor").exists()
    assert target.is_file()


def test_writer_replaces_only_the_approved_terminal_exception_delta(tmp_path: Path) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    reference = _reference(
        lake_root,
        staging_root,
        basic_row("510330.SH"),
        basic_row("512390.SH"),
    )
    raw_path = write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_ADJ_RAW_SPEC,
        partition_key=PARTITION,
        rows=(_adj_row("510330.SH"),),
    )
    target_path = FUND_ADJ_SILVER_SPEC.target_path_builder(lake_root, PARTITION)
    target_path.parent.mkdir(parents=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            f"COPY (SELECT ts_code, strptime(trade_date, '%Y%m%d')::DATE AS trade_date, adj_factor, discount_rate FROM {read_parquet(raw_path, hive_partitioning=False)}) TO {duckdb_string(target_path)} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )

    result = write_etf_adj_factor_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="terminal-delta",
        basic_reference=reference,
    )

    assert result.write_mode == "promote_terminal_exception_delta"
    assert result.written_row_count == 2


def test_non_listed_basic_does_not_inject_terminal_factor(tmp_path: Path) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    reference = _reference(
        lake_root,
        staging_root,
        basic_row("512390.SH", list_status="D"),
    )
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_ADJ_RAW_SPEC,
        partition_key=PARTITION,
        rows=(_adj_row("512390.SH"),),
    )

    result = write_etf_adj_factor_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        operation_id="not-listed",
        basic_reference=reference,
    )

    assert result.written_row_count == 0
    assert result.approved_exception_row_count == 0


def test_resolver_rejects_retired_registry_entries(tmp_path: Path) -> None:
    registry_path = tmp_path / "retired.yaml"
    registry_path.write_text(
        "schema_version: 1\nentries:\n"
        "  - ts_code: 512390.SH\n"
        "    effective_from: '2026-09-15'\n"
        "    effective_to: null\n"
        "    frozen_adj_factor: '1.3094'\n"
        "    frozen_discount_rate: null\n"
        "    status: retired\n"
        "    reason_code: terminal_trading_suspension\n"
        "    approval_ref: test\n",
        encoding="utf-8",
    )
    registry = load_etf_adj_factor_terminal_exception_registry(registry_path)
    with DuckDBResource().connect() as connection:
        resolution = resolve_etf_adj_factor_terminal_exceptions(
            connection,
            partition_key=PARTITION,
            raw_relation_sql="SELECT '512390.SH'::VARCHAR AS ts_code, '20260915'::VARCHAR AS trade_date, 1.0::DOUBLE AS adj_factor, NULL::DOUBLE AS discount_rate WHERE FALSE",
            basic_relation_sql="SELECT '512390.SH'::VARCHAR AS ts_code, 'SH'::VARCHAR AS exchange, 'L'::VARCHAR AS list_status, DATE '2020-01-01' AS list_date",
            registry=registry,
        )
    assert resolution.approved_exception_row_count == 0
    assert resolution.eligible_entries == ()


def test_resolver_rejects_expired_registry_entries(tmp_path: Path) -> None:
    registry_path = tmp_path / "expired.yaml"
    registry_path.write_text(
        "schema_version: 1\nentries:\n"
        "  - ts_code: 512390.SH\n"
        "    effective_from: '2026-09-14'\n"
        "    effective_to: '2026-09-14'\n"
        "    frozen_adj_factor: '1.3094'\n"
        "    frozen_discount_rate: null\n"
        "    status: active\n"
        "    reason_code: terminal_trading_suspension\n"
        "    approval_ref: test\n",
        encoding="utf-8",
    )
    registry = load_etf_adj_factor_terminal_exception_registry(registry_path)
    with DuckDBResource().connect() as connection:
        resolution = resolve_etf_adj_factor_terminal_exceptions(
            connection,
            partition_key=PARTITION,
            raw_relation_sql="SELECT '512390.SH'::VARCHAR AS ts_code, '20260915'::VARCHAR AS trade_date, 1.0::DOUBLE AS adj_factor, NULL::DOUBLE AS discount_rate WHERE FALSE",
            basic_relation_sql="SELECT '512390.SH'::VARCHAR AS ts_code, 'SH'::VARCHAR AS exchange, 'L'::VARCHAR AS list_status, DATE '2020-01-01' AS list_date",
            registry=registry,
        )
    assert resolution.approved_exception_row_count == 0
    assert resolution.eligible_entries == ()
