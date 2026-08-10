from pathlib import Path

from orchestrator.defs.checks.idx_factor_pro_checks import (
    audit_idx_factor_pro_raw_partition,
    raw_tushare_idx_factor_pro_contract_check,
    raw_tushare_idx_factor_pro_key_integrity_check,
    raw_tushare_idx_factor_pro_nullable_drift_check,
    raw_tushare_idx_factor_pro_partition_scope_check,
    raw_tushare_idx_factor_pro_selection_parity_check,
)
from orchestrator.defs.paths import raw_idx_factor_pro_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_RAW_CHECKS,
    IDX_FACTOR_PRO_RAW_NULLABLE_CHECK,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
)
from tests._idx_factor_pro_helpers import (
    idx_factor_pro_row,
    write_idx_factor_pro_rows,
)

PARTITION = "2026-08-07"
SOURCE_TRADE_DATE = "20260807"


def _expected_rows(*, null_column: str | None = None) -> list[dict[str, object]]:
    return [
        idx_factor_pro_row(
            code,
            SOURCE_TRADE_DATE,
            null_column=null_column if index == 0 else None,
        )
        for index, code in enumerate(active_idx_factor_pro_daily_codes(PARTITION))
    ]


def test_raw_audit_accepts_exact_pool_and_records_nullable_ratios(
    tmp_path: Path,
) -> None:
    duckdb = DuckDBResource()
    path = raw_idx_factor_pro_path(tmp_path, PARTITION)
    write_idx_factor_pro_rows(
        path=path,
        rows=_expected_rows(null_column="asi_bfq"),
        duckdb_resource=duckdb,
    )

    audit = audit_idx_factor_pro_raw_partition(
        lake_root_path=tmp_path,
        duckdb_resource=duckdb,
        partition_key=PARTITION,
    )

    assert audit.error_type is None
    assert audit.relation is not None
    assert audit.relation.errors == ()
    assert audit.relation.null_ratios[0] == (
        "asi_bfq",
        1 / len(active_idx_factor_pro_daily_codes(PARTITION)),
    )


def test_raw_audit_reports_missing_duplicate_and_schema_drift(
    tmp_path: Path,
) -> None:
    duckdb = DuckDBResource()
    path = raw_idx_factor_pro_path(tmp_path, PARTITION)
    rows = _expected_rows()[:-1]
    rows.append(dict(rows[0]))
    write_idx_factor_pro_rows(
        path=path,
        rows=rows,
        duckdb_resource=duckdb,
    )

    audit = audit_idx_factor_pro_raw_partition(
        lake_root_path=tmp_path,
        duckdb_resource=duckdb,
        partition_key=PARTITION,
    )
    assert audit.relation is not None
    assert "missing_codes" in audit.relation.scope_errors
    assert "duplicate_key" in audit.relation.key_errors
    assert "row_count" in audit.relation.parity_errors

    path.unlink()
    write_idx_factor_pro_rows(
        path=path,
        rows=_expected_rows(),
        duckdb_resource=duckdb,
        columns=IDX_FACTOR_PRO_SOURCE_COLUMNS[:-1],
    )
    schema_audit = audit_idx_factor_pro_raw_partition(
        lake_root_path=tmp_path,
        duckdb_resource=duckdb,
        partition_key=PARTITION,
    )
    assert schema_audit.relation is not None
    assert "schema_columns" in schema_audit.relation.schema_errors


def test_raw_check_definitions_match_blocking_and_warn_contracts() -> None:
    blocking_checks = (
        raw_tushare_idx_factor_pro_contract_check,
        raw_tushare_idx_factor_pro_partition_scope_check,
        raw_tushare_idx_factor_pro_key_integrity_check,
        raw_tushare_idx_factor_pro_selection_parity_check,
    )
    assert tuple(
        next(iter(check.check_specs)).name for check in blocking_checks
    ) == IDX_FACTOR_PRO_RAW_CHECKS
    assert all(next(iter(check.check_specs)).blocking for check in blocking_checks)
    nullable_spec = next(
        iter(raw_tushare_idx_factor_pro_nullable_drift_check.check_specs)
    )
    assert nullable_spec.name == IDX_FACTOR_PRO_RAW_NULLABLE_CHECK
    assert nullable_spec.blocking is False
