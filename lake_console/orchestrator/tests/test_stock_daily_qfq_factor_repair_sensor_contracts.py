import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

import dagster as dg

from orchestrator.defs.asset_guards.stock_daily_qfq_factor_repair import (
    GoldStockDailyQfqFactorRepairStatus,
)
from orchestrator.defs.run_contracts.run_keys import build_batch_id
from orchestrator.defs.sensors import (
    gold_stock_daily_qfq_factor_repair_job_sensor as sensor_module,
)
from orchestrator.defs.sensors.gold_stock_daily_qfq_factor_repair_job_sensor import (
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_SENSOR_NAME,
    GoldStockDailyQfqFactorRepairRunStatusDecision,
    build_gold_stock_daily_qfq_factor_repair_run_status_decision,
    build_gold_stock_daily_qfq_factor_repair_upstream_batch_id,
    gold_stock_daily_qfq_factor_repair_job_sensor,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    DatasetReadinessStatus,
)
from orchestrator.defs.stock_daily_qfq import (
    GoldStockDailyQfqFactorRepairPlan,
    gold_stock_daily_qfq_factor_repair_codes_hash,
)


TARGET_DATE = "2026-06-18"
PREVIOUS_DATE = "2026-06-17"
AFFECTED_HASH = gold_stock_daily_qfq_factor_repair_codes_hash(("000001.SZ",))
EMPTY_HASH = gold_stock_daily_qfq_factor_repair_codes_hash(())
UPSTREAM_BATCH_ID = "gold_stock_daily_qfq_update:2026-06-18:abc123"


def _ready_gold_status() -> DatasetReadinessStatus:
    return DatasetReadinessStatus(
        ready=True,
        statuses=(
            AssetReadinessStatus(
                asset_key="gold_stock_daily_qfq",
                partition_key=TARGET_DATE,
                ready=True,
                materialized=True,
                checks_passed=True,
                freshness_passed=True,
                materialization_storage_id=1,
                materialization_date=TARGET_DATE,
                missing_check_names=(),
                failed_check_names=(),
                reason="ready",
            ),
        ),
    )


def _repair_plan(
    *,
    repair_required_codes: tuple[str, ...] = ("000001.SZ",),
) -> GoldStockDailyQfqFactorRepairPlan:
    return GoldStockDailyQfqFactorRepairPlan(
        qfq_factor_trade_date=TARGET_DATE,
        previous_trade_date=PREVIOUS_DATE,
        reason="factor_changed" if repair_required_codes else "no_factor_changed",
        can_execute_repair=True,
        repair_required=bool(repair_required_codes),
        repair_required_codes=repair_required_codes,
        repair_required_codes_hash=gold_stock_daily_qfq_factor_repair_codes_hash(
            repair_required_codes
        ),
    )


def _not_ready_repair_status() -> GoldStockDailyQfqFactorRepairStatus:
    return GoldStockDailyQfqFactorRepairStatus(
        ready=False,
        trade_date=TARGET_DATE,
        reason="missing repair status",
    )


class _FakeRunStatusContext:
    def __init__(self) -> None:
        self.dagster_run = SimpleNamespace(
            run_id="daily-run-id",
            tags={"dagster/partition": TARGET_DATE},
        )
        self.instance = object()
        self.cursor = None

    def update_cursor(self, cursor: str) -> None:
        self.cursor = cursor


def _single_sensor_result(context: _FakeRunStatusContext) -> object:
    return sensor_module._evaluate_gold_stock_daily_qfq_factor_repair_job_sensor(
        context
    )


class StockDailyQfqFactorRepairSensorContractTests(unittest.TestCase):
    def test_sensor_definition_is_stopped_and_tagged(self) -> None:
        self.assertEqual(
            gold_stock_daily_qfq_factor_repair_job_sensor.name,
            GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_SENSOR_NAME,
        )
        self.assertEqual(
            gold_stock_daily_qfq_factor_repair_job_sensor.default_status,
            dg.DefaultSensorStatus.STOPPED,
        )

    def test_decision_selects_no_op_reconciliation_when_no_factor_changed(self) -> None:
        decision = build_gold_stock_daily_qfq_factor_repair_run_status_decision(
            target_trade_date=TARGET_DATE,
            gold_stock_daily_qfq_ready=True,
            repair_plan=_repair_plan(repair_required_codes=()),
            repair_status=None,
            upstream_batch_id=UPSTREAM_BATCH_ID,
        )

        self.assertEqual(decision.selected_trade_date, TARGET_DATE)
        self.assertEqual(decision.reason_code, "selected_for_reconciliation")
        self.assertEqual(decision.repair_required_codes_hash, EMPTY_HASH)
        self.assertEqual(decision.repair_required_code_count, 0)

    def test_public_upstream_batch_builder_uses_frozen_source_facts(self) -> None:
        actual = build_gold_stock_daily_qfq_factor_repair_upstream_batch_id(
            producer_run_id="daily-run-id",
            target_trade_date=TARGET_DATE,
            repair_required_codes_hash=EMPTY_HASH,
        )

        self.assertEqual(
            actual,
            build_batch_id(
                producer="gold_stock_daily_qfq_update",
                scope=TARGET_DATE,
                payload={
                    "producer_run_id": "daily-run-id",
                    "qfq_factor_trade_date": TARGET_DATE,
                    "repair_required_codes_hash": EMPTY_HASH,
                },
            ),
        )

    def test_decision_skips_when_scope_exceeds_auto_limit(self) -> None:
        codes = tuple(f"{index:06d}.SZ" for index in range(501))
        decision = build_gold_stock_daily_qfq_factor_repair_run_status_decision(
            target_trade_date=TARGET_DATE,
            gold_stock_daily_qfq_ready=True,
            repair_plan=_repair_plan(repair_required_codes=codes),
            repair_status=None,
            upstream_batch_id=UPSTREAM_BATCH_ID,
        )

        self.assertIsNone(decision.selected_trade_date)
        self.assertEqual(decision.reason_code, "repair_scope_exceeds_auto_limit")
        self.assertEqual(decision.repair_required_code_count, 501)

    def test_decision_does_not_duplicate_ready_no_op_reconciliation(self) -> None:
        decision = build_gold_stock_daily_qfq_factor_repair_run_status_decision(
            target_trade_date=TARGET_DATE,
            gold_stock_daily_qfq_ready=True,
            repair_plan=_repair_plan(repair_required_codes=()),
            repair_status=GoldStockDailyQfqFactorRepairStatus(
                ready=True,
                trade_date=TARGET_DATE,
                reason="no-op reconciliation ready",
            ),
            upstream_batch_id=UPSTREAM_BATCH_ID,
        )

        self.assertIsNone(decision.selected_trade_date)
        self.assertEqual(decision.reason_code, "repair_status_ready")

    def test_selected_decision_builds_upstream_triggered_run_request_without_codes(self) -> None:
        decision = GoldStockDailyQfqFactorRepairRunStatusDecision(
            target_trade_date=TARGET_DATE,
            selected_trade_date=TARGET_DATE,
            reason_code="selected_for_repair",
            reason="repair required",
            next_action="submit",
            repair_required_codes_hash=AFFECTED_HASH,
            upstream_batch_id=UPSTREAM_BATCH_ID,
            repair_required_code_count=1,
        )

        request = sensor_module._run_request_for_repair_decision(decision)

        self.assertEqual(
            request.run_key,
            f"gold_stock_daily_qfq_factor_repair:{UPSTREAM_BATCH_ID}",
        )
        config = request.run_config["ops"]["gold_stock_daily_qfq_factor_repair_op"][
            "config"
        ]
        self.assertEqual(config["qfq_factor_trade_date"], TARGET_DATE)
        self.assertEqual(config["repair_required_codes_hash"], AFFECTED_HASH)
        self.assertEqual(config["upstream_batch_id"], UPSTREAM_BATCH_ID)
        self.assertNotIn("stock_codes", config)

    def test_sensor_submits_when_daily_ready_factor_changed_and_status_not_ready(self) -> None:
        with (
            patch.object(
                sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                return_value=_ready_gold_status(),
            ),
            patch.object(
                sensor_module,
                "_load_expected_stock_trade_dates",
                return_value=(PREVIOUS_DATE, TARGET_DATE),
            ),
            patch.object(
                sensor_module,
                "connect_configured_duckdb",
                return_value=nullcontext(object()),
            ),
            patch.object(
                sensor_module,
                "build_gold_stock_daily_qfq_factor_repair_plan",
                return_value=_repair_plan(),
            ) as plan_builder,
            patch.object(
                sensor_module,
                "gold_stock_daily_qfq_factor_repair_status",
                return_value=_not_ready_repair_status(),
            ) as repair_status,
            patch.object(sensor_module, "assert_lake_root_available_for_run"),
        ):
            result = _single_sensor_result(_FakeRunStatusContext())

        self.assertIsInstance(result, dg.RunRequest)
        self.assertEqual(
            result.run_config["ops"]["gold_stock_daily_qfq_factor_repair_op"][
                "config"
            ]["repair_required_codes_hash"],
            AFFECTED_HASH,
        )
        plan_builder.assert_called_once()
        repair_status.assert_called_once()

    def test_sensor_submits_no_op_reconciliation_when_no_factor_changed(self) -> None:
        with (
            patch.object(
                sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                return_value=_ready_gold_status(),
            ),
            patch.object(
                sensor_module,
                "_load_expected_stock_trade_dates",
                return_value=(PREVIOUS_DATE, TARGET_DATE),
            ),
            patch.object(
                sensor_module,
                "connect_configured_duckdb",
                return_value=nullcontext(object()),
            ),
            patch.object(
                sensor_module,
                "build_gold_stock_daily_qfq_factor_repair_plan",
                return_value=_repair_plan(repair_required_codes=()),
            ),
            patch.object(
                sensor_module,
                "gold_stock_daily_qfq_factor_repair_status",
                return_value=_not_ready_repair_status(),
            ),
            patch.object(sensor_module, "assert_lake_root_available_for_run"),
        ):
            result = _single_sensor_result(_FakeRunStatusContext())

        self.assertIsInstance(result, dg.RunRequest)
        config = result.run_config["ops"]["gold_stock_daily_qfq_factor_repair_op"][
            "config"
        ]
        self.assertEqual(config["qfq_factor_trade_date"], TARGET_DATE)
        self.assertEqual(config["repair_required_codes_hash"], EMPTY_HASH)
        self.assertEqual(
            config["upstream_batch_id"],
            build_gold_stock_daily_qfq_factor_repair_upstream_batch_id(
                producer_run_id="daily-run-id",
                target_trade_date=TARGET_DATE,
                repair_required_codes_hash=EMPTY_HASH,
            ),
        )

    def test_sensor_does_not_read_repair_status_when_daily_not_ready(self) -> None:
        not_ready = DatasetReadinessStatus(
            ready=False,
            statuses=(
                AssetReadinessStatus(
                    asset_key="gold_stock_daily_qfq",
                    partition_key=TARGET_DATE,
                    ready=False,
                    materialized=False,
                    checks_passed=False,
                    freshness_passed=False,
                    materialization_storage_id=None,
                    materialization_date=None,
                    missing_check_names=("gold_stock_daily_qfq_contract_check",),
                    failed_check_names=(),
                    reason="missing",
                ),
            ),
        )
        repair_status = Mock()
        with (
            patch.object(
                sensor_module,
                "partition_dataset_readiness_status_from_latest_checks",
                return_value=not_ready,
            ),
            patch.object(
                sensor_module,
                "gold_stock_daily_qfq_factor_repair_status",
                repair_status,
            ),
        ):
            result = _single_sensor_result(_FakeRunStatusContext())

        self.assertIsInstance(result, dg.SkipReason)
        repair_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
