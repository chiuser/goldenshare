import unittest
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor import (
    DAGSTER_PARTITION_TAG,
    GOLD_STK_MINS_QFQ_MACD_KDJ_READINESS_SPECS,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS,
    STOCK_MINS_QFQ_DAILY_UPDATE_JOB_NAME,
    STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
    _run_request_for_trade_date,
    _evaluate_daily_run_status_decision,
    _successful_run_for_trade_date_exists,
    _trade_date_from_dagster_run,
    build_gold_stk_mins_qfq_macd_kdj_daily_run_status_decision,
    gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    DatasetReadinessStatus,
)


PARTITION_KEY = "2026-06-05"
TARGET_TRADE_DATE = "2026-06-16"
PREVIOUS_EXPECTED_TRADE_DATE = "2026-06-15"
REPAIR_CODES_HASH = "a" * 64


def _repair_gate_status(
    *,
    ready: bool = True,
    requires_macd_kdj_repair: bool = False,
    qfq_event_ids: tuple[int, ...] = (101, 102, 103, 104, 105, 106, 107),
) -> GoldStkMinsQfqFactorRepairStatus:
    return GoldStkMinsQfqFactorRepairStatus(
        ready=ready,
        trade_date=PARTITION_KEY,
        reason="ready" if ready else "not ready",
        repair_required=requires_macd_kdj_repair,
        qfq_factor_repair_event_storage_ids=qfq_event_ids,
        repair_start_trade_date="2014-01-02",
        repair_end_trade_date=PARTITION_KEY,
        selected_partition_count=1800,
        repair_required_code_count=1 if requires_macd_kdj_repair else 0,
        repair_required_codes=("600000.SH",) if requires_macd_kdj_repair else (),
        repair_required_codes_hash=REPAIR_CODES_HASH,
        repair_required_codes_truncated=False,
        rewritten_file_count=1 if requires_macd_kdj_repair else 0,
        rewritten_row_count=10 if requires_macd_kdj_repair else 0,
    )


def _run(
    *,
    job_name: str,
    status: dg.DagsterRunStatus = dg.DagsterRunStatus.SUCCESS,
    tags: dict[str, str] | None = None,
    run_config: dict[str, object] | None = None,
):
    return SimpleNamespace(
        job_name=job_name,
        status=status,
        tags=tags or {},
        run_config=run_config or {},
    )


class _FakeInstance:
    def __init__(self, runs):
        self.runs = runs
        self.filters = []

    def get_run_records(self, *, filters, limit=None):
        self.filters.append((filters, limit))
        matches = []
        for dagster_run in self.runs:
            if filters.job_name and dagster_run.job_name != filters.job_name:
                continue
            if filters.statuses and dagster_run.status not in filters.statuses:
                continue
            if any(dagster_run.tags.get(key) != value for key, value in filters.tags.items()):
                continue
            matches.append(SimpleNamespace(dagster_run=dagster_run))
        return matches[:limit]


def _asset_status(
    *,
    asset_key: str = "gold_stk_mins_qfq_1m",
    ready: bool = True,
    materialized: bool = True,
    checks_passed: bool = True,
    reason: str = "ready",
) -> AssetReadinessStatus:
    return AssetReadinessStatus(
        asset_key=asset_key,
        partition_key=None,
        ready=ready,
        materialized=materialized,
        checks_passed=checks_passed,
        freshness_passed=ready,
        materialization_storage_id=1 if materialized else None,
        materialization_date="2026-06-16" if materialized else None,
        missing_check_names=() if checks_passed else (f"{asset_key}_file_exists",),
        failed_check_names=(),
        reason=reason,
    )


def _dataset_status(
    *,
    ready: bool = True,
    materialized: bool = True,
    checks_passed: bool = True,
    reason: str = "ready",
    asset_key: str = "gold_stk_mins_qfq_1m",
) -> DatasetReadinessStatus:
    return DatasetReadinessStatus(
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


def _successful_runs_for_target(trade_date: str) -> tuple[object, ...]:
    return (
        _run(
            job_name=STOCK_MINS_QFQ_DAILY_UPDATE_JOB_NAME,
            tags={DAGSTER_PARTITION_TAG: trade_date},
        ),
        _run(
            job_name=STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
            run_config={
                "ops": {
                    "stock_mins_qfq_factor_repair_op": {
                        "config": {"trade_date": trade_date}
                    }
                }
            },
        ),
    )


def _context_for_triggered_run(*, trade_date: str):
    return SimpleNamespace(
        instance=_FakeInstance(_successful_runs_for_target(trade_date)),
        dagster_run=_run(
            job_name=STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
            run_config={
                "ops": {
                    "stock_mins_qfq_factor_repair_op": {
                        "config": {"trade_date": trade_date}
                    }
                }
            },
        ),
    )


class StkMinsQfqM12SensorContractTests(unittest.TestCase):
    def test_daily_sensor_definition_contract(self) -> None:
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.name,
            "gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor",
        )
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.default_status,
            dg.DefaultSensorStatus.STOPPED,
        )

    def test_trade_date_from_partition_tag_or_factor_repair_run_config(self) -> None:
        partitioned_run = _run(
            job_name=STOCK_MINS_QFQ_DAILY_UPDATE_JOB_NAME,
            tags={DAGSTER_PARTITION_TAG: PARTITION_KEY},
        )
        repair_run = _run(
            job_name=STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
            run_config={
                "ops": {
                    "stock_mins_qfq_factor_repair_op": {
                        "config": {"trade_date": PARTITION_KEY}
                    }
                }
            },
        )

        self.assertEqual(_trade_date_from_dagster_run(partitioned_run), PARTITION_KEY)
        self.assertEqual(_trade_date_from_dagster_run(repair_run), PARTITION_KEY)

    def test_successful_run_lookup_handles_partitioned_and_typed_config_runs(self) -> None:
        instance = _FakeInstance(
            [
                _run(
                    job_name=STOCK_MINS_QFQ_DAILY_UPDATE_JOB_NAME,
                    tags={DAGSTER_PARTITION_TAG: PARTITION_KEY},
                ),
                _run(
                    job_name=STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
                    run_config={
                        "ops": {
                            "stock_mins_qfq_factor_repair_op": {
                                "config": {"trade_date": PARTITION_KEY}
                            }
                        }
                    },
                ),
            ]
        )

        self.assertTrue(
            _successful_run_for_trade_date_exists(
                instance,
                job_name=STOCK_MINS_QFQ_DAILY_UPDATE_JOB_NAME,
                trade_date=PARTITION_KEY,
            )
        )
        self.assertTrue(
            _successful_run_for_trade_date_exists(
                instance,
                job_name=STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
                trade_date=PARTITION_KEY,
            )
        )

    def test_daily_decision_waits_for_qfq_daily_and_factor_repair_success(self) -> None:
        no_qfq_daily = build_gold_stk_mins_qfq_macd_kdj_daily_run_status_decision(
            target_trade_date=PARTITION_KEY,
            previous_trade_date="2026-06-04",
            qfq_daily_succeeded=False,
            qfq_factor_repair_status=_repair_gate_status(),
            qfq_ready=True,
            previous_state_ready=True,
            target_ready=False,
            target_has_materialized_check_problem=False,
        )
        no_factor_repair = build_gold_stk_mins_qfq_macd_kdj_daily_run_status_decision(
            target_trade_date=PARTITION_KEY,
            previous_trade_date="2026-06-04",
            qfq_daily_succeeded=True,
            qfq_factor_repair_status=None,
            qfq_ready=True,
            previous_state_ready=True,
            target_ready=False,
            target_has_materialized_check_problem=False,
        )

        self.assertIsNone(no_qfq_daily.selected_trade_date)
        self.assertIsNone(no_factor_repair.selected_trade_date)

    def test_daily_decision_submits_run_after_upstreams_ready_without_custom_tags(
        self,
    ) -> None:
        status = _repair_gate_status(requires_macd_kdj_repair=True)

        decision = build_gold_stk_mins_qfq_macd_kdj_daily_run_status_decision(
            target_trade_date=PARTITION_KEY,
            previous_trade_date="2026-06-04",
            qfq_daily_succeeded=True,
            qfq_factor_repair_status=status,
            qfq_ready=True,
            previous_state_ready=True,
            target_ready=False,
            target_has_materialized_check_problem=False,
        )
        request = _run_request_for_trade_date(PARTITION_KEY)

        self.assertEqual(decision.selected_trade_date, PARTITION_KEY)
        self.assertEqual(
            request.run_key,
            f"gold_stk_mins_qfq_macd_kdj_daily_update:{PARTITION_KEY}",
        )
        self.assertEqual(request.partition_key, PARTITION_KEY)
        self.assertEqual(request.tags, {})

    def test_daily_sensor_uses_previous_expected_not_previous_registered(
        self,
    ) -> None:
        context = _context_for_triggered_run(trade_date=TARGET_TRADE_DATE)
        calls: list[tuple[object, str]] = []

        def fake_readiness(_instance, specs, *, partition_key):
            calls.append((specs, partition_key))
            if specs is GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS:
                return _dataset_status(
                    ready=False,
                    materialized=False,
                    checks_passed=False,
                    reason="previous expected state missing",
                    asset_key="gold_stk_mins_qfq_macd_kdj_state_1m",
                )
            return _dataset_status(
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="target missing",
                asset_key="gold_stk_mins_qfq_macd_kdj_1m",
            )

        with patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "gold_stk_mins_qfq_factor_repair_status",
            return_value=_repair_gate_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "partition_dataset_readiness_status_from_latest_checks",
            side_effect=fake_readiness,
        ), patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "_effective_qfq_ready_for_target_trade_date",
            return_value=True,
        ):
            decision, _ = _evaluate_daily_run_status_decision(
                context=context,
                target_trade_date=TARGET_TRADE_DATE,
                expected_trade_dates=(
                    "2026-06-13",
                    PREVIOUS_EXPECTED_TRADE_DATE,
                    TARGET_TRADE_DATE,
                ),
            )

        self.assertIsNone(decision.selected_trade_date)
        self.assertIn("上一交易日", decision.reason)
        self.assertIn(
            (
                GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS,
                PREVIOUS_EXPECTED_TRADE_DATE,
            ),
            calls,
        )
        self.assertNotIn(
            (GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS, "2026-06-13"),
            calls,
        )

    def test_daily_sensor_submits_when_previous_expected_state_is_ready(self) -> None:
        context = _context_for_triggered_run(trade_date=TARGET_TRADE_DATE)

        def fake_readiness(_instance, specs, *, partition_key):
            if specs is GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS:
                self.assertEqual(partition_key, PREVIOUS_EXPECTED_TRADE_DATE)
                return _dataset_status(
                    ready=True,
                    asset_key="gold_stk_mins_qfq_macd_kdj_state_1m",
                )
            self.assertIs(specs, GOLD_STK_MINS_QFQ_MACD_KDJ_READINESS_SPECS)
            self.assertEqual(partition_key, TARGET_TRADE_DATE)
            return _dataset_status(
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="target missing",
                asset_key="gold_stk_mins_qfq_macd_kdj_1m",
            )

        with patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "gold_stk_mins_qfq_factor_repair_status",
            return_value=_repair_gate_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "partition_dataset_readiness_status_from_latest_checks",
            side_effect=fake_readiness,
        ), patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "_effective_qfq_ready_for_target_trade_date",
            return_value=True,
        ):
            decision, _ = _evaluate_daily_run_status_decision(
                context=context,
                target_trade_date=TARGET_TRADE_DATE,
                expected_trade_dates=(
                    "2026-06-13",
                    PREVIOUS_EXPECTED_TRADE_DATE,
                    TARGET_TRADE_DATE,
                ),
            )

        self.assertEqual(decision.selected_trade_date, TARGET_TRADE_DATE)
        result = _run_request_for_trade_date(decision.selected_trade_date)
        self.assertIsInstance(result, dg.RunRequest)
        self.assertEqual(
            result.run_key,
            f"gold_stk_mins_qfq_macd_kdj_daily_update:{TARGET_TRADE_DATE}",
        )
        self.assertEqual(result.partition_key, TARGET_TRADE_DATE)
        self.assertEqual(result.tags, {})

    def test_daily_sensor_uses_effective_qfq_readiness_gate(self) -> None:
        context = _context_for_triggered_run(trade_date=TARGET_TRADE_DATE)

        def fake_readiness(_instance, specs, *, partition_key):
            if specs is GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS:
                self.assertEqual(partition_key, PREVIOUS_EXPECTED_TRADE_DATE)
                return _dataset_status(
                    ready=True,
                    asset_key="gold_stk_mins_qfq_macd_kdj_state_1m",
                )
            self.assertIs(specs, GOLD_STK_MINS_QFQ_MACD_KDJ_READINESS_SPECS)
            return _dataset_status(
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="target missing",
                asset_key="gold_stk_mins_qfq_macd_kdj_1m",
            )

        with patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "gold_stk_mins_qfq_factor_repair_status",
            return_value=_repair_gate_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "partition_dataset_readiness_status_from_latest_checks",
            side_effect=fake_readiness,
        ), patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "_effective_qfq_ready_for_target_trade_date",
            return_value=True,
        ) as effective_qfq_mock:
            decision, _ = _evaluate_daily_run_status_decision(
                context=context,
                target_trade_date=TARGET_TRADE_DATE,
                expected_trade_dates=(
                    "2026-06-13",
                    PREVIOUS_EXPECTED_TRADE_DATE,
                    TARGET_TRADE_DATE,
                ),
            )

        self.assertEqual(decision.selected_trade_date, TARGET_TRADE_DATE)
        effective_qfq_mock.assert_called_once()

    def test_daily_sensor_skips_when_target_is_not_expected(self) -> None:
        context = _context_for_triggered_run(trade_date=TARGET_TRADE_DATE)
        with patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "gold_stk_mins_qfq_factor_repair_status",
        ) as repair_status_mock, patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "partition_dataset_readiness_status_from_latest_checks",
        ) as readiness_mock:
            decision, _ = _evaluate_daily_run_status_decision(
                context=context,
                target_trade_date=TARGET_TRADE_DATE,
                expected_trade_dates=("2026-06-13", PREVIOUS_EXPECTED_TRADE_DATE),
            )

        self.assertIsNone(decision.selected_trade_date)
        self.assertIn("不在股票分钟线 expected calendar", decision.reason)
        repair_status_mock.assert_not_called()
        readiness_mock.assert_not_called()

    def test_daily_sensor_allows_baseline_without_previous_state_lookup(self) -> None:
        baseline_trade_date = "2014-01-02"
        context = _context_for_triggered_run(trade_date=baseline_trade_date)

        def fake_readiness(_instance, specs, *, partition_key):
            self.assertNotEqual(specs, GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_READINESS_SPECS)
            self.assertEqual(partition_key, baseline_trade_date)
            return _dataset_status(
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="target missing",
                asset_key="gold_stk_mins_qfq_macd_kdj_1m",
            )

        with patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "gold_stk_mins_qfq_factor_repair_status",
            return_value=_repair_gate_status(ready=True),
        ), patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "partition_dataset_readiness_status_from_latest_checks",
            side_effect=fake_readiness,
        ), patch(
            "orchestrator.defs.sensors.gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor."
            "_effective_qfq_ready_for_target_trade_date",
            return_value=True,
        ):
            decision, _ = _evaluate_daily_run_status_decision(
                context=context,
                target_trade_date=baseline_trade_date,
                expected_trade_dates=(baseline_trade_date,),
            )

        self.assertEqual(decision.selected_trade_date, baseline_trade_date)
        result = _run_request_for_trade_date(decision.selected_trade_date)
        self.assertIsInstance(result, dg.RunRequest)
        self.assertEqual(result.partition_key, baseline_trade_date)


if __name__ == "__main__":
    unittest.main()
