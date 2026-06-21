import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import duckdb
import orchestrator.defs.sensors.stock_mins_qfq_daily_sensor as daily_sensor_module
from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
)
from orchestrator.defs.asset_guards.stk_mins_continuity import (
    StockMinsContinuityStatus,
)
from orchestrator.defs.checks.stk_mins_checks import (
    GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK,
)
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
    _run_request_for_trade_date,
    build_stock_mins_qfq_daily_update_decision,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)


PARTITION_KEY = "2026-05-29"
EVALUATED_AT = datetime(2026, 5, 29, 20, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
BEFORE_WINDOW = datetime(2026, 5, 29, 20, 5, tzinfo=ZoneInfo("Asia/Shanghai"))


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


def _date_status(
    *,
    dataset: str,
    ready: bool,
    materialized: bool = True,
    checks_passed: bool = True,
    reason: str = "ready",
    expected_file_count: int = 1,
) -> StkMinsDateReadiness:
    return StkMinsDateReadiness(
        trade_date=PARTITION_KEY,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        reason=reason,
        failed_check_names=() if ready else (f"{dataset}_file_exists",),
        missing_file_paths=(),
        expected_file_count=expected_file_count,
        existing_file_count=expected_file_count if materialized else 0,
        checked_row_count=expected_file_count if materialized else 0,
        failed_row_count=0 if ready else 1,
    )


def _batch_status(
    *,
    dataset: str,
    status: StkMinsDateReadiness,
    freq_count: int,
) -> StkMinsBatchReadiness:
    return StkMinsBatchReadiness(
        dataset=dataset,
        expected_start_date=PARTITION_KEY,
        expected_end_date=PARTITION_KEY,
        expected_count=1,
        freq_count=freq_count,
        elapsed_ms=1.0,
        statuses_by_trade_date={PARTITION_KEY: status},
    )


@contextmanager
def _patched_batch_readiness(
    *,
    silver_status: StkMinsDateReadiness | None = None,
    adj_status: StkMinsDateReadiness | None = None,
    gold_status: StkMinsDateReadiness | None = None,
):
    silver_status = silver_status or _date_status(
        dataset="silver_stk_mins",
        ready=True,
        expected_file_count=5,
    )
    adj_status = adj_status or _date_status(
        dataset="adj_factor",
        ready=True,
        expected_file_count=2,
    )
    gold_status = gold_status or _date_status(
        dataset="gold_stk_mins_qfq",
        ready=False,
        materialized=False,
        checks_passed=False,
        reason="gold missing",
        expected_file_count=7,
    )
    with (
        patch.object(
            daily_sensor_module,
            "batch_silver_stk_mins_lake_readiness",
            return_value=_batch_status(
                dataset="silver_stk_mins",
                status=silver_status,
                freq_count=5,
            ),
        ),
        patch.object(
            daily_sensor_module,
            "batch_adj_factor_lake_readiness",
            return_value=_batch_status(
                dataset="adj_factor",
                status=adj_status,
                freq_count=1,
            ),
        ),
        patch.object(
            daily_sensor_module,
            "batch_gold_stk_mins_qfq_lake_readiness",
            return_value=_batch_status(
                dataset="gold_stk_mins_qfq",
                status=gold_status,
                freq_count=7,
            ),
        ),
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


class StkMinsQfqM9ASensorContractTests(unittest.TestCase):
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
        self.assertIn("20:10", before_window.reason)

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
        self.assertEqual(STOCK_MINS_QFQ_DAILY_RUN_START.isoformat(), "20:10:00")
        self.assertEqual(BEFORE_WINDOW.time().isoformat(), "20:05:00")

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

    def test_cursor_reason_prefers_specific_not_ready_reason(self) -> None:
        decision = build_stock_mins_qfq_daily_update_decision(
            target_trade_date=PARTITION_KEY,
            run_window_started=True,
            silver_ready=True,
            adj_factor_ready=False,
        )
        cursor = json.loads(
            build_stock_mins_qfq_daily_sensor_cursor(
                decision=decision,
                evaluated_at=EVALUATED_AT,
                registered_trade_day_count=3014,
                silver_status=_date_status(
                    dataset="silver_stk_mins",
                    ready=True,
                    expected_file_count=5,
                ),
                adj_factor_status=_date_status(
                    dataset="adj_factor",
                    ready=False,
                    materialized=True,
                    checks_passed=False,
                    reason="adj_factor_not_ready",
                    expected_file_count=2,
                ),
                continuity_status=StockMinsContinuityStatus(
                    partition_set_name="cn_a_stock_mins_silver_trade_days",
                    expected_start_date=PARTITION_KEY,
                    expected_end_date=PARTITION_KEY,
                    expected_count=1,
                    registered_count=1,
                    ready_count=0,
                    first_missing_registered_date=None,
                    missing_registered_date_samples=(),
                    first_not_ready_trade_date=PARTITION_KEY,
                    first_not_ready_reason="adj_factor_not_ready",
                    previous_expected_trade_date=None,
                    ready_through_trade_date=None,
                    next_actionable_trade_date=None,
                    blocked_reason="materialized_check_problem",
                ),
            )
        )

        self.assertEqual(cursor["decision"], "skip")
        self.assertEqual(cursor["details"]["reason_code"], "adj_factor_not_ready")
        self.assertEqual(cursor["details"]["blocked_component"], "adj_factor")
        self.assertEqual(
            cursor["details"]["continuity_status"]["blocked_reason"],
            "materialized_check_problem",
        )

    def test_sensor_skips_before_window_without_readiness_scan(self) -> None:
        context = _FakeSensorContext()
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                side_effect=AssertionError("calendar must not be loaded before window"),
            ),
            patch.object(
                daily_sensor_module,
                "batch_silver_stk_mins_lake_readiness",
                side_effect=AssertionError("silver batch must not run before window"),
            ),
            patch.object(
                daily_sensor_module,
                "batch_adj_factor_lake_readiness",
                side_effect=AssertionError("adj factor batch must not run before window"),
            ),
            patch.object(
                daily_sensor_module,
                "batch_gold_stk_mins_qfq_lake_readiness",
                side_effect=AssertionError("gold qfq batch must not run before window"),
            ),
        ):
            mock_datetime.now.return_value = BEFORE_WINDOW
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertIn("20:10", result.skip_reason.skip_message)
        cursor = json.loads(result.cursor)
        self.assertEqual(cursor["target_date"], None)
        self.assertEqual(cursor["selected_count"], 0)
        self.assertFalse(cursor["details"]["run_window_started"])
        self.assertNotIn("continuity_status", cursor["details"])
        self.assertNotIn("silver_batch_status", cursor["details"])
        self.assertNotIn("adj_factor_batch_status", cursor["details"])
        self.assertNotIn("gold_batch_status", cursor["details"])

    def test_sensor_does_not_load_adj_or_gold_batch_when_silver_blocks(self) -> None:
        context = _FakeSensorContext()
        silver_status = _date_status(
            dataset="silver_stk_mins",
            ready=False,
            materialized=False,
            checks_passed=False,
            reason="silver missing",
            expected_file_count=5,
        )
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            patch.object(
                daily_sensor_module,
                "batch_silver_stk_mins_lake_readiness",
                return_value=_batch_status(
                    dataset="silver_stk_mins",
                    status=silver_status,
                    freq_count=5,
                ),
            ) as silver_batch_mock,
            patch.object(
                daily_sensor_module,
                "batch_adj_factor_lake_readiness",
                side_effect=AssertionError("adj batch must not run when silver blocks"),
            ) as adj_batch_mock,
            patch.object(
                daily_sensor_module,
                "batch_gold_stk_mins_qfq_lake_readiness",
                side_effect=AssertionError("gold batch must not run when silver blocks"),
            ) as gold_batch_mock,
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("silver 五频度", result.skip_reason.skip_message)
        silver_batch_mock.assert_called_once()
        adj_batch_mock.assert_not_called()
        gold_batch_mock.assert_not_called()
        cursor = json.loads(result.cursor)
        self.assertIsNotNone(cursor["details"]["silver_status"])
        self.assertIsNone(cursor["details"]["adj_factor_batch_status"])
        self.assertIsNone(cursor["details"]["gold_batch_status"])

    def test_sensor_does_not_load_gold_batch_when_adj_factor_blocks(self) -> None:
        context = _FakeSensorContext()
        adj_status = _date_status(
            dataset="adj_factor",
            ready=False,
            materialized=False,
            checks_passed=False,
            reason="adj factor missing",
            expected_file_count=2,
        )
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            patch.object(
                daily_sensor_module,
                "batch_silver_stk_mins_lake_readiness",
                return_value=_batch_status(
                    dataset="silver_stk_mins",
                    status=_date_status(
                        dataset="silver_stk_mins",
                        ready=True,
                        expected_file_count=5,
                    ),
                    freq_count=5,
                ),
            ) as silver_batch_mock,
            patch.object(
                daily_sensor_module,
                "batch_adj_factor_lake_readiness",
                return_value=_batch_status(
                    dataset="adj_factor",
                    status=adj_status,
                    freq_count=1,
                ),
            ) as adj_batch_mock,
            patch.object(
                daily_sensor_module,
                "batch_gold_stk_mins_qfq_lake_readiness",
                side_effect=AssertionError("gold batch must not run when adj blocks"),
            ) as gold_batch_mock,
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertEqual(result.run_requests, [])
        self.assertIn("复权因子", result.skip_reason.skip_message)
        silver_batch_mock.assert_called_once()
        adj_batch_mock.assert_called_once()
        gold_batch_mock.assert_not_called()
        cursor = json.loads(result.cursor)
        self.assertIsNotNone(cursor["details"]["silver_status"])
        self.assertIsNotNone(cursor["details"]["adj_factor_status"])
        self.assertIsNone(cursor["details"]["gold_batch_status"])

    def test_sensor_cursor_fast_path_skips_after_frontier_selects_same_target(
        self,
    ) -> None:
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
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_batch_readiness(),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(context)

        cursor = json.loads(result.cursor)
        self.assertIn("已经提交过", result.skip_reason.skip_message)
        self.assertTrue(cursor["details"]["already_submitted_for_trade_date"])

    def test_sensor_legacy_selected_count_cursor_fast_path_skips_same_target(
        self,
    ) -> None:
        context = _FakeSensorContext(cursor=_legacy_submitted_cursor())
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_batch_readiness(),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertIn("已经提交过", result.skip_reason.skip_message)
        self.assertTrue(
            json.loads(result.cursor)["details"]["already_submitted_for_trade_date"]
        )

    def test_sensor_legacy_sample_keys_cursor_fast_path_skips_same_target(self) -> None:
        context = _FakeSensorContext(
            cursor=_legacy_submitted_cursor(
                selected_count=0,
                sample_keys=(PARTITION_KEY,),
            )
        )
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_batch_readiness(),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(context)

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
                    daily_sensor_module._already_submitted_for_target_date(
                        cursor,
                        PARTITION_KEY,
                    )
                )

    def test_sensor_non_fast_path_cursor_continues_readiness(self) -> None:
        context = _FakeSensorContext(cursor=_legacy_submitted_cursor(selected_count=0))
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_batch_readiness(
                silver_status=_date_status(
                    dataset="silver_stk_mins",
                    ready=False,
                    materialized=False,
                    checks_passed=False,
                    reason="silver blocked",
                    expected_file_count=5,
                )
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(context)

        self.assertIn("silver 五频度", result.skip_reason.skip_message)

    def test_sensor_checks_readiness_in_order_and_stops_when_silver_not_ready(
        self,
    ) -> None:
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_batch_readiness(
                silver_status=_date_status(
                    dataset="silver_stk_mins",
                    ready=False,
                    materialized=False,
                    checks_passed=False,
                    reason="silver blocked",
                    expected_file_count=5,
                )
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertIn("silver 五频度", result.skip_reason.skip_message)

    def test_sensor_submits_daily_run_when_upstream_ready_and_gold_missing(
        self,
    ) -> None:
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_batch_readiness(),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertEqual(len(result.run_requests), 1)
        self.assertEqual(result.run_requests[0].partition_key, PARTITION_KEY)
        self.assertTrue(json.loads(result.cursor)["details"]["already_submitted_for_trade_date"])

    def test_sensor_skips_when_gold_materialized_checks_are_not_green(self) -> None:
        with (
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_batch_readiness(
                gold_status=_date_status(
                    dataset="gold_stk_mins_qfq",
                    ready=False,
                    materialized=True,
                    checks_passed=False,
                    reason="gold failed",
                    expected_file_count=7,
                )
            ),
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertEqual(result.run_requests, [])
        self.assertIn("blocking checks 未全绿", result.skip_reason.skip_message)

    def test_sensor_does_not_resubmit_repair_adjusted_formula_mismatch(self) -> None:
        repair_adjusted_status = StkMinsDateReadiness(
            trade_date=PARTITION_KEY,
            ready=True,
            materialized=True,
            checks_passed=True,
            reason="ready_after_qfq_factor_repair",
            failed_check_names=(),
            missing_file_paths=(),
            expected_file_count=7,
            existing_file_count=7,
            checked_row_count=7,
            failed_row_count=0,
        )
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
            patch.object(daily_sensor_module, "datetime") as mock_datetime,
            patch.object(
                daily_sensor_module,
                "_load_stock_mins_qfq_expected_trade_dates",
                return_value=(PARTITION_KEY,),
            ),
            _patched_batch_readiness(gold_status=same_day_formula_failed_status),
            patch.object(
                daily_sensor_module,
                "effective_gold_qfq_readiness_for_trade_date",
                return_value=SimpleNamespace(status=repair_adjusted_status),
            ) as effective_readiness_mock,
        ):
            mock_datetime.now.return_value = EVALUATED_AT
            result = daily_sensor_module.stock_mins_qfq_daily_sensor._raw_fn(
                _FakeSensorContext()
            )

        self.assertEqual(result.run_requests, [])
        self.assertIn("已经 ready", result.skip_reason.skip_message)
        effective_readiness_mock.assert_called_once()
        cursor = json.loads(result.cursor)
        self.assertIsNone(cursor["details"]["gold_status"])
        self.assertEqual(
            cursor["details"]["continuity_status"]["ready_through_trade_date"],
            PARTITION_KEY,
        )


if __name__ == "__main__":
    unittest.main()
