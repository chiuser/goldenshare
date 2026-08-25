import tempfile
import unittest
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.bootstrap.wealth_market_turnover_history import (
    build_wealth_market_turnover_history_candidates,
    plan_wealth_market_turnover_history,
    promote_wealth_market_turnover_history_candidates,
)
from orchestrator.defs.bootstrap.wealth_market_turnover_runless_events import (
    GOLD_WEALTH_MARKET_TURNOVER_ASSET_KEY,
    WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE,
    plan_wealth_market_turnover_runless_events,
    recent_wealth_market_turnover_partitions,
    report_wealth_market_turnover_runless_events,
)
from orchestrator.defs.paths import silver_stk_mins_path, silver_stock_daily_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)
from orchestrator.defs.wealth_market_turnover_contract import (
    WEALTH_MARKET_TURNOVER_CHECK_NAME,
)

DATE_1 = "2026-06-22"


class WealthMarketTurnoverRunlessEventTests(unittest.TestCase):
    def test_runless_helpers_do_not_define_active_dagster_components(self) -> None:
        helper_paths = (
            Path(
                "src/orchestrator/defs/bootstrap/"
                "wealth_market_turnover_runless_events.py"
            ),
            Path(
                "src/orchestrator/defs/bootstrap/"
                "wealth_market_turnover_runless_events_cli.py"
            ),
        )
        for helper_path in helper_paths:
            source = helper_path.read_text()
            for token in ("@dg.asset", "@dg.asset_check", "@dg.sensor", "define_asset_job"):
                self.assertNotIn(token, source)

    def test_recent_window_requires_twenty_partitions_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            _write_valid_gold_partition(lake_root, DATE_1)

            with self.assertRaisesRegex(ValueError, "window is incomplete"):
                recent_wealth_market_turnover_partitions(lake_root)

    def test_dry_run_audits_without_writing_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            _write_valid_gold_partition(lake_root, DATE_1)
            instance = dg.DagsterInstance.ephemeral()

            report = report_wealth_market_turnover_runless_events(
                instance=instance,
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
                dry_run=True,
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=GOLD_WEALTH_MARKET_TURNOVER_ASSET_KEY,
                    asset_partitions=[DATE_1],
                ),
                limit=1,
            ).records

        self.assertTrue(report.dry_run)
        self.assertEqual(report.plan.planned_event_count, 2)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(materializations, [])

    def test_apply_reports_materialization_and_single_check_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            _write_valid_gold_partition(lake_root, DATE_1)
            instance = dg.DagsterInstance.ephemeral()

            report = report_wealth_market_turnover_runless_events(
                instance=instance,
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
                dry_run=False,
                history_audit_report_path="/private/tmp/example.json",
            )
            status = asset_readiness_status(
                instance,
                AssetReadinessSpec(
                    GOLD_WEALTH_MARKET_TURNOVER_ASSET_KEY,
                    (WEALTH_MARKET_TURNOVER_CHECK_NAME,),
                ),
                partition_key=DATE_1,
            )

        self.assertEqual(report.reported_partition_keys, (DATE_1,))
        self.assertEqual(report.reported_event_count, 2)
        self.assertTrue(status.ready)
        self.assertEqual(status.failed_check_names, ())

    def test_plan_rejects_more_than_recent_twenty_partition_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lake_root = Path(temporary_dir)
            instance = dg.DagsterInstance.ephemeral()

            with self.assertRaisesRegex(ValueError, "exceeds recent 20"):
                plan_wealth_market_turnover_runless_events(
                    instance=instance,
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    partition_keys=tuple(
                        f"2026-05-{day:02d}"
                        for day in range(1, WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE + 2)
                    ),
                )


def _write_valid_gold_partition(root: Path, partition_key: str) -> None:
    for freq in STK_MINS_FREQS:
        _write_silver_file(root, partition_key, freq)
    _write_stock_daily_file(root, partition_key)
    plan = plan_wealth_market_turnover_history(
        duckdb_resource=DuckDBResource(),
        lake_root=root,
        staging_root=root / "staging",
        partition_keys=(partition_key,),
    )
    write_report = build_wealth_market_turnover_history_candidates(
        plan=plan,
        lake_root=root,
        duckdb_resource=DuckDBResource(),
        partition_keys=(partition_key,),
    )
    promote_wealth_market_turnover_history_candidates(
        plan=plan,
        lake_root=root,
        partition_keys=(partition_key,),
        candidate_hashes=write_report.candidate_hashes,
    )


def _write_silver_file(root: Path, partition_key: str, freq: int) -> None:
    path = silver_stk_mins_path(root, freq, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ")"
        for row in (
            ("000001.SZ", freq, f"{partition_key} 09:30:00", 100, 1000.0),
            ("920001.BJ", freq, f"{partition_key} 09:30:00", 100 + freq, 1000.0 + freq * 10),
            ("000001.SZ", freq, f"{partition_key} 15:00:00", 200, 2000.0),
            ("920001.BJ", freq, f"{partition_key} 15:00:00", 0, 0.0),
        )
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(freq AS INTEGER) AS freq,
                DATE '{partition_key}' AS trade_date,
                CAST(trade_time AS TIMESTAMP) AS trade_time,
                CAST(vol AS DOUBLE) AS vol,
                CAST(amount AS DOUBLE) AS amount
              FROM (
                VALUES {values_sql}
              ) AS rows(ts_code, freq, trade_time, vol, amount)
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_stock_daily_file(root: Path, partition_key: str) -> None:
    path = silver_stock_daily_path(root, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (
                VALUES
                  ('000001.SZ', DATE '{partition_key}', 3.0, 3.0),
                  ('920001.BJ', DATE '{partition_key}', 10.0, 10.0)
              ) rows(ts_code, trade_date, vol, amount)
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


if __name__ == "__main__":
    unittest.main()
