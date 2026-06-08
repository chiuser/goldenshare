from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

from orchestrator.defs.checks import namechange_checks
from orchestrator.defs.jobs import namechange_update as namechange_jobs
from orchestrator.defs.jobs import stock_basic_update as stock_basic_jobs
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import stock_basic_sensor as stock_basic_sensor_module
from orchestrator.defs.sensors import stock_namechange_sensor as namechange_sensor_module
from orchestrator.defs.sensors.readiness import (
    RAW_NAMECHANGE_CHECKS,
    RAW_NAMECHANGE_READINESS_SPEC,
    RAW_STOCK_BASIC_CHECKS,
    RAW_STOCK_BASIC_READINESS_SPEC,
    STOCK_BASIC_READINESS_SPECS,
    AssetReadinessStatus,
    DatasetReadinessStatus,
)
from orchestrator.defs.sensors.stock_basic_sensor import (
    raw_stock_basic_update_job_sensor,
    silver_stock_basic_update_job_sensor,
)
from orchestrator.defs.sensors.stock_namechange_sensor import (
    raw_namechange_update_job_sensor,
    silver_namechange_update_job_sensor,
)


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 5, 10, 0, tzinfo=tz)


class _BeforeWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 5, 9, 0, tzinfo=tz)


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]):
        self._partitions = partitions

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._partitions)


class _FakeContext:
    def __init__(
        self,
        *,
        partitions: tuple[str, ...] = ("2026-06-05",),
        cursor: str | None = None,
    ):
        self.instance = _FakeInstance(partitions)
        self.cursor = cursor


def _asset_status(
    *,
    asset_key: str,
    ready: bool = True,
    materialized: bool = True,
    checks_passed: bool = True,
    freshness_passed: bool = True,
    missing_check_names: tuple[str, ...] = (),
    failed_check_names: tuple[str, ...] = (),
    reason: str = "ready",
) -> AssetReadinessStatus:
    return AssetReadinessStatus(
        asset_key=asset_key,
        partition_key=None,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=freshness_passed,
        materialization_storage_id=1 if materialized else None,
        materialization_date="2026-06-05" if freshness_passed else "2026-06-04",
        missing_check_names=missing_check_names,
        failed_check_names=failed_check_names,
        reason=reason,
    )


def _dataset_status(*, ready: bool) -> DatasetReadinessStatus:
    return DatasetReadinessStatus(
        ready=ready,
        statuses=(
            _asset_status(
                asset_key="raw_tushare_stock_basic",
                ready=ready,
                materialized=ready,
                checks_passed=ready,
                freshness_passed=ready,
                missing_check_names=() if ready else ("raw_stock_basic_file_exists",),
                reason="ready" if ready else "raw_tushare_stock_basic not ready",
            ),
            _asset_status(
                asset_key="silver_stock_basic",
                ready=ready,
                materialized=ready,
                checks_passed=ready,
                freshness_passed=ready,
                missing_check_names=() if ready else ("silver_stock_basic_unique_ts_code",),
                reason="ready" if ready else "silver_stock_basic not ready",
            ),
        ),
    )


def _raw_stock_basic_result(context: _FakeContext):
    return raw_stock_basic_update_job_sensor._raw_fn(context)


def _silver_stock_basic_result(context: _FakeContext):
    return silver_stock_basic_update_job_sensor._raw_fn(context)


def _raw_namechange_result(context: _FakeContext):
    return raw_namechange_update_job_sensor._raw_fn(context)


def _silver_namechange_result(context: _FakeContext):
    return silver_namechange_update_job_sensor._raw_fn(context)


def _skip_message(result) -> str:
    return result.skip_reason.skip_message


class StockBasicNamechangeSplitContractTests(unittest.TestCase):
    def test_job_and_sensor_names_follow_split_rule(self) -> None:
        self.assertTrue(hasattr(stock_basic_jobs, "raw_stock_basic_update_job"))
        self.assertTrue(hasattr(stock_basic_jobs, "silver_stock_basic_update_job"))
        self.assertFalse(hasattr(stock_basic_jobs, "stock_basic_update_job"))
        self.assertFalse(hasattr(stock_basic_sensor_module, "stock_basic_sensor"))
        self.assertTrue(hasattr(namechange_jobs, "raw_namechange_update_job"))
        self.assertTrue(hasattr(namechange_jobs, "silver_namechange_update_job"))
        self.assertFalse(hasattr(namechange_jobs, "namechange_update_job"))
        self.assertFalse(hasattr(namechange_sensor_module, "stock_namechange_sensor"))

        self.assertEqual(
            raw_stock_basic_update_job_sensor.name,
            "raw_stock_basic_update_job_sensor",
        )
        self.assertEqual(
            silver_stock_basic_update_job_sensor.name,
            "silver_stock_basic_update_job_sensor",
        )
        self.assertEqual(
            raw_namechange_update_job_sensor.name,
            "raw_namechange_update_job_sensor",
        )
        self.assertEqual(
            silver_namechange_update_job_sensor.name,
            "silver_namechange_update_job_sensor",
        )
        self.assertEqual(
            raw_stock_basic_update_job_sensor.job_name,
            "raw_stock_basic_update_job",
        )
        self.assertEqual(
            silver_stock_basic_update_job_sensor.job_name,
            "silver_stock_basic_update_job",
        )
        self.assertEqual(
            raw_namechange_update_job_sensor.job_name,
            "raw_namechange_update_job",
        )
        self.assertEqual(
            silver_namechange_update_job_sensor.job_name,
            "silver_namechange_update_job",
        )

    def test_job_selections_are_layer_specific(self) -> None:
        raw_stock_selection = repr(stock_basic_jobs.raw_stock_basic_update_job.selection)
        silver_stock_selection = repr(
            stock_basic_jobs.silver_stock_basic_update_job.selection
        )
        raw_namechange_selection = repr(namechange_jobs.raw_namechange_update_job.selection)
        silver_namechange_selection = repr(
            namechange_jobs.silver_namechange_update_job.selection
        )

        self.assertIn("raw_tushare_stock_basic", raw_stock_selection)
        self.assertNotIn("silver_stock_basic", raw_stock_selection)
        self.assertIn("silver_stock_basic", silver_stock_selection)
        self.assertNotIn("raw_tushare_stock_basic", silver_stock_selection)
        self.assertIn("raw_tushare_namechange", raw_namechange_selection)
        self.assertNotIn("silver_namechange", raw_namechange_selection)
        self.assertIn("silver_namechange", silver_namechange_selection)
        self.assertNotIn("raw_tushare_namechange", silver_namechange_selection)

    def test_sensor_tags_are_layer_specific(self) -> None:
        expected_raw_tags = {
            SENSOR_DOMAIN_TAG: "basic_data",
            SENSOR_TARGET_LAYER_TAG: "raw",
            SENSOR_ROLE_TAG: "asset_update",
        }
        expected_silver_tags = {
            SENSOR_DOMAIN_TAG: "basic_data",
            SENSOR_TARGET_LAYER_TAG: "silver",
            SENSOR_ROLE_TAG: "asset_update",
        }
        self.assertEqual(raw_stock_basic_update_job_sensor.tags, expected_raw_tags)
        self.assertEqual(silver_stock_basic_update_job_sensor.tags, expected_silver_tags)
        self.assertEqual(raw_namechange_update_job_sensor.tags, expected_raw_tags)
        self.assertEqual(silver_namechange_update_job_sensor.tags, expected_silver_tags)

    def test_readiness_specs_keep_existing_check_names(self) -> None:
        self.assertEqual(
            RAW_STOCK_BASIC_READINESS_SPEC.blocking_check_names,
            RAW_STOCK_BASIC_CHECKS,
        )
        self.assertIn(RAW_STOCK_BASIC_READINESS_SPEC, STOCK_BASIC_READINESS_SPECS)

        expected_names = (
            "raw_namechange_file_exists",
            "raw_namechange_row_count_positive",
            "raw_namechange_required_columns",
            "raw_namechange_schema_matches_tushare_contract",
            "raw_namechange_required_fields_non_null",
            "raw_namechange_date_string_format_valid",
            "raw_namechange_exact_duplicate_absent",
        )
        for check_name in expected_names:
            self.assertTrue(hasattr(namechange_checks, check_name))
        self.assertEqual(RAW_NAMECHANGE_CHECKS, expected_names)
        self.assertEqual(
            RAW_NAMECHANGE_READINESS_SPEC.blocking_check_names,
            expected_names,
        )
        self.assertNotIn(
            "raw_namechange_multi_open_interval_observed",
            RAW_NAMECHANGE_CHECKS,
        )
        self.assertNotIn(
            "raw_namechange_overlap_interval_observed",
            RAW_NAMECHANGE_CHECKS,
        )

    def test_raw_stock_basic_sensor_submits_when_missing(self) -> None:
        context = _FakeContext()
        with patch(
            "orchestrator.defs.sensors.stock_basic_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_basic_sensor.raw_tushare_stock_basic_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="raw_tushare_stock_basic",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                missing_check_names=("raw_stock_basic_file_exists",),
                reason="raw_tushare_stock_basic has no materialization",
            ),
        ):
            result = _raw_stock_basic_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.run_key, "raw_stock_basic_update:2026-06-05")
        self.assertIsNone(request.partition_key)

    def test_raw_stock_basic_sensor_skips_failed_checks(self) -> None:
        context = _FakeContext()
        with patch(
            "orchestrator.defs.sensors.stock_basic_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_basic_sensor.raw_tushare_stock_basic_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="raw_tushare_stock_basic",
                ready=False,
                checks_passed=False,
                failed_check_names=("raw_stock_basic_ts_code_present",),
                reason="raw_tushare_stock_basic failed blocking checks",
            ),
        ):
            result = _raw_stock_basic_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", _skip_message(result))

    def test_silver_stock_basic_sensor_waits_for_raw_ready(self) -> None:
        context = _FakeContext()
        with patch(
            "orchestrator.defs.sensors.stock_basic_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_basic_sensor.silver_stock_basic_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="silver_stock_basic",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                reason="silver_stock_basic has no materialization",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_basic_sensor.raw_tushare_stock_basic_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="raw_tushare_stock_basic",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                reason="raw_tushare_stock_basic has no materialization",
            ),
        ):
            result = _silver_stock_basic_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("等待 raw readiness", _skip_message(result))

    def test_silver_stock_basic_sensor_submits_when_raw_ready_and_silver_missing(self) -> None:
        context = _FakeContext()
        with patch(
            "orchestrator.defs.sensors.stock_basic_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_basic_sensor.silver_stock_basic_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="silver_stock_basic",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                reason="silver_stock_basic has no materialization",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_basic_sensor.raw_tushare_stock_basic_ready_for_trade_date",
            return_value=_asset_status(asset_key="raw_tushare_stock_basic"),
        ):
            result = _silver_stock_basic_result(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.run_key, "silver_stock_basic_update:2026-06-05")
        self.assertIsNone(request.partition_key)

    def test_raw_namechange_sensor_respects_window_and_once_per_day(self) -> None:
        with patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.datetime",
            _BeforeWindowDateTime,
        ):
            before_window = _raw_namechange_result(_FakeContext())
        self.assertEqual(before_window.run_requests, [])
        self.assertIn("尚未到 09:30", _skip_message(before_window))

        with patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.raw_tushare_namechange_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="raw_tushare_namechange",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                reason="raw_tushare_namechange has no materialization",
            ),
        ):
            submitted = _raw_namechange_result(_FakeContext())
        self.assertEqual(len(submitted.run_requests), 1)
        self.assertEqual(
            submitted.run_requests[0].run_key,
            "raw_namechange_update:2026-06-05",
        )
        self.assertIsNone(submitted.run_requests[0].partition_key)

        with patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.raw_tushare_namechange_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="raw_tushare_namechange",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                reason="raw_tushare_namechange has no materialization",
            ),
        ):
            repeated = _raw_namechange_result(_FakeContext(cursor=submitted.cursor))
        self.assertEqual(repeated.run_requests, [])
        self.assertIn("已经提交过", _skip_message(repeated))
        self.assertTrue(
            load_sensor_cursor(submitted.cursor)["details"][
                "already_submitted_for_trade_date"
            ]
        )

    def test_raw_namechange_sensor_skips_failed_checks(self) -> None:
        context = _FakeContext()
        with patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.raw_tushare_namechange_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="raw_tushare_namechange",
                ready=False,
                checks_passed=False,
                failed_check_names=("raw_namechange_exact_duplicate_absent",),
                reason="raw_tushare_namechange failed blocking checks",
            ),
        ):
            result = _raw_namechange_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", _skip_message(result))

    def test_silver_namechange_sensor_waits_for_raw_and_stock_basic(self) -> None:
        context = _FakeContext()
        with patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.silver_namechange_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="silver_namechange",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                reason="silver_namechange has no materialization",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.raw_tushare_namechange_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="raw_tushare_namechange",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                reason="raw_tushare_namechange has no materialization",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.stock_basic_ready_for_trade_date"
        ) as stock_basic_readiness:
            raw_blocked = _silver_namechange_result(context)
        self.assertEqual(raw_blocked.run_requests, [])
        self.assertIn("等待 raw readiness", _skip_message(raw_blocked))
        stock_basic_readiness.assert_not_called()

        with patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.silver_namechange_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="silver_namechange",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                reason="silver_namechange has no materialization",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.raw_tushare_namechange_ready_for_trade_date",
            return_value=_asset_status(asset_key="raw_tushare_namechange"),
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=False),
        ):
            stock_basic_blocked = _silver_namechange_result(context)
        self.assertEqual(stock_basic_blocked.run_requests, [])
        self.assertIn("等待 stock_basic", _skip_message(stock_basic_blocked))

    def test_silver_namechange_sensor_uses_stock_basic_final_ready_and_submits(self) -> None:
        self.assertFalse(
            hasattr(namechange_sensor_module, "silver_stock_basic_ready_for_trade_date")
        )

        context = _FakeContext()
        with patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.silver_namechange_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="silver_namechange",
                ready=False,
                materialized=False,
                checks_passed=False,
                freshness_passed=False,
                reason="silver_namechange has no materialization",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.raw_tushare_namechange_ready_for_trade_date",
            return_value=_asset_status(asset_key="raw_tushare_namechange"),
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.stock_basic_ready_for_trade_date",
            return_value=_dataset_status(ready=True),
        ) as stock_basic_readiness:
            result = _silver_namechange_result(context)

        stock_basic_readiness.assert_called_once()
        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.run_key, "silver_namechange_update:2026-06-05")
        self.assertIsNone(request.partition_key)

    def test_silver_namechange_sensor_skips_failed_silver_checks(self) -> None:
        context = _FakeContext()
        with patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.silver_namechange_ready_for_trade_date",
            return_value=_asset_status(
                asset_key="silver_namechange",
                ready=False,
                checks_passed=False,
                failed_check_names=("silver_namechange_schema_matches_contract",),
                reason="silver_namechange failed blocking checks",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_namechange_sensor.raw_tushare_namechange_ready_for_trade_date"
        ) as raw_readiness:
            result = _silver_namechange_result(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", _skip_message(result))
        raw_readiness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
