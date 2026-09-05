import errno
import json
import os
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import duckdb

import orchestrator.defs.bootstrap.stk_mins_raw_replace_from_prod as recovery
import orchestrator.defs.bootstrap.stk_mins_raw_replace_from_prod_cli as cli
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
        self.lake_root = Path(self.temp_dir.name).resolve() / "lake"
        self.staging_root = self.lake_root.parent / "staging"
        self.lake_root.mkdir()
        self.staging_root.mkdir()
        for module in (recovery, cli):
            for name, value in (("DEFAULT_LAKE_ROOT", self.lake_root), ("DEFAULT_LAKE_STAGING_ROOT", self.staging_root)):
                patcher = patch.object(module, name, str(value))
                patcher.start()
                self.addCleanup(patcher.stop)
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

    def _apply(self, *, plan, source: _FixtureSource, run_id: str | None = None, **kwargs):
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
                **kwargs,
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

        self._apply(plan=missing_plan, source=_FixtureSource(), abort_before_promote=True)
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

        task_run["id"] = 1
        self.assertIsNotNone(
            recovery.full_market_stk_mins_task_run_from_row(
                task_run,
                trade_date=TRADE_DATE,
            )
        )

        with_code_filter = {**task_run, "filters_json": {**task_run["filters_json"], "ts_code": "000001.SZ"}}
        incomplete = {**task_run, "unit_done": 29354}
        zero_units = {**task_run, "unit_total": 0, "unit_done": 0}
        self.assertIsNone(
            recovery.full_market_stk_mins_task_run_from_row(
                with_code_filter,
                trade_date=TRADE_DATE,
            )
        )
        self.assertIsNone(
            recovery.full_market_stk_mins_task_run_from_row(
                incomplete,
                trade_date=TRADE_DATE,
            )
        )
        self.assertIsNone(
            recovery.full_market_stk_mins_task_run_from_row(
                zero_units,
                trade_date=TRADE_DATE,
            )
        )

    def test_apply_verifies_five_frequencies_without_backups(self) -> None:
        source = _FixtureSource()
        plan = self._plan(source)
        report = self._apply(plan=plan, source=source)
        self.assertEqual(report.promoted_frequency_count, 5)
        self.assertEqual(report.phase, "completed")
        self.assertEqual(source.stage_calls, [1, 5, 15, 30, 60])
        checkpoint = json.loads(Path(report.checkpoint_path).read_text())
        self.assertEqual(checkpoint["phase"], "completed")
        self.assertTrue(all(item["state"] == "verified" for item in checkpoint["frequencies"].values()))
        self.assertTrue(Path(report.final_report_path).is_file())
        self.assertEqual(len(list(self.run_root(plan).glob("audits/*.json"))), 5)
        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE)), 10.0)
        self.assertFalse((self.lake_root / "_quarantine").exists())
        self.assertFalse((self.lake_root / "raw/tushare/stk_mins/_staging").exists())
        self.assertFalse(list(self.run_root(plan).rglob("*backup*")))

    def test_stage_failure_does_not_move_any_existing_raw_file(self) -> None:
        source = _FixtureSource(fail_stage_frequency=15)
        plan = self._plan(source)

        with self.assertRaisesRegex(RuntimeError, "fixture staging failure"):
            self._apply(plan=plan, source=source)

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

    def test_duplicate_staging_key_fails_before_any_target_replace(self) -> None:
        source = _FixtureSource(duplicate_stage_frequency=30)
        plan = self._plan(source)

        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "duplicate_key"):
            self._apply(plan=plan, source=source)

        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE)), 1.0)
        self.assertFalse((self.lake_root / "_quarantine").exists())

    def test_invalid_candidate_contracts_never_replace_any_target(self):
        source = _FixtureSource()
        plan = self._plan(source)
        original_export = source.write_frequency_staging_file
        before = {f.freq: f.sha256 for f in plan.target_files}
        cases = (
            ("* EXCLUDE (vwap)", "", "schema mismatch"),
            ("* REPLACE (CAST(vol AS DOUBLE) AS vol)", "", "schema mismatch"),
            ("freq, ts_code, * EXCLUDE (freq, ts_code)", "", "schema mismatch"),
            ("*", "LIMIT 3", "row_count"),
            ("* REPLACE ('000002.SZ'::VARCHAR AS ts_code)", "", "code_coverage"),
            ("* REPLACE (NULL::VARCHAR AS ts_code)", "", "empty_key"),
            ("* REPLACE (NULL::TIMESTAMP AS trade_time)", "", "empty_key"),
            ("* REPLACE (NULL::INTEGER AS freq)", "", "freq"),
            ("* REPLACE (5::INTEGER AS freq)", "", "freq"),
            ("* REPLACE (trade_time + INTERVAL 1 DAY AS trade_time)", "", "trade_date"),
            ("* REPLACE (trade_time - INTERVAL 1 MINUTE AS trade_time)", "", "time_range"),
        )
        for projection, suffix, error in cases:
            with self.subTest(projection=projection, suffix=suffix):
                def invalid_export(projection=projection, suffix=suffix, **kwargs):
                    original_export(**kwargs)
                    path = kwargs["target_path"]
                    malformed = path.with_suffix(".invalid.parquet")
                    with duckdb.connect(database=":memory:") as connection:
                        connection.execute(
                            f"COPY (SELECT {projection} FROM read_parquet({duckdb_string(path)}, hive_partitioning=false) {suffix}) "
                            f"TO {duckdb_string(malformed)} (FORMAT PARQUET)"
                        )
                    os.replace(malformed, path)

                with patch.object(source, "write_frequency_staging_file", side_effect=invalid_export), self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, error):
                    self._apply(plan=plan, source=source)
                self.assertFalse(self.checkpoint(plan)["promote_started"])
                self.assertEqual(before, {
                    freq: recovery._sha256_path(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE))
                    for freq in recovery.STK_MINS_RECOVERY_FREQS
                })
        self.assertEqual(self._apply(plan=plan, source=source).phase, "completed")

    def test_duckdb_resource_exhaustion_retains_run_before_promotion(self):
        source = _FixtureSource()
        plan = self._plan(source)
        with patch.object(source, "write_frequency_staging_file", side_effect=duckdb.OutOfMemoryException("fixture OOM")), self.assertRaises(duckdb.OutOfMemoryException):
            self._apply(plan=plan, source=source)
        self.assertEqual(self.checkpoint(plan)["failure_code"], "resource_exhausted")
        self.assertFalse(self.checkpoint(plan)["promote_started"])
        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE)), 1.0)

    def test_promote_failure_preserves_completed_files_and_resumes(self) -> None:
        source = _FixtureSource()
        plan = self._plan(source)
        original_replace = os.replace

        def fail_second_promote(source_path, target_path):
            if target_path == raw_stk_mins_path(self.lake_root, 5, TRADE_DATE):
                raise OSError("fixture promote failure")
            return original_replace(source_path, target_path)

        with patch.object(recovery.os, "replace", side_effect=fail_second_promote), self.assertRaisesRegex(OSError, "fixture promote failure"):
            self._apply(plan=plan, source=source)
        self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, 1, TRADE_DATE)), 10.0)
        self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, 5, TRADE_DATE)), 1.0)
        self.assertEqual(self.checkpoint(plan)["phase"], "failed")
        report = self._apply(plan=plan, source=source)
        self.assertEqual(report.promoted_frequency_count, 5)
        self.assertEqual(source.stage_calls, [1, 5, 15, 30, 60])

    def test_completed_run_reentry_only_audits_and_other_run_id_is_rejected(self) -> None:
        source = _FixtureSource()
        plan = self._plan(source)
        self._apply(plan=plan, source=source)
        with patch.object(source, "write_frequency_staging_file", side_effect=AssertionError("no export")), patch.object(
            source, "load_frequency_facts", side_effect=AssertionError("no source query")
        ):
            report = self._apply(plan=plan, source=source)
        self.assertEqual(report.promoted_frequency_count, 5)
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "checkpoint_identity_mismatch"):
            self._apply(plan=plan, source=source, run_id=str(uuid4()))

    def test_plan_report_must_be_green_and_read_only_before_apply(self) -> None:
        plan = self._plan(_FixtureSource())
        report_path = self.run_root(plan) / "plan.json"
        report_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

        loaded = recovery.load_stk_mins_raw_replace_from_prod_plan(report_path)

        self.assertEqual(loaded.plan_fingerprint, plan.plan_fingerprint)
        stopped_payload = plan.to_dict()
        stopped_payload["should_stop"] = True
        stopped_payload["stop_reasons"] = ["fixture_stop"]
        report_path.write_text(json.dumps(stopped_payload), encoding="utf-8")
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "identity"):
            recovery.load_stk_mins_raw_replace_from_prod_plan(report_path)

    def test_recovery_module_stays_outside_active_definitions(self) -> None:
        source = Path(recovery.__file__).read_text(encoding="utf-8")
        self.assertNotIn("@dg.asset", source)
        self.assertNotIn("@dg.asset_check", source)
        self.assertNotIn("@dg.sensor", source)
        self.assertNotIn("report_runless_asset_event", source)


    def run_root(self, plan):
        return recovery.stk_mins_raw_recovery_run_root(self.staging_root, TRADE_DATE, plan.recovery_run_id)

    def checkpoint(self, plan):
        return json.loads((self.run_root(plan) / "checkpoint.json").read_text())

    def freeze_candidates(self, plan, source):
        original_replace = os.replace

        def stop_before_promote(source_path, target_path):
            if target_path == raw_stk_mins_path(self.lake_root, 1, TRADE_DATE):
                raise KeyboardInterrupt()
            return original_replace(source_path, target_path)

        with patch.object(recovery.os, "replace", side_effect=stop_before_promote), self.assertRaises(KeyboardInterrupt):
            self._apply(plan=plan, source=source)

    def test_second_run_is_blocked_until_explicit_safe_abort(self):
        source = _FixtureSource()
        plan = self._plan(source)
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "unfinished_run"):
            self._plan(source)
        report = self._apply(plan=plan, source=source, abort_before_promote=True)
        self.assertEqual(report.phase, "aborted_before_promote")
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "run_aborted"):
            self._apply(plan=plan, source=source)
        self.assertNotEqual(self._plan(source).recovery_run_id, plan.recovery_run_id)

    def test_stopped_plan_with_already_absent_target_can_only_abort_if_unchanged(self):
        target = raw_stk_mins_path(self.lake_root, 1, TRADE_DATE)
        target.unlink()
        source = _FixtureSource()
        plan = self._plan(source)
        self.assertIn("target_raw_file_missing:1", plan.stop_reasons)
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "scope_invalid"):
            self._apply(plan=plan, source=source)
        _write_raw_file(target, trade_date=TRADE_DATE, freq=1, stock_codes=STOCK_CODES, open_value=9.0)
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "abort_unsafe"):
            self._apply(plan=plan, source=source, abort_before_promote=True)
        target.unlink()
        self.assertEqual(self._apply(plan=plan, source=source, abort_before_promote=True).phase, "aborted_before_promote")
        self.assertEqual(source.stage_calls, [])

    def test_target_drift_blocks_all_promotions(self):
        source = _FixtureSource()
        plan = self._plan(source)
        target = raw_stk_mins_path(self.lake_root, 60, TRADE_DATE)
        target.write_bytes(b"foreign content")
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "target_drift"):
            self._apply(plan=plan, source=source)
        self.assertEqual(source.stage_calls, [])
        self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, 1, TRADE_DATE)), 1.0)

    def test_frozen_candidate_drift_requires_manual_abort_not_regeneration(self):
        source = _FixtureSource()
        plan = self._plan(source)
        self.freeze_candidates(plan, source)
        candidate = self.run_root(plan) / "candidates/freq=30/part-000.parquet"
        candidate.write_bytes(b"changed candidate")
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "candidate_drift"):
            self._apply(plan=plan, source=source)
        self.assertEqual(source.stage_calls, [1, 5, 15, 30, 60])
        self.assertEqual(self._apply(plan=plan, source=source, abort_before_promote=True).phase, "aborted_before_promote")

    def _interrupt_after_replace(self, freq):
        source = _FixtureSource()
        plan = self._plan(source)
        original_replace = os.replace

        def interrupt(source_path, target_path):
            result = original_replace(source_path, target_path)
            if target_path == raw_stk_mins_path(self.lake_root, freq, TRADE_DATE):
                raise KeyboardInterrupt()
            return result

        with patch.object(recovery.os, "replace", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self._apply(plan=plan, source=source)
        self.assertEqual(self.checkpoint(plan)["frequencies"][str(freq)]["state"], "pending")
        self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE)), 10.0)
        report = self._apply(plan=plan, source=source)
        self.assertEqual(report.promoted_frequency_count, 5)
        self.assertEqual(source.stage_calls, [1, 5, 15, 30, 60])
        return plan, source

    def test_interrupt_after_frequency_1(self):
        self._interrupt_after_replace(1)

    def test_interrupt_after_frequency_5(self):
        self._interrupt_after_replace(5)

    def test_interrupt_after_frequency_15(self):
        self._interrupt_after_replace(15)

    def test_interrupt_after_frequency_30(self):
        self._interrupt_after_replace(30)

    def test_interrupt_after_frequency_60(self):
        self._interrupt_after_replace(60)

    def test_partial_promote_missing_candidate_preserves_run_and_exact_reconstruction(self):
        source = _FixtureSource()
        plan = self._plan(source)
        original_replace = os.replace

        def interrupt(source_path, target_path):
            result = original_replace(source_path, target_path)
            if target_path == raw_stk_mins_path(self.lake_root, 1, TRADE_DATE):
                raise KeyboardInterrupt()
            return result

        with patch.object(recovery.os, "replace", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self._apply(plan=plan, source=source)
        candidate = self.run_root(plan) / "candidates/freq=5/part-000.parquet"
        frozen_bytes = candidate.read_bytes()
        candidate.unlink()
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "candidate_drift"):
            self._apply(plan=plan, source=source)
        self.assertTrue(self.checkpoint(plan)["operator_action_required"])
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "abort_unsafe"):
            self._apply(plan=plan, source=source, abort_before_promote=True)
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "unfinished_run"):
            self._plan(source)
        candidate.write_bytes(b"not an identical reconstruction")
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "candidate_drift"):
            self._apply(plan=plan, source=source)
        candidate.write_bytes(frozen_bytes)
        self.assertEqual(self._apply(plan=plan, source=source).promoted_frequency_count, 5)
        self.assertEqual(source.stage_calls, [1, 5, 15, 30, 60])

    def test_checkpoint_target_mismatch_cannot_repromote(self):
        source = _FixtureSource()
        plan = self._plan(source)
        old_bytes = raw_stk_mins_path(self.lake_root, 1, TRADE_DATE).read_bytes()
        self._apply(plan=plan, source=source)
        raw_stk_mins_path(self.lake_root, 1, TRADE_DATE).write_bytes(old_bytes)
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "checkpoint_target_mismatch"):
            self._apply(plan=plan, source=source)

    def test_unfinished_candidate_build_resumes_without_reexporting_frozen_candidates(self):
        source = _FixtureSource(fail_stage_frequency=15)
        plan = self._plan(source)
        with self.assertRaises(RuntimeError):
            self._apply(plan=plan, source=source)
        source.fail_stage_frequency = None
        report = self._apply(plan=plan, source=source)
        self.assertEqual(report.promoted_frequency_count, 5)
        self.assertEqual(source.stage_calls, [1, 5, 15, 15, 30, 60])

    def test_checkpoint_identity_mismatch_is_read_only(self):
        source = _FixtureSource()
        plan = self._plan(source)
        checkpoint = self.checkpoint(plan)
        checkpoint["trade_date"] = "2026-07-28"
        recovery._save_checkpoint(self.run_root(plan), checkpoint)
        before = (self.run_root(plan) / "checkpoint.json").read_bytes()
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "checkpoint_identity_mismatch"):
            self._apply(plan=plan, source=source)
        self.assertEqual((self.run_root(plan) / "checkpoint.json").read_bytes(), before)
        self.assertEqual(source.stage_calls, [])

    def test_plan_payload_cannot_change_without_changing_fingerprint(self):
        plan = self._plan(_FixtureSource())
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "identity"):
            self._apply(plan=replace(plan, expected_code_count=99), source=_FixtureSource())

    def test_atomic_checkpoint_write_failure_keeps_valid_previous_json(self):
        plan = self._plan(_FixtureSource())
        path = self.run_root(plan) / "checkpoint.json"
        before = path.read_bytes()
        checkpoint = self.checkpoint(plan)
        checkpoint["phase"] = "promoting"
        with patch.object(recovery.os, "replace", side_effect=OSError("cannot rename")), self.assertRaises(OSError):
            recovery._save_checkpoint(self.run_root(plan), checkpoint)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(path.read_text())["phase"], "planned")

    def test_checkpoint_write_failure_after_replace_can_resume(self):
        source = _FixtureSource()
        plan = self._plan(source)
        save = recovery._save_checkpoint

        def fail_promoted(run_root, checkpoint):
            if checkpoint["frequencies"]["1"]["state"] == "promoted":
                raise OSError("checkpoint write failed")
            return save(run_root, checkpoint)

        with patch.object(recovery, "_save_checkpoint", side_effect=fail_promoted), self.assertRaisesRegex(OSError, "checkpoint write failed"):
            self._apply(plan=plan, source=source)
        self.assertEqual(self.checkpoint(plan)["frequencies"]["1"]["state"], "pending")
        self.assertEqual(self._apply(plan=plan, source=source).promoted_frequency_count, 5)

    def test_resource_exhaustion_stops_before_promote_and_keeps_checkpoint(self):
        source = _FixtureSource()
        plan = self._plan(source)
        with patch.object(source, "write_frequency_staging_file", side_effect=OSError(errno.ENOSPC, "disk full")), self.assertRaises(OSError):
            self._apply(plan=plan, source=source)
        self.assertEqual(self.checkpoint(plan)["failure_code"], "resource_exhausted")
        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE)), 1.0)

    def test_slow_operation_warns_but_still_completes(self):
        source = _FixtureSource()
        plan = self._plan(source)
        clock = iter(range(0, 100_000, 301))
        with patch.object(recovery, "perf_counter", side_effect=lambda: next(clock)):
            report = self._apply(plan=plan, source=source)
        self.assertTrue(report.slow_operation_warning)
        self.assertEqual(report.promoted_frequency_count, 5)

    def test_cancel_before_next_unit_preserves_same_run(self):
        source = _FixtureSource()
        plan = self._plan(source)
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "cancelled"):
            self._apply(plan=plan, source=source, cancel_requested=lambda: len(source.stage_calls) == 1)
        self.assertEqual(source.stage_calls, [1])
        self.assertEqual(self.checkpoint(plan)["phase"], "failed")
        self.assertEqual(self._apply(plan=plan, source=source).promoted_frequency_count, 5)

    def test_same_old_and_candidate_only_audits_without_target_replace(self):
        for freq in recovery.STK_MINS_RECOVERY_FREQS:
            _write_raw_file(raw_stk_mins_path(self.lake_root, freq, TRADE_DATE),
                            trade_date=TRADE_DATE, freq=freq, stock_codes=STOCK_CODES, open_value=10.0)
        source = _FixtureSource()
        plan = self._plan(source)
        original_replace = os.replace

        def no_target_replace(source_path, target_path):
            self.assertFalse(Path(target_path).is_relative_to(self.lake_root))
            return original_replace(source_path, target_path)

        with patch.object(recovery.os, "replace", side_effect=no_target_replace):
            self.assertEqual(self._apply(plan=plan, source=source).promoted_frequency_count, 5)

    def test_source_drift_after_candidate_export_stops_before_promote(self):
        source = _FixtureSource()
        plan = self._plan(source)
        original_load = source.load_frequency_facts

        def drift(**kwargs):
            facts = original_load(**kwargs)
            if source.stage_calls:
                return (replace(facts[0], row_count=100), *facts[1:])
            return facts

        with patch.object(source, "load_frequency_facts", side_effect=drift), self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "plan_stale"):
            self._apply(plan=plan, source=source)
        self.assertEqual(_raw_open_value(raw_stk_mins_path(self.lake_root, 1, TRADE_DATE)), 1.0)

    def test_cross_filesystem_gate_uses_device_ids(self):
        same = SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=1))
        other = SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=2))
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "cross_filesystem"):
            recovery._assert_same_volume([same, other])

    def test_noncanonical_roots_dates_and_ids_are_rejected(self):
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "scope_invalid"):
            recovery._recovery_paths(self.lake_root, self.lake_root, TRADE_DATE, str(uuid4()))
        for run_id in ("../escape", "not-uuid", ""):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                recovery._recovery_paths(self.lake_root, self.staging_root, TRADE_DATE, run_id)
        with self.assertRaises(ValueError):
            recovery._recovery_paths(self.lake_root, self.staging_root, "20260727", str(uuid4()))

    def test_cli_paths_confirmation_and_same_run_dispatch(self):
        source = _FixtureSource()
        with patch.object(recovery, "_expected_stock_codes", return_value=STOCK_CODES), patch.object(
            recovery, "ProdStkMinsRawReplaceSource", return_value=source
        ):
            plan_path = cli.main(["plan", "--trade-date", TRADE_DATE])
            self.assertTrue(plan_path.is_relative_to(self.staging_root))
            plan = recovery.load_stk_mins_raw_replace_from_prod_plan(plan_path)
            result = cli.main(["apply", "--trade-date", TRADE_DATE, "--plan-report", str(plan_path), "--apply"])
            self.assertEqual(result, self.run_root(plan) / "final-report.json")
            self.assertEqual(cli.main(["apply", "--trade-date", TRADE_DATE, "--plan-report", str(plan_path), "--apply"]), result)
        with patch.object(cli, "apply_stk_mins_raw_replace_from_prod") as apply:
            for args in (
                ["apply", "--trade-date", TRADE_DATE],
                ["apply", "--trade-date", TRADE_DATE, "--plan-report", str(plan_path)],
                ["apply", "--trade-date", TRADE_DATE, "--plan-report", str(plan_path), "--apply", "--recovery-run-id", str(uuid4())],
            ):
                with self.subTest(args=args), self.assertRaises(SystemExit):
                    cli.main(args)
            apply.assert_not_called()

    def test_cli_output_cannot_escape_or_overwrite_run_evidence(self):
        plan = self._plan(_FixtureSource())
        for output in (
            self.lake_root / "bad.json",
            self.run_root(plan) / "checkpoint.json",
            self.run_root(plan) / "plan.json",
            self.run_root(plan) / "audits/freq=1.json",
            self.run_root(plan) / "candidates/freq=1/part-000.parquet",
        ):
            with self.subTest(output=output), self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "scope_invalid"):
                cli._report_output(output, self.run_root(plan), "apply")

    def test_symlink_candidate_is_rejected(self):
        source = _FixtureSource()
        plan = self._plan(source)
        run_root = self.run_root(plan)
        (run_root / "candidates").symlink_to(self.lake_root, target_is_directory=True)
        with self.assertRaisesRegex(recovery.StkMinsRawReplaceFromProdError, "scope_invalid"):
            self._apply(plan=plan, source=source)
        self.assertEqual(source.stage_calls, [])


if __name__ == "__main__":
    unittest.main()
