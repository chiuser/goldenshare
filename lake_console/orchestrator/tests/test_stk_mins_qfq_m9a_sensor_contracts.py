import json
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import orchestrator.defs.sensors.stock_mins_qfq_daily_sensor as daily_sensor_module
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    DatasetReadinessStatus,
)
from orchestrator.defs.sensors.stock_mins_qfq_daily_sensor import (
    STOCK_MINS_QFQ_DAILY_RUN_START,
    STOCK_MINS_QFQ_DAILY_SENSOR_JOB_NAME,
    _cursor_payload as build_stock_mins_qfq_daily_sensor_cursor,
)
from orchestrator.defs.sensors.stock_mins_qfq_daily_sensor import (
    _has_materialized_check_problem,
    _latest_registered_silver_trade_date,
    _run_request_for_trade_date,
    build_stock_mins_qfq_daily_update_decision,
)


PARTITION_KEY = "2026-05-29"
EVALUATED_AT = datetime(2026, 5, 29, 23, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
BEFORE_WINDOW = datetime(2026, 5, 29, 22, 55, tzinfo=ZoneInfo("Asia/Shanghai"))


def _asset_status(
    asset_key: str,
    *,
    ready: bool = True,
    materialized: bool = True,
    checks_passed: bool = True,
    freshness_passed: bool = True,
    reason: str = "ready",
) -> AssetReadinessStatus:
    return AssetReadinessStatus(
        asset_key=asset_key,
        partition_key=PARTITION_KEY,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=freshness_passed,
        materialization_storage_id=1 if materialized else None,
        materialization_date="2026-05-29" if materialized else None,
        missing_check_names=() if checks_passed else ("example_check",),
        failed_check_names=() if checks_passed else ("example_check",),
        reason=reason,
    )


def _dataset_status(
    asset_keys: tuple[str, ...],
    *,
    ready: bool = True,
    materialized: bool = True,
    checks_passed: bool = True,
    reason: str = "ready",
) -> DatasetReadinessStatus:
    statuses = tuple(
        _asset_status(
            asset_key,
            ready=ready,
            materialized=materialized,
            checks_passed=checks_passed,
            reason=reason,
        )
        for asset_key in asset_keys
    )
    return DatasetReadinessStatus(
        ready=all(asset_status.ready for asset_status in statuses),
        statuses=statuses,
    )


class _FakeSensorInstance:
    def __init__(self, trade_days: tuple[str, ...] = (PARTITION_KEY,)):
        self.trade_days = trade_days

    def get_dynamic_partitions(self, partition_set_name: str):
        return list(self.trade_days)


class _FakeSensorContext:
    def __init__(
        self,
        *,
        cursor: str | None = None,
        trade_days: tuple[str, ...] = (PARTITION_KEY,),
    ):
        self.cursor = cursor
        self.instance = _FakeSensorInstance(trade_days)


class StkMinsQfqM9ASensorContractTests(unittest.TestCase):
    def test_latest_registered_silver_trade_date_uses_latest_not_after_today(self) -> None:
        self.assertEqual(
            _latest_registered_silver_trade_date(
                ("2026-05-28", "2026-05-29", "2026-05-30"),
                EVALUATED_AT,
            ),
            "2026-05-29",
        )
        self.assertIsNone(
            _latest_registered_silver_trade_date(("2026-05-30",), EVALUATED_AT)
        )

    def test_decision_skips_before_window_and_without_partition(self) -> None:
        no_partition = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=None,
            run_window_started=True,
        )
        before_window = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=False,
            silver_ready=True,
            adj_factor_ready=True,
        )

        self.assertIsNone(no_partition.selected_trade_date)
        self.assertIn("没有注册", no_partition.reason)
        self.assertIsNone(before_window.selected_trade_date)
        self.assertIn("23:00", before_window.reason)

    def test_decision_skips_when_silver_or_adj_factor_is_not_ready(self) -> None:
        silver_blocked = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=False,
            adj_factor_ready=True,
        )
        adj_blocked = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            adj_factor_ready=False,
        )

        self.assertIsNone(silver_blocked.selected_trade_date)
        self.assertIn("silver 五频度", silver_blocked.reason)
        self.assertIsNone(adj_blocked.selected_trade_date)
        self.assertIn("复权因子", adj_blocked.reason)

    def test_decision_skips_when_gold_is_ready_or_has_failed_checks(self) -> None:
        ready_decision = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            adj_factor_ready=True,
            gold_ready=True,
        )
        failed_decision = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            adj_factor_ready=True,
            gold_has_materialized_check_problem=True,
        )

        self.assertIsNone(ready_decision.selected_trade_date)
        self.assertIn("已经 ready", ready_decision.reason)
        self.assertIsNone(failed_decision.selected_trade_date)
        self.assertIn("blocking checks 未全绿", failed_decision.reason)

    def test_decision_requests_run_when_all_gates_pass_and_gold_is_missing(self) -> None:
        decision = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            adj_factor_ready=True,
            gold_ready=False,
            gold_has_materialized_check_problem=False,
        )

        self.assertEqual(decision.selected_trade_date, PARTITION_KEY)
        self.assertIn("提交七频度 qfq 更新", decision.reason)

        request = _run_request_for_trade_date(PARTITION_KEY)
        self.assertEqual(request.partition_key, PARTITION_KEY)
        self.assertEqual(
            request.run_key,
            f"stock_mins_qfq_daily_update:{PARTITION_KEY}",
        )
        self.assertEqual(request.tags, {})
        self.assertEqual(request.run_config, {})

    def test_materialized_check_problem_requires_materialized_failed_status(self) -> None:
        self.assertTrue(
            _has_materialized_check_problem(
                _dataset_status(
                    ("gold_stk_mins_qfq_1m",),
                    ready=False,
                    materialized=True,
                    checks_passed=False,
                    reason="failed",
                )
            )
        )
        self.assertFalse(
            _has_materialized_check_problem(
                _dataset_status(
                    ("gold_stk_mins_qfq_1m",),
                    ready=False,
                    materialized=False,
                    checks_passed=False,
                    reason="missing",
                )
            )
        )

    def test_cursor_contract_for_selected_qfq_run(self) -> None:
        decision = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            adj_factor_ready=True,
        )
        cursor = json.loads(
            build_stock_mins_qfq_daily_sensor_cursor(
                decision=decision,
                evaluated_at=EVALUATED_AT,
                registered_trade_day_count=3014,
                silver_status=_dataset_status(("silver_stk_mins_1m",)),
                adj_factor_status=_dataset_status(("silver_adj_factor",)),
                gold_status=_dataset_status(
                    ("gold_stk_mins_qfq_1m",),
                    ready=False,
                    materialized=False,
                    checks_passed=False,
                    reason="missing",
                ),
            )
        )

        self.assertEqual(cursor["decision"], "request_runs")
        self.assertEqual(cursor["target_date"], PARTITION_KEY)
        self.assertEqual(cursor["selected_count"], 1)
        self.assertEqual(cursor["blocked_count"], 0)
        self.assertEqual(cursor["sample_keys"], [PARTITION_KEY])
        self.assertEqual(
            cursor["details"]["partition_set"],
            "cn_a_stock_mins_silver_trade_days",
        )
        self.assertEqual(
            cursor["details"]["job_name"],
            STOCK_MINS_QFQ_DAILY_SENSOR_JOB_NAME,
        )
        self.assertTrue(cursor["details"]["run_window_started"])
        self.assertIsNotNone(cursor["details"]["silver_status"])
        self.assertIsNotNone(cursor["details"]["adj_factor_status"])
        self.assertIsNotNone(cursor["details"]["gold_status"])
        self.assertEqual(STOCK_MINS_QFQ_DAILY_RUN_START.isoformat(), "23:00:00")
        self.assertEqual(BEFORE_WINDOW.time().isoformat(), "22:55:00")

    def test_cursor_contract_for_ready_skip_is_not_blocked(self) -> None:
        decision = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            adj_factor_ready=True,
            gold_ready=True,
        )
        cursor = json.loads(
            build_stock_mins_qfq_daily_sensor_cursor(
                decision=decision,
                evaluated_at=EVALUATED_AT,
                registered_trade_day_count=3014,
                gold_status=_dataset_status(("gold_stk_mins_qfq_1m",), ready=True),
            )
        )

        self.assertEqual(cursor["decision"], "skip")
        self.assertEqual(cursor["blocked_count"], 0)
        self.assertIsNone(cursor["details"]["selected_trade_date"])

    def test_sensor_skips_before_window_without_readiness_lookup(self) -> None:
        context = _FakeSensorContext()
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                side_effect=AssertionError("readiness must not run before 23:00"),
            ),
        ):
            mock_datetime.now.return_value = BEFORE_WINDOW
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertIn("23:00", result.skip_reason.skip_message)

    def test_sensor_cursor_fast_path_skips_without_readiness_lookup(self) -> None:
        selected_decision = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            adj_factor_ready=True,
        )
        submitted_cursor = build_stock_mins_qfq_daily_sensor_cursor(
            decision=selected_decision,
            evaluated_at=EVALUATED_AT,
            registered_trade_day_count=3014,
            already_submitted_for_trade_date=True,
        )
        context = _FakeSensorContext(cursor=submitted_cursor)
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                side_effect=AssertionError("readiness must not run after submission"),
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(context)

        cursor = json.loads(result.cursor)
        self.assertIn("已经提交过", result.skip_reason.skip_message)
        self.assertTrue(cursor["details"]["already_submitted_for_trade_date"])

    def test_sensor_checks_readiness_in_order_and_stops_when_silver_not_ready(
        self,
    ) -> None:
        calls = []

        def fake_readiness(instance, specs, *, partition_key):
            calls.append(specs)
            return _dataset_status(
                ("silver_stk_mins_1m",),
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="silver blocked",
            )

        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                side_effect=fake_readiness,
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertIn("silver 五频度", result.skip_reason.skip_message)
        self.assertEqual(calls, [daily_sensor_module.SILVER_STK_MINS_READINESS_SPECS])

    def test_sensor_submits_daily_run_when_upstream_ready_and_gold_missing(
        self,
    ) -> None:
        statuses = [
            _dataset_status(("silver_stk_mins_1m",), ready=True),
            _dataset_status(("silver_adj_factor",), ready=True),
            _dataset_status(
                ("gold_stk_mins_qfq_1m",),
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="gold missing",
            ),
        ]

        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                side_effect=lambda instance, specs, *, partition_key: statuses.pop(0),
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, PARTITION_KEY)
        self.assertTrue(json.loads(result.cursor)["details"]["already_submitted_for_trade_date"])

    def test_sensor_skips_when_gold_materialized_checks_are_not_green(self) -> None:
        statuses = [
            _dataset_status(("silver_stk_mins_1m",), ready=True),
            _dataset_status(("silver_adj_factor",), ready=True),
            _dataset_status(
                ("gold_stk_mins_qfq_1m",),
                ready=False,
                materialized=True,
                checks_passed=False,
                reason="gold failed",
            ),
        ]

        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                side_effect=lambda instance, specs, *, partition_key: statuses.pop(0),
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", result.skip_reason.skip_message)


if __name__ == "__main__":
    unittest.main()
