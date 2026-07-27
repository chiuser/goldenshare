import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

import orchestrator.defs.bootstrap.stk_mins_raw_replace_from_prod as recovery
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import raw_stk_mins_path
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource


TRADE_DATE = "2026-07-27"
STOCK_CODES = ("000001.SZ", "600000.SH")


class _FixtureSource:
    def __init__(
        self,
        *,
        missing_frequency: int | None = None,
        source_hash_override: str | None = None,
        duplicate_stage_frequency: int | None = None,
        fail_stage_frequency: int | None = None,
    ) -> None:
        self.missing_frequency = missing_frequency
        self.source_hash_override = source_hash_override
        self.duplicate_stage_frequency = duplicate_stage_frequency
        self.fail_stage_frequency = fail_stage_frequency
        self.stage_calls: list[int] = []

    def select_full_market_task_run(self, *, trade_date: str):
        self.last_task_run_request = trade_date
        return recovery.StkMinsRecoveryTaskRun(
            task_run_id=6544,
            ended_at="2026-07-27T20:51:33+08:00",
            unit_total=29355,
            unit_done=29355,
            unit_failed=0,
            progress_percent=100.0,
            rows_fetched=20,
            rows_saved=20,
            rows_rejected=0,
        )

    def load_frequency_facts(self, *, trade_date: str, stock_codes):
        facts = []
        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            if freq == self.missing_frequency:
                continue
            facts.append(
                recovery.StkMinsRecoveryFrequencyFact(
                    freq=freq,
                    row_count=len(stock_codes) * 2,
                    code_count=len(stock_codes),
                    code_hash=self.source_hash_override
                    or recovery.stock_code_set_hash(stock_codes),
                    duplicate_key_count=0,
                    empty_key_count=0,
                    min_trade_time=f"{trade_date} 09:30:00",
                    max_trade_time=f"{trade_date} 15:00:00",
                )
            )
        return tuple(facts)

    def write_frequency_staging_file(
        self,
        *,
        trade_date: str,
        freq: int,
        stock_codes,
        target_path: Path,
    ) -> None:
        self.stage_calls.append(freq)
        if freq == self.fail_stage_frequency:
            raise RuntimeError(f"fixture staging failure for freq={freq}")
        _write_raw_file(
            target_path,
            trade_date=trade_date,
            freq=freq,
            stock_codes=stock_codes,
            open_value=10.0,
            duplicate_key=freq == self.duplicate_stage_frequency,
        )


def _write_raw_file(
    path: Path,
    *,
    trade_date: str,
    freq: int,
    stock_codes,
    open_value: float,
    duplicate_key: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    selects = []
    for code in stock_codes:
        for trade_time in (f"{trade_date} 09:30:00", f"{trade_date} 15:00:00"):
            selects.append(
                f"""
                SELECT
                  {duckdb_string(code)}::VARCHAR AS ts_code,
                  {freq}::INTEGER AS freq,
                  CAST({duckdb_string(trade_time)} AS TIMESTAMP) AS trade_time,
                  {open_value}::DOUBLE AS open,
                  10.1::DOUBLE AS close,
                  10.2::DOUBLE AS high,
                  9.9::DOUBLE AS low,
                  100::BIGINT AS vol,
                  1000.0::DOUBLE AS amount,
                  'XSHE'::VARCHAR AS exchange,
                  10.0::DOUBLE AS vwap
                """
            )
    if duplicate_key:
        selects.append(selects[0])
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"COPY ({' UNION ALL '.join(selects)}) TO {duckdb_string(path)} (FORMAT PARQUET)"
        )


def _raw_open_value(path: Path) -> float:
    with duckdb.connect(database=":memory:") as connection:
        return float(connection.execute(f"SELECT min(open) FROM read_parquet({duckdb_string(path)})").fetchone()[0])


class StkMinsRawReplaceFromProdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.lake_root = Path(self.temp_dir.name)
        self.duckdb = DuckDBResource()
        self.prod_postgres = ProdPostgresResource()
        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            _write_raw_file(
                raw_stk_mins_path(self.lake_root, freq, TRADE_DATE),
                trade_date=TRADE_DATE,
                freq=freq,
                stock_codes=STOCK_CODES,
                open_value=1.0,
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _plan(self, source: _FixtureSource):
        with patch.object(recovery, "_expected_stock_codes", return_value=STOCK_CODES):
            return recovery.plan_stk_mins_raw_replace_from_prod(
                lake_root=self.lake_root,
                duckdb=self.duckdb,
                prod_postgres=self.prod_postgres,
                trade_date=TRADE_DATE,
                source=source,
            )

    def _apply(self, *, plan, source: _FixtureSource, run_id: str = "fixture"):
        with patch.object(recovery, "_expected_stock_codes", return_value=STOCK_CODES):
            return recovery.apply_stk_mins_raw_replace_from_prod(
                lake_root=self.lake_root,
                duckdb=self.duckdb,
                prod_postgres=self.prod_postgres,
                plan=plan,
                expected_plan_fingerprint=plan.plan_fingerprint,
                confirm_apply=True,
                source=source,
                recovery_run_id=run_id,
            )

    def test_plan_is_read_only_and_freezes_all_five_frequency_facts(self) -> None:
        source = _FixtureSource()
        before = {
            freq: recovery._sha256_path(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE))
            for freq in recovery.STK_MINS_RECOVERY_FREQS
        }

        plan = self._plan(source)

        self.assertFalse(plan.should_stop)
        self.assertEqual(plan.expected_code_count, 2)
        self.assertEqual(plan.expected_code_hash, recovery.stock_code_set_hash(STOCK_CODES))
        self.assertEqual(source.last_task_run_request, TRADE_DATE)
        self.assertEqual([fact.freq for fact in plan.frequency_facts], [1, 5, 15, 30, 60])
        self.assertEqual(
            before,
            {
                freq: recovery._sha256_path(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE))
                for freq in recovery.STK_MINS_RECOVERY_FREQS
            },
        )
        self.assertFalse(
            (self.lake_root / "raw" / "tushare" / "stk_mins" / "_staging").exists()
        )
        self.assertFalse((self.lake_root / "_quarantine").exists())

    def test_plan_stops_for_missing_frequency_or_source_code_hash_mismatch(self) -> None:
        missing_plan = self._plan(_FixtureSource(missing_frequency=15))
        self.assertIn("source_frequency_missing:15", missing_plan.stop_reasons)

        mismatched_plan = self._plan(_FixtureSource(source_hash_override="not-the-dg-hash"))
        self.assertEqual(
            mismatched_plan.stop_reasons,
            tuple(f"source_code_coverage_mismatch:{freq}" for freq in (1, 5, 15, 30, 60)),
        )

    def test_task_run_evidence_rejects_subset_or_incomplete_success(self) -> None:
        task_run = {
            "task_type": "dataset_action",
            "resource_key": "stk_mins",
            "action": "maintain",
            "status": "success",
            "ended_at": "2026-07-27T20:51:33+08:00",
            "unit_total": 29355,
            "unit_done": 29355,
            "unit_failed": 0,
            "progress_percent": 100.0,
            "rows_fetched": 20,
            "rows_saved": 20,
            "rows_rejected": 0,
            "time_input_json": {"trade_date": TRADE_DATE},
            "filters_json": {"freq": ["1min", "5min", "15min", "30min", "60min"]},
        }

        self.assertTrue(
            recovery._task_run_row_is_full_market(
                task_run,
                trade_date=TRADE_DATE,
            )
        )

        with_code_filter = {**task_run, "filters_json": {**task_run["filters_json"], "ts_code": "000001.SZ"}}
        incomplete = {**task_run, "unit_done": 29354}
        zero_units = {**task_run, "unit_total": 0, "unit_done": 0}
        self.assertFalse(
            recovery._task_run_row_is_full_market(
                with_code_filter,
                trade_date=TRADE_DATE,
            )
        )
        self.assertFalse(
            recovery._task_run_row_is_full_market(
                incomplete,
                trade_date=TRADE_DATE,
            )
        )
        self.assertFalse(
            recovery._task_run_row_is_full_market(
                zero_units,
                trade_date=TRADE_DATE,
            )
        )

    def test_apply_replaces_all_frequencies_after_staging_and_keeps_quarantine(self) -> None:
        source = _FixtureSource()
        plan = self._plan(source)
        report = self._apply(plan=plan, source=source, run_id="successful")

        self.assertEqual(report.promoted_frequency_count, 5)
        self.assertEqual(source.stage_calls, [1, 5, 15, 30, 60])
        manifest = json.loads(Path(report.quarantine_manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "promoted")
        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            target_path = raw_stk_mins_path(self.lake_root, freq, TRADE_DATE)
            self.assertEqual(_raw_open_value(target_path), 10.0)
            backup_path = Path(manifest["backup_paths"][str(freq)])
            self.assertTrue(backup_path.is_file())
            self.assertEqual(_raw_open_value(backup_path), 1.0)

    def test_stage_failure_does_not_move_any_existing_raw_file(self) -> None:
        source = _FixtureSource(fail_stage_frequency=15)
        plan = self._plan(source)

        with self.assertRaisesRegex(RuntimeError, "fixture staging failure"):
            self._apply(plan=plan, source=source, run_id="stage-failure")

        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE)), 1.0)
        self.assertFalse(
            (
                self.lake_root
                / "raw"
                / "tushare"
                / "stk_mins"
                / "_staging"
                / "recovery_run_id=stage-failure"
            ).exists()
        )

    def test_duplicate_staging_key_fails_before_quarantine(self) -> None:
        source = _FixtureSource(duplicate_stage_frequency=30)
        plan = self._plan(source)

        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "duplicate_key"):
            self._apply(plan=plan, source=source, run_id="duplicate")

        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE)), 1.0)
        self.assertFalse((self.lake_root / "_quarantine").exists())

    def test_promote_failure_restores_every_original_file(self) -> None:
        source = _FixtureSource()
        plan = self._plan(source)
        original_replace = os.replace
        failed = False

        def fail_second_promote(source_path, target_path):
            nonlocal failed
            if (
                not failed
                and "recovery_run_id=promote-failure" in str(source_path)
                and "freq=5" in str(source_path)
                and target_path == raw_stk_mins_path(self.lake_root, 5, TRADE_DATE)
            ):
                failed = True
                raise OSError("fixture promote failure")
            return original_replace(source_path, target_path)

        with patch.object(recovery.os, "replace", side_effect=fail_second_promote):
            with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "restored"):
                self._apply(plan=plan, source=source, run_id="promote-failure")

        self.assertTrue(failed)
        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE)), 1.0)

    def test_stale_or_already_applied_plan_is_rejected_without_second_replace(self) -> None:
        source = _FixtureSource()
        plan = self._plan(source)
        self._apply(plan=plan, source=source, run_id="first-apply")
        stage_call_count = len(source.stage_calls)

        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "stale"):
            self._apply(plan=plan, source=source, run_id="second-apply")

        self.assertEqual(len(source.stage_calls), stage_call_count)

    def test_plan_report_must_be_green_and_read_only_before_apply(self) -> None:
        plan = self._plan(_FixtureSource())
        report_path = self.lake_root / "plan.json"
        report_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

        loaded = recovery.load_stk_mins_raw_replace_from_prod_plan(report_path)

        self.assertEqual(loaded.plan_fingerprint, plan.plan_fingerprint)
        stopped_payload = plan.to_dict()
        stopped_payload["should_stop"] = True
        stopped_payload["stop_reasons"] = ["fixture_stop"]
        report_path.write_text(json.dumps(stopped_payload), encoding="utf-8")
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "stop reasons"):
            recovery.load_stk_mins_raw_replace_from_prod_plan(report_path)

    def test_recovery_module_stays_outside_active_definitions(self) -> None:
        source = Path(recovery.__file__).read_text(encoding="utf-8")
        self.assertNotIn("@dg.asset", source)
        self.assertNotIn("@dg.asset_check", source)
        self.assertNotIn("@dg.sensor", source)
        self.assertNotIn("report_runless_asset_event", source)


if __name__ == "__main__":
    unittest.main()
