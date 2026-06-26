import ast
import unittest
from pathlib import Path

from orchestrator.defs.assets.stk_mins import (
    GoldStkMinsQfqDerivedPartitionWriteResult,
    GoldStkMinsQfqPartitionWriteResult,
    SilverStkMinsWriteResult,
    StkMinsRawWriteResult,
    _gold_stk_mins_qfq_derived_human_metadata,
    _gold_stk_mins_qfq_human_metadata,
    _raw_stk_mins_human_metadata,
    _silver_stk_mins_human_metadata,
    gold_stk_mins_qfq_1m,
    raw_stk_mins_1m,
    silver_stk_mins_1m,
)
from orchestrator.defs.assets.stk_mins_qfq_macd_kdj import (
    _macd_kdj_indicator_human_metadata,
    _macd_kdj_state_human_metadata,
    gold_stk_mins_qfq_macd_kdj_1m,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GoldStkMinsQfqMacdKdjPartitionWriteResult,
)
from orchestrator.defs.jobs.stock_mins_qfq_daily_update import (
    stock_mins_qfq_daily_update_job,
)
from orchestrator.defs.checks.stk_mins_checks import _readable_check_metadata
from orchestrator.defs.jobs.stock_mins_raw_update import (
    stock_mins_raw_update_from_prod_job,
    stock_mins_raw_update_job,
)
from orchestrator.defs.jobs.stock_mins_silver_update import (
    stock_mins_silver_update_job,
)
from orchestrator.defs.sensors.stock_mins_raw_sensor import stock_mins_raw_sensor
from orchestrator.defs.sensors.stock_mins_qfq_daily_sensor import (
    stock_mins_qfq_daily_sensor,
)
from orchestrator.defs.sensors.stock_mins_qfq_factor_repair_sensor import (
    stock_mins_qfq_factor_repair_sensor,
)
from orchestrator.defs.sensors.stock_mins_silver_sensor import stock_mins_silver_sensor


ASSET_PATH = Path("src/orchestrator/defs/assets/stk_mins.py")
MACD_KDJ_ASSET_PATH = Path("src/orchestrator/defs/assets/stk_mins_qfq_macd_kdj.py")


def _asset_description(asset_definition) -> str:  # noqa: ANN001
    descriptions = tuple(asset_definition.descriptions_by_key.values())
    return descriptions[0] if descriptions else ""


def _stdout_calls(path: Path = ASSET_PATH) -> list[ast.Call]:
    tree = ast.parse(path.read_text(), filename=str(path))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "stdout":
            calls.append(node)
    return calls


class StkMinsHumanReadableContractTests(unittest.TestCase):
    def test_asset_job_and_sensor_descriptions_explain_business_purpose(self) -> None:
        descriptions = (
            _asset_description(raw_stk_mins_1m),
            _asset_description(silver_stk_mins_1m),
            _asset_description(gold_stk_mins_qfq_1m),
            _asset_description(gold_stk_mins_qfq_macd_kdj_1m),
            stock_mins_raw_update_job.description or "",
            stock_mins_raw_update_from_prod_job.description or "",
            stock_mins_silver_update_job.description or "",
            stock_mins_qfq_daily_update_job.description or "",
            stock_mins_raw_sensor.description or "",
            stock_mins_silver_sensor.description or "",
            stock_mins_qfq_daily_sensor.description or "",
            stock_mins_qfq_factor_repair_sensor.description or "",
        )

        for description in descriptions:
            with self.subTest(description=description):
                self.assertRegex(description, r"[\u4e00-\u9fff]")
                self.assertNotIn("selection", description.lower())

        self.assertIn("raw", descriptions[0])
        self.assertIn("silver", descriptions[1])
        self.assertIn("前复权", descriptions[2])
        self.assertIn("MACD/KDJ", descriptions[3])
        self.assertIn("prod DB", descriptions[5])

    def test_stk_mins_stdout_events_are_small_and_named(self) -> None:
        calls = _stdout_calls()
        events = {
            call.args[0].value
            for call in calls
            if call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        }

        self.assertEqual(
            {
                "raw_stk_mins_started",
                "raw_stk_mins_completed",
                "raw_stk_mins_repair_started",
                "raw_stk_mins_repair_completed",
                "silver_stk_mins_started",
                "silver_stk_mins_completed",
                "gold_stk_mins_qfq_started",
                "gold_stk_mins_qfq_completed",
                "gold_stk_mins_qfq_derived_started",
                "gold_stk_mins_qfq_derived_completed",
            }
            - events,
            set(),
        )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "stock_codes",
            "ts_codes",
            "sample_rows",
            "raw_file_path",
            "silver_file_path",
            "input_file_paths",
        }
        issues = []
        for call in calls:
            keyword_names = {keyword.arg for keyword in call.keywords if keyword.arg}
            forbidden = keyword_names & forbidden_stdout_fields
            if forbidden:
                issues.append(f"stdout call writes forbidden fields {sorted(forbidden)}")

        self.assertEqual(issues, [])

    def test_macd_kdj_stdout_events_are_small_and_named(self) -> None:
        calls = _stdout_calls(MACD_KDJ_ASSET_PATH)
        events = {
            call.args[0].value
            for call in calls
            if call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        }

        self.assertEqual(
            {
                "gold_stk_mins_qfq_macd_kdj_started",
                "gold_stk_mins_qfq_macd_kdj_indicator_completed",
                "gold_stk_mins_qfq_macd_kdj_state_completed",
            }
            - events,
            set(),
        )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "stock_codes",
            "ts_codes",
            "sample_rows",
            "input_file_paths",
            "indicator_sample_file_paths",
            "previous_state_file_path",
        }
        issues = []
        for call in calls:
            keyword_names = {keyword.arg for keyword in call.keywords if keyword.arg}
            forbidden = keyword_names & forbidden_stdout_fields
            if forbidden:
                issues.append(f"stdout call writes forbidden fields {sorted(forbidden)}")

        self.assertEqual(issues, [])

    def test_raw_human_materialization_metadata_uses_operator_fields(self) -> None:
        result = StkMinsRawWriteResult(
            raw_file_path=Path("/tmp/raw.parquet"),
            row_count=100,
            observed_columns=("ts_code", "freq"),
            stock_code_count=3,
            returned_stock_code_count=2,
            empty_stock_code_count=1,
            page_count=3,
            source_method="prod_db_raw_tushare",
            query_count=1,
            write_mode="replace",
        )

        metadata = _raw_stk_mins_human_metadata(
            write_result=result,
            partition_key="2026-05-29",
            freq=1,
        )

        self.assertIn("股票 1min 分钟 raw 源镜像", metadata["goldenshare/summary"])
        self.assertIn("silver_stk_mins", metadata["goldenshare/next_action"])
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(
            metadata["goldenshare/input_summary"]["source_method"],
            "prod_db_raw_tushare",
        )
        self.assertEqual(metadata["goldenshare/filter_summary"]["output_row_count"], 100)

    def test_silver_human_materialization_metadata_uses_operator_fields(self) -> None:
        result = SilverStkMinsWriteResult(
            raw_file_path=Path("/tmp/raw.parquet"),
            one_minute_raw_file_path=Path("/tmp/raw_1m.parquet"),
            identity_map_file_path=Path("/tmp/identity.parquet"),
            stock_daily_file_path=Path("/tmp/daily.parquet"),
            suspend_file_path=Path("/tmp/suspend.parquet"),
            silver_file_path=Path("/tmp/silver.parquet"),
            source_row_count=120,
            mapped_row_count=118,
            duplicate_removed_count=2,
            full_day_suspend_deleted_row_count=3,
            price_correction_row_count=4,
            recomputed_row_count=5,
            vol_amount_normalized_row_count=6,
            row_count=109,
            observed_columns=("ts_code", "freq"),
        )

        metadata = _silver_stk_mins_human_metadata(
            write_result=result,
            partition_key="2026-05-29",
            freq=5,
        )

        self.assertIn("股票 5min 分钟 silver 标准事实", metadata["goldenshare/summary"])
        self.assertIn("qfq", metadata["goldenshare/next_action"])
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(
            metadata["goldenshare/input_summary"]["source_asset"],
            "raw_stk_mins_5m",
        )
        self.assertEqual(metadata["goldenshare/filter_summary"]["output_row_count"], 109)

    def test_qfq_human_materialization_metadata_uses_operator_fields(self) -> None:
        result = GoldStkMinsQfqPartitionWriteResult(
            silver_file_path=Path("/tmp/silver.parquet"),
            trade_adj_factor_file_path=Path("/tmp/adj.parquet"),
            as_of_adj_factor_file_path=Path("/tmp/adj.parquet"),
            as_of_trade_date="2026-05-29",
            output_root_path=Path("/tmp/gold"),
            output_file_count=2,
            output_sample_file_paths=("/tmp/gold/a.parquet",),
            row_count=100,
            replacement_row_count=90,
            observed_columns=("ts_code", "freq"),
        )

        metadata = _gold_stk_mins_qfq_human_metadata(
            write_result=result,
            partition_key="2026-05-29",
            freq=1,
        )

        self.assertIn("gold 前复权行情", metadata["goldenshare/summary"])
        self.assertIn("factor repair", metadata["goldenshare/next_action"])
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(
            metadata["goldenshare/input_summary"]["source_asset"],
            "silver_stk_mins_1m",
        )
        self.assertEqual(metadata["goldenshare/filter_summary"]["output_file_count"], 2)

    def test_qfq_derived_human_materialization_metadata_uses_operator_fields(
        self,
    ) -> None:
        result = GoldStkMinsQfqDerivedPartitionWriteResult(
            source_freq=30,
            source_file_count=2,
            output_root_path=Path("/tmp/gold"),
            output_file_count=2,
            output_sample_file_paths=("/tmp/gold/a.parquet",),
            source_row_count=120,
            source_stock_day_count=2,
            expected_window_count=60,
            generated_window_count=58,
            incomplete_window_count=2,
            exchange_mismatch_window_count=0,
            replacement_row_count=50,
            observed_columns=("ts_code", "freq"),
        )

        metadata = _gold_stk_mins_qfq_derived_human_metadata(
            write_result=result,
            partition_key="2026-05-29",
            freq=90,
        )

        self.assertIn("派生行情", metadata["goldenshare/summary"])
        self.assertIn("MACD/KDJ", metadata["goldenshare/next_action"])
        self.assertEqual(
            metadata["goldenshare/input_summary"]["source_asset"],
            "gold_stk_mins_qfq_30m",
        )
        self.assertEqual(
            metadata["goldenshare/filter_summary"]["generated_window_count"],
            58,
        )

    def test_macd_kdj_indicator_human_metadata_uses_operator_fields(self) -> None:
        result = GoldStkMinsQfqMacdKdjPartitionWriteResult(
            freq=1,
            trade_date="2026-05-29",
            source_file_count=2,
            previous_state_file_path=Path("/tmp/state.parquet"),
            indicator_file_count=3,
            indicator_sample_file_paths=("/tmp/indicator.parquet",),
            indicator_row_count=100,
            indicator_replacement_row_count=90,
            state_file_path=Path("/tmp/state.parquet"),
            state_row_count=10,
            initialized_without_previous_state=False,
            observed_indicator_columns=("ts_code", "freq"),
            observed_state_columns=("ts_code", "freq"),
        )

        metadata = _macd_kdj_indicator_human_metadata(
            write_result=result,
            partition_key="2026-05-29",
            previous_trade_date="2026-05-28",
        )

        self.assertIn("MACD/KDJ 指标", metadata["goldenshare/summary"])
        self.assertIn("blocking checks", metadata["goldenshare/next_action"])
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(
            metadata["goldenshare/input_summary"]["source_asset"],
            "gold_stk_mins_qfq_1m",
        )
        self.assertEqual(metadata["goldenshare/filter_summary"]["output_row_count"], 100)

    def test_macd_kdj_state_human_metadata_uses_operator_fields(self) -> None:
        result = GoldStkMinsQfqMacdKdjPartitionWriteResult(
            freq=5,
            trade_date="2026-05-29",
            source_file_count=2,
            previous_state_file_path=None,
            indicator_file_count=3,
            indicator_sample_file_paths=("/tmp/indicator.parquet",),
            indicator_row_count=100,
            indicator_replacement_row_count=90,
            state_file_path=Path("/tmp/state.parquet"),
            state_row_count=10,
            initialized_without_previous_state=True,
            observed_indicator_columns=("ts_code", "freq"),
            observed_state_columns=("ts_code", "freq"),
        )

        metadata = _macd_kdj_state_human_metadata(
            write_result=result,
            partition_key="2026-05-29",
            previous_trade_date=None,
        )

        self.assertIn("日终 state", metadata["goldenshare/summary"])
        self.assertIn("下一 expected 交易日", metadata["goldenshare/next_action"])
        self.assertEqual(metadata["goldenshare/result_status"], "written")
        self.assertEqual(
            metadata["goldenshare/input_summary"]["source_asset"],
            "gold_stk_mins_qfq_macd_kdj_5m",
        )
        self.assertEqual(metadata["goldenshare/filter_summary"]["state_row_count"], 10)


    def test_check_readable_metadata_keeps_rule_summary_and_next_action(self) -> None:
        metadata = _readable_check_metadata(
            dataset_label="股票 1 分钟 raw 契约",
            rule_names=("file_exists", "schema"),
            failed_rule_names=("schema",),
            success_next_action="无需处理。",
            failure_next_action="先修复 schema。",
        )

        self.assertIn("失败", metadata["summary"])
        self.assertEqual(metadata["next_action"], "先修复 schema。")
        self.assertEqual(
            metadata["rule_summary"],
            [
                {"rule_name": "file_exists", "passed": True},
                {"rule_name": "schema", "passed": False},
            ],
        )


if __name__ == "__main__":
    unittest.main()
