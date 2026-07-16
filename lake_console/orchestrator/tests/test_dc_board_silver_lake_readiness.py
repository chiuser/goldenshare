from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.asset_guards.dc_board_silver_lake_readiness import (
    batch_silver_dc_daily_lake_readiness,
    batch_silver_dc_index_lake_readiness,
    batch_silver_dc_member_lake_readiness,
)
from orchestrator.defs.paths import (
    silver_dc_daily_path,
    silver_dc_index_path,
    silver_dc_member_path,
)


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


def _write_silver(path: Path, dataset: str, *, invalid: bool = False, empty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    if dataset == "dc_index":
        connection.execute(
            """
            CREATE TABLE source AS SELECT
                CAST(? AS VARCHAR) AS ts_code,
                DATE '2026-07-14' AS trade_date,
                '板块一'::VARCHAR AS name,
                '股票一'::VARCHAR AS leading,
                '000001.SZ'::VARCHAR AS leading_code,
                1.0::DOUBLE AS pct_change,
                2.0::DOUBLE AS leading_pct,
                100.0::DOUBLE AS total_mv,
                3.0::DOUBLE AS turnover_rate,
                10::INTEGER AS up_num,
                2::INTEGER AS down_num,
                '行业板块'::VARCHAR AS idx_type,
                'L1'::VARCHAR AS level
            """,
            ["BAD" if invalid else "BK0001.DC"],
        )
        target = path
    elif dataset == "dc_member":
        connection.execute(
            """
            CREATE TABLE source AS SELECT
                DATE '2026-07-14' AS trade_date,
                'BK0001.DC'::VARCHAR AS ts_code,
                CAST(? AS VARCHAR) AS con_code,
                '股票一'::VARCHAR AS name
            """,
            ["BAD" if invalid else "000001.SZ"],
        )
        target = path
    else:
        connection.execute(
            """
            CREATE TABLE source AS SELECT
                'BK0001.DC'::VARCHAR AS ts_code,
                DATE '2026-07-14' AS trade_date,
                10.0::DOUBLE AS close,
                9.0::DOUBLE AS open,
                11.0::DOUBLE AS high,
                8.0::DOUBLE AS low,
                1.0::DOUBLE AS change,
                10.0::DOUBLE AS pct_change,
                100.0::DOUBLE AS vol,
                1000.0::DOUBLE AS amount,
                3.0::DOUBLE AS swing,
                2.0::DOUBLE AS turnover_rate,
                '行业板块'::VARCHAR AS category
            """
        )
        if invalid:
            connection.execute("UPDATE source SET category = '未知分类'")
        target = path
    if empty:
        connection.execute("DELETE FROM source")
    connection.execute(f"COPY source TO '{target}' (FORMAT PARQUET)")
    connection.close()


@pytest.mark.parametrize(
    ("dataset", "builder"),
    (
        ("dc_index", silver_dc_index_path),
        ("dc_member", silver_dc_member_path),
        ("dc_daily", silver_dc_daily_path),
    ),
)
def test_silver_batch_readiness_passes_full_semantics(tmp_path, dataset, builder) -> None:
    root = Path(tmp_path)
    if dataset != "dc_index":
        _write_silver(silver_dc_index_path(root, "2026-07-14"), "dc_index")
    _write_silver(builder(root, "2026-07-14"), dataset)
    reader = {
        "dc_index": batch_silver_dc_index_lake_readiness,
        "dc_member": batch_silver_dc_member_lake_readiness,
        "dc_daily": batch_silver_dc_daily_lake_readiness,
    }[dataset]
    with _MemoryDuckDB().connect() as connection:
        batch = reader(
            connection=connection,
            lake_root=root,
            expected_trade_dates=("2026-07-14", "2026-07-15"),
            registered_trade_days=("2026-07-14", "2026-07-15"),
        )
    assert batch.status_for_trade_date("2026-07-14").ready is True
    missing = batch.status_for_trade_date("2026-07-15")
    assert missing.materialized is False
    assert missing.checks_passed is False
    assert batch.scanned_file_count == 1
    assert batch.elapsed_ms >= 0


def test_existing_silver_invalid_file_is_materialized_check_problem(tmp_path) -> None:
    root = Path(tmp_path)
    path = silver_dc_index_path(root, "2026-07-14")
    _write_silver(path, "dc_index", invalid=True)
    with _MemoryDuckDB().connect() as connection:
        batch = batch_silver_dc_index_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
    status = batch.status_for_trade_date("2026-07-14")
    assert status.ready is False
    assert status.materialized is True
    assert status.checks_passed is False
    assert "dataset_identity_fields_legal" in status.summary["failed_rules"]


def test_existing_empty_silver_file_is_not_auto_rerun_candidate(tmp_path) -> None:
    root = Path(tmp_path)
    _write_silver(
        silver_dc_member_path(root, "2026-07-14"),
        "dc_member",
        empty=True,
    )
    _write_silver(silver_dc_index_path(root, "2026-07-14"), "dc_index")
    with _MemoryDuckDB().connect() as connection:
        batch = batch_silver_dc_member_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
    status = batch.status_for_trade_date("2026-07-14")
    assert status.ready is False
    assert status.materialized is True
    assert "row_count_positive" in status.summary["failed_rules"]


def test_existing_schema_mismatch_is_materialized_check_problem(tmp_path) -> None:
    root = Path(tmp_path)
    path = silver_dc_index_path(root, "2026-07-14")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE source AS SELECT 'BK0001.DC'::VARCHAR AS ts_code, DATE '2026-07-14' AS trade_date"
    )
    connection.execute(f"COPY source TO '{path}' (FORMAT PARQUET)")
    connection.close()
    with _MemoryDuckDB().connect() as connection:
        batch = batch_silver_dc_index_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
    status = batch.status_for_trade_date("2026-07-14")
    assert status.materialized is True
    assert status.checks_passed is False
    assert "schema_matches_contract" in status.summary["failed_rules"]


def test_unknown_date_fails_closed() -> None:
    connection = duckdb.connect(":memory:")
    batch = batch_silver_dc_daily_lake_readiness(
        connection=connection,
        lake_root=Path("/tmp/no-board-silver-lake"),
        expected_trade_dates=("2026-07-14",),
        registered_trade_days=(),
    )
    status = batch.status_for_trade_date("2026-07-15")
    connection.close()
    assert status.ready is False
    assert status.reason == "unknown_trade_date"
