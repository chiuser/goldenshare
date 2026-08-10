from pathlib import Path

import pytest

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.idx_factor_pro_raw_writer import (
    IdxFactorProRawValidationError,
    validate_idx_factor_pro_raw_relation,
    write_idx_factor_pro_raw_partition,
)
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    raw_idx_factor_pro_staging_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy
from tests._idx_factor_pro_helpers import FakeIdxFactorProTushare, idx_factor_pro_row

PARTITION = "2026-08-07"
SOURCE_TRADE_DATE = "20260807"


def _source_rows(*, include_all_expected: bool = True) -> list[dict[str, object]]:
    codes = active_idx_factor_pro_daily_codes(PARTITION)
    expected = codes if include_all_expected else codes[:-1]
    return [idx_factor_pro_row(code, SOURCE_TRADE_DATE) for code in expected] + [
        idx_factor_pro_row("999999.SH", SOURCE_TRADE_DATE)
    ]


def _write(
    *,
    tmp_path: Path,
    tushare: FakeIdxFactorProTushare,
):
    return write_idx_factor_pro_raw_partition(
        lake_root_path=tmp_path / "data_lake",
        staging_root_path=tmp_path / "data_lake_staging",
        duckdb_resource=DuckDBResource(),
        tushare=tushare,  # type: ignore[arg-type]
        partition_key=PARTITION,
        run_id="run-1",
        request_policy=TushareRequestPolicy(
            minimum_interval_seconds=0.0,
            max_retries=0,
            max_requests=5,
            max_elapsed_seconds=30.0,
        ),
    )


def test_daily_writer_filters_full_market_and_reconciles_atomic_output(
    tmp_path: Path,
) -> None:
    tushare = FakeIdxFactorProTushare(rows=_source_rows())
    result = _write(tmp_path=tmp_path, tushare=tushare)

    expected_codes = active_idx_factor_pro_daily_codes(PARTITION)
    assert result.source_row_count == len(expected_codes) + 1
    assert result.selected_row_count == len(expected_codes)
    assert result.written_row_count == len(expected_codes)
    assert result.code_count == len(expected_codes)
    assert result.page_count == 1
    assert result.request_count == 1
    assert result.min_trade_date == SOURCE_TRADE_DATE
    assert result.max_trade_date == SOURCE_TRADE_DATE
    assert result.output_bytes > 0
    assert result.target_path.is_file()
    assert not result.staging_path.exists()
    assert result.target_path == raw_idx_factor_pro_path(
        tmp_path / "data_lake",
        PARTITION,
    )
    assert result.staging_path == raw_idx_factor_pro_staging_path(
        tmp_path / "data_lake_staging",
        "run-1",
        PARTITION,
    )
    assert tushare.calls == [
        (
            "idx_factor_pro",
            {"trade_date": SOURCE_TRADE_DATE, "limit": 8_000, "offset": 0},
            IDX_FACTOR_PRO_SOURCE_COLUMNS,
        )
    ]
    with DuckDBResource().connect() as connection:
        audit = validate_idx_factor_pro_raw_relation(
            connection,
            relation_sql=read_parquet(result.target_path, hive_partitioning=False),
            expected_codes=expected_codes,
            partition_key=PARTITION,
        )
    assert audit.errors == ()


@pytest.mark.parametrize(
    ("rows", "columns", "expected_message"),
    [
        (
            _source_rows(include_all_expected=False),
            IDX_FACTOR_PRO_SOURCE_COLUMNS,
            "missing_count=1",
        ),
        (
            _source_rows(),
            IDX_FACTOR_PRO_SOURCE_COLUMNS[:-1],
            "schema_drift",
        ),
    ],
)
def test_daily_writer_fails_closed_on_missing_code_or_schema_drift(
    tmp_path: Path,
    rows: list[dict[str, object]],
    columns: tuple[str, ...],
    expected_message: str,
) -> None:
    tushare = FakeIdxFactorProTushare(rows=rows, columns=columns)

    with pytest.raises(IdxFactorProRawValidationError, match=expected_message):
        _write(tmp_path=tmp_path, tushare=tushare)

    assert not raw_idx_factor_pro_path(tmp_path / "data_lake", PARTITION).exists()


def test_daily_writer_rejects_duplicate_source_key_before_page_consumption(
    tmp_path: Path,
) -> None:
    rows = _source_rows()
    rows.append(dict(rows[0]))
    tushare = FakeIdxFactorProTushare(rows=rows)

    with pytest.raises(IdxFactorProRawValidationError, match="duplicate row"):
        _write(tmp_path=tmp_path, tushare=tushare)

    assert not raw_idx_factor_pro_path(tmp_path / "data_lake", PARTITION).exists()


def test_daily_writer_refuses_existing_healthy_partition_without_source_call(
    tmp_path: Path,
) -> None:
    first_source = FakeIdxFactorProTushare(rows=_source_rows())
    _write(tmp_path=tmp_path, tushare=first_source)
    second_source = FakeIdxFactorProTushare(rows=[])

    with pytest.raises(IdxFactorProRawValidationError, match="refuses overwrite"):
        _write(tmp_path=tmp_path, tushare=second_source)

    assert second_source.calls == []
