import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityExpectedDateWindow,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import stock_daily_qfq_sensor as sensor_module
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    DatasetReadinessStatus,
)
from orchestrator.defs.sensors.stock_daily_qfq_sensor import (
    GOLD_STOCK_DAILY_QFQ_SENSOR_NAME,
    gold_stock_daily_qfq_update_job_sensor,
)


EVALUATED_AT = datetime(2026, 6, 18, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
EXPECTED_DATES = ("2026-06-15", "2026-06-16", "2026-06-17")


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self._partitions = partitions

    def get_dynamic_partitions(self, name: str) -> list[str]:
        if name != cn_a_stock_trade_days.name:
            return []
        return list(self._partitions)


class _FakeContext:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self.instance = _FakeInstance(partitions)
        self.resources = SimpleNamespace(lake_root=object(), duckdb=object())


def _expected_window(
    trade_dates: tuple[str, ...] = EXPECTED_DATES,
) -> ContinuityExpectedDateWindow:
    return ContinuityExpectedDateWindow(
        expected_trade_dates=trade_dates,
        min_trade_date=trade_dates[0] if trade_dates else None,
        max_trade_date=trade_dates[-1] if trade_dates else None,
        evaluated_at=EVALUATED_AT,
        window_limit=10,
    )


def _dataset_status(
    *,
    asset_key: str,
    trade_date: str,
    ready: bool,
    materialized: bool,
    checks_passed: bool,
    reason: str = "ready",
    failed_check_names: tuple[str, ...] = (),
    missing_check_names: tuple[str, ...] = (),
) -> DatasetReadinessStatus:
    return DatasetReadinessStatus(
        ready=ready,
        statuses=(
            AssetReadinessStatus(
                asset_key=asset_key,
                partition_key=trade_date,
                ready=ready,
                materialized=materialized,
                checks_passed=checks_passed,
                freshness_passed=ready,
                materialization_storage_id=1 if materialized else None,
                materialization_date=trade_date if materialized else None,
                missing_check_names=missing_check_names,
                failed_check_names=failed_check_names,
                reason=reason,
            ),
        ),
    )


def _missing_gold_status(trade_date: str) -> DatasetReadinessStatus:
    return _dataset_status(
        asset_key="gold_stock_daily_qfq",
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason="gold_stock_daily_qfq has no materialization",
        missing_check_names=("gold_stock_daily_qfq_contract_check",),
    )


def _failed_gold_status(trade_date: str) -> DatasetReadinessStatus:
    return _dataset_status(
        asset_key="gold_stock_daily_qfq",
        trade_date=trade_date,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason="gold_stock_daily_qfq failed blocking checks",
        failed_check_names=("gold_stock_daily_qfq_contract_check",),
    )


def _ready_status(asset_key: str, trade_date: str) -> DatasetReadinessStatus:
    return _dataset_status(
        asset_key=asset_key,
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
    )


class GoldStockDailyQfqSensorContractTests(unittest.TestCase):
    def test_sensor_definition_is_stopped_and_tagged(self) -> None:
        self.assertEqual(
            gold_stock_daily_qfq_update_job_sensor.name,
            GOLD_STOCK_DAILY_QFQ_SENSOR_NAME,
        )
        self.assertEqual(
            gold_stock_daily_qfq_update_job_sensor.default_status,
            dg.DefaultSensorStatus.STOPPED,
        )
        self.assertEqual(gold_stock_daily_qfq_update_job_sensor.minimum_interval_seconds, 600)
        self.assertEqual(
            gold_stock_daily_qfq_update_job_sensor.tags[SENSOR_DOMAIN_TAG],
            "quote_data",
        )
        self.assertEqual(
            gold_stock_daily_qfq_update_job_sensor.tags[SENSOR_TARGET_LAYER_TAG],
            "gold",
        )
        self.assertEqual(
            gold_stock_daily_qfq_update_job_sensor.tags[SENSOR_ROLE_TAG],
            "asset_update",
        )

    def test_missing_registered_partition_skips_before_readiness(self) -> None:
        selector = Mock()
        context = _FakeContext(("2026-06-15", "2026-06-17"))

        with (
            patch.object(
                sensor_module,
                "_load_expected_stock_trade_day_window",
                return_value=_expected_window(),
            ),
            patch.object(
                sensor_module,
                "select_first_not_ready_gold_stock_daily_qfq_partition",
                selector,
            ),
        ):
            result = gold_stock_daily_qfq_update_job_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        selector.assert_not_called()
        cursor = load_sensor_cursor(result.cursor)
        details = cursor["details"]
        self.assertEqual(details["reason_code"], "missing_registered_partition")
        self.assertEqual(
            details["continuity_status"]["first_missing_registered_date"],
            "2026-06-16",
        )

    def test_missing_gold_partition_and_ready_upstreams_submits_selected_date(self) -> None:
        selected_date = "2026-06-16"
        context = _FakeContext(EXPECTED_DATES)

        with (
            patch.object(
                sensor_module,
                "_load_expected_stock_trade_day_window",
                return_value=_expected_window(),
            ),
            patch.object(
                sensor_module,
                "select_first_not_ready_gold_stock_daily_qfq_partition",
                return_value=(selected_date, _missing_gold_status(selected_date)),
            ),
            patch.object(
                sensor_module,
                "stock_daily_ready_for_trade_date",
                return_value=_ready_status("silver_stock_daily", selected_date),
            ) as stock_daily_ready,
            patch.object(
                sensor_module,
                "adj_factor_ready_for_trade_date",
                return_value=_ready_status("silver_adj_factor", selected_date),
            ) as adj_factor_ready,
        ):
            result = gold_stock_daily_qfq_update_job_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, selected_date)
        self.assertEqual(
            request.run_key,
            f"gold_stock_daily_qfq_update:{selected_date}",
        )
        stock_daily_ready.assert_called_once_with(context.instance, selected_date)
        adj_factor_ready.assert_called_once_with(context.instance, selected_date)
        cursor = load_sensor_cursor(result.cursor)
        self.assertEqual(cursor["decision"], "request_runs")
        self.assertEqual(cursor["details"]["reason_code"], "selected_for_update")
        self.assertEqual(
            cursor["details"]["continuity_status"]["selected_date"],
            selected_date,
        )

    def test_materialized_check_problem_does_not_auto_rerun(self) -> None:
        selected_date = "2026-06-16"
        context = _FakeContext(EXPECTED_DATES)
        stock_daily_ready = Mock()

        with (
            patch.object(
                sensor_module,
                "_load_expected_stock_trade_day_window",
                return_value=_expected_window(),
            ),
            patch.object(
                sensor_module,
                "select_first_not_ready_gold_stock_daily_qfq_partition",
                return_value=(selected_date, _failed_gold_status(selected_date)),
            ),
            patch.object(
                sensor_module,
                "stock_daily_ready_for_trade_date",
                stock_daily_ready,
            ),
        ):
            result = gold_stock_daily_qfq_update_job_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        stock_daily_ready.assert_not_called()
        cursor = load_sensor_cursor(result.cursor)
        self.assertEqual(
            cursor["details"]["reason_code"],
            "gold_stock_daily_qfq_not_ready",
        )
        self.assertEqual(
            cursor["details"]["continuity_status"]["blocked_reason"],
            "materialized_check_problem",
        )

    def test_selected_date_waits_for_stock_daily_upstream(self) -> None:
        selected_date = "2026-06-16"
        context = _FakeContext(EXPECTED_DATES)

        with (
            patch.object(
                sensor_module,
                "_load_expected_stock_trade_day_window",
                return_value=_expected_window(),
            ),
            patch.object(
                sensor_module,
                "select_first_not_ready_gold_stock_daily_qfq_partition",
                return_value=(selected_date, _missing_gold_status(selected_date)),
            ),
            patch.object(
                sensor_module,
                "stock_daily_ready_for_trade_date",
                return_value=_dataset_status(
                    asset_key="silver_stock_daily",
                    trade_date=selected_date,
                    ready=False,
                    materialized=False,
                    checks_passed=False,
                    reason="silver_stock_daily has no materialization",
                ),
            ),
            patch.object(sensor_module, "adj_factor_ready_for_trade_date") as adj_ready,
        ):
            result = gold_stock_daily_qfq_update_job_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        adj_ready.assert_not_called()
        cursor = load_sensor_cursor(result.cursor)
        self.assertEqual(
            cursor["details"]["reason_code"],
            "upstream_silver_stock_daily_not_ready",
        )

    def test_all_ready_skips_with_ready_frontier(self) -> None:
        context = _FakeContext(EXPECTED_DATES)

        with (
            patch.object(
                sensor_module,
                "_load_expected_stock_trade_day_window",
                return_value=_expected_window(),
            ),
            patch.object(
                sensor_module,
                "select_first_not_ready_gold_stock_daily_qfq_partition",
                return_value=(None, None),
            ),
        ):
            result = gold_stock_daily_qfq_update_job_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        cursor = load_sensor_cursor(result.cursor)
        self.assertEqual(cursor["details"]["reason_code"], "all_ready")
        self.assertEqual(
            cursor["details"]["continuity_status"]["ready_through_date"],
            "2026-06-17",
        )

    def test_cursor_json_reason_values_are_ascii(self) -> None:
        context = _FakeContext(EXPECTED_DATES)

        with (
            patch.object(
                sensor_module,
                "_load_expected_stock_trade_day_window",
                return_value=_expected_window(),
            ),
            patch.object(
                sensor_module,
                "select_first_not_ready_gold_stock_daily_qfq_partition",
                return_value=(None, None),
            ),
        ):
            result = gold_stock_daily_qfq_update_job_sensor._raw_fn(context)

        payload = json.loads(result.cursor)
        serialized = json.dumps(
            {
                key: value
                for key, value in payload["details"].items()
                if key.endswith("reason") or key.endswith("reason_code")
            },
            ensure_ascii=False,
        )
        self.assertTrue(serialized.isascii())


if __name__ == "__main__":
    unittest.main()
