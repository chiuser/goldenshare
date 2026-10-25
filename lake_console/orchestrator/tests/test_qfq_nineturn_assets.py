import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from orchestrator.defs.assets import qfq_nineturn as asset_module
from orchestrator.defs.assets.qfq_nineturn import (
    GOLD_STK_MINS_QFQ_NINETURN_ASSETS,
    gold_stock_daily_qfq_nineturn,
)
from orchestrator.defs.catalog.lake_assets import get_lake_asset_catalog_entry
from orchestrator.defs.checks.qfq_nineturn_checks import GOLD_QFQ_NINETURN_CHECKS
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_trade_days,
)
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QfqNineturnPartitionWriteResult,
    QfqNineturnSourcePlan,
)


class QfqNineturnAssetContractTests(unittest.TestCase):
    def test_assets_use_expected_keys_partitions_and_human_descriptions(self) -> None:
        expected_minute_keys = tuple(
            f"gold_stk_mins_qfq_nineturn_{freq}m" for freq in (30, 60, 90, 120)
        )
        self.assertEqual(
            gold_stock_daily_qfq_nineturn.key.to_user_string(),
            "gold_stock_daily_qfq_nineturn",
        )
        self.assertEqual(
            gold_stock_daily_qfq_nineturn.partitions_def,
            cn_a_stock_trade_days,
        )
        self.assertRegex(
            next(iter(gold_stock_daily_qfq_nineturn.descriptions_by_key.values())),
            r"[\u4e00-\u9fff]",
        )
        self.assertEqual(
            tuple(
                asset.key.to_user_string()
                for asset in GOLD_STK_MINS_QFQ_NINETURN_ASSETS
            ),
            expected_minute_keys,
        )
        for asset in GOLD_STK_MINS_QFQ_NINETURN_ASSETS:
            self.assertEqual(asset.partitions_def, cn_a_stock_mins_silver_trade_days)
            self.assertRegex(
                next(iter(asset.descriptions_by_key.values())),
                r"[\u4e00-\u9fff]",
            )

    def test_one_blocking_check_and_catalog_entry_per_asset(self) -> None:
        check_pairs = {
            (
                next(iter(check_definition.check_specs)).asset_key.to_user_string(),
                next(iter(check_definition.check_specs)).name,
            )
            for check_definition in GOLD_QFQ_NINETURN_CHECKS
        }
        asset_keys = ("gold_stock_daily_qfq_nineturn",) + tuple(
            f"gold_stk_mins_qfq_nineturn_{freq}m" for freq in (30, 60, 90, 120)
        )
        self.assertEqual(len(check_pairs), 5)
        for asset_key in asset_keys:
            entry = get_lake_asset_catalog_entry(asset_key)
            expected_check = (
                "gold_stock_daily_qfq_nineturn_integrity_check"
                if asset_key == "gold_stock_daily_qfq_nineturn"
                else f"{asset_key}_integrity_check"
            )
            self.assertEqual(entry.blocking_check_names, (expected_check,))
            self.assertIn((asset_key, expected_check), check_pairs)
            self.assertEqual(entry.source_system.value, "derived")


class QfqNineturnMinuteWriterArgumentsTests(unittest.TestCase):
    """Exercise asset wiring only; planner, SQL computation and writer are replaced."""

    def _assert_minute_writer_arguments(
        self, *, current_run_id: str, root_run_id: str | None, expected_run_id: str
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for freq, asset in zip(
                (30, 60, 90, 120), GOLD_STK_MINS_QFQ_NINETURN_ASSETS, strict=True
            ):
                with self.subTest(freq=freq):
                    plan = QfqNineturnSourcePlan(
                        source_paths=(root / "source.parquet",),
                        fingerprint_source_paths=(root / "source.parquet",),
                        fallback_source_paths=(),
                        fallback_codes=(),
                        previous_partition_path=root / "previous.parquet",
                        source_row_count=3,
                    )
                    # These are wiring objects, not Parquet/schema or Dagster-run fixtures.
                    context = SimpleNamespace(
                        partition_key="2026-10-22",
                        run_id=current_run_id,
                        run=SimpleNamespace(
                            run_id=current_run_id, root_run_id=root_run_id
                        ),
                        instance=SimpleNamespace(
                            get_dynamic_partitions=MagicMock(
                                return_value=("2026-10-21", "2026-10-22")
                            )
                        ),
                    )
                    lake_root = MagicMock()
                    lake_root.root.return_value = root
                    connection = object()
                    duckdb = MagicMock()
                    duckdb.connect.return_value = nullcontext(connection)
                    result = QfqNineturnPartitionWriteResult(
                        target_path=root / "target.parquet",
                        source_row_count=3,
                        output_row_count=3,
                        stock_code_count=1,
                        fallback_recomputed_code_count=0,
                        source_file_count=1,
                        source_fingerprint="source-fingerprint",
                        observed_columns=(
                            "ts_code", "freq", "trade_date", "trade_time",
                            "up_count", "down_count", "nine_up_turn", "nine_down_turn",
                        ),
                    )
                    with (
                        patch.object(
                            asset_module,
                            "plan_gold_stk_mins_qfq_nineturn_source",
                            return_value=plan,
                        ) as planner,
                        patch.object(
                            asset_module,
                            "build_gold_stk_mins_qfq_nineturn_partition_select_sql",
                            return_value="SELECT minute_output",
                        ),
                        patch.object(
                            asset_module,
                            "write_gold_stk_mins_qfq_nineturn_partition",
                            return_value=result,
                        ) as writer,
                    ):
                        asset.op.compute_fn.decorated_fn(context, lake_root, duckdb)
                    planner.assert_called_once_with(
                        connection,
                        lake_root=root,
                        freq=freq,
                        partition_key="2026-10-22",
                        previous_trade_date="2026-10-21",
                    )
                    writer.assert_called_once_with(
                        duckdb_resource=duckdb,
                        lake_root=root,
                        freq=freq,
                        partition_key="2026-10-22",
                        run_id=expected_run_id,
                        select_sql="SELECT minute_output",
                        source_plan=plan,
                    )
                    self.assertIs(writer.call_args.kwargs["source_plan"], plan)
                    lake_root.ensure_available_for_run.assert_called_once_with()

    def test_first_run_passes_current_run_and_complete_plan(self) -> None:
        self._assert_minute_writer_arguments(
            current_run_id="first-run", root_run_id=None, expected_run_id="first-run"
        )

    def test_child_run_passes_original_root_and_complete_plan(self) -> None:
        self._assert_minute_writer_arguments(
            current_run_id="child-run", root_run_id="first-run", expected_run_id="first-run"
        )


if __name__ == "__main__":
    unittest.main()
