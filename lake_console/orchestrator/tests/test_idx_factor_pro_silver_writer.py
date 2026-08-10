from pathlib import Path

import pytest

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    read_parquet,
)
from orchestrator.defs.io.idx_factor_pro_silver_writer import (
    IdxFactorProSilverValidationError,
    validate_idx_factor_pro_raw_silver_parity,
    validate_idx_factor_pro_silver_relation,
    write_idx_factor_pro_silver_partition,
)
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    silver_index_factor_pro_path,
    silver_index_factor_pro_staging_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_SILVER_COLUMN_TYPES,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
)
from tests._idx_factor_pro_helpers import (
    idx_factor_pro_row,
    write_idx_factor_pro_rows,
)

PARTITION = "2026-08-07"
SOURCE_TRADE_DATE = "20260807"


def _raw_rows(*, null_column: str | None = None) -> list[dict[str, object]]:
    return [
        idx_factor_pro_row(
            code,
            SOURCE_TRADE_DATE,
            null_column=null_column if index == 0 else None,
        )
        for index, code in enumerate(active_idx_factor_pro_daily_codes(PARTITION))
    ]


def _write_raw(
    tmp_path: Path,
    *,
    rows: list[dict[str, object]] | None = None,
    columns: tuple[str, ...] = IDX_FACTOR_PRO_SOURCE_COLUMNS,
) -> Path:
    raw_path = raw_idx_factor_pro_path(tmp_path / "data_lake", PARTITION)
    write_idx_factor_pro_rows(
        path=raw_path,
        rows=rows or _raw_rows(),
        duckdb_resource=DuckDBResource(),
        columns=columns,
    )
    return raw_path


def _write_silver(tmp_path: Path):
    return write_idx_factor_pro_silver_partition(
        lake_root_path=tmp_path / "data_lake",
        staging_root_path=tmp_path / "data_lake_staging",
        duckdb_resource=DuckDBResource(),
        partition_key=PARTITION,
        run_id="run-1",
    )


def test_silver_writer_pure_casts_all_columns_and_preserves_nulls(
    tmp_path: Path,
) -> None:
    raw_path = _write_raw(tmp_path, rows=_raw_rows(null_column="asi_bfq"))

    result = _write_silver(tmp_path)

    assert result.source_path == raw_path
    assert result.target_path == silver_index_factor_pro_path(
        tmp_path / "data_lake",
        PARTITION,
    )
    assert result.staging_path == silver_index_factor_pro_staging_path(
        tmp_path / "data_lake_staging",
        "run-1",
        PARTITION,
    )
    assert result.source_row_count == 11
    assert result.written_row_count == 11
    assert result.code_count == 11
    assert result.min_trade_date == PARTITION
    assert result.max_trade_date == PARTITION
    assert result.output_bytes > 0
    assert result.target_path.is_file()
    assert not result.staging_path.exists()

    with DuckDBResource().connect() as connection:
        silver_sql = read_parquet(result.target_path, hive_partitioning=False)
        audit = validate_idx_factor_pro_silver_relation(
            connection,
            relation_sql=silver_sql,
            expected_codes=active_idx_factor_pro_daily_codes(PARTITION),
            partition_key=PARTITION,
        )
        parity = validate_idx_factor_pro_raw_silver_parity(
            connection,
            raw_relation_sql=read_parquet(raw_path, hive_partitioning=False),
            silver_relation_sql=silver_sql,
        )
        null_count = connection.execute(
            f"SELECT count(*) FROM {silver_sql} WHERE asi_bfq IS NULL"
        ).fetchone()[0]

    assert audit.columns == IDX_FACTOR_PRO_SOURCE_COLUMNS
    assert audit.column_types == tuple(
        IDX_FACTOR_PRO_SILVER_COLUMN_TYPES[column]
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
    )
    assert audit.errors == ()
    assert parity.errors == ()
    assert null_count == 1


def test_silver_writer_fails_closed_when_raw_is_missing_or_invalid(
    tmp_path: Path,
) -> None:
    with pytest.raises(IdxFactorProSilverValidationError, match="source is missing"):
        _write_silver(tmp_path)

    _write_raw(tmp_path, columns=IDX_FACTOR_PRO_SOURCE_COLUMNS[:-1])
    with pytest.raises(
        IdxFactorProSilverValidationError,
        match="failed contract validation",
    ):
        _write_silver(tmp_path)

    assert not silver_index_factor_pro_path(
        tmp_path / "data_lake",
        PARTITION,
    ).exists()


def test_silver_writer_refuses_existing_target_without_rewriting(
    tmp_path: Path,
) -> None:
    _write_raw(tmp_path)
    first = _write_silver(tmp_path)
    original_bytes = first.target_path.read_bytes()

    with pytest.raises(IdxFactorProSilverValidationError, match="refuses overwrite"):
        _write_silver(tmp_path)

    assert first.target_path.read_bytes() == original_bytes


def test_raw_silver_parity_detects_value_changes_and_source_null_filling(
    tmp_path: Path,
) -> None:
    raw_path = _write_raw(tmp_path, rows=_raw_rows(null_column="asi_bfq"))
    result = _write_silver(tmp_path)
    mutated_path = tmp_path / "mutated-silver.parquet"
    silver_sql = read_parquet(result.target_path, hive_partitioning=False)
    first_code = active_idx_factor_pro_daily_codes(PARTITION)[0]
    with DuckDBResource().connect() as connection:
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT * REPLACE (
                  CASE WHEN ts_code = '{first_code}' THEN 999.0 ELSE open END AS open,
                  CASE WHEN ts_code = '{first_code}' THEN 1.0 ELSE asi_bfq END AS asi_bfq
                )
                FROM {silver_sql}
                ORDER BY ts_code, trade_date
                """,
                mutated_path,
            )
        )
        parity = validate_idx_factor_pro_raw_silver_parity(
            connection,
            raw_relation_sql=read_parquet(raw_path, hive_partitioning=False),
            silver_relation_sql=read_parquet(mutated_path, hive_partitioning=False),
        )

    assert parity.source_parity_errors == ()
    assert parity.numeric_mismatch_count == 2
    assert parity.raw_nonnull_to_silver_null_count == 0
    assert parity.raw_null_to_silver_nonnull_count == 1
    assert set(parity.cast_integrity_errors) == {
        "numeric_value_mismatch",
        "source_null_filled",
    }
    assert {sample[1] for sample in parity.mismatch_samples} == {
        "asi_bfq",
        "open",
    }
