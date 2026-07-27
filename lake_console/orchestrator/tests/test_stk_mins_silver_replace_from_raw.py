import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import orchestrator.defs.bootstrap.stk_mins_silver_replace_from_raw as recovery
from orchestrator.defs.checks.stk_mins_checks import (
    SilverStkMinsPartitionDiagnostics,
    SilverStkMinsRuleDiagnostic,
)
from orchestrator.defs.paths import (
    raw_stk_mins_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource


TRADE_DATE = "2026-07-27"


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class StkMinsSilverReplaceFromRawTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.lake_root = Path(self.temp_dir.name)
        self.duckdb = DuckDBResource()
        for freq in recovery.STK_MINS_SILVER_RECOVERY_FREQS:
            _write_file(
                raw_stk_mins_path(self.lake_root, freq, TRADE_DATE),
                f"raw-{freq}",
            )
            _write_file(
                silver_stk_mins_path(self.lake_root, freq, TRADE_DATE),
                f"old-silver-{freq}",
            )
        for path, content in (
            (silver_stock_identity_map_path(self.lake_root), "identity-map"),
            (silver_stock_daily_path(self.lake_root, TRADE_DATE), "stock-daily"),
            (silver_stock_suspend_daily_path(self.lake_root, TRADE_DATE), "suspend"),
            (silver_stock_lifecycle_path(self.lake_root), "lifecycle"),
        ):
            _write_file(path, content)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _plan(self) -> recovery.StkMinsSilverReplaceFromRawPlan:
        return recovery.plan_stk_mins_silver_replace_from_raw(
            lake_root=self.lake_root,
            trade_date=TRADE_DATE,
        )

    def _apply(
        self,
        *,
        plan: recovery.StkMinsSilverReplaceFromRawPlan,
        run_id: str,
    ) -> recovery.StkMinsSilverReplaceFromRawApplyReport:
        return recovery.apply_stk_mins_silver_replace_from_raw(
            lake_root=self.lake_root,
            duckdb=self.duckdb,
            plan=plan,
            expected_plan_fingerprint=plan.plan_fingerprint,
            confirm_apply=True,
            recovery_run_id=run_id,
        )

    @staticmethod
    def _successful_diagnostics(*, freq: int, silver_path: Path, **_kwargs):
        return SilverStkMinsPartitionDiagnostics(
            freq=freq,
            partition_key=TRADE_DATE,
            silver_path=silver_path,
            rules=(SilverStkMinsRuleDiagnostic("fixture_rule", True),),
        )

    @staticmethod
    def _failed_diagnostics(*, freq: int, silver_path: Path, **_kwargs):
        return SilverStkMinsPartitionDiagnostics(
            freq=freq,
            partition_key=TRADE_DATE,
            silver_path=silver_path,
            rules=(SilverStkMinsRuleDiagnostic("fixture_rule", False),),
        )

    @staticmethod
    def _write_staging_file(*, freq: int, output_path_override: Path, **_kwargs):
        _write_file(output_path_override, f"new-silver-{freq}")
        return SimpleNamespace(
            row_count=1,
            observed_columns=("ts_code", "trade_time"),
        )

    def test_plan_is_read_only_and_freezes_five_raw_four_reference_and_targets(
        self,
    ) -> None:
        before = {
            freq: silver_stk_mins_path(self.lake_root, freq, TRADE_DATE).read_text(
                encoding="utf-8"
            )
            for freq in recovery.STK_MINS_SILVER_RECOVERY_FREQS
        }

        plan = self._plan()

        self.assertFalse(plan.should_stop)
        self.assertEqual(len(plan.input_files), 9)
        self.assertEqual(len(plan.target_files), 5)
        self.assertEqual(
            before,
            {
                freq: silver_stk_mins_path(self.lake_root, freq, TRADE_DATE).read_text(
                    encoding="utf-8"
                )
                for freq in recovery.STK_MINS_SILVER_RECOVERY_FREQS
            },
        )
        self.assertFalse((self.lake_root / "_quarantine").exists())
        self.assertFalse(
            (self.lake_root / "silver" / "quote" / "stk_mins" / "_staging").exists()
        )

    def test_apply_stages_all_frequencies_then_promotes_and_keeps_quarantine(
        self,
    ) -> None:
        plan = self._plan()
        with (
            patch.object(
                recovery,
                "write_silver_stk_mins_partition",
                side_effect=self._write_staging_file,
            ),
            patch.object(
                recovery,
                "evaluate_silver_stk_mins_partition_diagnostics",
                side_effect=self._successful_diagnostics,
            ),
        ):
            report = self._apply(plan=plan, run_id="successful")

        self.assertEqual(report.promoted_frequency_count, 5)
        manifest = json.loads(
            Path(report.quarantine_manifest_path).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "promoted")
        self.assertEqual(len(manifest["staged_files"]), 5)
        self.assertEqual(
            manifest["staged_files"][0]["observed_columns"],
            ["ts_code", "trade_time"],
        )
        self.assertEqual(manifest["staged_files"][0]["row_count"], 1)
        for freq in recovery.STK_MINS_SILVER_RECOVERY_FREQS:
            self.assertEqual(
                silver_stk_mins_path(self.lake_root, freq, TRADE_DATE).read_text(
                    encoding="utf-8"
                ),
                f"new-silver-{freq}",
            )
            backup_path = Path(manifest["backup_paths"][str(freq)])
            self.assertEqual(
                backup_path.read_text(encoding="utf-8"), f"old-silver-{freq}"
            )

    def test_staged_diagnostic_failure_keeps_all_existing_targets(self) -> None:
        plan = self._plan()
        with (
            patch.object(
                recovery,
                "write_silver_stk_mins_partition",
                side_effect=self._write_staging_file,
            ),
            patch.object(
                recovery,
                "evaluate_silver_stk_mins_partition_diagnostics",
                side_effect=self._failed_diagnostics,
            ),
        ):
            with self.assertRaisesRegex(
                recovery.StkMinsSilverReplaceFromRawError,
                "failed current rule diagnostics",
            ):
                self._apply(plan=plan, run_id="diagnostic-failure")

        for freq in recovery.STK_MINS_SILVER_RECOVERY_FREQS:
            self.assertEqual(
                silver_stk_mins_path(self.lake_root, freq, TRADE_DATE).read_text(
                    encoding="utf-8"
                ),
                f"old-silver-{freq}",
            )
        self.assertFalse((self.lake_root / "_quarantine").exists())

    def test_stale_plan_is_rejected_before_staging(self) -> None:
        plan = self._plan()
        _write_file(raw_stk_mins_path(self.lake_root, 1, TRADE_DATE), "changed-raw")
        with patch.object(recovery, "write_silver_stk_mins_partition") as writer:
            with self.assertRaisesRegex(
                recovery.StkMinsSilverReplaceFromRawError,
                "stale",
            ):
                self._apply(plan=plan, run_id="stale")
        writer.assert_not_called()

    def test_promote_failure_restores_all_original_targets(self) -> None:
        plan = self._plan()
        original_replace = os.replace
        failed = False

        def fail_second_promote(source_path, target_path):
            nonlocal failed
            if (
                not failed
                and "recovery_run_id=promote-failure" in str(source_path)
                and "freq=5" in str(source_path)
                and target_path == silver_stk_mins_path(self.lake_root, 5, TRADE_DATE)
            ):
                failed = True
                raise OSError("fixture promote failure")
            return original_replace(source_path, target_path)

        with (
            patch.object(
                recovery,
                "write_silver_stk_mins_partition",
                side_effect=self._write_staging_file,
            ),
            patch.object(
                recovery,
                "evaluate_silver_stk_mins_partition_diagnostics",
                side_effect=self._successful_diagnostics,
            ),
            patch.object(recovery.os, "replace", side_effect=fail_second_promote),
        ):
            with self.assertRaisesRegex(
                recovery.StkMinsSilverReplaceFromRawError,
                "restored",
            ):
                self._apply(plan=plan, run_id="promote-failure")

        self.assertTrue(failed)
        for freq in recovery.STK_MINS_SILVER_RECOVERY_FREQS:
            self.assertEqual(
                silver_stk_mins_path(self.lake_root, freq, TRADE_DATE).read_text(
                    encoding="utf-8"
                ),
                f"old-silver-{freq}",
            )

    def test_plan_report_must_be_green_and_read_only_before_apply(self) -> None:
        plan = self._plan()
        report_path = self.lake_root / "plan.json"
        report_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")

        loaded = recovery.load_stk_mins_silver_replace_from_raw_plan(report_path)

        self.assertEqual(loaded.plan_fingerprint, plan.plan_fingerprint)
        stopped_payload = plan.to_dict()
        stopped_payload["should_stop"] = True
        stopped_payload["stop_reasons"] = ["fixture_stop"]
        report_path.write_text(json.dumps(stopped_payload), encoding="utf-8")
        with self.assertRaisesRegex(
            recovery.StkMinsSilverReplaceFromRawError,
            "stop reasons",
        ):
            recovery.load_stk_mins_silver_replace_from_raw_plan(report_path)

    def test_recovery_module_stays_outside_active_definitions(self) -> None:
        source = Path(recovery.__file__).read_text(encoding="utf-8")
        self.assertNotIn("@dg.asset", source)
        self.assertNotIn("@dg.asset_check", source)
        self.assertNotIn("@dg.sensor", source)
        self.assertNotIn("report_runless_asset_event", source)


if __name__ == "__main__":
    unittest.main()
