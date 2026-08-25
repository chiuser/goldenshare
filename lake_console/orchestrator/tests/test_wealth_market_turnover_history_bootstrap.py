import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap.wealth_market_turnover_history import (
    WEALTH_MARKET_TURNOVER_HISTORY_AUDIT_SECONDS_LIMIT,
    audit_wealth_market_turnover_history,
    audit_wealth_market_turnover_history_candidates,
    build_wealth_market_turnover_history_candidates,
    plan_wealth_market_turnover_history,
    promote_wealth_market_turnover_history_candidates,
    wealth_market_turnover_history_plan_from_dict,
)
from orchestrator.defs.paths import (
    gold_wealth_market_turnover_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS

DATE_1 = "2026-06-22"
DATE_2 = "2026-06-23"


class WealthMarketTurnoverHistoryBootstrapTests(unittest.TestCase):
    def test_history_helpers_are_staged_and_do_not_write_dagster_events(self) -> None:
        helper_paths = (
            Path("src/orchestrator/defs/bootstrap/wealth_market_turnover_history.py"),
            Path(
                "src/orchestrator/defs/bootstrap/"
                "wealth_market_turnover_history_cli.py"
            ),
        )
        forbidden_tokens = (
            "@dg.asset",
            "@dg.asset_check",
            "@dg.sensor",
            "define_asset_job",
            "report_runless_asset_event",
            "wealth_market_turnover_runless_events",
        )
        combined_source = "\n".join(path.read_text() for path in helper_paths)
        for token in forbidden_tokens:
            self.assertNotIn(token, combined_source)
        for required_stage in (
            "build-candidates",
            "audit-candidates",
            "promote",
            "formal-audit",
            "prod-publish",
        ):
            self.assertIn(required_stage, combined_source)

    def test_plan_requires_five_minute_sources_daily_source_and_bse_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            staging_root = root / "staging"
            _write_all_sources(root, DATE_1)
            _write_all_sources(root, DATE_2, include_daily=False)

            plan = plan_wealth_market_turnover_history(
                duckdb_resource=DuckDBResource(),
                lake_root=root,
                staging_root=staging_root,
            )

        self.assertEqual(plan.selected_partition_keys, (DATE_1,))
        self.assertEqual(plan.eligible_source_partition_count, 1)
        self.assertEqual(plan.planned_write_count, 1)
        self.assertEqual(plan.planned_event_count, 0)
        self.assertEqual(len(plan.partition_plans[0].source_files), 6)

    def test_requested_incomplete_partition_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            _write_all_sources(root, DATE_2, include_daily=False)

            with self.assertRaisesRegex(
                ValueError,
                "missing complete minute and stock daily inputs",
            ):
                plan_wealth_market_turnover_history(
                    duckdb_resource=DuckDBResource(),
                    lake_root=root,
                    staging_root=root / "staging",
                    partition_keys=(DATE_1, DATE_2),
                )

    def test_plan_caps_batches_at_twenty_and_rejects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            with self.assertRaisesRegex(ValueError, "batch_size must be 1..20"):
                plan_wealth_market_turnover_history(
                    duckdb_resource=DuckDBResource(),
                    lake_root=root,
                    staging_root=root / "staging",
                    batch_size=21,
                )
            plan = plan_wealth_market_turnover_history(
                duckdb_resource=DuckDBResource(),
                lake_root=root,
                staging_root=root / "staging",
            )
            payload = asdict(plan)
            payload["correction_method"] = "changed"

            with self.assertRaisesRegex(RuntimeError, "plan hash mismatch"):
                wealth_market_turnover_history_plan_from_dict(payload)

    def test_candidate_audit_promote_and_formal_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            target_path = gold_wealth_market_turnover_path(root, DATE_1)
            plan = plan_wealth_market_turnover_history(
                duckdb_resource=DuckDBResource(),
                lake_root=root,
                staging_root=root / "staging",
                partition_keys=(DATE_1,),
            )

            write_report = build_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
            )
            self.assertFalse(target_path.exists())
            candidate_audit = audit_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
                expected_candidate_hashes=write_report.candidate_hashes,
            )
            self.assertTrue(candidate_audit.passed)
            self.assertLess(
                candidate_audit.elapsed_ms,
                WEALTH_MARKET_TURNOVER_HISTORY_AUDIT_SECONDS_LIMIT * 1000,
            )
            promote_report = promote_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                partition_keys=(DATE_1,),
                candidate_hashes=write_report.candidate_hashes,
            )
            formal_audit = audit_wealth_market_turnover_history(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
                expected_hashes=write_report.candidate_hashes,
            )

        self.assertEqual(write_report.written_partition_keys, (DATE_1,))
        self.assertEqual(promote_report.promoted_partition_keys, (DATE_1,))
        self.assertTrue(formal_audit.passed)
        self.assertEqual(formal_audit.target_file_count, 1)
        self.assertEqual(formal_audit.target_row_count, 5)

    def test_promote_rejects_concurrent_target_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            plan = plan_wealth_market_turnover_history(
                duckdb_resource=DuckDBResource(),
                lake_root=root,
                staging_root=root / "staging",
                partition_keys=(DATE_1,),
            )
            write_report = build_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=root,
                duckdb_resource=DuckDBResource(),
                partition_keys=(DATE_1,),
            )
            target_path = gold_wealth_market_turnover_path(root, DATE_1)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"concurrent change")

            with self.assertRaisesRegex(RuntimeError, "appeared after plan"):
                promote_wealth_market_turnover_history_candidates(
                    plan=plan,
                    lake_root=root,
                    partition_keys=(DATE_1,),
                    candidate_hashes=write_report.candidate_hashes,
                )

    def test_build_rejects_source_fingerprint_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_all_sources(root, DATE_1)
            plan = plan_wealth_market_turnover_history(
                duckdb_resource=DuckDBResource(),
                lake_root=root,
                staging_root=root / "staging",
                partition_keys=(DATE_1,),
            )
            _write_minute_file(root, DATE_1, 1, extra_sh_row=True)

            with self.assertRaisesRegex(RuntimeError, "Source fingerprint changed"):
                build_wealth_market_turnover_history_candidates(
                    plan=plan,
                    lake_root=root,
                    duckdb_resource=DuckDBResource(),
                    partition_keys=(DATE_1,),
                )


def _write_all_sources(
    root: Path,
    partition_key: str,
    *,
    include_daily: bool = True,
) -> None:
    for freq in STK_MINS_FREQS:
        _write_minute_file(root, partition_key, freq)
    if include_daily:
        _write_daily_file(root, partition_key)


def _write_minute_file(
    root: Path,
    partition_key: str,
    freq: int,
    *,
    extra_sh_row: bool = False,
) -> None:
    path = silver_stk_mins_path(root, freq, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("000001.SZ", freq, partition_key, f"{partition_key} 09:30:00", 100, 1000.0),
        ("920001.BJ", freq, partition_key, f"{partition_key} 09:30:00", 100 + freq, 1000.0 + freq * 10),
        ("000001.SZ", freq, partition_key, f"{partition_key} 15:00:00", 200, 2000.0),
        ("920001.BJ", freq, partition_key, f"{partition_key} 15:00:00", 0, 0.0),
    ]
    if extra_sh_row:
        rows.append(
            ("600000.SH", freq, partition_key, f"{partition_key} 14:59:00", 1, 10.0)
        )
    values_sql = ", ".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ")"
        for row in rows
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(freq AS INTEGER) AS freq,
                CAST(trade_date AS DATE) AS trade_date,
                CAST(trade_time AS TIMESTAMP) AS trade_time,
                CAST(vol AS DOUBLE) AS vol,
                CAST(amount AS DOUBLE) AS amount
              FROM (VALUES {values_sql})
                rows(ts_code, freq, trade_date, trade_time, vol, amount)
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_daily_file(root: Path, partition_key: str) -> None:
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
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


if __name__ == "__main__":
    unittest.main()
