from pathlib import Path

import duckdb

from orchestrator.defs.asset_guards.dc_board_lake_readiness import (
    batch_raw_dc_daily_lake_readiness,
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


def _write_daily(path: Path, *, codes: tuple[str, str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    categories = ("行业板块", "概念板块", "地域板块")
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE source (
            ts_code VARCHAR, trade_date VARCHAR, close DOUBLE, open DOUBLE,
            high DOUBLE, low DOUBLE, change DOUBLE, pct_change DOUBLE,
            vol DOUBLE, amount DOUBLE, swing DOUBLE, turnover_rate DOUBLE,
            category VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO source VALUES (?, '20260714', 10, 9, 11, 8, 1, 10, 100, 1000, 3, 2, ?)",
        list(zip(codes, categories, strict=True)),
    )
    connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])
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


def test_daily_missing_category_is_materialized_but_not_ready(tmp_path) -> None:
    root = Path(tmp_path)
    path = root / "raw/board/dc_daily/trade_date=2026-07-14/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(
        """
        COPY (
            SELECT
                'BK0001.DC'::VARCHAR AS ts_code,
                '20260714'::VARCHAR AS trade_date,
                10.0::DOUBLE AS close,
                9.0::DOUBLE AS open,
                11.0::DOUBLE AS high,
                8.0::DOUBLE AS low,
                1.0::DOUBLE AS change,
                10.0::DOUBLE AS pct_change,
                100.0::DOUBLE AS vol,
                1000.0::DOUBLE AS amount,
                3.0::DOUBLE AS swing,
                1.0::DOUBLE AS turnover_rate,
                '行业板块'::VARCHAR AS category
        ) TO ? (FORMAT PARQUET)
        """,
        [str(path)],
    )
    try:
        batch = batch_raw_dc_daily_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=("2026-07-14",),
        )
    finally:
        connection.close()
    status = batch.status_for_trade_date("2026-07-14")
    assert status.ready is False
    assert status.materialized is True
    assert status.checks_passed is False
    assert "category_coverage_complete" in status.summary["failed_rules"]


def test_daily_readiness_allows_codes_beyond_same_day_index(tmp_path) -> None:
    root = Path(tmp_path)
    trade_date = "2026-07-14"
    _write_index(
        root / f"raw/board/dc_index/trade_date={trade_date}/part-000.parquet",
        rows=[("BK0001.DC", "20260714", "行业板块")],
    )
    _write_daily(
        root / f"raw/board/dc_daily/trade_date={trade_date}/part-000.parquet",
        codes=("BK0001.DC", "BK0002.DC", "BK0003.DC"),
    )

    with _MemoryDuckDB().connect() as connection:
        batch = batch_raw_dc_daily_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(trade_date,),
            registered_trade_days=(trade_date,),
        )

    assert batch.status_for_trade_date(trade_date).ready is True


def test_daily_readiness_rejects_index_code_missing_from_daily(tmp_path) -> None:
    root = Path(tmp_path)
    trade_date = "2026-07-14"
    _write_index(
        root / f"raw/board/dc_index/trade_date={trade_date}/part-000.parquet",
        rows=[("BK9999.DC", "20260714", "行业板块")],
    )
    _write_daily(
        root / f"raw/board/dc_daily/trade_date={trade_date}/part-000.parquet",
        codes=("BK0001.DC", "BK0002.DC", "BK0003.DC"),
    )

    with _MemoryDuckDB().connect() as connection:
        batch = batch_raw_dc_daily_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(trade_date,),
            registered_trade_days=(trade_date,),
        )

    status = batch.status_for_trade_date(trade_date)
    assert status.ready is False
    assert status.summary["reason_code"] == "cross_dataset_code_set_mismatch"
    assert status.summary["relation_failure_count"] == 1
