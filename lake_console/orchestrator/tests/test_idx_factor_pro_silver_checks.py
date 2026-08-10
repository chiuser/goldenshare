from pathlib import Path

from orchestrator.defs.checks.idx_factor_pro_checks import (
    audit_idx_factor_pro_silver_partition,
    silver_index_factor_pro_cast_integrity_check,
    silver_index_factor_pro_contract_check,
    silver_index_factor_pro_source_parity_check,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.idx_factor_pro_silver_writer import (
    write_idx_factor_pro_silver_partition,
)
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    silver_index_factor_pro_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_SILVER_ASSET_KEY,
    IDX_FACTOR_PRO_SILVER_CHECKS,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
)
from tests._idx_factor_pro_helpers import (
    idx_factor_pro_row,
    write_idx_factor_pro_rows,
)

PARTITION = "2026-08-07"
SOURCE_TRADE_DATE = "20260807"


def _prepare_partition(tmp_path: Path, *, null_column: str | None = None) -> Path:
    lake_root = tmp_path / "data_lake"
    rows = [
        idx_factor_pro_row(
            code,
            SOURCE_TRADE_DATE,
            null_column=null_column if index == 0 else None,
        )
        for index, code in enumerate(active_idx_factor_pro_daily_codes(PARTITION))
    ]
    write_idx_factor_pro_rows(
        path=raw_idx_factor_pro_path(lake_root, PARTITION),
        rows=rows,
        duckdb_resource=DuckDBResource(),
    )
    write_idx_factor_pro_silver_partition(
        lake_root_path=lake_root,
        staging_root_path=tmp_path / "data_lake_staging",
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        run_id="checks",
    )
    return lake_root


def _replace_silver_with_query(lake_root: Path, select_sql: str) -> None:
    target = silver_index_factor_pro_path(lake_root, PARTITION)
    replacement = target.with_name("replacement.parquet")
    with DuckDBResource().connect() as connection:
        connection.execute(copy_query_to_parquet(select_sql, replacement))
    replacement.replace(target)


def test_silver_audit_accepts_exact_contract_source_parity_and_nulls(
    tmp_path: Path,
) -> None:
    lake_root = _prepare_partition(tmp_path, null_column="asi_bfq")

    audit = audit_idx_factor_pro_silver_partition(
        lake_root_path=lake_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
    )

    assert audit.raw_error_type is None
    assert audit.silver_error_type is None
    assert audit.raw_relation is not None
    assert audit.raw_relation.errors == ()
    assert audit.silver_relation is not None
    assert audit.silver_relation.errors == ()
    assert audit.parity is not None
    assert audit.parity.errors == ()


def test_silver_check_definitions_are_blocking_and_match_contract() -> None:
    checks = (
        silver_index_factor_pro_contract_check,
        silver_index_factor_pro_source_parity_check,
        silver_index_factor_pro_cast_integrity_check,
    )
    assert tuple(next(iter(check.check_specs)).name for check in checks) == (
        IDX_FACTOR_PRO_SILVER_CHECKS
    )
    for check in checks:
        spec = next(iter(check.check_specs))
        assert spec.asset_key.to_user_string() == IDX_FACTOR_PRO_SILVER_ASSET_KEY
        assert spec.blocking is True


def test_silver_audit_detects_schema_and_source_key_drift(tmp_path: Path) -> None:
    lake_root = _prepare_partition(tmp_path)
    target = silver_index_factor_pro_path(lake_root, PARTITION)
    source = read_parquet(target, hive_partitioning=False)
    columns = ", ".join(
        f'"{column}"' for column in IDX_FACTOR_PRO_SOURCE_COLUMNS[:-1]
    )
    _replace_silver_with_query(lake_root, f"SELECT {columns} FROM {source}")

    schema_audit = audit_idx_factor_pro_silver_partition(
        lake_root_path=lake_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
    )
    assert schema_audit.silver_relation is not None
    assert "schema_columns" in schema_audit.silver_relation.schema_errors
    assert schema_audit.parity is None

    lake_root = _prepare_partition(tmp_path / "key-drift")
    target = silver_index_factor_pro_path(lake_root, PARTITION)
    source = read_parquet(target, hive_partitioning=False)
    missing_code = active_idx_factor_pro_daily_codes(PARTITION)[-1]
    _replace_silver_with_query(
        lake_root,
        f"SELECT * FROM {source} WHERE ts_code != '{missing_code}'",
    )
    key_audit = audit_idx_factor_pro_silver_partition(
        lake_root_path=lake_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
    )
    assert key_audit.silver_relation is not None
    assert key_audit.silver_relation.missing_codes == (missing_code,)
    assert key_audit.parity is None


def test_silver_audit_detects_numeric_and_null_mutation(tmp_path: Path) -> None:
    lake_root = _prepare_partition(tmp_path, null_column="asi_bfq")
    target = silver_index_factor_pro_path(lake_root, PARTITION)
    source = read_parquet(target, hive_partitioning=False)
    first_code = active_idx_factor_pro_daily_codes(PARTITION)[0]
    _replace_silver_with_query(
        lake_root,
        f"""
        SELECT * REPLACE (
          CASE WHEN ts_code = '{first_code}' THEN 999.0 ELSE open END AS open,
          CASE WHEN ts_code = '{first_code}' THEN 1.0 ELSE asi_bfq END AS asi_bfq
        )
        FROM {source}
        """,
    )

    audit = audit_idx_factor_pro_silver_partition(
        lake_root_path=lake_root,
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
    )

    assert audit.parity is not None
    assert audit.parity.source_parity_errors == ()
    assert audit.parity.numeric_mismatch_count == 2
    assert audit.parity.raw_null_to_silver_nonnull_count == 1
    assert set(audit.parity.cast_integrity_errors) == {
        "numeric_value_mismatch",
        "source_null_filled",
    }
