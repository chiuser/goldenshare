from pathlib import Path

import duckdb

from orchestrator.defs.asset_guards.dc_board_lake_readiness import (
    batch_raw_dc_index_lake_readiness,
)


def _write_index(path: Path, *, rows: list[tuple[str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
            SELECT
                CAST(ts_code AS VARCHAR) AS ts_code, CAST(trade_date AS VARCHAR) AS trade_date,
                CAST(name AS VARCHAR) AS name, CAST("leading" AS VARCHAR) AS "leading",
                CAST(leading_code AS VARCHAR) AS leading_code,
                CAST(pct_change AS DOUBLE) AS pct_change, CAST(leading_pct AS DOUBLE) AS leading_pct,
                CAST(total_mv AS DOUBLE) AS total_mv, CAST(turnover_rate AS DOUBLE) AS turnover_rate,
                CAST(up_num AS INTEGER) AS up_num, CAST(down_num AS INTEGER) AS down_num,
                CAST(idx_type AS VARCHAR) AS idx_type, CAST(level AS VARCHAR) AS level
                FROM (VALUES (?, ?, '板块', '股票', '000001.SZ', 1.0, 2.0, 3.0, 4.0, 5, 6, ?, 'L1'))
                AS t(ts_code, trade_date, name, "leading", leading_code, pct_change,
                    leading_pct, total_mv, turnover_rate, up_num, down_num, idx_type, level)
        ) TO '{path}' (FORMAT PARQUET)
        """,
        [rows[0][0], rows[0][1], rows[0][2]],
    )
    connection.close()


class _MemoryDuckDB:
    def connect(self):
        connection = duckdb.connect()
        class _Context:
            def __enter__(self):
                return connection
            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False
        return _Context()


def test_batch_readiness_distinguishes_ready_and_missing(tmp_path) -> None:
    root = Path(tmp_path)
    _write_index(
        root / "raw/board/dc_index/trade_date=2026-07-14/part-000.parquet",
        rows=[("BK0001.DC", "20260714", "行业板块")],
    )
    with _MemoryDuckDB().connect() as connection:
        batch = batch_raw_dc_index_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=("2026-07-14", "2026-07-15"),
            registered_trade_days=("2026-07-14", "2026-07-15"),
        )
    assert batch.status_for_trade_date("2026-07-14").ready is True
    missing = batch.status_for_trade_date("2026-07-15")
    assert missing.materialized is False
    assert missing.checks_passed is False
    assert missing.missing_check_names == ("raw_tushare_dc_index_core_check",)
    assert batch.scanned_file_count == 1


def test_batch_readiness_marks_existing_invalid_file_as_materialized_problem(tmp_path) -> None:
    root = Path(tmp_path)
    _write_index(
        root / "raw/board/dc_index/trade_date=2026-07-14/part-000.parquet",
        rows=[("BAD", "20260713", "行业板块")],
    )
    with _MemoryDuckDB().connect() as connection:
        batch = batch_raw_dc_index_lake_readiness(
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
    assert "trade_date_matches_partition" in status.summary["failed_rules"]


def test_unknown_date_fails_closed() -> None:
    batch = batch_raw_dc_index_lake_readiness(
        connection=duckdb.connect(),
        lake_root=Path("/tmp/no-board-lake"),
        expected_trade_dates=("2026-07-14",),
        registered_trade_days=(),
    )
    status = batch.status_for_trade_date("2026-07-15")
    assert status.ready is False
    assert status.reason == "unknown_trade_date"
