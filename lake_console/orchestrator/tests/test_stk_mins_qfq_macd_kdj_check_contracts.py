import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

from orchestrator.defs.assets.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS,
)
from orchestrator.defs.checks import stk_mins_qfq_macd_kdj_checks as checks
from orchestrator.defs.jobs.gold_stk_mins_qfq_macd_kdj_daily_update import (
    gold_stk_mins_qfq_macd_kdj_check_refresh_job,
    gold_stk_mins_qfq_macd_kdj_daily_update_job,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days


def _write_parquet(path: Path, sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped_path = str(path).replace("'", "''")
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(f"COPY ({sql}) TO '{escaped_path}' (FORMAT PARQUET)")


def _macd_kdj_asset_keys() -> set:
    return {
        asset_key
        for asset_definition in GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS
        for asset_key in asset_definition.keys
    }


def _metadata_value(metadata: dict, key: str):  # noqa: ANN001
    value = metadata[f"goldenshare/{key}"]
    for attribute in ("value", "text", "data"):
        if hasattr(value, attribute):
            return getattr(value, attribute)
    return value


def _assert_no_tuple_values(value) -> None:  # noqa: ANN001
    for attribute in ("value", "text", "data"):
        if hasattr(value, attribute):
            _assert_no_tuple_values(getattr(value, attribute))
            return
    if isinstance(value, tuple):
        raise AssertionError(f"metadata contains tuple value: {value!r}")
    if isinstance(value, dict):
        for child in value.values():
            _assert_no_tuple_values(child)
    if isinstance(value, list):
        for child in value:
            _assert_no_tuple_values(child)


class StkMinsQfqMacdKdjCheckContractTests(unittest.TestCase):
    def test_macd_kdj_indicator_and_state_checks_are_partitioned(self) -> None:
        for freq in (1, 5, 15, 30, 60, 90, 120):
            for check_name in checks.GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES:
                with self.subTest(freq=freq, check_name=check_name):
                    check_definition = getattr(
                        checks,
                        f"gold_stk_mins_qfq_macd_kdj_{freq}m_{check_name}",
                    )
                    self.assertEqual(
                        check_definition.partitions_def,
                        cn_a_stock_mins_silver_trade_days,
                    )

            for check_name in checks.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECK_NAMES:
                with self.subTest(freq=freq, check_name=check_name):
                    check_definition = getattr(
                        checks,
                        f"gold_stk_mins_qfq_macd_kdj_state_{freq}m_{check_name}",
                    )
                    self.assertEqual(
                        check_definition.partitions_def,
                        cn_a_stock_mins_silver_trade_days,
                    )

    def test_check_refresh_job_selects_checks_only(self) -> None:
        selected_assets = gold_stk_mins_qfq_macd_kdj_check_refresh_job.selection.resolve(
            GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS
        )

        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_check_refresh_job.name,
            "gold_stk_mins_qfq_macd_kdj_check_refresh_job",
        )
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_check_refresh_job.partitions_def,
            cn_a_stock_mins_silver_trade_days,
        )
        self.assertEqual(selected_assets, set())
        self.assertIn(
            "AssetChecksForAssetKeysSelection",
            repr(gold_stk_mins_qfq_macd_kdj_check_refresh_job.selection),
        )
        self.assertNotIn(
            "KeysAssetSelection",
            repr(gold_stk_mins_qfq_macd_kdj_check_refresh_job.selection),
        )

    def test_daily_job_still_selects_assets_and_checks(self) -> None:
        selected_assets = gold_stk_mins_qfq_macd_kdj_daily_update_job.selection.resolve(
            GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS
        )

        self.assertEqual(
            selected_assets,
            _macd_kdj_asset_keys(),
        )
        self.assertIn(
            "AssetChecksForAssetKeysSelection",
            repr(gold_stk_mins_qfq_macd_kdj_daily_update_job.selection),
        )
        self.assertIn(
            "KeysAssetSelection",
            repr(gold_stk_mins_qfq_macd_kdj_daily_update_job.selection),
        )

    def test_source_coverage_missing_source_metadata_is_dagster_compatible(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir, patch.object(
            checks,
            "discover_gold_stk_mins_qfq_source_year_paths",
            return_value=(),
        ):
            result = checks._indicator_source_coverage_result(
                lake_root=Path(temp_dir),
                freq=1,
                partition_key="2026-06-24",
            )

        self.assertFalse(result.passed)
        self.assertIn("goldenshare/failed_rule_names", result.metadata)
        self.assertIn("MACD/KDJ source 覆盖", _metadata_value(result.metadata, "summary"))
        self.assertIn("qfq source", _metadata_value(result.metadata, "next_action"))
        self.assertEqual(
            _metadata_value(result.metadata, "failed_rule_names"),
            [checks.GOLD_STK_MINS_QFQ_MACD_KDJ_SOURCE_READY_CHECK],
        )
        _assert_no_tuple_values(result.metadata)

    def test_source_coverage_missing_indicator_metadata_is_dagster_compatible(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.parquet"
            _write_parquet(
                source_path,
                """
                SELECT
                  '000001.SZ' AS ts_code,
                  1 AS freq,
                  DATE '2026-06-24' AS trade_date
                """,
            )
            with patch.object(
                checks,
                "discover_gold_stk_mins_qfq_source_year_paths",
                return_value=(source_path,),
            ), patch.object(checks, "_indicator_expected_paths", return_value=()):
                result = checks._indicator_source_coverage_result(
                    lake_root=Path(temp_dir),
                    freq=1,
                    partition_key="2026-06-24",
                )

        self.assertFalse(result.passed)
        self.assertIn("goldenshare/failed_rule_names", result.metadata)
        self.assertIn("检查失败", _metadata_value(result.metadata, "summary"))
        self.assertIn("indicator 文件", _metadata_value(result.metadata, "next_action"))
        rule_summary = _metadata_value(result.metadata, "rule_summary")
        self.assertEqual(
            rule_summary,
            [
                {
                    "rule_name": checks.GOLD_STK_MINS_QFQ_MACD_KDJ_SOURCE_READY_CHECK,
                    "passed": True,
                },
                {
                    "rule_name": (
                        checks.GOLD_STK_MINS_QFQ_MACD_KDJ_ROW_COUNT_MATCHES_QFQ_CHECK
                    ),
                    "passed": False,
                },
            ],
        )
        _assert_no_tuple_values(result.metadata)

    def test_source_coverage_count_mismatch_metadata_is_dagster_compatible(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.parquet"
            indicator_path = Path(temp_dir) / "indicator.parquet"
            _write_parquet(
                source_path,
                """
                SELECT
                  '000001.SZ' AS ts_code,
                  1 AS freq,
                  DATE '2026-06-24' AS trade_date
                """,
            )
            _write_parquet(
                indicator_path,
                """
                SELECT
                  CAST(NULL AS VARCHAR) AS ts_code,
                  CAST(NULL AS INTEGER) AS freq,
                  CAST(NULL AS DATE) AS trade_date
                WHERE false
                """,
            )
            with patch.object(
                checks,
                "discover_gold_stk_mins_qfq_source_year_paths",
                return_value=(source_path,),
            ), patch.object(
                checks,
                "_indicator_expected_paths",
                return_value=(indicator_path,),
            ):
                result = checks._indicator_source_coverage_result(
                    lake_root=Path(temp_dir),
                    freq=1,
                    partition_key="2026-06-24",
                )

        self.assertFalse(result.passed)
        self.assertIn("goldenshare/failed_rule_names", result.metadata)
        self.assertIn("source 覆盖", _metadata_value(result.metadata, "summary"))
        self.assertIn("goldenshare/source_row_count", result.metadata)
        _assert_no_tuple_values(result.metadata)

    def test_formula_check_readable_metadata_is_dagster_compatible(self) -> None:
        with TemporaryDirectory() as temp_dir:
            indicator_path = Path(temp_dir) / "indicator.parquet"
            _write_parquet(
                indicator_path,
                """
                SELECT
                  '000001.SZ' AS ts_code,
                  1 AS freq,
                  DATE '2026-06-24' AS trade_date,
                  TIMESTAMP '2026-06-24 10:00:00' AS trade_time,
                  1.0 AS macd_dif_qfq,
                  0.5 AS macd_dea_qfq,
                  99.0 AS macd_qfq,
                  1.0 AS kdj_k_qfq,
                  0.5 AS kdj_d_qfq,
                  99.0 AS kdj_qfq
                """,
            )
            with patch.object(
                checks,
                "discover_gold_stk_mins_qfq_source_year_paths",
                return_value=(indicator_path,),
            ), patch.object(
                checks,
                "_indicator_expected_paths",
                return_value=(indicator_path,),
            ):
                result = checks._indicator_formula_result(
                    lake_root=Path(temp_dir),
                    freq=1,
                    partition_key="2026-06-24",
                )

        self.assertFalse(result.passed)
        self.assertIn("公式抽样", _metadata_value(result.metadata, "summary"))
        self.assertIn("goldenshare/failure_samples", result.metadata)
        self.assertEqual(
            _metadata_value(result.metadata, "failed_rule_names"),
            [checks.GOLD_STK_MINS_QFQ_MACD_KDJ_FORMULA_SAMPLE_CHECK],
        )
        _assert_no_tuple_values(result.metadata)


if __name__ == "__main__":
    unittest.main()
