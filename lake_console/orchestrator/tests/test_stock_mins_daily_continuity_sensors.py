import json
import unittest
from datetime import datetime
from unittest.mock import patch

from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_mins_trade_days,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.sensors import readiness
from orchestrator.defs.sensors import stock_mins_qfq_daily_sensor as qfq_daily_module
from orchestrator.defs.sensors import (
    stock_mins_qfq_factor_repair_sensor as qfq_factor_repair_module,
)
from orchestrator.defs.sensors.stock_mins_raw_sensor import stock_mins_raw_sensor
from orchestrator.defs.sensors.stock_mins_qfq_daily_sensor import (
    stock_mins_qfq_daily_sensor,
)
from orchestrator.defs.sensors.stock_mins_qfq_factor_repair_sensor import (
    stock_mins_qfq_factor_repair_sensor,
)
from orchestrator.defs.sensors.stock_mins_silver_sensor import stock_mins_silver_sensor
from orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor import (
    stock_mins_silver_trade_day_sensor,
)


class _AfterRawWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 35, tzinfo=tz)


class _BeforeRawWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 20, tzinfo=tz)


class _AfterSilverPartitionWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 46, tzinfo=tz)


class _BeforeSilverPartitionWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 44, tzinfo=tz)


class _AfterSilverRunWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 55, tzinfo=tz)


class _BeforeSilverRunWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 19, 49, tzinfo=tz)


class _AfterQfqDailyWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 20, 15, tzinfo=tz)


class _BeforeQfqDailyWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 20, 5, tzinfo=tz)


class _AfterQfqFactorRepairWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 20, 45, tzinfo=tz)


class _BeforeQfqFactorRepairWindowDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 16, 20, 35, tzinfo=tz)


class _Instance:
    def __init__(
        self,
        partitions: tuple[str, ...],
        *,
        partitions_by_name: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._partitions = partitions
        self._partitions_by_name = partitions_by_name or {}

    def get_dynamic_partitions(self, name: str) -> list[str]:
        return list(self._partitions_by_name.get(name, self._partitions))


class _Context:
    def __init__(
        self,
        partitions: tuple[str, ...] = (),
        *,
        cursor: str | None = None,
        partitions_by_name: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.cursor = cursor
        self.instance = _Instance(partitions, partitions_by_name=partitions_by_name)


def _asset_status(
    *,
    asset_key: str,
    ready: bool,
    materialized: bool,
    checks_passed: bool,
    reason: str,
) -> readiness.AssetReadinessStatus:
    return readiness.AssetReadinessStatus(
        asset_key=asset_key,
        partition_key=None,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=ready,
        materialization_storage_id=1 if materialized else None,
        materialization_date="2026-06-16" if ready else None,
        missing_check_names=() if checks_passed else (f"{asset_key}_file_exists",),
        failed_check_names=(),
        reason=reason,
    )


def _dataset_status(
    *,
    ready: bool,
    materialized: bool = False,
    checks_passed: bool = False,
    reason: str = "not ready",
    asset_key: str = "raw_stk_mins_1m",
) -> readiness.DatasetReadinessStatus:
    return readiness.DatasetReadinessStatus(
        ready=ready,
        statuses=(
            _asset_status(
                asset_key=asset_key,
                ready=ready,
                materialized=materialized,
                checks_passed=checks_passed,
                reason=reason,
            ),
        ),
    )


def _asset_readiness_status(
    *,
    ready: bool,
    reason: str = "ready",
    asset_key: str = "silver_stock_identity_map",
) -> readiness.AssetReadinessStatus:
    return _asset_status(
        asset_key=asset_key,
        ready=ready,
        materialized=True,
        checks_passed=True,
        reason=reason,
    )


def _stock_basic_status(*, ready: bool) -> readiness.DatasetReadinessStatus:
    return readiness.DatasetReadinessStatus(
        ready=ready,
        statuses=(
            _asset_status(
                asset_key="silver_stock_basic",
                ready=ready,
                materialized=True,
                checks_passed=True,
                reason="ready" if ready else "stock basic not fresh",
            ),
        ),
    )


def _qfq_factor_repair_status(
    *,
    trade_date: str,
    ready: bool,
    reason: str = "ready",
) -> GoldStkMinsQfqFactorRepairStatus:
    return GoldStkMinsQfqFactorRepairStatus(
        ready=ready,
        trade_date=trade_date,
        reason=reason,
        upstream_batch_id=f"qfq_factor_repair:{trade_date}:digest",
    )


def _skip_message(result) -> str:
    return getattr(result.skip_reason, "skip_message", str(result.skip_reason))


class StockMinsDailyContinuitySensorTests(unittest.TestCase):
    def test_raw_sensor_skips_missing_registered_gap_before_readiness_scan(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-16"))
        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "raw_stk_mins_ready_for_trade_date",
        ) as raw_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        raw_ready_mock.assert_not_called()
        self.assertIn("交易日分区存在缺口", _skip_message(result))

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")
        self.assertEqual(continuity["blocked_reason"], "missing_registered_partition")

    def test_raw_sensor_submits_first_not_ready_date_not_latest_registered(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        raw_statuses = {
            "2026-06-13": _dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            "2026-06-15": _dataset_status(ready=False, reason="missing raw"),
            "2026-06-16": _dataset_status(ready=False, reason="should not scan"),
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "raw_stk_mins_ready_for_trade_date",
            side_effect=lambda _instance, trade_date: raw_statuses[trade_date],
        ) as raw_ready_mock, patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
            return_value=_stock_basic_status(ready=True),
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-15")
        self.assertEqual(
            request.run_key,
            "stock_mins_raw_update_from_prod:2026-06-15",
        )
        self.assertEqual(
            [call.args[1] for call in raw_ready_mock.call_args_list],
            ["2026-06-13", "2026-06-15"],
        )
        stock_basic_ready_mock.assert_called_once_with(context.instance, "2026-06-15")

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(cursor["details"]["selected_trade_date"], "2026-06-15")
        self.assertEqual(continuity["ready_through_trade_date"], "2026-06-13")
        self.assertEqual(continuity["next_actionable_trade_date"], "2026-06-15")

    def test_raw_sensor_blocks_materialized_check_problem_without_later_date(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        raw_statuses = {
            "2026-06-13": _dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            "2026-06-15": _dataset_status(
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="blocking checks failed",
            ),
            "2026-06-16": _dataset_status(ready=False, reason="should not scan"),
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "raw_stk_mins_ready_for_trade_date",
            side_effect=lambda _instance, trade_date: raw_statuses[trade_date],
        ) as raw_ready_mock, patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("暂不自动重跑", _skip_message(result))
        self.assertEqual(
            [call.args[1] for call in raw_ready_mock.call_args_list],
            ["2026-06-13", "2026-06-15"],
        )
        stock_basic_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["blocked_reason"], "materialized_check_problem")

    def test_raw_sensor_records_continuity_before_source_window(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15"))
        raw_statuses = {
            "2026-06-13": _dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            "2026-06-15": _dataset_status(ready=False, reason="missing raw"),
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _BeforeRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "raw_stk_mins_ready_for_trade_date",
            side_effect=lambda _instance, trade_date: raw_statuses[trade_date],
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("19:30", _skip_message(result))
        stock_basic_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertFalse(cursor["details"]["source_window_started"])
        self.assertEqual(continuity["first_not_ready_trade_date"], "2026-06-15")

    def test_raw_sensor_skips_when_stock_basic_not_ready_for_selected_date(
        self,
    ) -> None:
        context = _Context(("2026-06-15",))

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-15",),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "raw_stk_mins_ready_for_trade_date",
            return_value=_dataset_status(ready=False, reason="missing raw"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
            return_value=_stock_basic_status(ready=False),
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("股票基础信息", _skip_message(result))
        stock_basic_ready_mock.assert_called_once_with(context.instance, "2026-06-15")

    def test_raw_sensor_skips_when_continuity_window_is_all_ready(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        with patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor.datetime",
            _AfterRawWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "_load_stock_mins_raw_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "raw_stk_mins_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_raw_sensor."
            "stock_basic_ready_for_trade_date",
        ) as stock_basic_ready_mock:
            result = stock_mins_raw_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("continuity 窗口内分区已经生成完成", _skip_message(result))
        stock_basic_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(cursor["target_date"], "2026-06-16")
        self.assertEqual(continuity["ready_through_trade_date"], "2026-06-16")

    def test_silver_trade_day_sensor_skips_raw_partition_gap_before_readiness_scan(
        self,
    ) -> None:
        context = _Context(
            partitions_by_name={
                cn_a_stock_mins_trade_days.name: ("2026-06-13", "2026-06-16"),
                cn_a_stock_mins_silver_trade_days.name: ("2026-06-13",),
            }
        )
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor.datetime",
            _AfterSilverPartitionWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "raw_stk_mins_ready_for_trade_date",
        ) as raw_ready_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "stock_daily_ready_for_trade_date",
        ) as stock_daily_ready_mock:
            result = stock_mins_silver_trade_day_sensor._raw_fn(context)

        self.assertEqual(result.dynamic_partitions_requests, [])
        self.assertIn("raw 交易日分区存在缺口", _skip_message(result))
        raw_ready_mock.assert_not_called()
        stock_daily_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        raw_continuity = cursor["details"]["raw_continuity_status"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(raw_continuity["first_missing_registered_date"], "2026-06-15")

    def test_silver_trade_day_sensor_registers_first_missing_silver_partition(
        self,
    ) -> None:
        context = _Context(
            partitions_by_name={
                cn_a_stock_mins_trade_days.name: (
                    "2026-06-13",
                    "2026-06-15",
                    "2026-06-16",
                ),
                cn_a_stock_mins_silver_trade_days.name: (
                    "2026-06-13",
                    "2026-06-16",
                ),
            }
        )
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor.datetime",
            _AfterSilverPartitionWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "raw_stk_mins_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
        ) as raw_ready_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "stock_daily_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "suspend_d_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_suspend_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "silver_stock_identity_map_ready_for_trade_date",
            return_value=_asset_readiness_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "silver_namechange_ready_for_trade_date",
            return_value=_asset_readiness_status(
                ready=True,
                asset_key="silver_namechange",
            ),
        ):
            result = stock_mins_silver_trade_day_sensor._raw_fn(context)

        self.assertEqual(len(result.dynamic_partitions_requests), 1)
        self.assertEqual(raw_ready_mock.call_args.args[1], "2026-06-15")

        cursor = json.loads(result.cursor)
        silver_continuity = cursor["details"]["silver_continuity_status"]
        self.assertEqual(cursor["details"]["selected_keys"], ["2026-06-15"])
        self.assertEqual(
            silver_continuity["first_missing_registered_date"],
            "2026-06-15",
        )

    def test_silver_trade_day_sensor_records_continuity_before_window(self) -> None:
        context = _Context(
            partitions_by_name={
                cn_a_stock_mins_trade_days.name: ("2026-06-13", "2026-06-15"),
                cn_a_stock_mins_silver_trade_days.name: ("2026-06-13",),
            }
        )
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor.datetime",
            _BeforeSilverPartitionWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_trade_day_sensor."
            "raw_stk_mins_ready_for_trade_date",
        ) as raw_ready_mock:
            result = stock_mins_silver_trade_day_sensor._raw_fn(context)

        self.assertEqual(result.dynamic_partitions_requests, [])
        self.assertIn("19:45", _skip_message(result))
        raw_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        silver_continuity = cursor["details"]["silver_continuity_status"]
        self.assertFalse(cursor["details"]["register_window_started"])
        self.assertEqual(
            silver_continuity["first_missing_registered_date"],
            "2026-06-15",
        )

    def test_silver_sensor_submits_first_not_ready_date_not_latest_registered(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        silver_statuses = {
            "2026-06-13": _dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stk_mins_1m",
            ),
            "2026-06-15": _dataset_status(
                ready=False,
                reason="missing silver",
                asset_key="silver_stk_mins_1m",
            ),
            "2026-06-16": _dataset_status(
                ready=False,
                reason="should not scan",
                asset_key="silver_stk_mins_1m",
            ),
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stk_mins_ready_for_trade_date",
            side_effect=lambda _instance, trade_date: silver_statuses[trade_date],
        ) as silver_ready_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "raw_stk_mins_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
        ) as raw_ready_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "stock_daily_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "suspend_d_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_suspend_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stock_identity_map_ready_for_trade_date",
            return_value=_asset_readiness_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_namechange_ready_for_trade_date",
            return_value=_asset_readiness_status(
                ready=True,
                asset_key="silver_namechange",
            ),
        ):
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-15")
        self.assertEqual(request.run_key, "stock_mins_silver_update:2026-06-15")
        self.assertEqual(
            [call.args[1] for call in silver_ready_mock.call_args_list],
            ["2026-06-13", "2026-06-15"],
        )
        raw_ready_mock.assert_called_once_with(context.instance, "2026-06-15")

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["next_actionable_trade_date"], "2026-06-15")

    def test_silver_sensor_skips_missing_silver_partition_without_readiness_scan(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-16"))
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stk_mins_ready_for_trade_date",
        ) as silver_ready_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("silver 交易日分区存在缺口", _skip_message(result))
        silver_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")

    def test_silver_sensor_blocks_materialized_check_problem_without_later_date(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        silver_statuses = {
            "2026-06-13": _dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stk_mins_1m",
            ),
            "2026-06-15": _dataset_status(
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="blocking checks failed",
                asset_key="silver_stk_mins_1m",
            ),
            "2026-06-16": _dataset_status(
                ready=False,
                reason="should not scan",
                asset_key="silver_stk_mins_1m",
            ),
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stk_mins_ready_for_trade_date",
            side_effect=lambda _instance, trade_date: silver_statuses[trade_date],
        ) as silver_ready_mock, patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "raw_stk_mins_ready_for_trade_date",
        ) as raw_ready_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("暂不自动重跑", _skip_message(result))
        self.assertEqual(
            [call.args[1] for call in silver_ready_mock.call_args_list],
            ["2026-06-13", "2026-06-15"],
        )
        raw_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(continuity["blocked_reason"], "materialized_check_problem")

    def test_silver_sensor_skips_when_selected_date_upstream_not_ready(self) -> None:
        context = _Context(("2026-06-15",))
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-15",),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stk_mins_ready_for_trade_date",
            return_value=_dataset_status(
                ready=False,
                reason="missing silver",
                asset_key="silver_stk_mins_1m",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "raw_stk_mins_ready_for_trade_date",
            return_value=_dataset_status(ready=False, reason="raw missing"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "stock_daily_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "suspend_d_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stock_suspend_daily",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stock_identity_map_ready_for_trade_date",
            return_value=_asset_readiness_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_namechange_ready_for_trade_date",
            return_value=_asset_readiness_status(
                ready=True,
                asset_key="silver_namechange",
            ),
        ):
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("raw 五频度", _skip_message(result))

    def test_silver_sensor_records_continuity_before_window(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15"))
        silver_statuses = {
            "2026-06-13": _dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stk_mins_1m",
            ),
            "2026-06-15": _dataset_status(
                ready=False,
                reason="missing silver",
                asset_key="silver_stk_mins_1m",
            ),
        }

        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _BeforeSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stk_mins_ready_for_trade_date",
            side_effect=lambda _instance, trade_date: silver_statuses[trade_date],
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "raw_stk_mins_ready_for_trade_date",
        ) as raw_ready_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("19:50", _skip_message(result))
        raw_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertFalse(cursor["details"]["run_window_started"])
        self.assertEqual(continuity["first_not_ready_trade_date"], "2026-06-15")

    def test_silver_sensor_skips_when_continuity_window_is_all_ready(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))
        with patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor.datetime",
            _AfterSilverRunWindowDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "_load_stock_mins_silver_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "silver_stk_mins_ready_for_trade_date",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="silver_stk_mins_1m",
            ),
        ), patch(
            "orchestrator.defs.sensors.stock_mins_silver_sensor."
            "raw_stk_mins_ready_for_trade_date",
        ) as raw_ready_mock:
            result = stock_mins_silver_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("continuity 窗口内分区已经 ready", _skip_message(result))
        raw_ready_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(continuity["ready_through_trade_date"], "2026-06-16")

    def test_qfq_daily_sensor_skips_missing_silver_partition_without_readiness_scan(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-16"))
        with patch.object(
            qfq_daily_module,
            "datetime",
            _AfterQfqDailyWindowDateTime,
        ), patch.object(
            qfq_daily_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_daily_module,
            "partition_dataset_readiness_status_from_latest_checks",
        ) as readiness_mock:
            result = stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("silver 交易日分区存在缺口", _skip_message(result))
        readiness_mock.assert_not_called()

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["first_missing_registered_date"], "2026-06-15")

    def test_qfq_daily_sensor_submits_first_not_ready_date_not_latest_registered(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        def fake_readiness(_instance, specs, *, partition_key):
            if specs is qfq_daily_module.SILVER_STK_MINS_READINESS_SPECS:
                return _dataset_status(
                    ready=True,
                    materialized=True,
                    checks_passed=True,
                    reason="ready",
                    asset_key="silver_stk_mins_1m",
                )
            if specs is qfq_daily_module.ADJ_FACTOR_READINESS_SPECS:
                return _dataset_status(
                    ready=True,
                    materialized=True,
                    checks_passed=True,
                    reason="ready",
                    asset_key="silver_adj_factor",
                )
            return _dataset_status(
                ready=partition_key == "2026-06-13",
                materialized=partition_key == "2026-06-13",
                checks_passed=partition_key == "2026-06-13",
                reason="ready" if partition_key == "2026-06-13" else "gold missing",
                asset_key="gold_stk_mins_qfq_1m",
            )

        with patch.object(
            qfq_daily_module,
            "datetime",
            _AfterQfqDailyWindowDateTime,
        ), patch.object(
            qfq_daily_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_daily_module,
            "partition_dataset_readiness_status_from_latest_checks",
            side_effect=fake_readiness,
        ) as readiness_mock:
            result = stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.partition_key, "2026-06-15")
        self.assertEqual(request.run_key, "stock_mins_qfq_daily_update:2026-06-15")
        self.assertEqual(
            [call.kwargs["partition_key"] for call in readiness_mock.call_args_list],
            [
                "2026-06-13",
                "2026-06-13",
                "2026-06-13",
                "2026-06-15",
                "2026-06-15",
                "2026-06-15",
            ],
        )

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["next_actionable_trade_date"], "2026-06-15")

    def test_qfq_daily_sensor_blocks_materialized_check_problem_without_later_date(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        def fake_readiness(_instance, specs, *, partition_key):
            if specs is qfq_daily_module.SILVER_STK_MINS_READINESS_SPECS:
                return _dataset_status(
                    ready=True,
                    materialized=True,
                    checks_passed=True,
                    reason="ready",
                    asset_key="silver_stk_mins_1m",
                )
            if specs is qfq_daily_module.ADJ_FACTOR_READINESS_SPECS:
                return _dataset_status(
                    ready=True,
                    materialized=True,
                    checks_passed=True,
                    reason="ready",
                    asset_key="silver_adj_factor",
                )
            return _dataset_status(
                ready=partition_key == "2026-06-13",
                materialized=True,
                checks_passed=partition_key == "2026-06-13",
                reason="ready" if partition_key == "2026-06-13" else "gold failed",
                asset_key="gold_stk_mins_qfq_1m",
            )

        with patch.object(
            qfq_daily_module,
            "datetime",
            _AfterQfqDailyWindowDateTime,
        ), patch.object(
            qfq_daily_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_daily_module,
            "partition_dataset_readiness_status_from_latest_checks",
            side_effect=fake_readiness,
        ) as readiness_mock:
            result = stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("暂不自动重跑", _skip_message(result))
        self.assertEqual(
            [call.kwargs["partition_key"] for call in readiness_mock.call_args_list],
            [
                "2026-06-13",
                "2026-06-13",
                "2026-06-13",
                "2026-06-15",
                "2026-06-15",
                "2026-06-15",
            ],
        )

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(continuity["blocked_reason"], "materialized_check_problem")

    def test_qfq_factor_repair_sensor_skips_when_gold_not_ready_without_later_date(
        self,
    ) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        def fake_gold_status(_instance, _specs, *, partition_key):
            return _dataset_status(
                ready=partition_key == "2026-06-13",
                materialized=partition_key == "2026-06-13",
                checks_passed=partition_key == "2026-06-13",
                reason="ready" if partition_key == "2026-06-13" else "gold missing",
                asset_key="gold_stk_mins_qfq_1m",
            )

        with patch.object(
            qfq_factor_repair_module,
            "datetime",
            _AfterQfqFactorRepairWindowDateTime,
        ), patch.object(
            qfq_factor_repair_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_factor_repair_module,
            "partition_dataset_readiness_status_from_latest_checks",
            side_effect=fake_gold_status,
        ) as gold_status_mock, patch.object(
            qfq_factor_repair_module,
            "gold_stk_mins_qfq_factor_repair_status",
            return_value=_qfq_factor_repair_status(
                trade_date="2026-06-13",
                ready=True,
            ),
        ) as repair_status_mock:
            result = stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("尚未全部 ready", _skip_message(result))
        self.assertEqual(
            [call.kwargs["partition_key"] for call in gold_status_mock.call_args_list],
            ["2026-06-13", "2026-06-15"],
        )
        repair_status_mock.assert_called_once_with(context.instance, "2026-06-13")

    def test_qfq_factor_repair_sensor_submits_first_not_completed_date(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        with patch.object(
            qfq_factor_repair_module,
            "datetime",
            _AfterQfqFactorRepairWindowDateTime,
        ), patch.object(
            qfq_factor_repair_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_factor_repair_module,
            "partition_dataset_readiness_status_from_latest_checks",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="gold_stk_mins_qfq_1m",
            ),
        ), patch.object(
            qfq_factor_repair_module,
            "gold_stk_mins_qfq_factor_repair_status",
            side_effect=lambda _instance, trade_date: _qfq_factor_repair_status(
                trade_date=trade_date,
                ready=trade_date == "2026-06-13",
                reason="ready" if trade_date == "2026-06-13" else "repair missing",
            ),
        ) as repair_status_mock:
            result = stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        request = result.run_requests[0]
        self.assertEqual(request.run_key, "stock_mins_qfq_factor_repair:2026-06-15")
        self.assertEqual(
            request.run_config["ops"]["stock_mins_qfq_factor_repair_op"]["config"],
            {"trade_date": "2026-06-15"},
        )
        self.assertEqual(
            [call.args[1] for call in repair_status_mock.call_args_list],
            ["2026-06-13", "2026-06-15"],
        )

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertEqual(cursor["target_date"], "2026-06-15")
        self.assertEqual(continuity["next_actionable_trade_date"], "2026-06-15")

    def test_qfq_factor_repair_sensor_advances_after_completed_repair(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15", "2026-06-16"))

        with patch.object(
            qfq_factor_repair_module,
            "datetime",
            _AfterQfqFactorRepairWindowDateTime,
        ), patch.object(
            qfq_factor_repair_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15", "2026-06-16"),
        ), patch.object(
            qfq_factor_repair_module,
            "partition_dataset_readiness_status_from_latest_checks",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="gold_stk_mins_qfq_1m",
            ),
        ), patch.object(
            qfq_factor_repair_module,
            "gold_stk_mins_qfq_factor_repair_status",
            side_effect=lambda _instance, trade_date: _qfq_factor_repair_status(
                trade_date=trade_date,
                ready=trade_date != "2026-06-16",
                reason="ready" if trade_date != "2026-06-16" else "repair missing",
            ),
        ):
            result = stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(
            result.run_requests[0].run_key,
            "stock_mins_qfq_factor_repair:2026-06-16",
        )

    def test_qfq_daily_sensor_records_continuity_before_window(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15"))

        def fake_readiness(_instance, specs, *, partition_key):
            if specs is qfq_daily_module.SILVER_STK_MINS_READINESS_SPECS:
                return _dataset_status(
                    ready=True,
                    materialized=True,
                    checks_passed=True,
                    reason="ready",
                    asset_key="silver_stk_mins_1m",
                )
            if specs is qfq_daily_module.ADJ_FACTOR_READINESS_SPECS:
                return _dataset_status(
                    ready=True,
                    materialized=True,
                    checks_passed=True,
                    reason="ready",
                    asset_key="silver_adj_factor",
                )
            return _dataset_status(
                ready=partition_key == "2026-06-13",
                materialized=partition_key == "2026-06-13",
                checks_passed=partition_key == "2026-06-13",
                reason="ready" if partition_key == "2026-06-13" else "gold missing",
                asset_key="gold_stk_mins_qfq_1m",
            )

        with patch.object(
            qfq_daily_module,
            "datetime",
            _BeforeQfqDailyWindowDateTime,
        ), patch.object(
            qfq_daily_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15"),
        ), patch.object(
            qfq_daily_module,
            "partition_dataset_readiness_status_from_latest_checks",
            side_effect=fake_readiness,
        ):
            result = stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("20:10", _skip_message(result))

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertFalse(cursor["details"]["run_window_started"])
        self.assertEqual(continuity["first_not_ready_trade_date"], "2026-06-15")

    def test_qfq_factor_repair_sensor_records_continuity_before_window(self) -> None:
        context = _Context(("2026-06-13", "2026-06-15"))

        with patch.object(
            qfq_factor_repair_module,
            "datetime",
            _BeforeQfqFactorRepairWindowDateTime,
        ), patch.object(
            qfq_factor_repair_module,
            "_load_stock_mins_qfq_expected_trade_dates",
            return_value=("2026-06-13", "2026-06-15"),
        ), patch.object(
            qfq_factor_repair_module,
            "partition_dataset_readiness_status_from_latest_checks",
            return_value=_dataset_status(
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
                asset_key="gold_stk_mins_qfq_1m",
            ),
        ), patch.object(
            qfq_factor_repair_module,
            "gold_stk_mins_qfq_factor_repair_status",
            side_effect=lambda _instance, trade_date: _qfq_factor_repair_status(
                trade_date=trade_date,
                ready=trade_date == "2026-06-13",
                reason="ready" if trade_date == "2026-06-13" else "repair missing",
            ),
        ):
            result = stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("20:40", _skip_message(result))

        cursor = json.loads(result.cursor)
        continuity = cursor["details"]["continuity_status"]
        self.assertFalse(cursor["details"]["run_window_started"])
        self.assertEqual(continuity["first_not_ready_trade_date"], "2026-06-15")


if __name__ == "__main__":
    unittest.main()
