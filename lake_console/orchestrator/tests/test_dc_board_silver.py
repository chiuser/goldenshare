from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.assets.dc_board_silver import (
    DcBoardSilverValidationError,
    write_silver_dc_daily_partition,
    write_silver_dc_index_partition,
    write_silver_dc_member_partition,
)
from orchestrator.defs.checks.dc_board_silver_checks import _core_check
from orchestrator.defs.paths import (
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
    silver_dc_index_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import SILVER_DC_INDEX_SCHEMA


class _MemoryDuckDB:
    def connect(self):
        connection = duckdb.connect(":memory:")

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


def _write_rows(path: Path, schema_sql: str, columns: str, rows: list[tuple[object, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    connection.execute(f"CREATE TABLE source ({schema_sql})")
    placeholders = ", ".join("?" for _ in rows[0])
    connection.executemany(f"INSERT INTO source VALUES ({placeholders})", rows)
    connection.execute(f"COPY (SELECT {columns} FROM source) TO '{path}' (FORMAT PARQUET)")
    connection.close()


def _write_calendar(root: Path, trade_date: str = "2026-07-14", is_open: bool = True) -> None:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    connection.execute(
        f"COPY (SELECT 'SSE' AS exchange, DATE '{trade_date}' AS trade_date, "
        f"{str(is_open).lower()} AS is_open, NULL::DATE AS pretrade_date) TO '{path}' (FORMAT PARQUET)"
    )
    connection.close()


def _index_row(trade_date: str = "20260714", ts_code: str = "BK0001.DC") -> tuple[object, ...]:
    return (
        ts_code,
        trade_date,
        "板块一",
        "股票一",
        "000001.SZ",
        1.0,
        2.0,
        100.0,
        3.0,
        10,
        2,
        "行业板块",
        "L1",
    )


def _member_row(trade_date: str = "20260714", ts_code: str = "BK0001.DC") -> tuple[object, ...]:
    return (trade_date, ts_code, "000001.SZ", "股票一")


def _daily_row(trade_date: str = "20260714", category: str = "行业板块") -> tuple[object, ...]:
    return (
        "BK0001.DC",
        trade_date,
        10.0,
        9.0,
        11.0,
        8.0,
        1.0,
        10.0,
        100.0,
        1000.0,
        3.0,
        2.0,
        category,
    )


def _write_valid_raw(root: Path, dataset: str, rows: list[tuple[object, ...]]) -> Path:
    if dataset == "dc_index":
        path = raw_dc_index_path(root, "2026-07-14")
        _write_rows(
            path,
            "ts_code VARCHAR, trade_date VARCHAR, name VARCHAR, \"leading\" VARCHAR, leading_code VARCHAR, "
            "pct_change DOUBLE, leading_pct DOUBLE, total_mv DOUBLE, turnover_rate DOUBLE, "
            "up_num INTEGER, down_num INTEGER, idx_type VARCHAR, level VARCHAR",
            "*",
            rows,
        )
    elif dataset == "dc_member":
        path = raw_dc_member_path(root, "2026-07-14")
        _write_rows(
            path,
            "trade_date VARCHAR, ts_code VARCHAR, con_code VARCHAR, name VARCHAR",
            "*",
            rows,
        )
    else:
        path = raw_dc_daily_path(root, "2026-07-14")
        _write_rows(
            path,
            "ts_code VARCHAR, trade_date VARCHAR, close DOUBLE, open DOUBLE, high DOUBLE, low DOUBLE, "
            "change DOUBLE, pct_change DOUBLE, vol DOUBLE, amount DOUBLE, swing DOUBLE, "
            "turnover_rate DOUBLE, category VARCHAR",
            "*",
            rows,
        )
    return path


@pytest.mark.parametrize(
    ("dataset", "row_factory"),
    (("dc_index", _index_row), ("dc_member", _member_row), ("dc_daily", _daily_row)),
)
def test_silver_writer_normalizes_date_and_writes_expected_partition(tmp_path, dataset, row_factory):
    root = Path(tmp_path)
    _write_calendar(root)
    _write_valid_raw(root, dataset, [row_factory()])
    writer = {
        "dc_index": write_silver_dc_index_partition,
        "dc_member": write_silver_dc_member_partition,
        "dc_daily": write_silver_dc_daily_partition,
    }[dataset]

    result = writer(lake_root_path=root, duckdb=_MemoryDuckDB(), partition_key="2026-07-14")
    assert result.source_row_count == 1
    assert result.output_row_count == 1
    assert result.rejected_row_count == 0
    assert result.target_file_path.exists()
    assert duckdb.connect(":memory:").execute(
        f"SELECT typeof(any_value(trade_date)), count(*) FROM read_parquet('{result.target_file_path}')"
    ).fetchone() == ("DATE", 1)


def test_dc_daily_keeps_category_in_business_key(tmp_path):
    root = Path(tmp_path)
    _write_calendar(root)
    _write_valid_raw(root, "dc_daily", [_daily_row(category="行业板块"), _daily_row(category="概念板块")])
    result = write_silver_dc_daily_partition(
        lake_root_path=root, duckdb=_MemoryDuckDB(), partition_key="2026-07-14"
    )
    connection = duckdb.connect(":memory:")
    assert connection.execute(
        f"SELECT count(*), count(DISTINCT category) FROM read_parquet('{result.target_file_path}')"
    ).fetchone() == (2, 2)


def test_identical_normalized_duplicates_are_deduplicated(tmp_path):
    root = Path(tmp_path)
    _write_calendar(root)
    _write_valid_raw(root, "dc_member", [_member_row(), _member_row()])
    result = write_silver_dc_member_partition(
        lake_root_path=root, duckdb=_MemoryDuckDB(), partition_key="2026-07-14"
    )
    assert result.duplicate_removed_count == 1
    assert result.output_row_count == 1


def test_conflicting_duplicate_does_not_replace_existing_target(tmp_path):
    root = Path(tmp_path)
    _write_calendar(root)
    first = list(_index_row())
    second = list(_index_row())
    second[2] = "另一个名称"
    _write_valid_raw(root, "dc_index", [tuple(first), tuple(second)])
    target = silver_dc_index_path(root, "2026-07-14")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"existing-silver")

    with pytest.raises(DcBoardSilverValidationError, match="conflict_key_count"):
        write_silver_dc_index_partition(
            lake_root_path=root, duckdb=_MemoryDuckDB(), partition_key="2026-07-14"
        )
    assert target.read_bytes() == b"existing-silver"


def test_out_of_partition_row_fails_closed_without_overwrite(tmp_path):
    root = Path(tmp_path)
    _write_calendar(root)
    _write_valid_raw(root, "dc_daily", [_daily_row(trade_date="20260713")])
    target = root / "silver/board/dc_daily/trade_date=2026-07-14/part-000.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"existing-silver")

    with pytest.raises(DcBoardSilverValidationError, match="trade_date_out_of_partition"):
        write_silver_dc_daily_partition(
            lake_root_path=root, duckdb=_MemoryDuckDB(), partition_key="2026-07-14"
        )
    assert target.read_bytes() == b"existing-silver"


class _CheckContext:
    partition_keys = ("2026-07-14",)


def test_silver_core_check_passes_for_writer_output(tmp_path):
    root = Path(tmp_path)
    _write_calendar(root)
    _write_valid_raw(root, "dc_index", [_index_row()])
    write_silver_dc_index_partition(
        lake_root_path=root, duckdb=_MemoryDuckDB(), partition_key="2026-07-14"
    )
    result = _core_check(
        context=_CheckContext(),
        lake_root=LakeRootResource(root_path=str(root)),
        duckdb_resource=_MemoryDuckDB(),
        path_builder=silver_dc_index_path,
        schema=SILVER_DC_INDEX_SCHEMA,
        key_columns=("ts_code", "trade_date"),
        identity_condition=(
            "ts_code IS NOT NULL AND regexp_full_match(ts_code, '^BK[0-9]{4}\\.DC$') "
            "AND name IS NOT NULL AND idx_type = '行业板块'"
        ),
        numeric_condition="FALSE",
    )
    assert result.passed is True
