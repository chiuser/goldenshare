from pathlib import Path

import duckdb

from orchestrator.defs.asset_guards.dc_daily_technical_lake_readiness import (
    batch_gold_dc_daily_technical_lake_readiness,
)
from orchestrator.defs.assets.dc_daily_technical import (
    write_gold_dc_daily_technical_partition,
)
from orchestrator.defs.paths import gold_dc_daily_technical_path, silver_dc_daily_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
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


def _write_silver(root: Path, trade_date: str) -> None:
    path = silver_dc_daily_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE source AS SELECT
              'BK0001.DC'::VARCHAR AS ts_code,
              CAST(? AS DATE) AS trade_date,
              10.0::DOUBLE AS close,
              10.0::DOUBLE AS open,
              11.0::DOUBLE AS high,
              9.0::DOUBLE AS low,
              0.0::DOUBLE AS change,
              0.0::DOUBLE AS pct_change,
              1.0::DOUBLE AS vol,
              1.0::DOUBLE AS amount,
              0.0::DOUBLE AS swing,
              0.0::DOUBLE AS turnover_rate,
              '行业板块'::VARCHAR AS category
            """,
            [trade_date],
        )
        connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])


def _write_calendar(root: Path, trade_date: str) -> None:
    path = root / "silver/calendar/trade_calendar/full/part-000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE calendar AS SELECT
              'SSE'::VARCHAR AS exchange,
              CAST(? AS DATE) AS trade_date,
              TRUE AS is_open,
              NULL::DATE AS pretrade_date
            """,
            [trade_date],
        )
        connection.execute("COPY calendar TO ? (FORMAT PARQUET)", [str(path)])


def test_missing_gold_file_is_triggerable_and_registered(tmp_path) -> None:
    root = Path(tmp_path)
    trade_date = "2026-07-14"
    _write_calendar(root, trade_date)
    _write_silver(root, trade_date)

    with _MemoryDuckDB().connect() as connection:
        batch = batch_gold_dc_daily_technical_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(trade_date,),
            registered_trade_days=(trade_date,),
        )

    status = batch.status_for_trade_date(trade_date)
    assert status.ready is False
    assert status.materialized is False
    assert status.checks_passed is False
    assert status.missing_check_names == ("gold_dc_daily_technical_core_check",)
    assert status.reason == "file_missing"
    assert batch.scanned_file_count == 0


def test_valid_gold_file_is_ready_with_one_bounded_batch_scan(tmp_path) -> None:
    root = Path(tmp_path)
    trade_date = "2026-07-14"
    _write_calendar(root, trade_date)
    _write_silver(root, trade_date)
    write_gold_dc_daily_technical_partition(
        lake_root_path=root,
        duckdb_resource=_MemoryDuckDB(),
        partition_key=trade_date,
    )

    with _MemoryDuckDB().connect() as connection:
        batch = batch_gold_dc_daily_technical_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(trade_date,),
            registered_trade_days=(trade_date,),
        )

    status = batch.status_for_trade_date(trade_date)
    assert status.ready is True
    assert status.materialized is True
    assert status.checks_passed is True
    assert batch.scanned_file_count == 1
    assert batch.elapsed_ms >= 0


def test_schema_failure_is_materialized_not_triggerable(tmp_path) -> None:
    root = Path(tmp_path)
    trade_date = "2026-07-14"
    _write_calendar(root, trade_date)
    _write_silver(root, trade_date)
    target = gold_dc_daily_technical_path(root, trade_date)
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE invalid AS SELECT 'BK0001.DC'::VARCHAR AS ts_code, CAST(? AS DATE) AS trade_date",
            [trade_date],
        )
        connection.execute("COPY invalid TO ? (FORMAT PARQUET)", [str(target)])

    with _MemoryDuckDB().connect() as connection:
        batch = batch_gold_dc_daily_technical_lake_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(trade_date,),
            registered_trade_days=(trade_date,),
        )

    status = batch.status_for_trade_date(trade_date)
    assert status.ready is False
    assert status.materialized is True
    assert status.checks_passed is False
    assert "schema_matches_contract" in status.summary["failed_rules"] or (
        status.reason == "scan_error"
    )


def test_unknown_date_fails_closed(tmp_path) -> None:
    with _MemoryDuckDB().connect() as connection:
        batch = batch_gold_dc_daily_technical_lake_readiness(
            connection=connection,
            lake_root=Path(tmp_path),
            expected_trade_dates=("2026-07-14",),
            registered_trade_days=(),
        )
    status = batch.status_for_trade_date("2026-07-15")
    assert status.ready is False
    assert status.reason == "unknown_trade_date"
