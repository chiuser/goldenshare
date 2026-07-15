import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import duckdb
import orchestrator.defs.sensors.stock_mins_qfq_factor_repair_sensor as repair_sensor_module
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.checks.stk_mins_checks import (
    GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    DatasetReadinessStatus,
)
from orchestrator.defs.sensors.stock_mins_qfq_factor_repair_sensor import (
    STOCK_MINS_QFQ_FACTOR_REPAIR_RUN_START,
    STOCK_MINS_QFQ_FACTOR_REPAIR_SENSOR_JOB_NAME,
    _cursor_payload as build_stock_mins_qfq_factor_repair_sensor_cursor,
)
from orchestrator.defs.sensors.stock_mins_qfq_factor_repair_sensor import (
    _has_materialized_check_problem,
    _run_request_for_trade_date,
    build_stock_mins_qfq_factor_repair_decision,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)


PARTITION_KEY = "2026-05-29"
EVALUATED_AT = datetime(2026, 5, 29, 20, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
BEFORE_WINDOW = datetime(2026, 5, 29, 20, 35, tzinfo=ZoneInfo("Asia/Shanghai"))


def _asset_status(
    asset_key: str,
    *,
    ready: bool = True,
    materialized: bool = True,
    checks_passed: bool = True,
    reason: str = "ready",
) -> AssetReadinessStatus:
    return AssetReadinessStatus(
        asset_key=asset_key,
        partition_key=PARTITION_KEY,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=True,
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
        self.resources = SimpleNamespace(
            lake_root=_FakeLakeRoot(),
            duckdb=_FakeDuckDBResource(),
        )


class _FakeLakeRoot:
    def root(self) -> Path:
        return Path("/tmp/goldenshare-test-lake-root")


class _FakeDuckDBResource:
    @contextmanager
    def connect(self):
        with duckdb.connect(":memory:") as connection:
            yield connection


def _gold_date_status(
    *,
    ready: bool,
    materialized: bool = True,
    checks_passed: bool = True,
    reason: str = "ready",
) -> StkMinsDateReadiness:
    return StkMinsDateReadiness(
        trade_date=PARTITION_KEY,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason,
        failed_check_names=() if ready else ("gold_stk_mins_qfq_file_exists",),
        missing_file_paths=(),
        expected_file_count=7,
        existing_file_count=7 if materialized else 0,
        checked_row_count=7 if materialized else 0,
        failed_row_count=0 if ready else 1,
    )


def _gold_batch_status(status: StkMinsDateReadiness) -> StkMinsBatchReadiness:
    return StkMinsBatchReadiness(
        dataset="gold_stk_mins_qfq",
        expected_start_date=PARTITION_KEY,
        expected_end_date=PARTITION_KEY,
        expected_count=1,
        freq_count=7,
        elapsed_ms=1.0,
        statuses_by_trade_date={PARTITION_KEY: status},
    )


@contextmanager
def _patched_gold_batch_readiness(
    status: StkMinsDateReadiness | None = None,
):
    with patch.object(
        repair_sensor_module,
        "batch_gold_stk_mins_qfq_lake_readiness",
        return_value=_gold_batch_status(status or _gold_date_status(ready=True)),
    ):
        yield


def _legacy_submitted_cursor(
    *,
    target_date: str | None = PARTITION_KEY,
    decision: SensorCursorDecision = SensorCursorDecision.REQUEST_RUNS,
    selected_count: int = 1,
    sample_keys: tuple[str, ...] = (),
) -> str:
    return build_sensor_cursor(
        evaluated_at=EVALUATED_AT,
        decision=decision,
        target_date=target_date,
        selected_count=selected_count,
        sample_keys=sample_keys,
    )


def _repair_status(*, ready: bool, reason: str = "ready") -> GoldStkMinsQfqFactorRepairStatus:
    return GoldStkMinsQfqFactorRepairStatus(
        ready=ready,
        trade_date=PARTITION_KEY,
        reason=reason,
        upstream_batch_id=f"qfq_factor_repair:{PARTITION_KEY}:digest",
    )


class StkMinsQfqM9CSensorContractTests(unittest.TestCase):
    def test_decision_skips_before_window_and_without_partition(self) -> None:
        no_partition = build_stock_mins_qfq_factor_repair_decision(
            target_trade_date=None,
            run_window_started=True,
        )
        before_window = build_stock_mins_qfq_factor_repair_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=False,
            gold_ready=True,
        )

        self.assertIsNone(no_partition.selected_trade_date)
        self.assertIn("没有注册", no_partition.reason)
        self.assertIsNone(before_window.selected_trade_date)
        self.assertIn("20:40", before_window.reason)

    def test_decision_requires_gold_ready_and_skips_failed_gold_checks(self) -> None:
        not_ready = build_stock_mins_qfq_factor_repair_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            gold_ready=False,
        )
        failed_gold = build_stock_mins_qfq_factor_repair_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            gold_ready=False,
            gold_has_materialized_check_problem=True,
        )

        self.assertIsNone(not_ready.selected_trade_date)
        self.assertIn("尚未全部 ready", not_ready.reason)
        self.assertIsNone(failed_gold.selected_trade_date)
        self.assertIn("blocking checks 未全绿", failed_gold.reason)

    def test_decision_requests_run_when_gold_is_ready(self) -> None:
        decision = build_stock_mins_qfq_factor_repair_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            gold_ready=True,
        )

        self.assertEqual(decision.selected_trade_date, PARTITION_KEY)
        self.assertIn("提交 factor repair", decision.reason)

        request = _run_request_for_trade_date(PARTITION_KEY)
        self.assertIsNone(request.partition_key)
        self.assertEqual(
            request.run_key,
            f"stock_mins_qfq_factor_repair:{PARTITION_KEY}",
        )
        self.assertEqual(request.tags, {})
        self.assertEqual(
            request.run_config,
            {
                "ops": {
                    "stock_mins_qfq_factor_repair_op": {
                        "config": {"trade_date": PARTITION_KEY}
                    }
                }
            },
        )

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

    def test_cursor_contract_for_selected_repair_run(self) -> None:
        decision = build_stock_mins_qfq_factor_repair_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            gold_ready=True,
        )
        cursor_text = build_stock_mins_qfq_factor_repair_sensor_cursor(
            decision=decision,
            evaluated_at=EVALUATED_AT,
            registered_trade_day_count=3014,
            gold_status=_dataset_status(("gold_stk_mins_qfq_1m",)),
        )
        cursor = json.loads(cursor_text)

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
            STOCK_MINS_QFQ_FACTOR_REPAIR_SENSOR_JOB_NAME,
        )
        self.assertTrue(cursor["details"]["evidence"]["run_window_started"])
        self.assertLess(len(cursor_text), 3072)
        self.assertIn("已触发", cursor["details"]["summary"])
        self.assertIn(
            "stock_mins_qfq_factor_repair_job",
            cursor["details"]["next_action"],
        )
        self.assertIsNotNone(cursor["details"]["gate_statuses"]["gold_stk_mins_qfq"])
        self.assertEqual(
            STOCK_MINS_QFQ_FACTOR_REPAIR_RUN_START.isoformat(),
            "20:40:00",
        )
        for fragment in (
            "status_samples",
            "to_cursor_details",
            "readiness_details",
            "repair_details",
            "sample_rows",
        ):
            self.assertNotIn(fragment, cursor_text)

    def test_sensor_skips_before_window_without_readiness_scan(self) -> None:
        context = _FakeSensorContext()
        with (
            patch.object(repair_sensor_module, "datetime") as mock_datetime,
            patch.object(
                repair_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                side_effect=AssertionError("calendar must not be loaded before window"),
            ),
            patch.object(
                repair_sensor_module,
                "batch_gold_stk_mins_qfq_lake_readiness",
                side_effect=AssertionError("gold qfq batch must not run before window"),
            ),
            patch.object(
                repair_sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                side_effect=AssertionError("repair status must not be read before window"),
            ),
        ):
            mock_datetime.now.return_value = BEFORE_WINDOW
            result = repair_sensor_module.stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        self.assertIn("20:40", result.skip_reason.skip_message)
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["target_date"], None)
        self.assertEqual(cursor["selected_count"], 0)
        self.assertFalse(cursor["details"]["evidence"]["run_window_started"])
        self.assertNotIn("continuity", cursor["details"].get("frontier", {}))
        self.assertNotIn("gold", cursor["details"].get("frontier", {}))
        self.assertNotIn("qfq_factor_repair", cursor["details"].get("gate_statuses", {}))

    def test_sensor_cursor_fast_path_skips_after_frontier_selects_same_target(
        self,
    ) -> None:
        selected_decision = build_stock_mins_qfq_factor_repair_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            gold_ready=True,
        )
        submitted_cursor = build_stock_mins_qfq_factor_repair_sensor_cursor(
            decision=selected_decision,
            evaluated_at=EVALUATED_AT,
            registered_trade_day_count=3014,
            already_submitted_for_trade_date=True,
        )
        context = _FakeSensorContext(cursor=submitted_cursor)

        with (
            patch.object(repair_sensor_module, "datetime") as mock_datetime,
            patch.object(
                repair_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_gold_batch_readiness(),
            patch.object(
                repair_sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                return_value=_repair_status(ready=False, reason="repair missing"),
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = repair_sensor_module.stock_mins_qfq_factor_repair_sensor._raw_fn(context)

        cursor = json.loads(result.cursor)
        self.assertIn("已经提交过", result.skip_reason.skip_message)
        self.assertTrue(
            cursor["details"]["runtime_state"]["already_submitted_for_trade_date"]
        )

    def test_sensor_legacy_selected_count_cursor_fast_path_skips_same_target(
        self,
    ) -> None:
        context = _FakeSensorContext(cursor=_legacy_submitted_cursor())

        with (
            patch.object(repair_sensor_module, "datetime") as mock_datetime,
            patch.object(
                repair_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_gold_batch_readiness(),
            patch.object(
                repair_sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                return_value=_repair_status(ready=False, reason="repair missing"),
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = repair_sensor_module.stock_mins_qfq_factor_repair_sensor._raw_fn(
                context
            )

        self.assertIn("已经提交过", result.skip_reason.skip_message)
        self.assertTrue(
            json.loads(result.cursor)["details"]["runtime_state"][
                "already_submitted_for_trade_date"
            ]
        )

    def test_sensor_legacy_sample_keys_cursor_fast_path_skips_same_target(self) -> None:
        context = _FakeSensorContext(
            cursor=_legacy_submitted_cursor(
                selected_count=0,
                sample_keys=(PARTITION_KEY,),
            )
        )

        with (
            patch.object(repair_sensor_module, "datetime") as mock_datetime,
            patch.object(
                repair_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_gold_batch_readiness(),
            patch.object(
                repair_sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                return_value=_repair_status(ready=False, reason="repair missing"),
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = repair_sensor_module.stock_mins_qfq_factor_repair_sensor._raw_fn(
                context
            )

        self.assertIn("已经提交过", result.skip_reason.skip_message)

    def test_legacy_cursor_negative_cases_do_not_fast_path(self) -> None:
        cases = (
            _legacy_submitted_cursor(decision=SensorCursorDecision.SKIP),
            _legacy_submitted_cursor(selected_count=0),
            _legacy_submitted_cursor(target_date="2026-05-28"),
            "{bad-json",
        )
        for cursor in cases:
            with self.subTest(cursor=cursor):
                self.assertFalse(
                    repair_sensor_module._already_submitted_for_target_date(
                        cursor,
                        PARTITION_KEY,
                    )
                )

    def test_sensor_non_fast_path_cursor_continues_readiness(self) -> None:
        context = _FakeSensorContext(cursor=_legacy_submitted_cursor(selected_count=0))
        with (
            patch.object(repair_sensor_module, "datetime") as mock_datetime,
            patch.object(
                repair_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_gold_batch_readiness(),
            patch.object(
                repair_sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                return_value=_repair_status(ready=False, reason="repair missing"),
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = repair_sensor_module.stock_mins_qfq_factor_repair_sensor._raw_fn(
                context
            )

        self.assertEqual(len(result.run_requests), 1)

    def test_sensor_submits_typed_repair_config_only_when_gold_ready(self) -> None:
        with (
            patch.object(repair_sensor_module, "datetime") as mock_datetime,
            patch.object(
                repair_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_gold_batch_readiness(),
            patch.object(
                repair_sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                return_value=_repair_status(ready=False, reason="repair missing"),
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = repair_sensor_module.stock_mins_qfq_factor_repair_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(
            result.run_requests[0].run_key,
            f"stock_mins_qfq_factor_repair:{PARTITION_KEY}",
        )
        self.assertEqual(
            result.run_requests[0].run_config,
            {
                "ops": {
                    "stock_mins_qfq_factor_repair_op": {
                        "config": {"trade_date": PARTITION_KEY}
                    }
                }
            },
        )
        self.assertTrue(
            json.loads(result.cursor)["details"]["runtime_state"][
                "already_submitted_for_trade_date"
            ]
        )

    def test_sensor_skips_when_gold_checks_are_not_green(self) -> None:
        with (
            patch.object(repair_sensor_module, "datetime") as mock_datetime,
            patch.object(
                repair_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_gold_batch_readiness(
                _gold_date_status(
                    ready=False,
                    materialized=True,
                    checks_passed=False,
                    reason="gold failed",
                )
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = repair_sensor_module.stock_mins_qfq_factor_repair_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", result.skip_reason.skip_message)

    def test_sensor_blocks_direct_formula_failure_without_repair_event_override(
        self,
    ) -> None:
        same_day_formula_failed_status = StkMinsDateReadiness(
            trade_date=PARTITION_KEY,
            ready=False,
            materialized=True,
            checks_passed=False,
            reason="same-day formula failed",
            failed_check_names=(
                GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK,
            ),
            missing_file_paths=(),
            expected_file_count=7,
            existing_file_count=7,
            checked_row_count=7,
            failed_row_count=1,
        )
        with (
            patch.object(repair_sensor_module, "datetime") as mock_datetime,
            patch.object(
                repair_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_gold_batch_readiness(same_day_formula_failed_status),
            patch.object(
                repair_sensor_module,
                "gold_stk_mins_qfq_factor_repair_status",
                side_effect=AssertionError(
                    "repair status must not be read while direct gold readiness is red"
                ),
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = repair_sensor_module.stock_mins_qfq_factor_repair_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", result.skip_reason.skip_message)
        cursor = json.loads(result.cursor)
        self.assertIn("gold_stk_mins_qfq", cursor["details"].get("gate_statuses", {}))


if __name__ == "__main__":
    unittest.main()
