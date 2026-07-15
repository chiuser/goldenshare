from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.asset_guards.dc_daily_silver_repair_producer import (
    SILVER_DC_DAILY_SOURCE_REVISION_PREFIX,
    DcDailySilverRepairValidationError,
    produce_dc_daily_silver_repair_batch,
)
from orchestrator.defs.assets.dc_board_silver import write_silver_dc_daily_partition
from orchestrator.defs.assets.dc_board_silver import DcBoardSilverValidationError
from orchestrator.defs.paths import raw_dc_daily_path, silver_dc_daily_path, silver_trade_calendar_path


class _MemoryDuckDB:
    def __init__(self) -> None:
        self.connection_count = 0

    def connect(self):
        self.connection_count += 1
        connection = duckdb.connect(":memory:")

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


def _write_calendar(root: Path, dates: tuple[str, ...]) -> None:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        f"('SSE', DATE '{trade_date}', TRUE, NULL::DATE)" for trade_date in dates
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(exchange, trade_date, is_open, pretrade_date)) "
            "TO ? (FORMAT PARQUET)",
            [str(path)],
        )


def _write_raw(root: Path, trade_date: str, *, close: float) -> None:
    path = raw_dc_daily_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE source (
              ts_code VARCHAR,
              trade_date VARCHAR,
              close DOUBLE,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              change DOUBLE,
              pct_change DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              swing DOUBLE,
              turnover_rate DOUBLE,
              category VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO source VALUES ('BK0001.DC', ?, ?, ?, ?, ?, 0, 0, 1, 1, 0, 0, '行业板块')",
            [trade_date.replace("-", ""), close, close, close + 1, close - 1],
        )
        connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])


def _prepare_lake(root: Path) -> tuple[str, ...]:
    dates = ("2024-01-02", "2024-01-03", "2024-01-04")
    _write_calendar(root, dates)
    for index, trade_date in enumerate(dates, start=1):
        _write_raw(root, trade_date, close=float(index))
        write_silver_dc_daily_partition(
            lake_root_path=root,
            duckdb=_MemoryDuckDB(),
            partition_key=trade_date,
        )
    return dates


def _produce(root: Path, resource: _MemoryDuckDB, *, run_id: str):
    dates = ("2024-01-02", "2024-01-03", "2024-01-04")
    return produce_dc_daily_silver_repair_batch(
        lake_root_path=root,
        duckdb_resource=resource,
        producer_run_id=run_id,
        source_repair_start_trade_date="2024-01-03",
        source_repair_end_trade_date="2024-01-03",
        indicator_recompute_end_trade_date="2024-01-04",
        target_frontier_trade_date="2024-01-04",
        context_start_trade_date="2024-01-02",
        expected_trade_dates=dates,
        registered_trade_dates=dates,
    )


def test_producer_rewrites_changed_silver_and_returns_ready_batch(tmp_path):
    dates = _prepare_lake(tmp_path)
    _write_raw(tmp_path, "2024-01-03", close=99.0)
    resource = _MemoryDuckDB()

    result = _produce(tmp_path, resource, run_id="silver-repair-1")

    assert resource.connection_count == 1
    assert result.batch is not None
    assert result.batch.ready is True
    assert result.batch.source_asset == "silver_dc_daily"
    assert result.batch.source_revision == result.source_revision
    assert result.batch.affected_date_count == 1
    assert result.batch.selected_partition_count == 2
    assert result.batch.affected_series_count == 1
    assert result.source_revision.startswith(SILVER_DC_DAILY_SOURCE_REVISION_PREFIX)
    assert result.rewritten_partition_count == 1
    assert result.no_op is False
    assert not list(tmp_path.rglob("*.tmp"))
    assert duckdb.connect(":memory:").execute(
        f"SELECT close FROM read_parquet('{silver_dc_daily_path(tmp_path, dates[1])}')"
    ).fetchone()[0] == 99.0


def test_identical_retry_is_noop_and_does_not_return_ready_batch(tmp_path):
    _prepare_lake(tmp_path)
    _write_raw(tmp_path, "2024-01-03", close=99.0)
    first = _produce(tmp_path, _MemoryDuckDB(), run_id="silver-repair-1")
    second = _produce(tmp_path, _MemoryDuckDB(), run_id="silver-repair-2")

    assert first.batch is not None
    assert second.batch is None
    assert second.no_op is True
    assert second.source_revision == first.source_revision
    assert second.rewritten_partition_count == 0
    assert not list(tmp_path.rglob("*.tmp"))


def test_indicator_budget_fails_before_existing_target_changes(tmp_path):
    _prepare_lake(tmp_path)
    _write_raw(tmp_path, "2024-01-03", close=99.0)
    target = silver_dc_daily_path(tmp_path, "2024-01-03")
    before = target.read_bytes()

    with pytest.raises(DcDailySilverRepairValidationError, match="exceeds bounded budget"):
        _produce_with_budget(tmp_path, max_indicator_recompute_dates=1)

    assert target.read_bytes() == before
    assert not list(tmp_path.rglob("*.tmp"))


def _produce_with_budget(tmp_path: Path, *, max_indicator_recompute_dates: int):
    dates = ("2024-01-02", "2024-01-03", "2024-01-04")
    return produce_dc_daily_silver_repair_batch(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        producer_run_id="silver-repair-budget",
        source_repair_start_trade_date="2024-01-03",
        source_repair_end_trade_date="2024-01-03",
        indicator_recompute_end_trade_date="2024-01-04",
        target_frontier_trade_date="2024-01-04",
        context_start_trade_date="2024-01-02",
        expected_trade_dates=dates,
        registered_trade_dates=dates,
        max_indicator_recompute_dates=max_indicator_recompute_dates,
    )


def test_invalid_raw_input_does_not_overwrite_existing_silver(tmp_path):
    _prepare_lake(tmp_path)
    target = silver_dc_daily_path(tmp_path, "2024-01-03")
    before = target.read_bytes()
    _write_raw(tmp_path, "2024-01-03", close=99.0)
    raw = raw_dc_daily_path(tmp_path, "2024-01-03")
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE invalid_source (
              ts_code VARCHAR,
              trade_date VARCHAR,
              close DOUBLE,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              change DOUBLE,
              pct_change DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              swing DOUBLE,
              turnover_rate DOUBLE,
              category VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO invalid_source VALUES ('BK0001.DC', '20240102', 99, 99, 100, 98, 0, 0, 1, 1, 0, 0, '行业板块')"
        )
        connection.execute(
            "COPY invalid_source TO ? (FORMAT PARQUET)",
            [str(raw)],
        )

    with pytest.raises(DcBoardSilverValidationError, match="trade_date_out_of_partition"):
        _produce(tmp_path, _MemoryDuckDB(), run_id="silver-repair-invalid")

    assert target.read_bytes() == before
    assert not list(tmp_path.rglob("*.tmp"))


def test_invalid_existing_target_fails_closed_without_replacing_it(tmp_path):
    _prepare_lake(tmp_path)
    target = silver_dc_daily_path(tmp_path, "2024-01-03")
    target.write_bytes(b"not parquet")
    _write_raw(tmp_path, "2024-01-03", close=99.0)

    with pytest.raises(Exception, match="Existing Silver dc_daily target schema is invalid"):
        _produce(tmp_path, _MemoryDuckDB(), run_id="silver-repair-corrupt-target")

    assert target.read_bytes() == b"not parquet"
    assert not list(tmp_path.rglob("*.tmp"))


def test_producer_has_no_dagster_event_history_or_sensor_dependency():
    source = (
        Path(__file__).parents[1]
        / "src"
        / "orchestrator"
        / "defs"
        / "asset_guards"
        / "dc_daily_silver_repair_producer.py"
    ).read_text()
    assert "get_event_records" not in source
    assert "DagsterInstance" not in source
    assert "@dg.sensor" not in source
